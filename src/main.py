"""
Main pipeline orchestrator — runs the full daily pipeline.

Flow:
  1. Create crawl_run record
  2. Fetch TVPL RSS triggers + MOJ incremental scan
  3. Merge & dedupe across sources
  4. Check DB for truly new documents
  5. Enrich: download .docx from TVPL + fetch detail from MOJ
  6. Save to PostgreSQL + local files
  7. Upload to Google Drive
  8. Send Telegram daily digest
  9. Close crawl_run with metrics

Usage:
  python -m src.main              # Full run
  python -m src.main --dry-run    # Print without sending Telegram
  python -m src.main --moj-only   # Skip TVPL (no login needed)
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from typing import Any

from pathlib import Path

from src.config import (
    AUTO_CLEANUP_LOCAL_FILES,
    LARK_APP_ID,
    TVPL_DOWNLOAD_ENABLED,
)

from src.notification.telegram_bot import (
    build_daily_digest,
    send_daily_digest,
    send_error_alert,
)
from src.pipeline.deduplicator import merge_triggers
from src.sources.moj_api import (
    fetch_doc_detail,
    parse_doc_detail,
    scan_incremental,
    search_by_doc_num,
)
from src.sources.tvpl_downloader import download_documents_sync
from src.sources.tvpl_rss import scan_rss
from src.storage.database import (
    create_crawl_run,
    finish_crawl_run,
    get_document_by_doc_num,
    get_session,
    get_unnotified_documents,
    init_db,
    insert_references,
    insert_status_change,
    upsert_document,
)
from src.storage.file_store import (
    save_document_metadata,
    save_moj_fulltext,
    save_snapshot,
)
from src.storage.gdrive import upload_document_files
from src.storage.lark_drive import get_lark_client, upload_document_files_lark
from src.pipeline.text_processor import process_fulltext


logger = logging.getLogger(__name__)

# Các trường mà API chi tiết của Bộ Tư pháp là nguồn chuẩn — luôn ghi đè giá trị
# thu được từ RSS/API danh sách (vốn thiếu hoặc chỉ có giá trị mặc định).
MOJ_AUTHORITATIVE_FIELDS = frozenset({
    "field_name",
    "field_code",
    "eff_status",
    "eff_from",
    "eff_to",
    "issue_date",
    "doc_type",
    "agency_name",
    "signer",
})


def setup_logging() -> None:
    """Configure structured logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def run_pipeline(
    dry_run: bool = False,
    moj_only: bool = False,
    skip_gdrive: bool = False,
    limit: int = 0,
) -> dict[str, int]:
    """
    Execute the full daily pipeline.
    Returns a metrics dict.
    """
    metrics = {
        "tvpl_new_found": 0,
        "tvpl_downloaded": 0,
        "moj_new_found": 0,
        "moj_enriched": 0,
        "total_new": 0,
        "total_notified": 0,
        "gdrive_uploaded": 0,
    }

    # Ensure database tables exist
    init_db()

    with get_session() as session:
        # Create crawl run record
        crawl_run = create_crawl_run(session)
        session.commit()

        try:
            # ── Step 1: Fetch triggers from both sources ──
            logger.info("=" * 60)
            logger.info("STEP 1: Fetching document triggers")
            logger.info("=" * 60)

            tvpl_items = []
            if not moj_only:
                try:
                    tvpl_items = scan_rss()
                    metrics["tvpl_new_found"] = len(tvpl_items)
                    save_snapshot("tvpl_rss", tvpl_items)
                    logger.info("TVPL RSS: %d business items found", len(tvpl_items))
                except Exception as e:
                    logger.error("TVPL RSS scan failed: %s", e)

            moj_items = []
            try:
                moj_items = scan_incremental()
                metrics["moj_new_found"] = len(moj_items)
                save_snapshot("moj_scan", moj_items)
                logger.info("MOJ scan: %d business items found", len(moj_items))
            except Exception as e:
                logger.error("MOJ scan failed: %s", e)

            if not tvpl_items and not moj_items:
                logger.warning("No items from any source. Possible issue.")
                finish_crawl_run(
                    session, crawl_run, status="SUCCESS",
                    error_message="No items from any source",
                    **metrics,
                )
                session.commit()
                return metrics

            # ── Step 2: Merge & dedupe across sources ──
            logger.info("=" * 60)
            logger.info("STEP 2: Merging & deduplicating")
            logger.info("=" * 60)

            candidates = merge_triggers(tvpl_items, moj_items)
            logger.info("Merged candidates: %d", len(candidates))

            # ── Step 3: Check DB for truly new documents ──
            new_docs: list[dict[str, Any]] = []
            for candidate in candidates:
                doc_num = candidate.get("doc_num", "")
                if not doc_num:
                    continue

                existing = get_document_by_doc_num(session, doc_num)
                if existing is None:
                    candidate["event_type"] = "A"  # New document
                    new_docs.append(candidate)
                else:
                    # Check for status change (event B)
                    new_status = candidate.get("eff_status", "")
                    if new_status and existing.eff_status and new_status != existing.eff_status:
                        candidate["event_type"] = "B"
                        insert_status_change(
                            session,
                            existing.id,
                            existing.eff_status,
                            new_status,
                            detected_by="MOJ" if candidate.get("source_moj") else "TVPL",
                        )
                        new_docs.append(candidate)

            if limit and len(new_docs) > limit:
                logger.warning(
                    "Giới hạn --limit=%d: chỉ xử lý %d/%d văn bản mới",
                    limit, limit, len(new_docs),
                )
                new_docs = new_docs[:limit]

            metrics["total_new"] = len(new_docs)
            logger.info("Truly new/changed documents: %d", len(new_docs))

            if not new_docs:
                logger.info("No new documents today.")
                finish_crawl_run(
                    session, crawl_run, status="SUCCESS", **metrics,
                )
                session.commit()

                # Still send "no new docs" notification
                if not dry_run:
                    send_daily_digest([])

                return metrics

            # ── Step 4: Enrich each new document ──
            logger.info("=" * 60)
            logger.info("STEP 4: Enriching %d documents", len(new_docs))
            logger.info("=" * 60)

            enriched_docs: list[dict[str, Any]] = []

            for doc_data in new_docs:
                # Văn bản phát hiện từ TVPL thường nằm ngoài cửa sổ quét MOJ →
                # tra cứu trực tiếp theo số hiệu để lấy dữ liệu Bộ Tư pháp.
                if not doc_data.get("moj_id") and doc_data.get("doc_num"):
                    moj_match = search_by_doc_num(doc_data["doc_num"])
                    if moj_match:
                        for key, value in moj_match.items():
                            if value:
                                doc_data.setdefault(key, value)
                        doc_data["moj_id"] = moj_match.get("moj_id")
                        logger.info(
                            "  → Khớp Bộ Tư pháp: %s (moj_id=%s)",
                            doc_data["doc_num"],
                            doc_data["moj_id"],
                        )
                    time.sleep(0.3)  # Rate limit

                # MOJ enrichment: fetch full detail + references
                moj_id = doc_data.get("moj_id")
                if moj_id:
                    try:
                        detail_resp = fetch_doc_detail(moj_id)
                        detail = parse_doc_detail(detail_resp)

                        # Merge enriched data.
                        # API danh sách không trả lĩnh vực (→ "Khác") nên với các
                        # trường Bộ Tư pháp là nguồn chuẩn phải GHI ĐÈ bằng dữ
                        # liệu từ API chi tiết, không dùng setdefault.
                        # Ngoại lệ: lĩnh vực chỉ ghi đè khi MOJ nhận diện được
                        # lĩnh vực doanh nghiệp, để không đẩy văn bản TVPL đã
                        # phân loại đúng sang thư mục lĩnh vực khác.
                        moj_knows_field = bool(detail.get("field_code"))
                        for key, value in detail.items():
                            if key in ("references", "fulltext_html") or not value:
                                continue
                            if key in ("field_name", "field_code") and not moj_knows_field:
                                doc_data.setdefault(key, value)
                            elif key in MOJ_AUTHORITATIVE_FIELDS:
                                doc_data[key] = value
                            else:
                                doc_data.setdefault(key, value)

                        # Văn bản chỉ có ở MOJ mới qua được bộ lọc thô theo tiêu
                        # đề; giờ mới có lĩnh vực thật để xác nhận. Không thuộc
                        # lĩnh vực doanh nghiệp thì loại.
                        if doc_data.pop("_needs_field_check", False) and not detail.get(
                            "field_code"
                        ):
                            logger.info(
                                "  → Bỏ qua %s: không thuộc lĩnh vực doanh nghiệp (%s)",
                                doc_data.get("doc_num"),
                                detail.get("field_name"),
                            )
                            continue

                        # Save fulltext HTML
                        fulltext = detail.get("fulltext_html", "")
                        if fulltext:
                            path = save_moj_fulltext(moj_id, fulltext)
                            doc_data["fulltext_path"] = path
                            doc_data["has_fulltext"] = True

                            # Clean Markdown + Legal Chunking (Phase 2 prep)
                            text_result = process_fulltext(
                                doc_id=moj_id,
                                html_content=fulltext,
                                doc_num=doc_data.get("doc_num", ""),
                            )
                            if text_result["clean_text_path"]:
                                doc_data["clean_text_path"] = text_result["clean_text_path"]
                                doc_data["chunks_path"] = text_result["chunks_path"]
                                doc_data["has_chunks"] = text_result["chunk_count"] > 0
                                logger.info(
                                    "  → Text processed: %d chars → %d chunks",
                                    text_result["char_count"],
                                    text_result["chunk_count"],
                                )

                        # Store references for later insertion
                        doc_data["_references"] = detail.get("references", [])

                        metrics["moj_enriched"] += 1
                        time.sleep(0.5)  # Rate limit
                    except Exception as e:
                        logger.error("MOJ enrich failed for %s: %s", moj_id, e)

                enriched_docs.append(doc_data)

            # ── Step 4b: Download .docx/.pdf from TVPL ──
            downloadable = [
                d for d in enriched_docs if d.get("tvpl_url") and d.get("tvpl_id")
            ]
            if TVPL_DOWNLOAD_ENABLED and downloadable:
                logger.info("=" * 60)
                logger.info("STEP 4b: Downloading %d files from TVPL", len(downloadable))
                logger.info("=" * 60)
                try:
                    by_tvpl_id = {
                        str(r.get("tvpl_id")): r
                        for r in download_documents_sync(downloadable)
                    }
                    for doc_data in enriched_docs:
                        result = by_tvpl_id.get(str(doc_data.get("tvpl_id")))
                        if not result or not result.get("success"):
                            continue
                        if result.get("docx_path"):
                            doc_data["docx_path"] = result["docx_path"]
                            doc_data["has_docx"] = True
                        if result.get("pdf_path"):
                            doc_data["pdf_path"] = result["pdf_path"]
                            doc_data["has_pdf"] = True
                        metrics["tvpl_downloaded"] += 1
                    logger.info(
                        "TVPL download: %d/%d documents có file",
                        metrics["tvpl_downloaded"],
                        len(downloadable),
                    )
                except Exception as e:
                    # Tải file hỏng (Playwright/Cloudflare/hết phiên) không được
                    # làm hỏng cả lần chạy — toàn văn từ MOJ vẫn dùng được.
                    logger.error("TVPL download step failed: %s", e)
            elif downloadable:
                logger.info("STEP 4b: bỏ qua tải file TVPL (TVPL_DOWNLOAD_ENABLED=false)")

            # ── Step 5: Save to database ──
            logger.info("=" * 60)
            logger.info("STEP 5: Saving to database")
            logger.info("=" * 60)

            saved_docs: list[dict[str, Any]] = []
            for doc_data in enriched_docs:
                refs = doc_data.pop("_references", [])
                # Remove non-model fields
                clean_data = {
                    k: v for k, v in doc_data.items()
                    if not k.startswith("_") and k not in (
                        "field_slug", "references", "fulltext_html",
                    )
                }
                doc_obj, is_new = upsert_document(session, clean_data)

                # Insert references
                if refs:
                    insert_references(session, doc_obj.id, refs)

                # Collect for notification. pub_date không phải cột DB nhưng bước
                # upload cần nó để xếp thư mục theo thời gian khi thiếu issue_date.
                saved_data = {
                    **clean_data,
                    "id": doc_obj.id,
                    "pub_date": doc_data.get("pub_date"),
                }
                saved_docs.append(saved_data)

            session.commit()
            logger.info("Saved %d documents to database.", len(saved_docs))

            # ── Step 6: Upload to Cloud Drive (Lark Drive / Google Drive) ──
            if not skip_gdrive:
                logger.info("=" * 60)
                if LARK_APP_ID:
                    logger.info("STEP 6: Uploading to Lark Drive")
                    access = get_lark_client().check_access()
                    if not access["ok"]:
                        logger.warning("Lark Drive: %s", access["reason"])
                else:
                    logger.info("STEP 6: Uploading to Google Drive")
                logger.info("=" * 60)

                for doc_data in saved_docs:
                    try:
                        # Hồ sơ metadata gộp cả hai nguồn, đi kèm file trong thư mục
                        doc_data["metadata_path"] = save_document_metadata(doc_data)

                        if LARK_APP_ID:
                            drive_result = upload_document_files_lark(doc_data)
                        else:
                            drive_result = upload_document_files(doc_data)

                        uploaded_any = any(
                            drive_result.get(key)
                            for key in (
                                "lark_docx_link",
                                "lark_pdf_link",
                                "lark_fulltext_link",
                                "gdrive_docx_link",
                                "gdrive_pdf_link",
                            )
                        )
                        if uploaded_any:
                            doc_data.update(drive_result)
                            # Update DB with Drive links
                            existing = get_document_by_doc_num(
                                session, doc_data["doc_num"]
                            )
                            if existing:
                                existing.gdrive_docx_link = drive_result.get("gdrive_docx_link")
                                existing.gdrive_pdf_link = drive_result.get("gdrive_pdf_link")
                                existing.gdrive_folder_id = drive_result.get("gdrive_folder_id")
                                existing.lark_docx_link = drive_result.get("lark_docx_link")
                                existing.lark_pdf_link = drive_result.get("lark_pdf_link")
                                existing.lark_folder_token = drive_result.get("lark_folder_token")
                            metrics["gdrive_uploaded"] += 1

                            # Auto-delete local docx/pdf files to save disk space
                            if AUTO_CLEANUP_LOCAL_FILES:
                                docx_p = doc_data.get("docx_path")
                                pdf_p = doc_data.get("pdf_path")
                                if docx_p and Path(docx_p).exists():
                                    try:
                                        Path(docx_p).unlink()
                                        logger.info("Cleaned up local file: %s", docx_p)
                                    except Exception as e:
                                        logger.warning("Failed to delete local temp file %s: %s", docx_p, e)
                                if pdf_p and Path(pdf_p).exists():
                                    try:
                                        Path(pdf_p).unlink()
                                        logger.info("Cleaned up local file: %s", pdf_p)
                                    except Exception as e:
                                        logger.warning("Failed to delete local temp file %s: %s", pdf_p, e)

                    except Exception as e:
                        logger.warning("Cloud Drive upload failed for %s: %s", doc_data.get("doc_num"), e)

                session.commit()


            # ── Step 7: Send Telegram notification ──
            logger.info("=" * 60)
            logger.info("STEP 7: Sending Telegram notification")
            logger.info("=" * 60)

            if dry_run:
                message = build_daily_digest(saved_docs)
                print("\n" + "=" * 60)
                print("DRY RUN — Telegram message preview:")
                print("=" * 60)
                print(message)
                print("=" * 60 + "\n")
                metrics["total_notified"] = len(saved_docs)
            else:
                success = send_daily_digest(saved_docs)
                if success:
                    # Mark documents as notified
                    now = datetime.utcnow()
                    for doc_data in saved_docs:
                        existing = get_document_by_doc_num(
                            session, doc_data["doc_num"]
                        )
                        if existing:
                            existing.notified_at = now
                    session.commit()
                    metrics["total_notified"] = len(saved_docs)
                    logger.info("Telegram digest sent: %d documents", len(saved_docs))
                else:
                    logger.error("Failed to send Telegram digest.")

            # ── Finalize crawl run ──
            finish_crawl_run(session, crawl_run, status="SUCCESS", **metrics)
            session.commit()

        except Exception as e:
            logger.exception("Pipeline failed: %s", e)
            finish_crawl_run(
                session, crawl_run,
                status="FAILED",
                error_message=str(e),
                **metrics,
            )
            session.commit()

            if not dry_run:
                send_error_alert(str(e))

            raise

    return metrics


def run_upload_only() -> dict[str, int]:
    """
    Đẩy lên Lark Drive những văn bản đã có trong DB nhưng chưa upload được.

    Dùng khi lần chạy trước thất bại ở bước upload (chưa cấu hình
    LARK_ROOT_FOLDER_TOKEN, mất mạng…) — dữ liệu đã có sẵn dưới data/ nên không
    cần quét lại nguồn.
    """
    from src.storage.models import Document

    init_db()
    metrics = {"gdrive_uploaded": 0, "total_new": 0}

    if LARK_APP_ID:
        access = get_lark_client().check_access()
        if not access["ok"]:
            logger.error("Lark Drive chưa dùng được: %s", access["reason"])
            return metrics
        logger.info("Kho lưu trữ Lark: %s", access["folder_url"])

    with get_session() as session:
        # Không lọc theo file: văn bản chưa tải được .docx/toàn văn vẫn cần thư
        # mục riêng kèm metadata, để kho trên Drive phản ánh đủ danh sách văn bản.
        pending = (
            session.query(Document)
            .filter(Document.lark_folder_token.is_(None))
            .all()
        )
        metrics["total_new"] = len(pending)
        logger.info("Có %d văn bản chờ upload.", len(pending))

        for doc in pending:
            doc_data = {
                col.name: getattr(doc, col.name) for col in Document.__table__.columns
            }
            doc_data["metadata_path"] = save_document_metadata(doc_data)

            result = upload_document_files_lark(doc_data)
            if not result.get("lark_folder_token"):
                continue

            doc.lark_docx_link = result.get("lark_docx_link")
            doc.lark_pdf_link = result.get("lark_pdf_link")
            doc.lark_folder_token = result.get("lark_folder_token")
            doc.gdrive_docx_link = result.get("gdrive_docx_link")
            doc.gdrive_pdf_link = result.get("gdrive_pdf_link")
            metrics["gdrive_uploaded"] += 1
            session.commit()

    logger.info("Đã upload %d/%d văn bản.", metrics["gdrive_uploaded"], metrics["total_new"])
    return metrics


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Hệ thống Cập nhật Văn bản Pháp luật Doanh nghiệp — Daily Pipeline"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print Telegram message without sending",
    )
    parser.add_argument(
        "--moj-only",
        action="store_true",
        help="Skip TVPL (no login needed, MOJ only)",
    )
    parser.add_argument(
        "--skip-gdrive",
        action="store_true",
        help="Skip Google Drive upload",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Chỉ xử lý N văn bản mới đầu tiên (dùng để chạy thử)",
    )
    parser.add_argument(
        "--upload-only",
        action="store_true",
        help="Chỉ upload lại các văn bản đã có trong DB nhưng chưa lên Lark Drive",
    )
    args = parser.parse_args()

    setup_logging()

    if args.upload_only:
        run_upload_only()
        return

    logger.info("Pipeline starting at %s", datetime.now().isoformat())

    start_time = time.time()
    metrics = run_pipeline(
        dry_run=args.dry_run,
        moj_only=args.moj_only,
        skip_gdrive=args.skip_gdrive,
        limit=args.limit,
    )
    elapsed = time.time() - start_time

    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE in %.1fs", elapsed)
    logger.info("Metrics: %s", metrics)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
