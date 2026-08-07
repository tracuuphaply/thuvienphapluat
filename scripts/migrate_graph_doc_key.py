"""
Đổi khoá bảng legal_graph từ SỐ HIỆU sang doc_key.

VẤN ĐỀ. `legal_graph` khoá duy nhất theo (source_doc_num, target_doc_num,
relation_type). Số hiệu chỉ duy nhất trong phạm vi một cơ quan, nên hai văn bản
của hai tỉnh khác nhau trùng số hiệu bị gộp thành MỘT cạnh. Đã có ca thật:
"64/2026/QĐ-UBND" của Huế và của Tây Ninh cùng "Căn cứ" 72/2025/QH15 — đồ thị
chỉ giữ một cạnh, và `impact_analysis("64/2026/QĐ-UBND")` không phân biệt nổi
văn bản của tỉnh nào.

Hiện mới 1/7.9xx cạnh, nhưng bao đóng dẫn chiếu sẽ kéo về hàng nghìn văn bản cấp
tỉnh nên tỷ lệ này chỉ tăng.

CÁCH LÀM. SQLite không đổi được ràng buộc UNIQUE tại chỗ, phải dựng lại bảng —
đúng quy trình mà scripts/migrate_doc_key.py đã dùng cho bảng documents.

GIỚI HẠN CÒN LẠI, ghi rõ để không ai tưởng đã xong: `legal_chunks` vẫn khoá theo
số hiệu. Nghĩa là hai văn bản trùng số hiệu vẫn dùng chung một tập chunk. Sửa
tầng đó phải index lại toàn bộ ~46.000 đoạn nên tách thành việc riêng.

    python -m scripts.migrate_graph_doc_key --dry-run
    python -m scripts.migrate_graph_doc_key
"""
from __future__ import annotations

import argparse
import logging
import sqlite3

from src.rag.db_rag import DEFAULT_RAG_DB_PATH
from src.storage.database import get_session
from src.storage.models import Document, DocumentReference

logger = logging.getLogger(__name__)

NEW_SCHEMA = """
CREATE TABLE legal_graph_new (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source_doc_key    TEXT NOT NULL,
    source_doc_num    TEXT NOT NULL,
    target_doc_key    TEXT,
    target_doc_num    TEXT NOT NULL,
    relation_type     TEXT NOT NULL,
    confidence        REAL DEFAULT 1.0
)
"""

# Khoá duy nhất nằm ở chỉ mục biểu thức chứ không phải ràng buộc UNIQUE trong
# bảng, vì SQL coi mỗi NULL là một giá trị riêng: UNIQUE thường sẽ bỏ qua toàn
# bộ 2.963 cạnh treo và cho phép chèn trùng không giới hạn.
#
# Đích chưa có trong kho thì target_doc_key NULL, nên phải đưa cả target_doc_num
# vào khoá; thiếu nó thì mọi cạnh treo của cùng một nguồn sẽ gộp làm một.
NEW_UNIQUE_INDEX = """
CREATE UNIQUE INDEX idx_graph_canh ON legal_graph(
    source_doc_key, COALESCE(target_doc_key, ''), target_doc_num, relation_type
)
"""


def collect_edges(session) -> list[dict]:
    """Cạnh lấy từ cơ sở dữ liệu chính, đã gắn doc_key hai đầu.

    Đích được phân giải qua target_doc_id (khoá ngoại thật) chứ không qua số
    hiệu — đó chính là điểm khác biệt so với bản cũ.
    """
    rows = (
        session.query(
            Document.doc_key, Document.doc_num,
            DocumentReference.target_doc_num,
            DocumentReference.target_doc_id,
            DocumentReference.relation_type,
        )
        .join(DocumentReference, DocumentReference.source_doc_id == Document.id)
        .all()
    )
    key_by_id = {d.id: d.doc_key for d in session.query(Document).all()}

    return [{
        "source_doc_key": src_key,
        "source_doc_num": src_num,
        "target_doc_key": key_by_id.get(tgt_id),
        "target_doc_num": tgt_num,
        "relation_type": rel,
    } for src_key, src_num, tgt_num, tgt_id, rel in rows]


def migrate(dry_run: bool) -> dict:
    stats = {"canh_nguon": 0, "canh_ghi": 0, "canh_cu_trong_rag": 0,
             "canh_cuu_khoi_gop": 0, "canh_chua_dong_bo": 0,
             "dich_chua_co_trong_kho": 0}

    with get_session() as session:
        edges = collect_edges(session)
    stats["canh_nguon"] = len(edges)
    stats["dich_chua_co_trong_kho"] = sum(1 for e in edges if not e["target_doc_key"])

    # Không dùng RAGDatabase: hàm dựng của nó gọi init_schema(), mà init_schema
    # tạo chỉ mục trên target_doc_key — cột chưa tồn tại cho tới khi migration
    # này chạy xong. Công cụ sửa lược đồ không được phụ thuộc vào lược đồ mới.
    rag = sqlite3.connect(str(DEFAULT_RAG_DB_PATH))
    rag.row_factory = sqlite3.Row
    try:
        stats["canh_cu_trong_rag"] = rag.execute(
            "SELECT COUNT(*) FROM legal_graph"
        ).fetchone()[0]

        # Bảng mới sẽ có bấy nhiêu cạnh; bảng cũ ít hơn vì HAI lý do khác nhau,
        # phải tách bạch nếu không con số "cứu được" sẽ thổi phồng lợi ích của
        # chính migration này.
        unique_new = {
            (e["source_doc_key"], e["target_doc_key"], e["target_doc_num"],
             e["relation_type"]) for e in edges
        }
        # (1) Cạnh bị khoá cũ gộp nhầm — đây mới là thứ migration này cứu.
        unique_old_key = {
            (e["source_doc_num"], e["target_doc_num"], e["relation_type"])
            for e in edges
        }
        stats["canh_cuu_khoi_gop"] = len(unique_new) - len(unique_old_key)
        # (2) Cạnh có trong kho chính nhưng chưa kịp đẩy sang rag — migration
        # nạp lại từ kho chính nên tiện thể đồng bộ luôn, không phải công của
        # việc đổi khoá.
        stats["canh_chua_dong_bo"] = len(unique_old_key) - stats["canh_cu_trong_rag"]

        if dry_run:
            return stats

        # Khử trùng ở đây chứ không nhờ INSERT OR IGNORE: chỉ mục duy nhất chỉ
        # được tạo sau khi đổi tên bảng (nếu tạo sớm sẽ trùng tên với chỉ mục
        # của bảng cũ chưa bị xoá), nên lúc chèn chưa có ràng buộc nào.
        seen, edges_unique = set(), []
        for e in edges:
            k = (e["source_doc_key"], e["target_doc_key"],
                 e["target_doc_num"], e["relation_type"])
            if k not in seen:
                seen.add(k)
                edges_unique.append(e)

        cur = rag.cursor()
        cur.execute("PRAGMA foreign_keys=OFF")
        cur.execute("BEGIN")
        try:
            cur.execute("DROP TABLE IF EXISTS legal_graph_new")
            cur.execute(NEW_SCHEMA)
            cur.executemany("""
                INSERT INTO legal_graph_new
                    (source_doc_key, source_doc_num, target_doc_key,
                     target_doc_num, relation_type, confidence)
                VALUES (:source_doc_key, :source_doc_num, :target_doc_key,
                        :target_doc_num, :relation_type, 1.0)
            """, edges_unique)
            stats["canh_ghi"] = cur.execute(
                "SELECT COUNT(*) FROM legal_graph_new"
            ).fetchone()[0]
            if stats["canh_ghi"] != len(unique_new):
                raise RuntimeError(
                    f"ghi {stats['canh_ghi']} cạnh nhưng phải là {len(unique_new)}"
                )

            cur.execute("DROP TABLE legal_graph")
            cur.execute("ALTER TABLE legal_graph_new RENAME TO legal_graph")
            cur.execute(NEW_UNIQUE_INDEX)
            # Cùng tên với init_schema của RAGDatabase, nếu không sẽ có hai chỉ
            # mục y hệt nhau trên cùng một cột.
            for col in ("target_doc_num", "source_doc_num", "target_doc_key"):
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_graph_{col} ON legal_graph({col})"
                )
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
        cur.execute("PRAGMA foreign_keys=ON")
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
    for k in ("canh_nguon", "canh_cu_trong_rag", "canh_ghi", "canh_cuu_khoi_gop",
              "canh_chua_dong_bo", "dich_chua_co_trong_kho"):
        print(f"  {k:26} {stats[k]}")


if __name__ == "__main__":
    main()
