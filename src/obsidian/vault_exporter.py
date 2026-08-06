"""
Export legal documents from SQLite/JSON to Obsidian Markdown format.
"""
import json
import re
from pathlib import Path
from typing import List, Dict, Any
import structlog

from src.obsidian.config_obsidian import VAULT_DIR, OBSIDIAN_TEMPLATE
from src.obsidian.industry_classifier import classify_industries
from src.storage.database import get_session
from src.storage.models import Document, DocumentReference
from src.config import DATA_DIR, BUSINESS_FIELDS

logger = structlog.get_logger(__name__)

def sanitize_filename(name: str) -> str:
    """Sanitize a string to be used as a filename."""
    if not name:
        return "Unknown"
    # Replace slashes and other unsafe characters with hyphens
    s = re.sub(r'[/\\:*?"<>|]', '-', name)
    return s.strip()


def load_clean_text(doc_data: Dict[str, Any], clean_dir: Path) -> str:
    """Đọc toàn văn đã làm sạch của một văn bản.

    data/metadata/ đặt tên theo số hiệu còn data/clean_text/ đặt tên theo UUID,
    nên không thể suy đường dẫn từ tên file metadata. Chính metadata đã có sẵn
    trường clean_text_path trỏ đúng file — dùng nó, chỉ đoán khi trường này thiếu.
    """
    candidates = []

    stored = doc_data.get("clean_text_path")
    if stored:
        p = Path(stored)
        candidates.append(p if p.is_absolute() else Path.cwd() / p)
        candidates.append(clean_dir / p.name)

    for key in ("moj_id", "tvpl_id", "doc_num"):
        val = doc_data.get(key)
        if val:
            candidates.append(clean_dir / f"{sanitize_filename(str(val))}.md")

    for path in candidates:
        try:
            if path.exists():
                return path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

    logger.warning("khong_tim_thay_toan_van", doc_num=doc_data.get("doc_num"))
    return ""

def format_yaml_list(items: List[str]) -> str:
    """Format a list of strings into a YAML list."""
    if not items:
        return "[]"
    formatted = [f'"{item}"' for item in items]
    return f"[{', '.join(formatted)}]"

def export_document_to_md(doc_data: Dict[str, Any], content: str, references: List[Dict[str, Any]]) -> str:
    """
    Format a document's data and content into an Obsidian Markdown string.
    """
    doc_num = doc_data.get("doc_num") or "Unknown"
    title = doc_data.get("title") or ""
    
    # Clean up double quotes in title for YAML
    safe_title = title.replace('"', '\\"')
    
    fields = []
    if doc_data.get("field_name"):
        fields.append(doc_data.get("field_name"))
        
    industries = classify_industries(title, doc_data.get("field_name"), content)
    
    # Build YAML arrays
    fields_yaml = format_yaml_list(fields)
    industries_yaml = format_yaml_list(industries)
    aliases_yaml = format_yaml_list([doc_num])
    
    tags = ["document"]
    if doc_data.get("doc_type"):
        # Create a tag like #Nghi_dinh
        safe_type = re.sub(r'\s+', '_', doc_data.get("doc_type").strip())
        tags.append(safe_type)
    tags_yaml = format_yaml_list(tags)
    
    # Format references as WikiLinks
    refs_md = ""
    if references:
        refs_lines = []
        for ref in references:
            rel_type = ref.get("relation_type", "Liên quan")
            target = ref.get("target_doc_num", "")
            if target:
                safe_target = sanitize_filename(target)
                refs_lines.append(f"- {rel_type}: [[{safe_target}]]")
        refs_md = "\n".join(refs_lines)
    else:
        refs_md = "- Không có văn bản liên quan"
        
    md_content = OBSIDIAN_TEMPLATE.format(
        doc_num=doc_num,
        title=safe_title,
        doc_type=doc_data.get("doc_type") or "",
        issue_date=doc_data.get("issue_date") or "",
        eff_from=doc_data.get("eff_from") or "",
        eff_to=doc_data.get("eff_to") or "",
        eff_status=doc_data.get("eff_status") or "",
        agency=doc_data.get("agency_name") or "",
        fields=fields_yaml,
        industries=industries_yaml,
        source_tvpl=str(doc_data.get("source_tvpl", False)).lower(),
        source_moj=str(doc_data.get("source_moj", False)).lower(),
        tvpl_url=doc_data.get("tvpl_url") or "",
        moj_url=doc_data.get("moj_url") or "",
        aliases=aliases_yaml,
        tags=tags_yaml,
        fields_str=", ".join(fields) if fields else "Không xác định",
        industries_str=", ".join(industries) if industries else "Không xác định",
        references_md=refs_md,
        content=content
    )
    
    return md_content

def export_all(vault_dir: Path = VAULT_DIR) -> None:
    """Export all documents from the database to the Obsidian vault."""
    docs_dir = vault_dir / "Documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    
    meta_dir = DATA_DIR / "metadata"
    clean_dir = DATA_DIR / "clean_text"
    
    if not meta_dir.exists():
        logger.warning("Metadata directory not found", dir=str(meta_dir))
        return
        
    count = 0
    with get_session() as session:
        for meta_file in meta_dir.glob("*.json"):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    doc_data = json.load(f)
                    
                doc_num = doc_data.get("doc_num")
                if not doc_num:
                    continue
                    
                content = load_clean_text(doc_data, clean_dir)
                        
                # Get references from DB
                db_doc = session.query(Document).filter(Document.doc_num == doc_num).first()
                references = []
                if db_doc:
                    db_refs = session.query(DocumentReference).filter(
                        DocumentReference.source_doc_id == db_doc.id
                    ).all()
                    references = [{"relation_type": r.relation_type, "target_doc_num": r.target_doc_num} for r in db_refs]
                
                md_content = export_document_to_md(doc_data, content, references)
                
                safe_name = sanitize_filename(doc_num)
                out_path = docs_dir / f"{safe_name}.md"
                
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(md_content)
                    
                count += 1
                
            except Exception as e:
                logger.error("Failed to export document", file=meta_file.name, error=str(e))
                
    logger.info("Exported documents to Obsidian vault", count=count, vault_dir=str(vault_dir))

if __name__ == "__main__":
    export_all()
