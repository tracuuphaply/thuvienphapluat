"""
Incremental synchronization between database and Obsidian vault.
"""
import hashlib
from pathlib import Path
import structlog

from src.obsidian.config_obsidian import VAULT_DIR
from src.obsidian.vault_exporter import (
    build_link_resolver,
    document_to_export_dict,
    export_document_to_md,
    load_clean_text,
    note_filename,
)
from src.storage.database import get_session
from src.storage.models import Document, DocumentReference
from src.config import DATA_DIR

logger = structlog.get_logger(__name__)

def get_content_hash(content: str) -> str:
    """Calculate SHA-256 hash of a string."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def sync(vault_dir: Path = VAULT_DIR) -> None:
    """Đồng bộ tăng dần từ cơ sở dữ liệu sang vault, so sánh theo SHA-256.

    Nguồn dữ liệu là bảng documents, không phải data/metadata/*.json. Các file
    JSON đó được ghi lúc cào và không cập nhật lại, nên bản cũ đọc từ đĩa khiến
    mọi sửa đổi trong cơ sở dữ liệu không bao giờ tới được vault — đó là lý do
    1015/1015 note vẫn render "[Bộ Tư pháp]()" sau khi cột moj_url đã đủ dữ liệu.
    """
    docs_dir = vault_dir / "Documents"
    docs_dir.mkdir(parents=True, exist_ok=True)

    clean_dir = DATA_DIR / "clean_text"
    stats = {"new": 0, "updated": 0, "skipped": 0, "deleted": 0}

    with get_session() as session:
        link_resolver = build_link_resolver(session)
        expected: set[str] = set()
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
                new_hash = get_content_hash(md_content)
                out_path = docs_dir / f"{note_filename(db_doc)}.md"
                expected.add(out_path.name)

                if db_doc.obsidian_hash == new_hash and out_path.exists():
                    stats["skipped"] += 1
                    continue

                is_new = not db_doc.obsidian_path
                out_path.write_text(md_content, encoding="utf-8")

                db_doc.obsidian_path = str(out_path.relative_to(vault_dir))
                db_doc.obsidian_hash = new_hash
                stats["new" if is_new else "updated"] += 1

            except Exception as e:
                logger.error("Failed to sync document", doc_num=db_doc.doc_num, error=str(e))

        stats["deleted"] = _remove_orphans(docs_dir, expected)
        session.commit()

    logger.info("Vault sync completed", **stats)


def _remove_orphans(docs_dir: Path, expected: set[str]) -> int:
    """Xoá note không còn ứng với văn bản nào trong kho.

    Cần thiết vì tên note đổi khi public_slug được điền: bản cũ đặt theo số
    hiệu trần sẽ nằm lại vĩnh viễn và hiện song song với bản mới trên sơ đồ
    tư duy. Thư mục này do máy sinh toàn bộ nên xoá là an toàn, nhưng vẫn ghi
    log từng file để đối chiếu được.
    """
    removed = 0
    for path in docs_dir.glob("*.md"):
        if path.name in expected:
            continue
        logger.info("xoa_note_mo_coi", file=path.name)
        path.unlink()
        removed += 1
    return removed

if __name__ == "__main__":
    sync()
