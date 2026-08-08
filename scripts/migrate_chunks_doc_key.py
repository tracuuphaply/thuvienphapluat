"""
Gắn doc_key cho legal_chunks và đổi khoá đoạn từ SỐ HIỆU sang doc_key.

VẤN ĐỀ. `legal_chunks` khoá theo (doc_num, chunk_index). Số hiệu chỉ duy nhất
trong phạm vi một cơ quan, nên hai văn bản của hai tỉnh trùng số hiệu dùng chung
MỘT tập đoạn: bên nạp sau ghi đè các đoạn đầu của bên nạp trước rồi để lại phần
đuôi của bên kia. Không phải lý thuyết — 46 đoạn mang số hiệu 42/2026/QĐ-UBND
hiện là hỗn hợp của UBND Tỉnh Phú Thọ và UBND Thành phố Hồ Chí Minh.

Hậu quả lan ra khắp hệ thống: điểm tác động ngành tính trên tập đoạn trộn lẫn,
báo cáo (b) đọc toàn văn của cả hai tỉnh, và một Quyết định bị bãi bỏ kéo theo
văn bản cùng số hiệu của tỉnh khác biến mất khỏi kết quả truy xuất.

CÁCH LÀM. ALTER TABLE ADD COLUMN chứ KHÔNG dựng lại bảng. `legal_chunks_vec`
khoá theo rowid = legal_chunks.id, nên dựng lại bảng là mất trắng 45.942 vector
và phải nhúng lại toàn bộ. Thêm cột rồi điền là giữ được id.

Đoạn của số hiệu bị trùng không cứu được — chúng đã trộn vào nhau và không có
thông tin nào tách ra được. Migration xoá chúng; file chunk trên đĩa vẫn nguyên
vẹn (đặt tên theo moj_id) nên một lượt `--sync-rag-only` sẽ nạp lại đúng.

    python -m scripts.migrate_chunks_doc_key --dry-run
    python -m scripts.migrate_chunks_doc_key
    python -m src.main --sync-rag-only
"""
from __future__ import annotations

import argparse
import logging
import sqlite3

from src.rag.db_rag import DEFAULT_RAG_DB_PATH, HAS_VEC
from src.storage.database import get_session
from src.storage.models import Document

if HAS_VEC:
    import sqlite_vec

logger = logging.getLogger(__name__)

UNIQUE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_chunks_doan
ON legal_chunks(COALESCE(doc_key, doc_num), chunk_index)
"""


def doc_keys_theo_so_hieu() -> tuple[dict[str, str], set[str]]:
    """Bảng tra số hiệu → doc_key, và tập số hiệu trùng nhiều cơ quan.

    Số hiệu trùng bị tách riêng chứ không chọn bừa một bên: gán nhầm doc_key
    làm đoạn của tỉnh này mang danh tính của tỉnh kia, tệ hơn hẳn để trống.
    """
    theo_so_hieu: dict[str, str] = {}
    trung: set[str] = set()
    with get_session() as session:
        for doc in session.query(Document).all():
            if doc.doc_num in theo_so_hieu:
                trung.add(doc.doc_num)
            theo_so_hieu[doc.doc_num] = doc.doc_key
    for doc_num in trung:
        theo_so_hieu.pop(doc_num, None)
    return theo_so_hieu, trung


def _them_cot(cur) -> None:
    cols = {r[1] for r in cur.execute("PRAGMA table_info(legal_chunks)")}
    if "doc_key" not in cols:
        cur.execute("ALTER TABLE legal_chunks ADD COLUMN doc_key TEXT")
        logger.info("legal_chunks: thêm cột doc_key")


def migrate(dry_run: bool) -> dict:
    stats = {"doan_hien_co": 0, "gan_duoc_doc_key": 0, "xoa_do_trung_so_hieu": 0,
             "so_hieu_trung": 0, "doan_khong_ro_van_ban": 0}

    theo_so_hieu, trung = doc_keys_theo_so_hieu()
    stats["so_hieu_trung"] = len(trung)

    # Không dùng RAGDatabase: init_schema tạo chỉ mục duy nhất trên cột mà
    # migration này mới thêm, nên sẽ chết ngay lúc khởi tạo trên kho chưa sửa.
    # Nhưng vẫn phải tự nạp sqlite-vec, nếu không legal_chunks_vec là bảng ảo
    # không đọc được và mọi thao tác lên nó ném "no such module: vec0".
    rag = sqlite3.connect(str(DEFAULT_RAG_DB_PATH))
    rag.row_factory = sqlite3.Row
    if HAS_VEC:
        rag.enable_load_extension(True)
        sqlite_vec.load(rag)
        rag.enable_load_extension(False)
    try:
        cur = rag.cursor()
        stats["doan_hien_co"] = cur.execute(
            "SELECT COUNT(*) FROM legal_chunks"
        ).fetchone()[0]

        theo_doc_num = {
            r["doc_num"]: r["n"] for r in cur.execute(
                "SELECT doc_num, COUNT(*) n FROM legal_chunks GROUP BY doc_num"
            )
        }
        stats["gan_duoc_doc_key"] = sum(
            n for d, n in theo_doc_num.items() if d in theo_so_hieu
        )
        stats["xoa_do_trung_so_hieu"] = sum(
            n for d, n in theo_doc_num.items() if d in trung
        )
        stats["doan_khong_ro_van_ban"] = (
            stats["doan_hien_co"] - stats["gan_duoc_doc_key"]
            - stats["xoa_do_trung_so_hieu"]
        )

        if dry_run:
            return stats

        cur.execute("BEGIN")
        try:
            _them_cot(cur)
            cur.executemany(
                "UPDATE legal_chunks SET doc_key = ? WHERE doc_num = ?",
                [(key, num) for num, key in theo_so_hieu.items()],
            )

            # Đoạn của số hiệu trùng đã trộn lẫn hai văn bản, không tách được.
            # Vector phải xoá bằng tay: legal_chunks_vec không có trigger như
            # FTS, vector mồ côi sẽ vẫn được tìm thấy rồi JOIN ra rỗng.
            if trung:
                marks = ",".join("?" * len(trung))
                ids = [r[0] for r in cur.execute(
                    f"SELECT id FROM legal_chunks WHERE doc_num IN ({marks})",
                    tuple(trung),
                )]
                if ids:
                    im = ",".join("?" * len(ids))
                    cur.execute(f"DELETE FROM legal_chunks_vec WHERE rowid IN ({im})", ids)
                    cur.execute(f"DELETE FROM legal_chunks WHERE id IN ({im})", ids)

            cur.execute(UNIQUE_INDEX)
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise

        kiem = rag.execute("PRAGMA integrity_check").fetchone()[0]
        if kiem != "ok":
            raise RuntimeError(f"integrity_check sau migration: {kiem}")
    finally:
        rag.close()

    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    stats = migrate(args.dry_run)
    print("\n=== Kết quả ===" + ("  (DRY RUN)" if args.dry_run else ""))
    for k in ("doan_hien_co", "gan_duoc_doc_key", "xoa_do_trung_so_hieu",
              "so_hieu_trung", "doan_khong_ro_van_ban"):
        print(f"  {k:24} {stats[k]}")
    if not args.dry_run:
        print("\nChạy tiếp để nạp lại đoạn đã xoá:")
        print("  python -m src.main --sync-rag-only")


if __name__ == "__main__":
    main()
