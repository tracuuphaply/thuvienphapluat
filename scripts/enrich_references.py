"""
KHÔNG DÙNG NỮA — đã được thay bằng scripts/backfill_cited_documents.py.

Script này không hoạt động: nó tra văn bản đích bằng `search_by_doc_num`, mà
endpoint /doc/all của Bộ Tư pháp bỏ qua mọi tham số lọc nên hàm đó gần như luôn
trả None. Ngoài ra nó còn BỎ QUA văn bản đích đã hết hiệu lực thay vì ghi nhận
— kể cả "Hết hiệu lực một phần", vốn vẫn còn hiệu lực ở phần chưa bị sửa — nên
cạnh trỏ tới các văn bản đó mãi mãi không phân giải được và không phân biệt
được với "không tìm thấy".

Dùng thay thế:
    python -m scripts.backfill_cited_documents --limit 701

Bản mới lấy `targetDocument.id` có sẵn trong payload quan hệ rồi fetch theo id,
và nạp mọi văn bản đích kèm trạng thái hiệu lực thật.

Giữ lại file để tham khảo lịch sử.

Usage (cũ):
  python scripts/enrich_references.py
"""
import sys
import time
import json
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import DATA_DIR
from src.storage.database import get_session, get_document_by_doc_num, upsert_document
from src.storage.models import Document, DocumentReference
from src.sources.moj_api import search_by_doc_num, fetch_doc_detail, parse_doc_detail
from src.pipeline.text_processor import process_fulltext
from src.obsidian.vault_syncer import sync as sync_vault
from src.rag.db_rag import RAGDatabase
from src.rag.rag_indexer import index_from_phase1

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def backfill_referenced_documents(limit: int = 100):
    """
    Find target_doc_num in document_references without target_doc_id,
    query MOJ API, and only enrich/download if document is IN EFFECT.
    """
    logger.info("Starting connected documents enrichment sweep...")
    
    with get_session() as session:
        # Find all unlinked references
        unlinked_refs = session.query(DocumentReference).filter(
            DocumentReference.target_doc_id.is_(None)
        ).all()
        
        target_nums = list(set([r.target_doc_num for r in unlinked_refs if r.target_doc_num]))
        logger.info(f"Found {len(target_nums)} unique connected document numbers to inspect.")
        
        added_count = 0
        skipped_expired_count = 0
        not_found_count = 0
        
        for idx, target_num in enumerate(target_nums[:limit]):
            # Check if doc already exists in master table
            existing = get_document_by_doc_num(session, target_num)
            if existing:
                # Link existing doc
                for ref in unlinked_refs:
                    if ref.target_doc_num == target_num:
                        ref.target_doc_id = existing.id
                session.commit()
                continue
                
            logger.info(f"[{idx+1}/{min(len(target_nums), limit)}] Searching MOJ for connected document: {target_num}...")
            
            # Query MOJ API
            search_info = search_by_doc_num(target_num)
            time.sleep(0.5)
            
            if not search_info or not isinstance(search_info, dict):
                not_found_count += 1
                continue
                
            moj_id = search_info.get("moj_id")
            if not moj_id:
                not_found_count += 1
                continue

                
            # Fetch detail from MOJ to inspect eff_status & fulltext
            detail_html = fetch_doc_detail(moj_id)
            time.sleep(0.5)
            
            if not detail_html:
                not_found_count += 1
                continue
                
            detail_data = parse_doc_detail(detail_html)
            eff_status = detail_data.get("eff_status", "")
            
            # FILTER CONSTRAINT: Skip expired / ineffective documents
            if "hết hiệu lực" in eff_status.lower() or "bị bãi bỏ" in eff_status.lower() or "hủy bỏ" in eff_status.lower():
                logger.info(f"⏩ SKIP (Expired/Bãi bỏ): {target_num} — Trạng thái: {eff_status}")
                skipped_expired_count += 1
                continue
                
            logger.info(f"✅ ACCEPT (Còn/Chưa hiệu lực): {target_num} — Trạng thái: {eff_status}")
            
            # Process fulltext & chunks
            fulltext_html = detail_data.get("fulltext_html", "")
            if fulltext_html:
                text_result = process_fulltext(
                    doc_id=moj_id,
                    html_content=fulltext_html,
                    doc_num=target_num,
                )
                detail_data["clean_text_path"] = text_result.get("clean_text_path")
                detail_data["chunks_path"] = text_result.get("chunks_path")
                detail_data["has_fulltext"] = True
                detail_data["has_chunks"] = text_result.get("chunk_count", 0) > 0


            # Remove non-column keys before SQLAlchemy constructor
            sub_refs = detail_data.pop("references", [])
            detail_data.pop("fulltext_html", None)

            # Insert document to master DB
            doc_obj, is_new = upsert_document(session, detail_data)
            session.commit()

            
            # Link references
            for ref in unlinked_refs:
                if ref.target_doc_num == target_num:
                    ref.target_doc_id = doc_obj.id
            session.commit()
            
            added_count += 1
            
        logger.info("=" * 60)
        logger.info(f"Enrichment Sweep Complete:")
        logger.info(f"  - Added active connected docs: {added_count}")
        logger.info(f"  - Filtered out expired docs:   {skipped_expired_count}")
        logger.info(f"  - Not found on MOJ API:         {not_found_count}")
        logger.info("=" * 60)

    # Re-sync Vault & RAG DB
    logger.info("Syncing Obsidian Vault...")
    sync_vault()
    
    logger.info("Re-indexing RAG DB...")
    rag_db = RAGDatabase()
    index_from_phase1(None, rag_db)
    logger.info("All sync complete!")

if __name__ == "__main__":
    backfill_referenced_documents(limit=50)
