"""
Bao đóng dẫn chiếu: kéo về mọi văn bản mà kho đang dẫn chiếu tới nhưng chưa có.

BÀI TOÁN. Kho hiện có 1.534 số hiệu bị dẫn chiếu mà không có trong `documents`.
Chúng là các luật, nghị định nền mà văn bản mới "Căn cứ" vào — thiếu chúng thì
chuỗi căn cứ pháp lý đứt ở giữa, và báo cáo không giải thích được vì sao một quy
định tồn tại.

KHÁC BIỆT BẮT BUỘC so với scripts/deep_research_active_laws.py:
  - KHÔNG bỏ văn bản hết hiệu lực. Văn bản bị bãi bỏ chính là mắt xích giải
    thích quy định hiện hành thay thế cái gì.
  - KHÔNG áp bộ lọc lĩnh vực doanh nghiệp. Văn bản kéo về theo dẫn chiếu là
    NGỮ CẢNH, không phải TRIGGER: chúng vào kho RAG nhưng không vào bản tin
    Telegram, không sinh báo cáo, và không đẩy lên Drive. Phân biệt bằng cột
    `is_closure_node`; thiếu nó thì bản tin hằng ngày ngập vài nghìn văn bản
    không liên quan.

CÁCH LẤY ID. Endpoint /doc/all bỏ qua mọi tham số lọc (đã thử keyword, docNum,
searchText, q, filter, text, soHieu) nên không tra được văn bản theo số hiệu.
Đường duy nhất là `references[].targetDocument.id` — id nằm sẵn trong phản hồi
chi tiết của văn bản nguồn, nay được lưu vào `document_references.target_moj_id`
và `moj_id_index`.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.config import (
    CLOSURE_HUB_INDEGREE,
    CLOSURE_MAX_DEPTH,
    CLOSURE_MAX_FETCH_PER_RUN,
    CLOSURE_MAX_NODES,
    MIN_FREE_DISK_GB,
    MOJ_RATE_LIMIT_SECONDS,
)
from src.utils import disk_guard

logger = logging.getLogger(__name__)

PENDING = "PENDING"
DONE = "DONE"
FAILED = "FAILED"
NO_ID = "NO_ID"
HUB_NOT_EXPANDED = "HUB_NOT_EXPANDED"

# Số hiệu không parse được đều rơi về cùng giá trị này — nó là thùng rác, không
# phải một văn bản. 165 cạnh đang trỏ tới nó; đưa vào hàng đợi là tự tạo ra một
# nút khổng lồ vô nghĩa giữa sơ đồ.
JUNK_DOC_NUMS = frozenset({"Không số", "Khong so", "", "-"})

# Trọng số quan hệ khi xếp ưu tiên. Văn bản sửa đổi/thay thế/bãi bỏ một văn bản
# trong kho quan trọng hơn hẳn văn bản chỉ được "Căn cứ".
RELATION_WEIGHT: dict[str, float] = {
    "Sửa đổi, bổ sung": 3.0,
    "Thay thế": 3.0,
    "Bãi bỏ": 3.0,
    "Hủy bỏ": 3.0,
    "Đình chỉ": 3.0,
    "Căn cứ": 1.0,
}
UNKNOWN_RELATION_WEIGHT = 0.5


@dataclass
class ClosureStats:
    seeded: int = 0
    fetched: int = 0
    saved: int = 0
    failed: int = 0
    no_id: int = 0
    hubs_skipped: int = 0
    junk_skipped: int = 0
    enqueued: int = 0
    stopped_reason: str = ""
    pending_after: int = 0

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def priority_of(relation_type: str, in_degree: int, depth: int) -> float:
    """Điểm ưu tiên của một đích trong hàng đợi.

    Ba thành phần: loại quan hệ (sửa đổi quan trọng hơn căn cứ), mức độ được
    nhiều văn bản dẫn tới (càng nhiều càng là văn bản nền), và độ sâu (càng xa
    seed càng ít liên quan tới doanh nghiệp).
    """
    weight = RELATION_WEIGHT.get(relation_type, UNKNOWN_RELATION_WEIGHT)
    return 3 * weight + 2 * math.log(1 + max(0, in_degree)) - 1.5 * depth


def seed_frontier(session: Session, max_new: int = 0) -> int:
    """Đưa các đích dẫn chiếu chưa có trong kho vào hàng đợi.

    Chỉ nhận đích đã biết id MOJ. Đích không có id được đánh dấu NO_ID ở bảng
    riêng chứ không im lặng bỏ qua — số lượng đó phải hiện ra trong khối hạn chế
    dữ liệu của báo cáo.
    """
    # Độ sâu suy từ VĂN BẢN PHÁT HIỆN ra đích, không gán cứng.
    #
    # Bản trước ghi depth = 1 cho mọi mục, nên first_seen_depth là dữ kiện sai
    # trên toàn bộ văn bản nền — đọc lên tưởng đâu tất cả đều được văn bản 2026
    # dẫn chiếu trực tiếp. Số hạng −1,5·depth trong công thức ưu tiên cũng thành
    # hằng số, tức xếp hạng mất hẳn phần phạt theo khoảng cách: văn bản cách 5
    # chặng đứng ngang văn bản được dẫn thẳng từ hạt giống.
    #
    # Hạt giống có first_seen_depth NULL vì chúng vào kho theo lĩnh vực chứ
    # không theo dẫn chiếu — coi là 0. MIN vì một đích có thể bị nhiều văn bản
    # ở nhiều tầng dẫn tới; đường ngắn nhất mới là khoảng cách thật.
    rows = session.execute(text("""
        SELECT r.target_moj_id AS moj_id,
               r.target_doc_num AS doc_num,
               MIN(r.relation_type) AS relation_type,
               COUNT(*) AS in_degree,
               MIN(COALESCE(src.first_seen_depth, 0)) + 1 AS depth
        FROM document_references r
        JOIN documents src ON src.id = r.source_doc_id
        WHERE r.target_doc_id IS NULL
          AND r.target_moj_id IS NOT NULL
          AND r.target_moj_id <> ''
          AND r.target_moj_id NOT IN (SELECT moj_id FROM documents WHERE moj_id IS NOT NULL)
          AND r.target_moj_id NOT IN (SELECT moj_id FROM crawl_frontier)
        GROUP BY r.target_moj_id, r.target_doc_num
        ORDER BY COUNT(*) DESC
    """)).mappings().all()

    added = 0
    bo_qua_qua_sau = 0
    for row in rows:
        if (row["doc_num"] or "").strip() in JUNK_DOC_NUMS:
            continue
        if CLOSURE_MAX_DEPTH and row["depth"] > CLOSURE_MAX_DEPTH:
            bo_qua_qua_sau += 1
            continue
        # ON CONFLICT DO NOTHING chứ KHÔNG dùng INSERT OR IGNORE: dạng OR IGNORE
        # nuốt mọi vi phạm ràng buộc, kể cả NOT NULL, nên thiếu một cột bắt buộc
        # là toàn bộ hàng đợi rỗng mà hàm vẫn báo đã nạp xong.
        result = session.execute(text("""
            INSERT INTO crawl_frontier
                (moj_id, doc_num, depth, priority, state, attempts,
                 discovered_via_relation)
            VALUES (:id, :num, :depth, :pri, 'PENDING', 0, :rel)
            ON CONFLICT(moj_id) DO NOTHING
        """), {
            "id": row["moj_id"],
            "num": row["doc_num"],
            "depth": row["depth"],
            "pri": priority_of(row["relation_type"], row["in_degree"], row["depth"]),
            "rel": row["relation_type"],
        })
        added += result.rowcount or 0
        if max_new and added >= max_new:
            break
    if bo_qua_qua_sau:
        logger.info(
            "Bỏ qua %d đích sâu quá %d chặng (CLOSURE_MAX_DEPTH)",
            bo_qua_qua_sau, CLOSURE_MAX_DEPTH,
        )
    return added


def unresolvable_targets(session: Session) -> int:
    """Số đích dẫn chiếu không có id MOJ nên không tải về được.

    Đưa vào báo cáo dưới dạng hạn chế dữ liệu, không nuốt im lặng.
    """
    return session.execute(text("""
        SELECT COUNT(DISTINCT target_doc_num) FROM document_references
        WHERE target_doc_id IS NULL
          AND (target_moj_id IS NULL OR target_moj_id = '')
    """)).scalar() or 0


def _next_batch(session: Session, size: int) -> list[dict]:
    rows = session.execute(text("""
        SELECT moj_id, doc_num, depth, attempts FROM crawl_frontier
        WHERE state = 'PENDING'
        ORDER BY priority DESC, depth ASC
        LIMIT :n
    """), {"n": size}).mappings().all()
    return [dict(r) for r in rows]


def _mark(session: Session, moj_id: str, state: str, error: str = "") -> None:
    session.execute(text("""
        UPDATE crawl_frontier
        SET state = :s, attempts = attempts + 1, last_error = :e,
            updated_at = datetime('now')
        WHERE moj_id = :id
    """), {"s": state, "e": (error or "")[:500], "id": moj_id})


def in_degree_of(session: Session, doc_num: str) -> int:
    return session.execute(
        text("SELECT COUNT(*) FROM document_references WHERE target_doc_num = :n"),
        {"n": doc_num},
    ).scalar() or 0


def corpus_size(session: Session) -> int:
    return session.execute(text("SELECT COUNT(*) FROM documents")).scalar() or 0


def pending_count(session: Session) -> int:
    return session.execute(
        text("SELECT COUNT(*) FROM crawl_frontier WHERE state = 'PENDING'")
    ).scalar() or 0


def run_closure(
    session: Session,
    max_fetch: int = 0,
    batch_size: int = 20,
    on_document=None,
) -> ClosureStats:
    """Rút hàng đợi bao đóng cho tới khi hết ngân sách hoặc hết việc.

    `on_document(detail, depth)` được gọi cho mỗi văn bản tải về; bên gọi lo
    phần ghi cơ sở dữ liệu và ghi file, để module này không phụ thuộc vào chi
    tiết lưu trữ và test được mà không cần mạng.

    Bốn van chặn, không cái nào thu hẹp phạm vi mà chỉ giữ vòng lặp hội tụ:
      1. Ngân sách mỗi lần chạy — frontier nằm trong DB nên chạy tiếp được.
      2. Cắt hub — văn bản bị dẫn chiếu quá nhiều vẫn TẢI VỀ nhưng không giãn
         nở tiếp. 72/2025/QH15 bị dẫn 204 lần; giãn nở từ nó sẽ kéo về cả hệ
         thống pháp luật mà không thêm giá trị nào cho doanh nghiệp.
      3. Trần tuyệt đối số văn bản trong kho.
      4. Chốt chặn dung lượng đĩa — đĩa đầy giữa lúc SQLite đang ghi có thể làm
         hỏng cơ sở dữ liệu.
    """
    from src.sources.moj_api import fetch_doc_detail, parse_doc_detail

    stats = ClosureStats()
    budget = max_fetch or CLOSURE_MAX_FETCH_PER_RUN

    while stats.fetched < budget:
        try:
            disk_guard.ensure_space(MIN_FREE_DISK_GB)
        except disk_guard.DiskSpaceExhausted as e:
            stats.stopped_reason = f"het_dung_luong_dia: {e}"
            logger.warning("Dừng bao đóng — %s", e)
            break

        if corpus_size(session) >= CLOSURE_MAX_NODES:
            stats.stopped_reason = f"cham_tran_{CLOSURE_MAX_NODES}_van_ban"
            logger.warning("Dừng bao đóng — kho đã chạm trần %d", CLOSURE_MAX_NODES)
            break

        batch = _next_batch(session, min(batch_size, budget - stats.fetched))
        if not batch:
            stats.stopped_reason = "het_hang_doi"
            break

        for item in batch:
            moj_id, doc_num, depth = item["moj_id"], item["doc_num"], item["depth"]

            if (doc_num or "").strip() in JUNK_DOC_NUMS:
                _mark(session, moj_id, NO_ID, "so hieu rac")
                stats.junk_skipped += 1
                continue

            try:
                detail = parse_doc_detail(fetch_doc_detail(moj_id))
            except Exception as e:
                _mark(session, moj_id, FAILED, str(e))
                stats.failed += 1
                logger.warning("Không tải được %s (%s): %s", doc_num, moj_id, e)
                time.sleep(MOJ_RATE_LIMIT_SECONDS)
                continue

            stats.fetched += 1

            # Cắt hub: tải về nhưng không giãn nở tiếp.
            degree = in_degree_of(session, doc_num or detail.get("doc_num", ""))
            expand = degree <= CLOSURE_HUB_INDEGREE
            if not expand:
                stats.hubs_skipped += 1
                logger.info(
                    "%s bị dẫn %d lần — tải về nhưng không giãn nở tiếp",
                    doc_num, degree,
                )

            if on_document is not None:
                try:
                    on_document(detail, depth)
                    stats.saved += 1
                except Exception as e:
                    # Rollback TRƯỚC khi đánh dấu. Sau một lỗi flush, SQLAlchemy
                    # từ chối mọi lệnh tiếp theo trên session đó, nên _mark cũng
                    # ném và giết luôn vòng lặp — một văn bản hỏng làm mất cả
                    # lô. Đã xảy ra thật: "05/2000/QĐ--BVHTT" đụng slug rồi kéo
                    # theo PendingRollbackError, lô 300 dừng ở văn bản đó.
                    session.rollback()
                    _mark(session, moj_id, FAILED, str(e))
                    session.commit()
                    stats.failed += 1
                    logger.warning("Không ghi được %s: %s", doc_num, e)
                    continue

            _mark(session, moj_id, DONE if expand else HUB_NOT_EXPANDED)
            session.commit()
            time.sleep(MOJ_RATE_LIMIT_SECONDS)

        # Đích mới phát hiện từ lô vừa xử lý.
        stats.enqueued += seed_frontier(session)
        session.commit()

    stats.no_id = unresolvable_targets(session)
    stats.pending_after = pending_count(session)
    return stats
