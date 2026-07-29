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

from src.config import BUSINESS_FIELDS
from src.notification.telegram_bot import (
    build_daily_digest,
    send_daily_digest,
    send_error_alert,
)
from src.pipeline.deduplicator import merge_triggers
from src.sources.moj_api import fetch_doc_detail, parse_doc_detail, scan_incremental
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
from src.storage.file_store import save_moj_fulltext, save_snapshot
from src.storage.gdrive import upload_document_files
from src.pipeline.text_processor import process_fulltext

logger = logging.getLogger(__name__)


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
                # MOJ enrichment: fetch full detail + references
                moj_id = doc_data.get("moj_id")
                if moj_id:
                    try:
                        detail_resp = fetch_doc_detail(moj_id)
                        detail = parse_doc_detail(detail_resp)

                        # Merge enriched data
                        for key, value in detail.items():
                            if key not in ("references", "fulltext_html") and value:
                                doc_data.setdefault(key, value)

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
                        "pub_date", "field_slug", "references",
                        "fulltext_html",
                    )
                }
                doc_obj, is_new = upsert_document(session, clean_data)

                # Insert references
                if refs:
                    insert_references(session, doc_obj.id, refs)

                # Collect for notification
                saved_data = {**clean_data, "id": doc_obj.id}
                saved_docs.append(saved_data)

            session.commit()
            logger.info("Saved %d documents to database.", len(saved_docs))

            # ── Step 6: Upload to Google Drive ──
            if not skip_gdrive:
                logger.info("=" * 60)
                logger.info("STEP 6: Uploading to Google Drive")
                logger.info("=" * 60)

                for doc_data in saved_docs:
                    try:
                        gdrive_result = upload_document_files(doc_data)
                        if gdrive_result.get("gdrive_docx_link") or gdrive_result.get("gdrive_pdf_link"):
                            doc_data.update(gdrive_result)
                            # Update DB with Drive links
                            existing = get_document_by_doc_num(
                                session, doc_data["doc_num"]
                            )
                            if existing:
                                existing.gdrive_docx_link = gdrive_result.get("gdrive_docx_link")
                                existing.gdrive_pdf_link = gdrive_result.get("gdrive_pdf_link")
                                existing.gdrive_folder_id = gdrive_result.get("gdrive_folder_id")
                            metrics["gdrive_uploaded"] += 1
                    except Exception as e:
                        logger.warning("GDrive upload failed for %s: %s", doc_data.get("doc_num"), e)

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
    args = parser.parse_args()

    setup_logging()
    logger.info("Pipeline starting at %s", datetime.now().isoformat())

    start_time = time.time()
    metrics = run_pipeline(
        dry_run=args.dry_run,
        moj_only=args.moj_only,
        skip_gdrive=args.skip_gdrive,
    )
    elapsed = time.time() - start_time

    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE in %.1fs", elapsed)
    logger.info("Metrics: %s", metrics)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
