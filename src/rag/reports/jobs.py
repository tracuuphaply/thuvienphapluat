"""
Hàng đợi sinh báo cáo và bốn cơ chế chống ngập.

BÀI TOÁN THẬT: một ngày có thể về 50 văn bản mới. Sinh mỗi văn bản một báo cáo
là gửi cho khách 50 file PDF trong một buổi sáng — không ai đọc, và hoá đơn API
thì có thật.

BỐN CƠ CHẾ, cần đủ cả bốn:

  1. GỘP THEO NGÀY + NGÀNH. `dedupe_key = "b:{ma_nganh}:{ngay}"` nên mọi văn bản
     mới của một ngành trong một ngày vào chung MỘT báo cáo. 50 văn bản rải trên
     21 ngành cho tối đa 21 job, thực tế 4–6.
  2. CỔNG TRỌNG YẾU. Chỉ xếp hàng khi văn bản đủ nặng. Một quyết định giá đất
     cấp tỉnh không đáng gửi báo cáo cho mọi công ty xây dựng cả nước.
  3. THỜI GIAN NGUỘI. Không sinh lại báo cáo cùng ngành trong N ngày, trừ khi có
     văn bản cấp rất cao.
  4. TRẦN NGÀY. Phần dư dời sang hôm sau theo thứ tự ưu tiên, KHÔNG bị đánh rơi.

Văn bản dưới ngưỡng không biến mất: chúng được ghi nhận là SKIPPED kèm lý do, để
đưa vào báo cáo định kỳ tiếp theo.
"""
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from src.config import MAX_REPORTS_PER_DAY, REPORT_B_COOLDOWN_DAYS

logger = logging.getLogger(__name__)

QUEUED = "QUEUED"
RUNNING = "RUNNING"
DONE = "DONE"
FAILED = "FAILED"
BLOCKED_CITATION = "BLOCKED_CITATION"
SKIPPED = "SKIPPED"

# ── Cổng trọng yếu ──
# Văn bản phải thoả ÍT NHẤT MỘT điều kiện mới đáng sinh báo cáo riêng.
MIN_INTENSITY = 60.0      # cường độ tác động tối thiểu với một ngành nào đó
MAX_LEVEL_ALWAYS = 5      # Nghị định trở lên thì luôn đáng báo, bất kể điểm

# Cấp cao tới mức bỏ qua cả thời gian nguội: Hiến pháp, luật, pháp lệnh.
LEVEL_BYPASS_COOLDOWN = 3


@dataclass
class JobDecision:
    should_queue: bool
    reason: str


def materiality(hierarchy_level: int | None, max_intensity: float,
                has_status_change: bool) -> JobDecision:
    """Văn bản này có đáng một báo cáo riêng không?"""
    level = 99 if hierarchy_level is None else int(hierarchy_level)

    if level <= MAX_LEVEL_ALWAYS:
        return JobDecision(True, f"cap_hieu_luc_{level}")
    if has_status_change:
        return JobDecision(True, "doi_trang_thai_hieu_luc")
    if max_intensity >= MIN_INTENSITY:
        return JobDecision(True, f"cuong_do_{max_intensity:.0f}")
    return JobDecision(
        False, f"duoi_nguong (cap {level}, cuong do {max_intensity:.0f})"
    )


def dedupe_key(kind: str, subject: str, day: datetime.date) -> str:
    return f"{kind}:{subject}:{day.isoformat()}"


def in_cooldown(session, vsic_code: str, day: datetime.date,
                hierarchy_level: int | None) -> bool:
    """Ngành này vừa có báo cáo gần đây chưa?

    Văn bản cấp rất cao (luật, pháp lệnh) bỏ qua thời gian nguội: một đạo luật
    mới đáng báo ngay kể cả khi tuần trước vừa có bản tin.
    """
    if hierarchy_level is not None and int(hierarchy_level) <= LEVEL_BYPASS_COOLDOWN:
        return False

    since = (day - datetime.timedelta(days=REPORT_B_COOLDOWN_DAYS)).isoformat()
    row = session.execute(text("""
        SELECT COUNT(*) FROM report_jobs
        WHERE kind = 'b' AND vsic_code = :c AND status IN ('DONE','RUNNING','QUEUED')
          AND date(created_at) >= :since
    """), {"c": vsic_code, "since": since}).scalar()
    return bool(row)


def _queued_today(session, day: datetime.date) -> int:
    return session.execute(text("""
        SELECT COUNT(*) FROM report_jobs
        WHERE date(COALESCE(scheduled_for, created_at)) = :d
          AND status IN ('QUEUED','RUNNING','DONE')
    """), {"d": day.isoformat()}).scalar() or 0


def enqueue(
    session,
    kind: str,
    subject: str,
    *,
    vsic_code: str = "",
    industry: str = "",
    subject_keys: str = "",
    parent_job_id: int | None = None,
    trigger_reason: str = "",
    priority: float = 0.0,
    day: datetime.date | None = None,
) -> int | None:
    """Xếp một báo cáo vào hàng đợi. Trả về id job, hoặc None nếu đã có.

    Chạm trần ngày thì DỜI sang hôm sau chứ không bỏ — báo cáo bị đánh rơi im
    lặng là mất dữ liệu, không phải tiết kiệm chi phí.
    """
    day = day or datetime.date.today()
    key = dedupe_key(kind, subject, day)

    scheduled = day
    while _queued_today(session, scheduled) >= MAX_REPORTS_PER_DAY:
        scheduled += datetime.timedelta(days=1)
        if (scheduled - day).days > 7:
            logger.warning("Hàng đợi báo cáo đầy quá 7 ngày — bỏ qua %s", key)
            return None

    result = session.execute(text("""
        INSERT INTO report_jobs
            (kind, status, vsic_code, industry, subject_keys, parent_job_id,
             trigger_reason, dedupe_key, priority, scheduled_for)
        VALUES (:k, 'QUEUED', :c, :i, :sk, :p, :tr, :dk, :pri, :sf)
        ON CONFLICT(dedupe_key) DO NOTHING
    """), {
        "k": kind, "c": vsic_code, "i": industry, "sk": subject_keys,
        "p": parent_job_id, "tr": trigger_reason, "dk": key,
        "pri": priority, "sf": scheduled.isoformat(),
    })
    if not result.rowcount:
        return None

    job_id = session.execute(text("SELECT last_insert_rowid()")).scalar()
    logger.info("Đã xếp hàng báo cáo %s (%s), chạy ngày %s", key, trigger_reason, scheduled)
    return job_id


def record_skip(session, kind: str, subject: str, reason: str,
                day: datetime.date | None = None) -> None:
    """Ghi nhận văn bản dưới ngưỡng.

    KHÔNG im lặng bỏ qua: phải biết cái gì đã không được báo cáo, để đưa vào bản
    tổng hợp định kỳ tiếp theo.
    """
    day = day or datetime.date.today()
    # Ghi đủ mọi cột NOT NULL. `priority` có giá trị mặc định ở tầng Python chứ
    # không ở tầng SQL, nên câu INSERT thô phải tự điền — và ON CONFLICT DO
    # NOTHING (khác INSERT OR IGNORE) sẽ ném lỗi thay vì giấu nếu thiếu.
    session.execute(text("""
        INSERT INTO report_jobs (kind, status, dedupe_key, trigger_reason, priority)
        VALUES (:k, 'SKIPPED', :dk, :r, 0)
        ON CONFLICT(dedupe_key) DO NOTHING
    """), {"k": kind, "dk": dedupe_key(kind, subject, day) + ":skip", "r": reason[:80]})


def next_job(session, day: datetime.date | None = None) -> dict[str, Any] | None:
    day = day or datetime.date.today()
    row = session.execute(text("""
        SELECT * FROM report_jobs
        WHERE status = 'QUEUED' AND date(scheduled_for) <= :d
        ORDER BY priority DESC, id ASC LIMIT 1
    """), {"d": day.isoformat()}).mappings().first()
    return dict(row) if row else None


def mark(session, job_id: int, status: str, **fields: Any) -> None:
    sets = ["status = :s"]
    params: dict[str, Any] = {"s": status, "id": job_id}
    if status == RUNNING:
        sets.append("started_at = datetime('now')")
    if status in (DONE, FAILED, BLOCKED_CITATION):
        sets.append("finished_at = datetime('now')")
    for key, value in fields.items():
        sets.append(f"{key} = :{key}")
        params[key] = value
    session.execute(
        text(f"UPDATE report_jobs SET {', '.join(sets)} WHERE id = :id"), params
    )


def enqueue_update_reports(session, saved_docs: list[dict]) -> int:
    """Xếp hàng báo cáo (b) cho các văn bản vừa cào về.

    Gộp theo (ngành, ngày) — đây là cơ chế chống ngập quan trọng nhất. 50 văn
    bản mới rải trên 21 ngành cho tối đa 21 job thay vì 50, và thực tế 4–6 vì
    phần lớn văn bản tập trung vào vài ngành.

    Văn bản dưới ngưỡng trọng yếu được ghi nhận SKIPPED kèm lý do chứ không biến
    mất — chúng sẽ vào báo cáo tổng hợp định kỳ tiếp theo.
    """
    import datetime as _dt
    import json as _json

    from sqlalchemy import text as _text

    if not saved_docs:
        return 0

    from src.legal.business_relevance import field_scope_by_key, is_business_document, reason_excluded

    today = _dt.date.today()
    version = _current_scorer_version()

    # Bộ lọc "liên quan doanh nghiệp": bỏ văn bản ngoài lĩnh vực kinh doanh và
    # văn bản cấp tỉnh trước khi xét trọng yếu. Đây là chốt chặn để một quyết
    # định y tế cấp tỉnh không thành báo cáo gửi chủ doanh nghiệp. Tra một lượt
    # cho cả lô.
    meta = field_scope_by_key(
        session, [d.get("doc_key") for d in saved_docs if d.get("doc_key")])

    # (mã ngành) → {doc_key}, kèm cấp cao nhất và cường độ mạnh nhất của nhóm
    groups: dict[str, dict] = {}

    for doc in saved_docs:
        doc_key = doc.get("doc_key")
        if not doc_key or doc.get("is_closure_node"):
            continue

        field, scope = meta.get(doc_key, (None, None))
        if not is_business_document(field, scope):
            record_skip(session, "b", doc_key, reason_excluded(field, scope), today)
            continue

        rows = session.execute(_text("""
            SELECT vsic_code, impact_pct_industry FROM document_industry_impact
            WHERE doc_key = :k AND scorer_version = :v
            ORDER BY impact_pct_industry DESC LIMIT 3
        """), {"k": doc_key, "v": version}).mappings().all()

        level = doc.get("hierarchy_level")
        best = rows[0]["impact_pct_industry"] if rows else 0.0
        decision = materiality(level, best, bool(doc.get("event_type") == "B"))
        if not decision.should_queue:
            record_skip(session, "b", doc_key, decision.reason, today)
            continue

        if not rows:
            # Chưa chấm điểm được thì vẫn phải báo nếu đủ trọng yếu — nhưng
            # không biết ngành, nên xếp vào nhóm "chưa phân ngành".
            rows = [{"vsic_code": "ZZ", "impact_pct_industry": 0.0}]

        for row in rows:
            code = row["vsic_code"]
            g = groups.setdefault(code, {"keys": [], "level": 99, "intensity": 0.0,
                                         "reason": decision.reason})
            g["keys"].append(doc_key)
            g["level"] = min(g["level"], 99 if level is None else int(level))
            g["intensity"] = max(g["intensity"], row["impact_pct_industry"])

    from src.obsidian.vsic import BY_CODE

    queued = 0
    for code, g in groups.items():
        if in_cooldown(session, code, today, g["level"]):
            record_skip(session, "b", f"{code}-cooldown", "trong_thoi_gian_nguoi", today)
            continue
        if enqueue(
            session, "b", code,
            vsic_code=code,
            industry=BY_CODE.get(code, {}).get("ten_ngan", code),
            subject_keys=_json.dumps(sorted(set(g["keys"])), ensure_ascii=False),
            trigger_reason=g["reason"],
            priority=g["intensity"],
            day=today,
        ):
            queued += 1
    return queued


def _current_scorer_version() -> str:
    from src.config import impact_scorer_version

    return impact_scorer_version()
