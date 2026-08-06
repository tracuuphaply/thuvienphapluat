"""
Bỏ ràng buộc UNIQUE trên documents.doc_num, thay bằng doc_key (số hiệu + cơ quan).

Số hiệu văn bản chỉ duy nhất trong phạm vi cơ quan ban hành. 63 tỉnh đánh số
độc lập nên "67/2026/QĐ-UBND" tồn tại ở 18 tỉnh. Với UNIQUE(doc_num), bản thứ
hai trở đi bị coi là đã biết và bị bỏ qua im lặng — đo trên một lần quét 6.906
văn bản thì 4.211 bản sẽ bị nuốt.

SQLite không cho DROP CONSTRAINT nên phải dựng lại bảng theo quy trình 12 bước
của chính SQLite: tạo bảng mới, chép dữ liệu, xoá bảng cũ, đổi tên.

Chạy:  python -m scripts.migrate_doc_key [--dry-run]
"""
import argparse
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from src.config import DATABASE_URL


def db_path() -> Path:
    url = DATABASE_URL.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
    return Path(url)


def already_migrated(conn: sqlite3.Connection) -> bool:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
    return "doc_key" in cols


def doc_num_is_unique(conn: sqlite3.Connection) -> bool:
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='documents'"
    ).fetchone()
    return bool(sql) and "doc_num VARCHAR(100) NOT NULL UNIQUE" in sql[0].replace("\n", " ")


def migrate(dry_run: bool = False) -> dict:
    path = db_path()
    if not path.exists():
        raise SystemExit(f"Không tìm thấy DB: {path}")

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    stats = {"tong_van_ban": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]}
    stats["da_migrate"] = already_migrated(conn)

    if stats["da_migrate"]:
        print("Bảng documents đã có doc_key — bỏ qua.")
        conn.close()
        return stats

    if dry_run:
        va_cham = conn.execute("""
            SELECT doc_num, COUNT(*) n FROM documents GROUP BY doc_num HAVING n > 1
        """).fetchall()
        stats["so_hieu_dang_trung"] = len(va_cham)
        conn.close()
        return stats

    backup = path.parent / "backups" / f"{path.stem}_pre_dockey_{datetime.now():%Y%m%d_%H%M%S}.db"
    backup.parent.mkdir(parents=True, exist_ok=True)
    conn.execute("VACUUM INTO ?", (str(backup),))
    stats["ban_sao_luu"] = str(backup)

    old_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='documents'"
    ).fetchone()[0]
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(documents)")]

    # Bảng mới = bảng cũ nhưng bỏ UNIQUE khỏi doc_num và thêm doc_key.
    # SQLAlchemy có thể sinh ràng buộc ở dạng inline hoặc dạng bảng, xử lý cả hai.
    new_sql = old_sql
    if "doc_num VARCHAR(100) NOT NULL UNIQUE" in new_sql:           # dạng inline
        new_sql = new_sql.replace(
            "doc_num VARCHAR(100) NOT NULL UNIQUE",
            "doc_num VARCHAR(100) NOT NULL",
        )
    elif re.search(r"UNIQUE\s*\(\s*doc_num\s*\)", new_sql):          # dạng bảng
        new_sql = re.sub(r",?\s*UNIQUE\s*\(\s*doc_num\s*\)", "", new_sql)
    else:
        conn.close()
        raise SystemExit("Không tìm thấy ràng buộc UNIQUE trên doc_num — dừng để tránh làm hỏng bảng.")

    # Chèn cột doc_key ngay sau doc_num cho dễ đọc khi .schema
    new_sql = re.sub(
        r"(doc_num VARCHAR\(100\) NOT NULL,)",
        r"\1\n\tdoc_key VARCHAR(300),",
        new_sql,
        count=1,
    )
    new_sql = new_sql.replace("CREATE TABLE documents", "CREATE TABLE documents_new", 1)
    if "doc_key VARCHAR(300)" not in new_sql:
        conn.close()
        raise SystemExit("Không chèn được cột doc_key — dừng để tránh làm hỏng bảng.")

    conn.executescript("PRAGMA foreign_keys=OFF; BEGIN;")
    try:
        conn.execute(new_sql)
        col_list = ", ".join(f'"{c}"' for c in cols)
        conn.execute(f"INSERT INTO documents_new ({col_list}) SELECT {col_list} FROM documents")

        # doc_key phải được tính bằng ĐÚNG hàm mà runtime dùng.
        # lower() của SQLite chỉ xử lý ASCII: lower('QĐ-UBND') = 'qĐ-ubnd' (chữ Đ
        # còn hoa) trong khi Python cho 'qđ-ubnd'. Tính bằng SQL sẽ tạo ra khoá
        # mà lần cào sau không khớp lại được → sinh bản ghi trùng.
        from src.storage.database import make_doc_key

        rows = conn.execute("SELECT id, doc_num, agency_name FROM documents_new").fetchall()
        conn.executemany(
            "UPDATE documents_new SET doc_key = ? WHERE id = ?",
            [(make_doc_key(r["doc_num"], r["agency_name"]), r["id"]) for r in rows],
        )

        trung = conn.execute("""
            SELECT doc_key, COUNT(*) n FROM documents_new GROUP BY doc_key HAVING n > 1
        """).fetchall()
        if trung:
            conn.execute("ROLLBACK")
            conn.close()
            raise SystemExit(
                f"{len(trung)} doc_key bị trùng sau khi tính — cần xử lý tay trước: "
                + ", ".join(r["doc_key"] for r in trung[:5])
            )

        conn.execute("DROP TABLE documents")
        conn.execute("ALTER TABLE documents_new RENAME TO documents")
        conn.execute("CREATE UNIQUE INDEX idx_documents_doc_key ON documents(doc_key)")
        for name, col in [
            ("idx_documents_doc_num", "doc_num"),
            ("idx_documents_issue_date", "issue_date"),
            ("idx_documents_field_code", "field_code"),
            ("idx_documents_event_type", "event_type"),
            ("idx_documents_moj_id", "moj_id"),
            ("idx_documents_tvpl_id", "tvpl_id"),
            ("idx_documents_eff_status", "eff_status"),
        ]:
            conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON documents({col})")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        conn.close()
        raise
    conn.execute("PRAGMA foreign_keys=ON")

    stats["sau_migrate"] = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    stats["con_unique_doc_num"] = doc_num_is_unique(conn)
    ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
    stats["integrity_check"] = ok
    conn.commit()
    conn.close()
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    stats = migrate(dry_run=args.dry_run)
    print("\n=== KẾT QUẢ ===")
    for k, v in stats.items():
        print(f"  {k:<22} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
