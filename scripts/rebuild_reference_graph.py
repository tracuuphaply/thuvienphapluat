"""
Dựng lại đồ thị quan hệ văn bản bằng bảng ánh xạ referenceType đã kiểm chứng.

Đồ thị cũ được sinh bằng bảng ánh xạ suy đoán: mã 3 (82% tổng số cạnh) là
"Căn cứ" nhưng bị ghi thành "Bãi bỏ", còn mã 10 và 12 — chính là "Sửa đổi,
bổ sung" và "Thay thế" — thì không có trong bảng nên bị dồn hết vào "Liên quan".

Không thể sửa bằng cách đổi tên nhãn: nhãn "Liên quan" đã trộn lẫn nhiều mã
khác nhau, không tách ngược ra được. Phải lấy lại quan hệ từ nguồn.

Chạy:  python -m scripts.rebuild_reference_graph [--dry-run]
"""
import argparse
import logging
import sys
import time

from src.rag.db_rag import RAGDatabase
from src.sources.moj_api import fetch_doc_detail, parse_doc_detail
from src.storage.database import get_session, insert_references, resolve_reference_targets
from src.storage.models import Document, DocumentReference

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def rebuild(dry_run: bool = False, sleep: float = 0.25) -> dict:
    stats = {"van_ban": 0, "loi": 0, "canh_cu": 0, "canh_moi": 0}

    with get_session() as session:
        docs = (
            session.query(Document)
            .filter(Document.moj_id.isnot(None))
            .order_by(Document.id)
            .all()
        )
        stats["canh_cu"] = session.query(DocumentReference).count()
        logger.info("Sẽ dựng lại quan hệ cho %d văn bản (đang có %d cạnh)",
                    len(docs), stats["canh_cu"])

        for doc in docs:
            try:
                parsed = parse_doc_detail(fetch_doc_detail(doc.moj_id))
            except Exception as e:
                stats["loi"] += 1
                logger.warning("  bỏ qua %s: %s", doc.doc_num, type(e).__name__)
                time.sleep(sleep)
                continue

            refs = parsed.get("references") or []
            if not dry_run:
                # Xoá cạnh cũ của đúng văn bản này rồi ghi lại theo nhãn mới.
                session.query(DocumentReference).filter(
                    DocumentReference.source_doc_id == doc.id
                ).delete(synchronize_session=False)
                insert_references(session, doc.id, refs)

            stats["van_ban"] += 1
            stats["canh_moi"] += len(refs)
            if stats["van_ban"] % 25 == 0:
                logger.info("  ... %d/%d văn bản", stats["van_ban"], len(docs))
                if not dry_run:
                    session.commit()
            time.sleep(sleep)

        if not dry_run:
            session.commit()
            noi_them = resolve_reference_targets(session)
            session.commit()
            stats["noi_duoc_target_id"] = noi_them

    if not dry_run:
        stats["dong_bo_rag"] = sync_to_rag_graph()

    return stats


def sync_to_rag_graph() -> int:
    """Chép quan hệ từ legal_docs.db sang bảng legal_graph trong rag.db."""
    rag = RAGDatabase()
    rag.db.execute("DELETE FROM legal_graph")
    written = 0
    with get_session() as session:
        rows = (
            session.query(Document.doc_num, DocumentReference.target_doc_num,
                          DocumentReference.relation_type)
            .join(DocumentReference, DocumentReference.source_doc_id == Document.id)
            .all()
        )
        for source, target, rel in rows:
            rag.db.execute(
                """INSERT OR REPLACE INTO legal_graph
                   (source_doc_num, target_doc_num, relation_type, confidence)
                   VALUES (?, ?, ?, 1.0)""",
                (source, target, rel),
            )
            written += 1
    rag.db.commit()
    rag.close()
    return written


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="chỉ đếm, không ghi")
    args = ap.parse_args()

    stats = rebuild(dry_run=args.dry_run)
    print("\n=== KẾT QUẢ ===")
    for k, v in stats.items():
        print(f"  {k:<24} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
