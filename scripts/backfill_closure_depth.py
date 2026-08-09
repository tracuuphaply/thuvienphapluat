"""
Tính lại độ sâu bao đóng cho văn bản đã kéo về và cho hàng đợi.

VẤN ĐỀ. `seed_frontier` từng gán cứng `depth = 1` cho mọi mục, bất kể văn bản
phát hiện ra đích nằm ở tầng nào. Hệ quả là `documents.first_seen_depth` sai
trên toàn bộ văn bản nền — đọc lên tưởng tất cả đều được văn bản 2026 dẫn chiếu
trực tiếp — và `crawl_frontier.depth` cũng vậy. Đặt trần độ sâu lên dữ liệu đó
thì trần không có ý nghĩa gì.

CÁCH LÀM. Duyệt theo chiều rộng từ tập hạt giống. Hạt giống là văn bản vào kho
theo lĩnh vực doanh nghiệp (`is_closure_node = 0`), độ sâu 0. Đi theo cạnh dẫn
chiếu đã phân giải (`target_doc_id`), mỗi bước cộng 1. Duyệt theo chiều rộng cho
đúng ĐƯỜNG NGẮN NHẤT: một văn bản có thể bị nhiều văn bản ở nhiều tầng dẫn tới,
và khoảng cách thật là đường ngắn nhất chứ không phải đường tình cờ tìm ra trước.

Văn bản nền không nối được về hạt giống qua cạnh đã phân giải giữ nguyên độ sâu
đang có — không đoán bừa. Số lượng được in ra.

    python -m scripts.backfill_closure_depth --dry-run
    python -m scripts.backfill_closure_depth
"""
from __future__ import annotations

import argparse
import logging
from collections import deque

from sqlalchemy import text

from src.config import CLOSURE_MAX_DEPTH
from src.storage.database import get_session

logger = logging.getLogger(__name__)

# Mục vượt trần độ sâu: giữ lại bản ghi thay vì xoá, để nâng trần sau này là
# chạy tiếp được chứ không phải dò lại từ đầu.
TOO_DEEP = "TOO_DEEP"


def do_sau_theo_bfs(session) -> dict[int, int]:
    """id văn bản → độ sâu ngắn nhất tính từ tập hạt giống."""
    canh = session.execute(text("""
        SELECT source_doc_id AS src, target_doc_id AS tgt
        FROM document_references WHERE target_doc_id IS NOT NULL
    """)).all()
    ke: dict[int, list[int]] = {}
    for src, tgt in canh:
        ke.setdefault(src, []).append(tgt)

    hat_giong = [r[0] for r in session.execute(text(
        "SELECT id FROM documents WHERE COALESCE(is_closure_node, 0) = 0"
    )).all()]

    do_sau = {i: 0 for i in hat_giong}
    hang_doi = deque(hat_giong)
    while hang_doi:
        u = hang_doi.popleft()
        for v in ke.get(u, ()):
            if v not in do_sau:
                do_sau[v] = do_sau[u] + 1
                hang_doi.append(v)
    return do_sau


def backfill(dry_run: bool) -> dict:
    stats = {"van_ban_nen": 0, "sua_do_sau_van_ban": 0, "khong_noi_duoc": 0,
             "hang_doi_dang_cho": 0, "sua_do_sau_hang_doi": 0,
             "hang_doi_qua_sau": 0, "tran": CLOSURE_MAX_DEPTH}

    with get_session() as session:
        do_sau = do_sau_theo_bfs(session)

        nen = session.execute(text("""
            SELECT id, doc_num, first_seen_depth FROM documents
            WHERE is_closure_node = 1
        """)).mappings().all()
        stats["van_ban_nen"] = len(nen)

        can_sua = []
        for row in nen:
            moi = do_sau.get(row["id"])
            if moi is None:
                stats["khong_noi_duoc"] += 1
                continue
            if moi != row["first_seen_depth"]:
                can_sua.append({"id": row["id"], "d": moi})
        stats["sua_do_sau_van_ban"] = len(can_sua)

        # Hàng đợi: độ sâu = đường ngắn nhất tới một văn bản DẪN TỚI nó, cộng 1.
        cho = session.execute(text("""
            SELECT f.moj_id, f.depth,
                   MIN(COALESCE(d.first_seen_depth, 0)) AS nguon_nong_nhat
            FROM crawl_frontier f
            JOIN document_references r ON r.target_moj_id = f.moj_id
            JOIN documents d ON d.id = r.source_doc_id
            WHERE f.state = 'PENDING'
            GROUP BY f.moj_id, f.depth
        """)).mappings().all()
        stats["hang_doi_dang_cho"] = len(cho)

        cho_sua, qua_sau = [], []
        for row in cho:
            # Dùng độ sâu ĐÃ SỬA của văn bản nguồn, không dùng giá trị cũ.
            nguon = session.execute(text(
                "SELECT r.source_doc_id FROM document_references r "
                "WHERE r.target_moj_id = :m"), {"m": row["moj_id"]}).scalars().all()
            ung_vien = [do_sau[i] for i in nguon if i in do_sau]
            moi = (min(ung_vien) + 1) if ung_vien else row["depth"]
            if CLOSURE_MAX_DEPTH and moi > CLOSURE_MAX_DEPTH:
                qua_sau.append(row["moj_id"])
            elif moi != row["depth"]:
                cho_sua.append({"m": row["moj_id"], "d": moi})
        stats["sua_do_sau_hang_doi"] = len(cho_sua)
        stats["hang_doi_qua_sau"] = len(qua_sau)

        if dry_run:
            return stats

        for batch in can_sua:
            session.execute(text(
                "UPDATE documents SET first_seen_depth = :d WHERE id = :id"), batch)
        for batch in cho_sua:
            session.execute(text(
                "UPDATE crawl_frontier SET depth = :d WHERE moj_id = :m"), batch)
        if qua_sau:
            # Chia lô tường minh: SQLite giới hạn số tham số một câu lệnh.
            for i in range(0, len(qua_sau), 500):
                lo = qua_sau[i:i + 500]
                marks = ",".join(f":m{j}" for j in range(len(lo)))
                session.execute(
                    text(f"UPDATE crawl_frontier SET state = :s, "
                         f"updated_at = datetime('now') WHERE moj_id IN ({marks})"),
                    {"s": TOO_DEEP, **{f"m{j}": v for j, v in enumerate(lo)}},
                )
        session.commit()

    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    stats = backfill(args.dry_run)
    print("\n=== Kết quả ===" + ("  (DRY RUN)" if args.dry_run else ""))
    for k in ("van_ban_nen", "sua_do_sau_van_ban", "khong_noi_duoc",
              "hang_doi_dang_cho", "sua_do_sau_hang_doi", "hang_doi_qua_sau",
              "tran"):
        print(f"  {k:24} {stats[k]}")
    if not stats["tran"]:
        print("\n  CLOSURE_MAX_DEPTH = 0 nên không cắt gì. Đặt trần trong .env "
              "rồi chạy lại nếu muốn cắt.")


if __name__ == "__main__":
    main()
