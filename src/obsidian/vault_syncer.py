"""
Incremental synchronization between database and Obsidian vault.
"""
import hashlib
import json
from pathlib import Path
import structlog

from src.obsidian.config_obsidian import VAULT_DIR
from src.obsidian.vault_exporter import load_clean_text, sanitize_filename, export_document_to_md
from src.storage.database import get_session
from src.storage.models import Document, DocumentReference
from src.config import DATA_DIR

logger = structlog.get_logger(__name__)

def get_content_hash(content: str) -> str:
    """Calculate SHA-256 hash of a string."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def sync(vault_dir: Path = VAULT_DIR) -> None:
    """Incrementally sync documents to Obsidian based on hash."""
    docs_dir = vault_dir / "Documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    
    meta_dir = DATA_DIR / "metadata"
    clean_dir = DATA_DIR / "clean_text"
    
    stats = {"new": 0, "updated": 0, "skipped": 0, "deleted": 0}
    
    with get_session() as session:
        for meta_file in meta_dir.glob("*.json"):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    doc_data = json.load(f)
                    
                doc_num = doc_data.get("doc_num")
                if not doc_num:
                    continue
                    
                db_doc = session.query(Document).filter(Document.doc_num == doc_num).first()
                if not db_doc:
                    continue
                    
                content = load_clean_text(doc_data, clean_dir)
                        
                references = []
                db_refs = session.query(DocumentReference).filter(
                    DocumentReference.source_doc_id == db_doc.id
                ).all()
                references = [{"relation_type": r.relation_type, "target_doc_num": r.target_doc_num} for r in db_refs]
                
                md_content = export_document_to_md(doc_data, content, references)
                new_hash = get_content_hash(md_content)
                
                safe_name = sanitize_filename(doc_num)
                out_path = docs_dir / f"{safe_name}.md"
                
                # Check if it needs updating
                if db_doc.obsidian_hash == new_hash and out_path.exists():
                    stats["skipped"] += 1
                    continue
                    
                # Write file
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(md_content)
                    
                # Update DB
                db_doc.obsidian_path = str(out_path.relative_to(vault_dir))
                db_doc.obsidian_hash = new_hash
                
                if not getattr(db_doc, "obsidian_path", None):
                    stats["new"] += 1
                else:
                    stats["updated"] += 1
                    
            except Exception as e:
                logger.error("Failed to sync document", file=meta_file.name, error=str(e))
                
        session.commit()
        
    logger.info("Vault sync completed", **stats)

if __name__ == "__main__":
    sync()
