"""
Export legal documents from SQLite/JSON to Obsidian Markdown format.
"""
import re
from pathlib import Path
from typing import List, Dict, Any
import structlog

from src.legal import effectivity
from src.legal.hierarchy import LEVEL_NON_NORMATIVE
from src.legal.provinces import province_name
from src.obsidian.config_obsidian import (
    HIERARCHY_LABELS,
    OBSIDIAN_TEMPLATE,
    VAULT_DIR,
)
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

# Các trường mà template và load_clean_text() cần. Lấy thẳng từ ORM thay vì đọc
# data/metadata/*.json: các file đó là bản sao được ghi lúc cào, nên mọi lần sửa
# dữ liệu trong cơ sở dữ liệu đều không bao giờ tới được vault. Đúng lỗi đã làm
# 1015/1015 note render "[Bộ Tư pháp]()" dù cột moj_url đã được điền đủ.
_EXPORT_FIELDS = (
    "doc_num", "doc_key", "title", "doc_type", "issue_date", "pub_date",
    "eff_from", "eff_to", "eff_status", "agency_name", "signer",
    "field_name", "field_code", "source_tvpl", "source_moj",
    "tvpl_id", "moj_id", "tvpl_url", "moj_url",
    "clean_text_path", "public_slug", "industries",
    "hierarchy_level", "doc_type_norm", "is_vbqppl",
    "territorial_scope", "province_code_raw", "province_code_current",
    "eff_state", "eff_state_as_of",
)


def document_to_export_dict(doc: Document) -> Dict[str, Any]:
    """Bản ghi ORM → dict mà export_document_to_md() và load_clean_text() dùng."""
    return {field: getattr(doc, field, None) for field in _EXPORT_FIELDS}


def format_yaml_list(items: List[str]) -> str:
    """Format a list of strings into a YAML list."""
    if not items:
        return "[]"
    formatted = [f'"{item}"' for item in items]
    return f"[{', '.join(formatted)}]"

def build_link_resolver(session) -> Dict[str, str]:
    """Bảng tra số hiệu → tên note, để wikilink trỏ đúng file.

    Chỉ nhận số hiệu duy nhất trong kho. Số hiệu xuất hiện ở nhiều tỉnh thì bản
    thân dẫn chiếu đã mơ hồ — không có căn cứ để chọn tỉnh nào, nên để link ở
    dạng chưa phân giải thay vì đoán và trỏ nhầm sang văn bản của tỉnh khác.
    """
    counts: Dict[str, int] = {}
    slugs: Dict[str, str] = {}
    for doc_num, slug in session.query(Document.doc_num, Document.public_slug).all():
        counts[doc_num] = counts.get(doc_num, 0) + 1
        slugs[doc_num] = slug or sanitize_filename(doc_num)
    return {num: slug for num, slug in slugs.items() if counts[num] == 1}


def export_document_to_md(
    doc_data: Dict[str, Any],
    content: str,
    references: List[Dict[str, Any]],
    link_resolver: Dict[str, str] | None = None,
) -> str:
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
                # Tên note của văn bản đích, không phải số hiệu đã làm sạch:
                # note của văn bản cấp tỉnh đặt theo public_slug nên link theo
                # số hiệu trần sẽ trỏ vào một file không tồn tại.
                safe_target = (link_resolver or {}).get(target) or sanitize_filename(target)
                refs_lines.append(f"- {rel_type}: [[{safe_target}]]")
        refs_md = "\n".join(refs_lines)
    else:
        refs_md = "- Không có văn bản liên quan"
        
    # Dữ kiện pháp lý suy được. Trước đây note chỉ có chuỗi doc_type, nên người
    # đọc (và mô hình sinh báo cáo) phải tự đoán văn bản nào có hiệu lực cao hơn.
    level = doc_data.get("hierarchy_level")
    level = LEVEL_NON_NORMATIVE if level is None else int(level)
    eff_state = doc_data.get("eff_state") or effectivity.KHONG_RO
    scope = doc_data.get("territorial_scope") or "khong_xac_dinh"
    province = province_name(doc_data.get("province_code_current"))

    if scope == "tinh":
        scope_label = f"Địa phương — {province}" if province else "Địa phương (chưa rõ tỉnh)"
    elif scope == "trung_uong":
        scope_label = "Toàn quốc"
    else:
        scope_label = "Chưa xác định"

    md_content = OBSIDIAN_TEMPLATE.format(
        doc_num=doc_num,
        title=safe_title,
        doc_type=doc_data.get("doc_type") or "",
        doc_type_norm=doc_data.get("doc_type_norm") or "",
        hierarchy_level=level,
        hierarchy_label=HIERARCHY_LABELS.get(level, HIERARCHY_LABELS[LEVEL_NON_NORMATIVE]),
        is_vbqppl=str(bool(doc_data.get("is_vbqppl"))).lower(),
        territorial_scope=scope,
        province=province,
        scope_label=scope_label,
        eff_state=eff_state,
        eff_state_label=effectivity.label(eff_state),
        eff_state_as_of=doc_data.get("eff_state_as_of") or "",
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
    """Dựng lại toàn bộ vault từ cơ sở dữ liệu.

    Duyệt bảng documents chứ không duyệt data/metadata/*.json: văn bản chưa kịp
    ghi file metadata vẫn phải có note, và metadata trên đĩa là bản sao có thể
    đã cũ so với cơ sở dữ liệu.
    """
    docs_dir = vault_dir / "Documents"
    docs_dir.mkdir(parents=True, exist_ok=True)

    clean_dir = DATA_DIR / "clean_text"
    count = 0

    with get_session() as session:
        link_resolver = build_link_resolver(session)
        for db_doc in session.query(Document).order_by(Document.id).all():
            try:
                doc_data = document_to_export_dict(db_doc)
                content = load_clean_text(doc_data, clean_dir)

                db_refs = session.query(DocumentReference).filter(
                    DocumentReference.source_doc_id == db_doc.id
                ).all()
                references = [
                    {"relation_type": r.relation_type, "target_doc_num": r.target_doc_num}
                    for r in db_refs
                ]

                md_content = export_document_to_md(
                    doc_data, content, references, link_resolver
                )
                out_path = docs_dir / f"{note_filename(db_doc)}.md"
                out_path.write_text(md_content, encoding="utf-8")
                count += 1

            except Exception as e:
                logger.error("Failed to export document", doc_num=db_doc.doc_num, error=str(e))

    logger.info("Exported documents to Obsidian vault", count=count, vault_dir=str(vault_dir))


def note_filename(doc: Document) -> str:
    """Tên file note của một văn bản, không đuôi.

    Ưu tiên public_slug vì số hiệu trần đụng nhau giữa các tỉnh — hai văn bản
    "40/2026/QĐ-UBND" của hai tỉnh sẽ ra cùng một file và bản sau ghi đè bản
    trước mà không báo gì. Lùi về số hiệu khi slug chưa được điền.
    """
    return doc.public_slug or sanitize_filename(doc.doc_num)

if __name__ == "__main__":
    export_all()
