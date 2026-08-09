"""
Chạy bao đóng dẫn chiếu: tải các văn bản mà kho đang dẫn chiếu tới nhưng chưa có.

Dừng-tiếp được: hàng đợi nằm trong bảng `crawl_frontier`, nên ngắt giữa chừng
rồi chạy lại là tiếp đúng chỗ dừng. Chạy nhiều lần cho tới khi `còn chờ` về 0.

    python -m scripts.run_closure --dry-run          # chỉ nạp hàng đợi, không tải
    python -m scripts.run_closure --max-fetch 50     # thử một lô nhỏ
    python -m scripts.run_closure                    # theo CLOSURE_MAX_FETCH_PER_RUN

Văn bản kéo về được đánh dấu `is_closure_node = 1`: chúng KHÔNG vào bản tin
Telegram và KHÔNG tự sinh báo cáo — chúng là ngữ cảnh, không phải sự kiện. Nhưng
vẫn vào kho RAG và vẫn lên Drive: bản đã bị bãi bỏ chính là thứ trả lời được
"quy định nào đã đổi", nên người đọc báo cáo phải mở được nó. Đặt
UPLOAD_CLOSURE_NODES=false nếu muốn giữ Drive gọn.

ĐIỀU KIỆN TIÊN QUYẾT — chạy MỘT LẦN trước lần bao đóng đầu tiên:

    python -m scripts.rebuild_reference_graph

Cạnh dẫn chiếu tạo trước tháng 8/2026 đều thiếu `target_moj_id`, mà đó là đường
duy nhất để tải văn bản đích (endpoint /doc/all bỏ qua mọi tham số lọc). Không
chạy bước này thì hàng đợi gần như rỗng.

SAU MỖI ĐỢT, đồng bộ lại tầng truy xuất, nếu không văn bản vừa kéo về không có
trong RAG và đồ thị hai kho lệch nhau:

    python -m src.main --sync-rag-only
"""
from __future__ import annotations

import argparse
import logging

from src.pipeline import closure
from src.pipeline.text_processor import process_fulltext
from src.storage.database import (
    get_session,
    init_db,
    insert_references,
    resolve_reference_targets,
    upsert_document,
)
from src.storage.file_store import save_moj_fulltext

logger = logging.getLogger(__name__)


def _save_closure_document(session, detail: dict, depth: int) -> None:
    """Ghi một văn bản bao đóng vào kho.

    KHÔNG lọc theo hiệu lực và KHÔNG lọc theo lĩnh vực doanh nghiệp — đó chính
    là điểm khác biệt của nhánh này. Văn bản bị bãi bỏ từ lâu vẫn phải vào kho:
    nó là mắt xích giải thích quy định hiện hành thay thế cái gì.
    """
    references = detail.pop("references", [])
    fulltext_html = detail.pop("fulltext_html", "")

    doc_data = dict(detail)
    # Cờ này quyết định văn bản có vào bản tin, báo cáo và Drive hay không.
    doc_data["is_closure_node"] = True
    doc_data["first_seen_depth"] = depth
    # Không gắn event_type: đây không phải văn bản mới đáng báo cho người dùng.
    doc_data.pop("event_type", None)

    moj_id = doc_data.get("moj_id", "")
    if fulltext_html and moj_id:
        # Gọi bằng TÊN THAM SỐ, không theo vị trí: process_fulltext nhận
        # (doc_id, html_content, doc_num) còn save_moj_fulltext nhận
        # (doc_id, html_content) — truyền nhầm thứ tự thì toàn văn HTML bị dùng
        # làm tên file và lỗi chỉ lộ ra ở dòng "File name too long".
        path = save_moj_fulltext(moj_id, fulltext_html)
        doc_data["fulltext_path"] = path
        doc_data["has_fulltext"] = bool(path)

        text_result = process_fulltext(
            doc_id=moj_id,
            html_content=fulltext_html,
            doc_num=doc_data.get("doc_num", ""),
        )
        if text_result["clean_text_path"]:
            doc_data["clean_text_path"] = text_result["clean_text_path"]
            doc_data["chunks_path"] = text_result["chunks_path"]
            doc_data["has_chunks"] = text_result["chunk_count"] > 0

    doc, _is_new = upsert_document(session, doc_data)
    session.flush()
    if references:
        insert_references(session, doc.id, references)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Chỉ nạp hàng đợi và in thống kê, không gọi mạng")
    parser.add_argument("--max-fetch", type=int, default=0,
                        help="Trần số văn bản tải về lần này")
    args = parser.parse_args()

    init_db()

    with get_session() as session:
        seeded = closure.seed_frontier(session)
        session.commit()
        pending = closure.pending_count(session)
        no_id = closure.unresolvable_targets(session)

        print("\n=== Hàng đợi bao đóng ===")
        print(f"  vừa nạp thêm         {seeded:>6}")
        print(f"  đang chờ tải         {pending:>6}")
        print(f"  không có id, bỏ qua  {no_id:>6}  (đưa vào hạn chế dữ liệu của báo cáo)")
        print(f"  kho hiện có          {closure.corpus_size(session):>6} văn bản")

        if args.dry_run:
            top = session.execute(closure.text("""
                SELECT doc_num, priority, discovered_via_relation
                FROM crawl_frontier WHERE state='PENDING'
                ORDER BY priority DESC LIMIT 10
            """)).mappings().all()
            print("\n  Ưu tiên cao nhất:")
            for r in top:
                print(f"    {r['priority']:6.2f}  {r['doc_num']:<24} ({r['discovered_via_relation']})")
            return

    with get_session() as session:
        stats = closure.run_closure(
            session,
            max_fetch=args.max_fetch,
            on_document=lambda detail, depth: _save_closure_document(
                session, detail, depth
            ),
        )
        # Cạnh tạo trước khi đích về kho có target_doc_id NULL mãi mãi nếu
        # không nối lại sau mỗi đợt.
        noi_lai = resolve_reference_targets(session)
        session.commit()

    print("\n=== Kết quả ===")
    for key, value in stats.as_dict().items():
        print(f"  {key:22} {value}")
    print(f"  {'canh_noi_lai':22} {noi_lai}")


if __name__ == "__main__":
    main()
