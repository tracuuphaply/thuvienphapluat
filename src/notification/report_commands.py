"""
Lõi điều khiển báo cáo qua Telegram — nhận session, trả về chuỗi để gửi.

TÁCH KHỎI TELEGRAM LÀ CỐ Ý. Ở đây không import python-telegram-bot, không có
async, không đụng mạng. Nhờ vậy toàn bộ logic kiểm thử được bằng một session
SQLite trong bộ nhớ; phần handler bên telegram_bot_server chỉ còn là lớp vỏ gọi
xuống đây rồi gửi chuỗi đi.

MỌI LỆNH ĐỀU ĐI QUA HÀNG ĐỢI, KHÔNG SINH BÁO CÁO TẠI CHỖ. Lý do là an toàn chứ
không phải kiến trúc: đường /report cũ gọi thẳng generate_compliance_report rồi
xuất PDF bằng pdf_exporter, tức KHÔNG qua check_citations. Một báo cáo có số
hiệu do mô hình bịa vẫn gửi được cho khách hàng — chính là điều mà cổng trích
dẫn sinh ra để chặn, và nó chỉ chặn ở tầng worker. Xếp hàng rồi để worker chạy
là cách duy nhất khiến cổng đó không thể đi vòng.

Lệnh:
    /baocao                 hướng dẫn + tóm tắt hàng đợi
    /baocao a K             xếp báo cáo tổng hợp ngành K
    /baocao b               xếp báo cáo cập nhật văn bản mới
    /nganh                  danh sách 21 ngành VSIC
    /hangdoi                các báo cáo đang chờ / đang chạy / vừa xong
    /xem <id>               chi tiết một báo cáo, kèm file PDF nếu có
    /huy <id>               huỷ một báo cáo còn đang chờ
    /chay                   chạy hàng đợi ngay, không đợi lịch
"""
from __future__ import annotations

import datetime
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text

from src.obsidian.vsic import BY_CODE, VSIC_LEVEL1
from src.rag.reports import jobs

logger = logging.getLogger(__name__)

# Huỷ tay từ Telegram. Không dùng lại SKIPPED vì SKIPPED đã mang nghĩa "dưới
# ngưỡng trọng yếu nên hệ thống tự bỏ" — gộp hai thứ lại thì về sau không phân
# biệt được máy bỏ hay người bỏ. Cột status không có ràng buộc CHECK nên thêm
# trạng thái không cần migration.
CANCELLED = "CANCELLED"

NHAN_TRANG_THAI = {
    jobs.QUEUED: "⏳ đang chờ",
    jobs.RUNNING: "⚙️ đang chạy",
    jobs.DONE: "✅ xong",
    jobs.FAILED: "❌ lỗi",
    jobs.BLOCKED_CITATION: "🚫 bị chặn (số hiệu lạ)",
    jobs.SKIPPED: "⏭️ bỏ qua (dưới ngưỡng)",
    CANCELLED: "🗑️ đã huỷ",
}

TEN_LOAI = {
    "a": "Tổng hợp ngành",
    "b": "Cập nhật văn bản mới",
    "c": "Chuyên sâu doanh nghiệp",
}


@dataclass
class KetQua:
    """Kết quả một lệnh: chuỗi để gửi, kèm đường dẫn file nếu có."""
    van_ban: str
    file_dinh_kem: str | None = None
    # Báo cáo có hai bản PDF khác nhau đúng ở chân trang; gửi cả hai để người
    # dùng chọn đúng bản cho đúng người nhận.
    file_bo_sung: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────
# Xếp hàng
# ──────────────────────────────────────────────

def xep_bao_cao(session, kind: str, ma_nganh: str = "") -> KetQua:
    """Xếp một báo cáo vào hàng đợi theo yêu cầu của người dùng.

    Báo cáo (c) KHÔNG xếp tay được: nó tiêu thụ đầu ra của (b) qua sidecar JSON,
    nên xếp một job (c) không có cha là tạo ra một job chắc chắn thất bại. Worker
    tự sinh (c) khi (b) xong và qua cổng trích dẫn.
    """
    kind = (kind or "").strip().lower()
    if kind == "c":
        return KetQua(
            "❌ Báo cáo loại (c) không đặt tay được.\n\n"
            "Nó dựa trên kết quả của báo cáo (b) nên hệ thống tự tạo sau khi (b) "
            "chạy xong và qua được kiểm tra trích dẫn."
        )
    if kind not in ("a", "b"):
        return KetQua(
            "❌ Không rõ loại báo cáo.\n\n"
            "`/baocao a <mã ngành>` — tổng hợp ngành\n"
            "`/baocao b` — cập nhật văn bản mới\n\n"
            "Gõ `/nganh` để xem mã ngành."
        )

    if kind == "a":
        ma = (ma_nganh or "").strip().upper()
        if not ma:
            return KetQua("❌ Thiếu mã ngành.\nVí dụ: `/baocao a K`\n"
                          "Gõ `/nganh` để xem danh sách.")
        nganh = BY_CODE.get(ma)
        if not nganh:
            return KetQua(f"❌ Không có ngành mã `{ma}`.\nGõ `/nganh` để xem 21 mã hợp lệ.")
        job_id = jobs.enqueue(
            session, "a", subject=ma, vsic_code=ma, industry=nganh["ten_ngan"],
            trigger_reason="telegram", priority=100.0,
        )
        ten = nganh["ten_ngan"]
    else:
        keys = _van_ban_moi_chua_bao_cao(session)
        if not keys:
            return KetQua(
                "ℹ️ Không có văn bản mới nào chưa được đưa vào báo cáo.\n\n"
                "Báo cáo (b) chỉ có nội dung khi kho vừa nhận văn bản mới hoặc "
                "vừa có văn bản đổi hiệu lực."
            )
        import json as _json
        job_id = jobs.enqueue(
            session, "b", subject=f"tay-{datetime.date.today().isoformat()}",
            subject_keys=_json.dumps(keys, ensure_ascii=False),
            trigger_reason="telegram", priority=100.0,
        )
        ten = f"{len(keys)} văn bản mới"

    if job_id is None:
        return KetQua(
            f"ℹ️ Báo cáo cho *{ten}* hôm nay đã có trong hàng đợi rồi.\n"
            f"Gõ `/hangdoi` để xem."
        )

    return KetQua(
        f"✅ Đã xếp hàng báo cáo #{job_id}\n\n"
        f"*Loại:* {TEN_LOAI[kind]}\n"
        f"*Chủ đề:* {ten}\n\n"
        f"Gõ `/chay` để chạy ngay, hoặc để hệ thống tự chạy theo lịch.\n"
        f"Theo dõi bằng `/xem {job_id}`."
    )


def _van_ban_moi_chua_bao_cao(session, gioi_han: int = 40) -> list[str]:
    """doc_key của văn bản mới/đổi hiệu lực chưa nằm trong báo cáo (b) nào.

    Lấy theo event_type như trigger tự động, nhưng KHÔNG áp ngưỡng trọng yếu:
    người dùng gõ lệnh tay là đã cố ý muốn báo cáo về chúng, còn ngưỡng sinh ra
    để chặn hệ thống tự phát báo cáo tràn lan.

    Vẫn áp bộ lọc "liên quan doanh nghiệp": lệnh tay bỏ qua ngưỡng trọng yếu chứ
    không bỏ qua mục tiêu người đọc — văn bản y tế hay cấp tỉnh vẫn bị loại. Lọc
    ngay trong SQL để LIMIT tính trên phần đã lọc, không phải lấy 40 rồi còn vài.
    """
    from src.config import report_central_only
    from src.legal.business_relevance import CENTRAL_SCOPE, business_field_codes

    codes = sorted(business_field_codes())
    ph = ",".join(f":f{i}" for i in range(len(codes)))
    params: dict = {f"f{i}": c for i, c in enumerate(codes)}
    params["n"] = gioi_han
    scope_cond = ""
    if report_central_only():
        scope_cond = "AND territorial_scope = :scope"
        params["scope"] = CENTRAL_SCOPE

    rows = session.execute(text(f"""
        SELECT doc_key FROM documents
        WHERE event_type IS NOT NULL AND doc_key IS NOT NULL
          AND tvpl_field_code IN ({ph})
          {scope_cond}
        ORDER BY COALESCE(issue_date, created_at) DESC
        LIMIT :n
    """), params).scalars().all()
    return [r for r in rows if r]


# ──────────────────────────────────────────────
# Xem và quản lý
# ──────────────────────────────────────────────

def danh_sach_nganh() -> KetQua:
    dong = [f"`{n['ma']}` — {n['ten_ngan']}" for n in VSIC_LEVEL1]
    return KetQua(
        "🏢 *21 ngành kinh tế (VSIC cấp 1)*\n"
        "_Theo Quyết định 27/2018/QĐ-TTg — đây là mã ghi trên giấy đăng ký "
        "doanh nghiệp._\n\n"
        + "\n".join(dong)
        + "\n\nĐặt báo cáo: `/baocao a K`"
    )


def danh_sach_hang_doi(session, gioi_han: int = 15) -> KetQua:
    rows = session.execute(text("""
        SELECT id, kind, status, industry, vsic_code, scheduled_for,
               citation_missing, error
        FROM report_jobs
        ORDER BY
            CASE status WHEN 'RUNNING' THEN 0 WHEN 'QUEUED' THEN 1 ELSE 2 END,
            id DESC
        LIMIT :n
    """), {"n": gioi_han}).mappings().all()

    if not rows:
        return KetQua("📭 Hàng đợi trống.\n\nĐặt báo cáo: `/baocao a K`")

    dem = session.execute(text(
        "SELECT status, COUNT(*) n FROM report_jobs GROUP BY status"
    )).mappings().all()
    tom_tat = " · ".join(
        f"{NHAN_TRANG_THAI.get(r['status'], r['status'])} {r['n']}" for r in dem)

    dong = ["📋 *HÀNG ĐỢI BÁO CÁO*", "", tom_tat, ""]
    for r in rows:
        chu_de = r["industry"] or r["vsic_code"] or TEN_LOAI.get(r["kind"], "")
        dong.append(
            f"`#{r['id']}` {NHAN_TRANG_THAI.get(r['status'], r['status'])} — "
            f"{TEN_LOAI.get(r['kind'], r['kind'])}"
            + (f" · {chu_de}" if chu_de else "")
        )
    dong += ["", "Chi tiết: `/xem <id>` · Huỷ: `/huy <id>` · Chạy ngay: `/chay`"]
    return KetQua("\n".join(dong))


def chi_tiet_job(session, job_id: int) -> KetQua:
    """Chi tiết một báo cáo. Đính kèm PDF nếu file còn trên đĩa."""
    r = session.execute(text("""
        SELECT id, kind, status, industry, vsic_code, trigger_reason,
               scheduled_for, started_at, finished_at, output_pdf_path,
               output_md_path, citation_total, citation_missing, model, error
        FROM report_jobs WHERE id = :i
    """), {"i": job_id}).mappings().first()

    if not r:
        return KetQua(f"❌ Không có báo cáo `#{job_id}`.\nGõ `/hangdoi` để xem danh sách.")

    dong = [
        f"📄 *BÁO CÁO #{r['id']}*", "",
        f"*Loại:* {TEN_LOAI.get(r['kind'], r['kind'])}",
        f"*Trạng thái:* {NHAN_TRANG_THAI.get(r['status'], r['status'])}",
    ]
    if r["industry"] or r["vsic_code"]:
        dong.append(f"*Ngành:* {r['vsic_code']} · {r['industry']}")
    if r["trigger_reason"]:
        dong.append(f"*Do:* {r['trigger_reason']}")
    for nhan, khoa in (("Đặt lịch", "scheduled_for"), ("Bắt đầu", "started_at"),
                       ("Kết thúc", "finished_at")):
        if r[khoa]:
            dong.append(f"*{nhan}:* {r[khoa]}")
    if r["model"]:
        dong.append(f"*Mô hình:* {r['model']}")

    if r["status"] == jobs.BLOCKED_CITATION:
        dong += ["", (
            f"🚫 *Bị chặn xuất bản.* {r['citation_missing']}/{r['citation_total']} "
            f"số hiệu trong báo cáo không có trong kho — nhiều khả năng do mô hình "
            f"bịa. Bản markdown vẫn được ghi lại để soi, nhưng KHÔNG dựng PDF và "
            f"KHÔNG gửi đi."
        )]
    elif r["status"] == jobs.FAILED and r["error"]:
        dong += ["", f"❌ *Lỗi:* `{str(r['error'])[:300]}`"]

    khach, doi_tac = _hai_ban_pdf(r["output_pdf_path"])
    if khach or doi_tac:
        dong += [""]
        if khach and doi_tac:
            dong += ["📎 Gửi *hai bản*:",
                     "• `_khach` — chân trang gọn, gửi doanh nghiệp",
                     "• `_doitac` — có lời ngỏ hợp tác, gửi công ty luật"]
        else:
            dong += ["📎 Đang gửi file PDF…"]
        co_ban = [p for p in (khach, doi_tac) if p]
        return KetQua("\n".join(dong), file_dinh_kem=co_ban[0],
                      file_bo_sung=co_ban[1:])

    if r["status"] == jobs.DONE:
        dong += ["", "⚠️ Báo cáo xong nhưng không có file PDF (thường do thiếu font)."]

    return KetQua("\n".join(dong))


def _hai_ban_pdf(duong_dan: str | None) -> tuple[str | None, str | None]:
    """(bản gửi khách, bản gửi đối tác) — chỉ trả về file thật sự còn trên đĩa.

    Worker ghi hai file cạnh nhau, tên chỉ khác hậu tố, nhưng DB chỉ giữ một
    đường dẫn. Suy ra bản kia từ tên thay vì thêm cột: hai bản luôn sinh cùng
    lúc và cùng chỗ, nên một cột nữa chỉ là hai nguồn sự thật cho một việc.
    """
    if not duong_dan:
        return None, None
    p = Path(duong_dan)
    goc = re.sub(r"_(khach|doitac)$", "", p.stem)

    def _co(hau_to: str) -> str | None:
        f = p.with_name(f"{goc}_{hau_to}.pdf")
        return str(f) if f.exists() else None

    khach, doi_tac = _co("khach"), _co("doitac")
    # Báo cáo cũ sinh trước khi tách hai bản chỉ có một file không hậu tố.
    if not khach and not doi_tac and p.exists():
        return str(p), None
    return khach, doi_tac


def huy_job(session, job_id: int) -> KetQua:
    """Huỷ một báo cáo còn đang chờ.

    CHỈ huỷ được job đang QUEUED. Job RUNNING đang có một lời gọi mô hình dở
    dang; đánh dấu huỷ ở đây không dừng được tiến trình đó, chỉ làm trạng thái
    trong DB nói sai về thực tế — rồi worker vẫn ghi đè kết quả khi xong.
    """
    r = session.execute(text(
        "SELECT id, status, kind, industry FROM report_jobs WHERE id = :i"
    ), {"i": job_id}).mappings().first()

    if not r:
        return KetQua(f"❌ Không có báo cáo `#{job_id}`.")
    if r["status"] == jobs.RUNNING:
        return KetQua(
            f"⚠️ Báo cáo `#{job_id}` đang chạy, không huỷ giữa chừng được.\n"
            f"Đợi nó xong rồi xem kết quả bằng `/xem {job_id}`."
        )
    if r["status"] != jobs.QUEUED:
        return KetQua(
            f"ℹ️ Báo cáo `#{job_id}` đã ở trạng thái "
            f"{NHAN_TRANG_THAI.get(r['status'], r['status'])}, không còn gì để huỷ."
        )

    session.execute(text(
        "UPDATE report_jobs SET status = :s, finished_at = :t WHERE id = :i"
    ), {"s": CANCELLED, "t": datetime.datetime.now().isoformat(timespec="seconds"),
        "i": job_id})
    session.commit()
    return KetQua(f"🗑️ Đã huỷ báo cáo `#{job_id}`.")


def huong_dan(session) -> KetQua:
    cho = session.execute(text(
        "SELECT COUNT(*) FROM report_jobs WHERE status IN ('QUEUED','RUNNING')"
    )).scalar() or 0
    return KetQua(
        "📊 *ĐIỀU KHIỂN BÁO CÁO*\n\n"
        "*Đặt báo cáo*\n"
        "`/baocao a <mã ngành>` — tổng hợp toàn ngành\n"
        "`/baocao b` — cập nhật văn bản mới\n"
        "`/nganh` — xem 21 mã ngành\n\n"
        "*Quản lý*\n"
        "`/hangdoi` — xem hàng đợi\n"
        "`/xem <id>` — chi tiết + tải PDF\n"
        "`/huy <id>` — huỷ báo cáo đang chờ\n"
        "`/chay` — chạy hàng đợi ngay\n\n"
        f"Hiện có *{cho}* báo cáo đang chờ hoặc đang chạy.\n\n"
        "_Báo cáo loại (c) — chuyên sâu doanh nghiệp — hệ thống tự tạo sau khi "
        "(b) chạy xong._"
    )
