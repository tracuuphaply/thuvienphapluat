"""
Lấy lại các trường Bộ Tư pháp làm chuẩn cho toàn bộ văn bản đã có trong kho.

Dùng khi cách đọc payload thay đổi và dữ liệu cũ đã bị ghi sai. Lần đầu cần
script này là khi phát hiện `agency_name` lấy nhầm `organization.name` (đơn vị
quản lý bản ghi) thay vì `agencyName` (cơ quan ban hành) — hệ quả là mọi đạo
Luật bị ghi do một Bộ ban hành thay vì Quốc hội.

Vì `doc_key` = số hiệu + cơ quan ban hành, sửa `agency_name` sẽ đổi định danh,
nên script tính lại `doc_key` ngay sau đó và kiểm tra không sinh khoá trùng.

Chạy:
    python -m scripts.refresh_moj_metadata --dry-run
    python -m scripts.refresh_moj_metadata
"""
import argparse
import collections
import logging
import sys
import time

from src.sources.moj_api import fetch_doc_detail, parse_doc_summary
from src.storage.database import get_session, make_doc_key
from src.storage.models import Document

logger = logging.getLogger(__name__)

# Trường Bộ Tư pháp là nguồn chuẩn — luôn ghi đè bằng giá trị mới đọc lại.
REFRESH_FIELDS = (
    "agency_name",
    "signer",
    "doc_type",
    "eff_status",
    "eff_from",
    "eff_to",
    "issue_date",
    "field_name",
    "field_code",
    "title",
)


def refresh(dry_run: bool = False, sleep: float = 0.25) -> dict:
    stats: dict = {"da_doc": 0, "co_thay_doi": 0, "loi": 0}
    changed_fields: collections.Counter = collections.Counter()

    with get_session() as session:
        docs = (
            session.query(Document)
            .filter(Document.moj_id.isnot(None))
            .order_by(Document.id)
            .all()
        )
        logger.info("Đọc lại %d văn bản từ Bộ Tư pháp", len(docs))

        for idx, doc in enumerate(docs, 1):
            try:
                fresh = parse_doc_summary(fetch_doc_detail(doc.moj_id).get("data") or {})
            except Exception as e:
                stats["loi"] += 1
                logger.debug("%s: %s", doc.doc_num, type(e).__name__)
                time.sleep(sleep)
                continue

            stats["da_doc"] += 1
            doc_changed = False
            for field in REFRESH_FIELDS:
                new = fresh.get(field)
                if new in (None, ""):
                    continue
                if getattr(doc, field, None) != new:
                    changed_fields[field] += 1
                    doc_changed = True
                    if not dry_run:
                        setattr(doc, field, new)

            if doc_changed:
                stats["co_thay_doi"] += 1
            if not dry_run:
                doc.doc_key = make_doc_key(doc.doc_num, doc.agency_name)

            if idx % 100 == 0:
                logger.info("  %d/%d", idx, len(docs))
                if not dry_run:
                    session.commit()
            time.sleep(sleep)

        if dry_run:
            session.rollback()
        else:
            # Đổi agency_name làm đổi doc_key — phải chắc không sinh khoá trùng
            # trước khi commit, nếu không sẽ vi phạm chỉ mục duy nhất.
            keys = collections.Counter(
                make_doc_key(d.doc_num, d.agency_name) for d in docs
            )
            dup = [k for k, n in keys.items() if n > 1]
            if dup:
                session.rollback()
                raise SystemExit(
                    f"{len(dup)} doc_key sẽ bị trùng sau khi sửa — đã huỷ bỏ. "
                    f"Ví dụ: {dup[:3]}"
                )
            session.commit()
            stats["metadata_json_da_ghi"] = _sync_metadata_files(session)

    stats["truong_da_sua"] = dict(changed_fields)
    return stats


def _sync_metadata_files(session) -> int:
    """Ghi lại data/metadata/*.json từ DB.

    Cùng một dữ kiện đang tồn tại ở bốn nơi: DB, metadata JSON, rag.db và vault.
    Sửa mỗi DB thì ba nơi kia vẫn giữ giá trị sai, vì cả vault_exporter lẫn
    rag_indexer đều đọc từ metadata JSON chứ không đọc DB.
    """
    from src.storage.file_store import save_document_metadata

    written = 0
    for doc in session.query(Document).all():
        payload = {
            col.name: getattr(doc, col.name) for col in doc.__table__.columns
        }
        if save_document_metadata(payload):
            written += 1
    logger.info("Đã ghi lại %d file metadata JSON từ DB", written)
    return written


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.25)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    stats = refresh(dry_run=args.dry_run, sleep=args.sleep)
    print("\n=== KẾT QUẢ ===")
    for k, v in stats.items():
        print(f"  {k:<16} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
