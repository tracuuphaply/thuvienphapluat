"""
Deep Research & Harvest Utility for Active Business Legal Documents (Pre-2026 to Present).

Scans MOJ API across all 10 business legal fields for active laws, decrees, circulars, and decisions
issued before 2026 that are currently in effect (Còn hiệu lực / Chưa có hiệu lực), skipping expired laws.

Usage:
  python scripts/deep_research_active_laws.py [--max-docs 200]
"""
import sys
import time
import json
import logging
import argparse
from pathlib import Path
from datetime import date, timedelta

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import DATA_DIR, BUSINESS_FIELD_CODES, MOJ_FIELD_KEYWORDS
from src.storage.database import get_session, get_document_by_doc_num, upsert_document, insert_references
from src.storage.models import Document, DocumentReference
from src.sources.moj_api import fetch_doc_list, _extract_items, fetch_doc_detail, parse_doc_detail, title_looks_business
from src.pipeline.text_processor import process_fulltext
from src.obsidian.vault_syncer import sync as sync_vault
from src.rag.db_rag import RAGDatabase
from src.rag.rag_indexer import index_from_phase1
from src.storage.lark_drive import upload_document_files_lark
from src.storage.file_store import save_document_metadata


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

def deep_research_active_laws(max_pages: int = 50, max_docs: int = 200):
    """
    Deep scan MOJ API for historical active legal documents in business fields.
    """
    logger.info("============================================================")
    logger.info("STARTING DEEP RESEARCH: Harvesting Active Business Laws")
    logger.info("============================================================")
    
    added_docs = []
    skipped_expired = []
    already_exists = 0
    
    with get_session() as session:
        for page in range(1, max_pages + 1):
            if len(added_docs) >= max_docs:
                logger.info(f"Reached max documents limit ({max_docs}). Stopping harvest.")
                break
                
            logger.info(f"Scanning MOJ API Page {page}/{max_pages}...")
            try:
                resp_json = fetch_doc_list(page=page, page_size=100)
            except Exception as e:
                logger.error(f"Error fetching page {page}: {e}")
                break
                
            items = _extract_items(resp_json)
            if not items:
                logger.info("No more items returned from MOJ API.")
                break
                
            for item in items:
                if len(added_docs) >= max_docs:
                    break
                    
                doc_num = (item.get("docNum") or "").strip()
                if not doc_num:
                    continue
                    
                # 1. Check if title looks business-related
                if not title_looks_business(item):
                    continue
                    
                # 2. Check if already in DB
                existing = get_document_by_doc_num(session, doc_num)
                if existing:
                    already_exists += 1
                    continue
                    
                moj_id = str(item.get("id") or "")
                if not moj_id:
                    continue
                    
                # 3. Fetch detail to inspect eff_status & fulltext
                try:
                    detail_html = fetch_doc_detail(moj_id)
                    time.sleep(0.3)
                except Exception as e:
                    logger.warning(f"Failed to fetch detail for {doc_num} ({moj_id}): {e}")
                    continue
                    
                if not detail_html:
                    continue
                    
                detail_data = parse_doc_detail(detail_html)
                eff_status = detail_data.get("eff_status", "")
                
                # 4. FILTER: Only keep active laws (Còn hiệu lực / Chưa có hiệu lực / Hết hiệu lực một phần)
                lowered_status = eff_status.lower()
                if "hết hiệu lực toàn bộ" in lowered_status or "bị bãi bỏ" in lowered_status or "hủy bỏ" in lowered_status:
                    logger.info(f"⏩ SKIP EXPIRED: [{doc_num}] — Status: {eff_status}")
                    skipped_expired.append(doc_num)
                    continue
                    
                logger.info(f"✨ HARVESTED ACTIVE LAW: [{doc_num}] — {detail_data.get('title', '')[:80]}... (Status: {eff_status})")
                
                # Process fulltext & chunks
                fulltext_html = detail_data.pop("fulltext_html", "")
                references = detail_data.pop("references", [])
                
                if fulltext_html:
                    text_res = process_fulltext(
                        doc_id=moj_id,
                        html_content=fulltext_html,
                        doc_num=doc_num
                    )
                    detail_data["clean_text_path"] = text_res.get("clean_text_path")
                    detail_data["chunks_path"] = text_res.get("chunks_path")
                    detail_data["has_fulltext"] = True
                    detail_data["has_chunks"] = text_res.get("chunk_count", 0) > 0

                # Upsert to SQLite
                doc_obj, is_new = upsert_document(session, detail_data)
                session.commit()
                
                if references:
                    insert_references(session, doc_obj.id, references)
                    session.commit()
                    
                added_docs.append({
                    "doc_num": doc_num,
                    "title": detail_data.get("title"),
                    "doc_type": detail_data.get("doc_type"),
                    "issue_date": detail_data.get("issue_date"),
                    "eff_status": eff_status,
                    "field_name": detail_data.get("field_name"),
                })
                
                # Save metadata JSON file for Obsidian / Lark
                doc_dict = {col.name: getattr(doc_obj, col.name) for col in Document.__table__.columns}
                save_document_metadata(doc_dict)

    logger.info("============================================================")
    logger.info("HARVEST COMPLETE SUMMARY:")
    logger.info(f"  - Newly Harvested Active Laws: {len(added_docs)}")
    logger.info(f"  - Filtered Out Expired Laws:   {len(skipped_expired)}")
    logger.info(f"  - Already Existed in DB:       {already_exists}")
    logger.info("============================================================")

    # Re-sync Vault & RAG DB
    logger.info("Syncing to Obsidian Vault...")
    sync_vault()
    
    logger.info("Re-indexing RAG Database with Vector Embeddings...")
    rag_db = RAGDatabase()
    index_from_phase1(None, rag_db)
    
    logger.info("Uploading new harvested documents to Lark Drive...")
    try:
        from src.storage.lark_drive import upload_document_files_lark
        with get_session() as session:
            pending_lark = session.query(Document).filter(Document.lark_folder_token.is_(None)).all()
            logger.info(f"Found {len(pending_lark)} documents pending Lark Drive upload.")
            for doc in pending_lark:
                doc_data = {col.name: getattr(doc, col.name) for col in Document.__table__.columns}
                res = upload_document_files_lark(doc_data)
                if res.get("lark_folder_token"):
                    doc.lark_folder_token = res.get("lark_folder_token")
                    doc.lark_docx_link = res.get("lark_docx_link")
                    session.commit()
    except Exception as e:
        logger.warning(f"Lark Drive upload sweep warning: {e}")
        
    return added_docs

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deep Research Active Business Laws")
    parser.add_argument("--max-pages", type=int, default=30)
    parser.add_argument("--max-docs", type=int, default=100)
    args = parser.parse_args()
    
    deep_research_active_laws(max_pages=args.max_pages, max_docs=args.max_docs)
