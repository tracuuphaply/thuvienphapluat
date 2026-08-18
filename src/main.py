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
import fcntl
import logging
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from typing import Any, Generator

from pathlib import Path

from src.config import (
    AUTO_CLEANUP_LOCAL_FILES,
    DATA_DIR,
    LARK_APP_ID,
    TVPL_DOWNLOAD_ENABLED,
    upload_closure_nodes,
)

from src.notification.telegram_bot import (
    send_error_alert,
)
from src.pipeline.deduplicator import merge_triggers, normalize_doc_num
from src.sources.moj_api import (
    fetch_doc_detail,
    parse_doc_detail,
    scan_incremental,
    search_by_doc_num,
)
from src.sources.tvpl_downloader import download_documents_sync
from src.sources.tvpl_rss import scan_rss
from src.storage.database import (
    clear_upload_queue,
    enqueue_upload,
    get_crawl_cutoff,
    update_crawl_watermark,
    create_crawl_run,
    finish_crawl_run,
    get_document_by_doc_num,
    resolve_existing_document,
    get_session,
    init_db,
    insert_references,
    insert_status_change,
    upsert_document,
)
from src.storage.file_store import (
    load_rejected_doc_nums,
    save_document_metadata,
    save_moj_fulltext,
    save_rejected_doc_nums,
    save_snapshot,
)
from src.rag.reports.jobs import enqueue_update_reports
from src.storage import cloud_drive
from src.storage.cloud_drive import active_provider
from src.storage.lark_drive import get_lark_client
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


# Quan hệ khiến văn bản ĐÍCH bị tác động → sinh sự kiện C cho văn bản đích.
# "Căn cứ" và "Dẫn chiếu" chỉ là tham chiếu, không làm thay đổi hiệu lực.
IMPACTING_RELATIONS = frozenset({
    "Sửa đổi, bổ sung",
    "Thay thế",
    "Bãi bỏ",
    "Hủy bỏ",
    "Đình chỉ",
})


def detect_affected_documents(
    session: Any,
    new_docs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Tìm các văn bản CŨ trong DB bị văn bản mới sửa đổi/thay thế (sự kiện C).

    Văn bản mới mang theo danh sách quan hệ từ Bộ Tư pháp; nếu văn bản đích đã
    có trong kho thì người dùng cần được báo là văn bản họ đang áp dụng vừa bị
    tác động — đây chính là giá trị chính của hệ thống, không chỉ báo văn bản mới.
    """
    affected: dict[str, dict[str, Any]] = {}
    # Văn bản của chính lần chạy này đã được báo là "mới", không báo lại là "bị sửa"
    current_run = {
        normalize_doc_num(str(d.get("doc_num", ""))) for d in new_docs
    }

    for doc_data in new_docs:
        for ref in doc_data.get("_references", []):
            if ref.get("relation_type") not in IMPACTING_RELATIONS:
                continue

            target = get_document_by_doc_num(session, ref["target_doc_num"])
            if target is None or target.doc_num in affected:
                continue
            if normalize_doc_num(target.doc_num) in current_run:
                continue

            target.event_type = "C"
            target.notified_at = None  # để được đưa vào bản tin lần này

            row = {
                col.name: getattr(target, col.name)
                for col in target.__table__.columns
            }
            row["impacted_by"] = doc_data.get("doc_num")
            row["impact_type"] = ref["relation_type"]
            affected[target.doc_num] = row

            logger.info(
                "  → Sự kiện C: %s bị %s bởi %s",
                target.doc_num,
                ref["relation_type"].lower(),
                doc_data.get("doc_num"),
            )

    return list(affected.values())


def setup_logging() -> None:
    """Configure structured logging.

    Ghi ra cả stdout lẫn file: chỉ có StreamHandler thì chạy tay xong đóng
    terminal là mất sạch log, không còn gì để điều tra khi pipeline hỏng.
    """
    log_dir = DATA_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    file_handler = TimedRotatingFileHandler(
        log_dir / "pipeline.log",
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d"
    handlers.append(file_handler)

    # force=True: basicConfig là no-op nếu root logger đã có handler, nên chỉ
    # cần một thư viện gọi logging trước là file handler không bao giờ được gắn.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )
    # httpx log mỗi request một dòng, lấn át log nghiệp vụ trong file.
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


@contextmanager
def pipeline_lock() -> Generator[None, None, None]:
    """Chặn hai lần chạy chồng lên nhau.

    Hai tiến trình cùng chạy sẽ đua ghi SQLite, đua ghi 314 file vault và tiêu
    gấp đôi hạn mức tải TVPL. Lệnh /sync trên Telegram khiến tình huống này rất
    dễ xảy ra.
    """
    lock_path = DATA_DIR / "pipeline.lock"
    lock_file = open(lock_path, "w")
    try:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(
                f"Một lần chạy khác đang giữ {lock_path}. Bỏ qua lần chạy này."
            )
        lock_file.write(str(os.getpid()))
        lock_file.flush()
        yield
    finally:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
        finally:
            lock_file.close()


def run_pipeline(
    dry_run: bool = False,
    moj_only: bool = False,
    skip_cloud: bool = False,
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
        "cloud_failed": 0,
        "cloud_skipped": 0,
        "reports_queued": 0,
        "save_failed": 0,
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
                # Mốc quét lấy từ watermark bền vững, không tính lại từ hôm nay:
                # cửa sổ trượt quét lại toàn bộ cửa sổ mỗi lần chạy, và máy tắt
                # lâu hơn cửa sổ là mất hẳn phần ở giữa mà không ai biết.
                cutoff, ly_do = get_crawl_cutoff(session, "moj")
                logger.info("MOJ scan: quét lùi tới %s (%s)", cutoff, ly_do)
                moj_items = scan_incremental(cutoff=cutoff)
                metrics["moj_new_found"] = len(moj_items)
                save_snapshot("moj_scan", moj_items)
                logger.info("MOJ scan: %d business items found", len(moj_items))
                # Chỉ dời watermark sau khi quét xong: dời sớm mà lượt quét hỏng
                # giữa chừng là bỏ sót vĩnh viễn phần chưa kịp lấy.
                update_crawl_watermark(
                    session, "moj", scan_incremental.last_high_water
                )
                session.commit()
            except Exception as e:
                logger.error("MOJ scan failed: %s", e)

            if not tvpl_items and not moj_items:
                # Mất nguồn hoàn toàn (Cloudflare chặn, API đổi, hết phiên) trông
                # y hệt một ngày yên tĩnh nếu vẫn ghi SUCCESS. Phải báo FAILED và
                # cảnh báo, nếu không hệ thống có thể chết hàng tuần mà không ai biết.
                msg = (
                    "Cả TVPL lẫn MOJ đều không trả về văn bản nào — nhiều khả năng "
                    "nguồn đã hỏng chứ không phải không có văn bản mới."
                )
                logger.error(msg)
                finish_crawl_run(
                    session, crawl_run, status="FAILED",
                    error_message=msg,
                    **metrics,
                )
                session.commit()
                try:
                    send_error_alert(msg)
                except Exception as e:
                    logger.error("Không gửi được cảnh báo: %s", e)
                return metrics

            # ── Step 2: Merge & dedupe across sources ──
            logger.info("=" * 60)
            logger.info("STEP 2: Merging & deduplicating")
            logger.info("=" * 60)

            candidates = merge_triggers(tvpl_items, moj_items)
            logger.info("Merged candidates: %d", len(candidates))

            # ── Step 3: Check DB for truly new documents ──
            rejected = load_rejected_doc_nums()
            skipped_known = 0

            new_docs: list[dict[str, Any]] = []
            for candidate in candidates:
                doc_num = candidate.get("doc_num", "")
                if not doc_num:
                    continue

                # Đã kiểm tra ở lần chạy trước và xác định không thuộc lĩnh vực
                # doanh nghiệp → khỏi tải lại chi tiết để rồi loại lần nữa.
                if doc_num in rejected:
                    skipped_known += 1
                    continue

                # Dùng resolver đầy đủ (moj_id → tvpl_id → doc_key) thay vì tra
                # theo số hiệu: số hiệu trùng giữa các tỉnh sẽ trả None và làm
                # văn bản đã có bị báo nhầm là mới.
                existing = resolve_existing_document(session, candidate)
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

            if skipped_known:
                logger.info(
                    "Bỏ qua %d văn bản đã xác định không thuộc lĩnh vực doanh nghiệp "
                    "ở các lần chạy trước.",
                    skipped_known,
                )

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
                    moj_match = search_by_doc_num(
                        doc_data["doc_num"], doc_data.get("title", "")
                    )
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
                            rejected.add(doc_data.get("doc_num", ""))
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

            save_rejected_doc_nums(rejected)

            # ── Step 4b: Download .docx from TVPL ──
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

            # Phải chạy trước vòng lặp bên dưới vì nó xoá key "_references"
            affected_docs = detect_affected_documents(session, enriched_docs)

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
                # Một văn bản hỏng KHÔNG được làm chết cả lượt cào. Trước đây
                # ngoại lệ ở đây làm session rơi vào PendingRollbackError, và
                # mọi văn bản còn lại trong lô cùng mất — kể cả những bản đã
                # tải về xong. Commit từng bản để lỗi chỉ giới hạn ở bản đó.
                try:
                    doc_obj, is_new = upsert_document(session, clean_data)
                    if refs:
                        insert_references(session, doc_obj.id, refs)
                    session.commit()
                except Exception as e:
                    session.rollback()
                    logger.error(
                        "Không lưu được %s: %s", clean_data.get("doc_num"), e
                    )
                    metrics["save_failed"] = metrics.get("save_failed", 0) + 1
                    continue

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

            if affected_docs:
                logger.info(
                    "Có %d văn bản cũ bị sửa đổi/thay thế (sự kiện C).",
                    len(affected_docs),
                )
                saved_docs.extend(affected_docs)

            # ── Step 6: Upload to Cloud Drive ──
            if not skip_cloud:
                provider = active_provider()
                logger.info("=" * 60)
                logger.info("STEP 6: Uploading to %s", provider)
                logger.info("=" * 60)
                if provider in (cloud_drive.LARK, cloud_drive.BOTH):
                    access = get_lark_client().check_access()
                    if not access["ok"]:
                        logger.warning("Lark Drive: %s", access["reason"])

                for doc_data in saved_docs:
                    existing = resolve_existing_document(session, doc_data)
                    try:
                        # Hồ sơ metadata gộp cả hai nguồn, đi kèm file trong thư mục
                        doc_data["metadata_path"] = save_document_metadata(doc_data)
                        outcome = cloud_drive.upload_document(doc_data)
                    except Exception as e:
                        logger.warning(
                            "Cloud Drive upload failed for %s: %s",
                            doc_data.get("doc_num"), e,
                        )
                        if existing:
                            enqueue_upload(session, existing, active_provider(),
                                           ["tat_ca"], str(e))
                        continue

                    if outcome.skipped:
                        metrics["cloud_skipped"] += 1
                        continue

                    doc_data.update(outcome.links)
                    if existing:
                        for column, value in outcome.links.items():
                            setattr(existing, column, value)

                    if outcome.failed:
                        # Thiếu dù chỉ một file cũng KHÔNG đánh dấu đã đồng bộ:
                        # cột này là cổng cho phép xoá file local, đánh dấu sớm
                        # là mất bản gốc mà trên mây cũng không có.
                        logger.warning(
                            "Chưa lên đủ %s: thiếu %s",
                            doc_data.get("doc_num"), ", ".join(outcome.failed),
                        )
                        if existing:
                            enqueue_upload(session, existing, outcome.provider,
                                           outcome.failed, "upload khong day du")
                        metrics["cloud_failed"] += 1
                        continue

                    if existing:
                        existing.cloud_synced_at = datetime.now(timezone.utc)
                        clear_upload_queue(session, existing.doc_key, outcome.provider)
                    metrics["gdrive_uploaded"] += 1

                    # Chỉ xoá .docx sau khi CHẮC CHẮN đã lên mây đủ. Toàn văn và
                    # metadata giữ lại vì tầng RAG đọc từ đĩa.
                    if AUTO_CLEANUP_LOCAL_FILES:
                        docx_p = doc_data.get("docx_path")
                        if docx_p and Path(docx_p).exists():
                            try:
                                Path(docx_p).unlink()
                                logger.info("Cleaned up local file: %s", docx_p)
                            except Exception as e:
                                logger.warning("Failed to delete local temp file %s: %s", docx_p, e)

                session.commit()


            # ── Step 7: (đã bỏ) bản tin Telegram về việc cào ──
            #
            # Cào dữ liệu chạy ngầm. Trước đây mỗi lần cào gửi một digest liệt
            # kê văn bản mới, nhưng đó là thông báo về CÔNG VIỆC NỘI BỘ của hệ
            # thống, không phải thứ cần người đọc quyết định gì. Kết quả cào
            # xem trực tiếp trên Google Drive; Telegram nay chỉ dùng để điều
            # khiển và nhận báo cáo (xem src/notification/report_commands.py).
            #
            # Vẫn đánh dấu notified_at: cột này là mốc "văn bản đã được đưa qua
            # vòng xử lý", và get_unnotified_documents() dựa vào nó. Để NULL
            # mãi thì mỗi lần chạy lại coi toàn bộ kho là chưa xử lý.
            now = datetime.now(timezone.utc)
            for doc_data in saved_docs:
                existing = resolve_existing_document(session, doc_data)
                if existing:
                    existing.notified_at = now
            session.commit()
            metrics["total_notified"] = len(saved_docs)
            logger.info("Đã cào %d văn bản (không gửi bản tin — xem trên Drive)",
                        len(saved_docs))

            # ── Step 8: Xếp hàng báo cáo phân tích văn bản mới ──
            #
            # XẾP HÀNG chứ không sinh báo cáo tại chỗ. Gọi mô hình mất tới 300
            # giây và lời gọi đó sẽ nằm trong khối try bao trọn hàm này — một
            # lỗi LLM đánh dấu cả lần cào là FAILED, kéo theo run_daily.sh bỏ
            # luôn hai bước đồng bộ vault và RAG. Báo cáo hỏng không được phép
            # làm hỏng ngày cào dữ liệu.
            logger.info("=" * 60)
            logger.info("STEP 8: Xếp hàng báo cáo")
            logger.info("=" * 60)
            try:
                queued = enqueue_update_reports(session, saved_docs)
                metrics["reports_queued"] = queued
                session.commit()
            except Exception as e:
                # Không để lỗi xếp hàng làm hỏng lần cào đã thành công.
                logger.error("Không xếp hàng được báo cáo: %s", e)

            # ── Step 9: Nối lại căn cứ biểu mẫu ──
            #
            # Biểu mẫu cào từ tháng trước dẫn tới những văn bản mà kho lúc đó
            # chưa có (đo trên mẫu thử: 2/2 căn cứ đều chưa có). Kho vừa lớn
            # thêm ở bước trên, nên đây là lúc rẻ nhất để nối lại — không phải
            # cào lại TVPL lần nào.
            try:
                from src.forms.store import noi_lai_can_cu

                noi_them = noi_lai_can_cu(session)
                metrics["form_refs_linked"] = noi_them
                session.commit()
            except Exception as e:
                logger.error("Không nối lại được căn cứ biểu mẫu: %s", e)

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


def run_upload_only(sync_after: bool = True) -> dict[str, int]:
    """
    Đẩy lên Lark Drive những văn bản đã có trong DB nhưng chưa upload được.

    Dùng khi lần chạy trước thất bại ở bước upload (chưa cấu hình
    LARK_ROOT_FOLDER_TOKEN, mất mạng…) — dữ liệu đã có sẵn dưới data/ nên không
    cần quét lại nguồn.
    """
    from src.storage.models import Document

    init_db()
    metrics = {"gdrive_uploaded": 0, "total_new": 0, "cloud_failed": 0,
               "cloud_skipped": 0}
    provider = active_provider()

    if provider in (cloud_drive.LARK, cloud_drive.BOTH):
        access = get_lark_client().check_access()
        if not access["ok"]:
            logger.error("Lark Drive chưa dùng được: %s", access["reason"])
            return metrics
        logger.info("Kho lưu trữ Lark: %s", access["folder_url"])

    with get_session() as session:
        # Không lọc theo file: văn bản chưa tải được .docx/toàn văn vẫn cần thư
        # mục riêng kèm metadata, để kho trên Drive phản ánh đủ danh sách văn bản.
        # Lọc theo cloud_synced_at chứ không theo lark_folder_token: cột token
        # chỉ đúng cho một đích lưu trữ, còn cổng đồng bộ thì chung cho cả hai.
        # Điều kiện "văn bản nền có lên mây không" đọc từ CÙNG một chỗ với
        # cloud_drive.upload_document. Trước đây chỗ này giữ bản sao cứng của
        # điều kiện đó, nên sau khi đổi mặc định sang "có đẩy", nhánh
        # --upload-only vẫn báo "0 văn bản chờ upload" trong khi kho có 3.443
        # văn bản chưa lên — hai nơi quyết định cùng một chính sách là đủ để
        # một nơi bị bỏ quên.
        query = session.query(Document).filter(Document.cloud_synced_at.is_(None))
        if not upload_closure_nodes():
            query = query.filter(
                (Document.is_closure_node.is_(None))
                | (Document.is_closure_node == False)  # noqa: E712
            )
        pending = query.all()
        metrics["total_new"] = len(pending)
        logger.info("Có %d văn bản chờ upload lên %s.", len(pending), provider)

        for doc in pending:
            doc_data = {
                col.name: getattr(doc, col.name) for col in Document.__table__.columns
            }
            doc_data["metadata_path"] = save_document_metadata(doc_data)

            try:
                outcome = cloud_drive.upload_document(doc_data)
            except Exception as e:
                logger.warning("Upload lỗi cho %s: %s", doc.doc_num, e)
                enqueue_upload(session, doc, provider, ["tat_ca"], str(e))
                metrics["cloud_failed"] += 1
                continue

            if outcome.skipped:
                metrics["cloud_skipped"] += 1
                continue

            for column, value in outcome.links.items():
                setattr(doc, column, value)

            if outcome.failed:
                enqueue_upload(session, doc, outcome.provider, outcome.failed,
                               "upload khong day du")
                metrics["cloud_failed"] += 1
                continue

            doc.cloud_synced_at = datetime.now(timezone.utc)
            clear_upload_queue(session, doc.doc_key, outcome.provider)
            metrics["gdrive_uploaded"] += 1
            session.commit()

    logger.info("Đã upload %d/%d văn bản.", metrics["gdrive_uploaded"], metrics["total_new"])

    # Step 8.1: Sync to Obsidian Vault (Phase 2)
    #
    # Bỏ qua được bằng --no-sync. Hai lý do: upload chỉ ghi legal_docs.db còn
    # index ghi rag.db, nên tách ra thì chạy song song với một lượt nhúng dài
    # được; và một lượt "chỉ upload" âm thầm index lại toàn kho là việc bên gọi
    # không yêu cầu.
    if not sync_after:
        logger.info("Bỏ qua đồng bộ vault/RAG theo yêu cầu (--no-sync).")
        return metrics

    try:
        from src.obsidian.vault_syncer import sync as sync_vault
        sync_vault()
        logger.info("Obsidian Vault sync completed.")
    except Exception as e:
        logger.warning("Obsidian Vault sync failed: %s", e)

    # Step 8.2: Index into RAG DB (Phase 3)
    try:
        from src.rag.db_rag import RAGDatabase
        from src.rag.rag_indexer import index_from_phase1
        rag_db = RAGDatabase()
        index_from_phase1(None, rag_db)
        logger.info("RAG Index sync completed.")
    except Exception as e:
        logger.warning("RAG Index sync failed: %s", e)

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
    # Tên cũ --skip-gdrive giữ lại làm bí danh: nó có trong run_daily.sh, trong
    # tài liệu bàn giao và trong thói quen gõ tay. Nhưng nó nói sai việc mình
    # làm — từ khi có bộ điều phối cloud_drive, cờ này bỏ qua CẢ Lark.
    parser.add_argument(
        "--skip-cloud", "--skip-gdrive",
        dest="skip_cloud",
        action="store_true",
        help="Không đẩy file lên mây (cả Google Drive lẫn Lark)",
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
        help="Chỉ upload các văn bản đã có trong DB nhưng chưa lên mây",
    )
    parser.add_argument(
        "--no-sync",
        action="store_true",
        help="Dùng với --upload-only: không đồng bộ vault/RAG sau khi upload",
    )
    parser.add_argument(
        "--sync-vault-only",
        action="store_true",
        help="Chỉ đồng bộ Obsidian Vault từ dữ liệu hiện có",
    )
    parser.add_argument(
        "--sync-rag-only",
        action="store_true",
        help="Chỉ đồng bộ RAG Database từ dữ liệu hiện có",
    )
    args = parser.parse_args()

    setup_logging()

    if args.upload_only:
        run_upload_only(sync_after=not args.no_sync)
        return

    if args.sync_vault_only:
        from src.obsidian.vault_syncer import sync as sync_vault
        sync_vault()
        logger.info("Obsidian Vault sync complete.")
        return

    if args.sync_rag_only:
        from src.rag.db_rag import RAGDatabase
        from src.rag.rag_indexer import index_from_phase1
        rag_db = RAGDatabase()
        index_from_phase1(None, rag_db)
        logger.info("RAG Index complete.")
        return

    logger.info("Pipeline starting at %s", datetime.now().isoformat())

    start_time = time.time()
    try:
        with pipeline_lock():
            metrics = run_pipeline(
                dry_run=args.dry_run,
                moj_only=args.moj_only,
                skip_cloud=args.skip_cloud,
                limit=args.limit,
            )
    except RuntimeError as e:
        # Lần chạy khác đang giữ khoá — thoát yên lặng, không phải lỗi.
        logger.warning("%s", e)
        return
    elapsed = time.time() - start_time

    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE in %.1fs", elapsed)
    logger.info("Metrics: %s", metrics)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()


