"""
Lõi lệnh /bieumau trên Telegram — nhận session, trả về chuỗi và đường dẫn file.

Cùng khuôn với src/notification/report_commands.py và cùng lý do: ở đây không
import python-telegram-bot, không async, không đụng mạng, nên toàn bộ logic kiểm
thử được bằng một session SQLite trong bộ nhớ. Handler bên telegram_bot_server
chỉ là lớp vỏ.

KHÁC BÁO CÁO Ở MỘT ĐIỂM: lệnh này KHÔNG xếp hàng. Báo cáo phải qua hàng đợi vì
cổng kiểm trích dẫn nằm ở tầng worker và không được đi vòng. Biểu mẫu thì không
có nội dung nào do mô hình sinh ra — file đã dựng sẵn nằm trên đĩa, gửi thẳng.

Lệnh:
    /bieumau                    hướng dẫn + 12 nhóm nghiệp vụ kèm số lượng
    /bieumau <từ khoá>          tìm, trả 10 kết quả đầu
    /bieumau nhom <mã>          liệt kê theo nhóm nghiệp vụ
    /bieumau <mã biểu mẫu>      gửi file DOCX + PDF
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from src.forms import effectivity as bm_eff
from src.forms import search
from src.forms.renderer import thu_muc_dung
from src.legal.form_taxonomy import NGHIEP_VU, ten_nhom_hop_dong
from src.sources.tvpl_forms_parse import SOURCE_HOP_DONG
from src.storage.models import LegalForm, LegalFormRef

logger = logging.getLogger(__name__)

GIOI_HAN_KET_QUA = 10
GIOI_HAN_NHOM = 15


@dataclass
class KetQua:
    van_ban: str
    file_dinh_kem: str | None = None
    file_bo_sung: list[str] = field(default_factory=list)


def _nghiep_vu_cua(form: LegalForm) -> list[str]:
    return json.loads(form.nghiep_vu or "[]")


#: Biểu tượng hiệu lực, đặt NGAY TRƯỚC mã mẫu trong danh sách kết quả.
#: Người dùng Telegram quét danh sách rất nhanh; nhãn chữ dài bị bỏ qua còn một
#: ký tự màu thì không.
_DAU_HIEU_LUC = {
    bm_eff.CON_HIEU_LUC: "🟢",
    bm_eff.CAN_KIEM_TRA: "🟡",
    bm_eff.CO_BAN_THAY_THE: "🟠",
    bm_eff.HET_HIEU_LUC: "🔴",
    bm_eff.KHONG_RO: "⚪",
}


def _dau_hieu_luc(eff_state: str | None) -> str:
    return _DAU_HIEU_LUC.get(eff_state or bm_eff.KHONG_RO, "⚪")


def _dong_ket_qua(stt: int, form_key: str, title: str, nghiep_vu: list[str],
                  eff_state: str | None = None) -> str:
    nhan = " · ".join(NGHIEP_VU.get(ma, ma) for ma in nghiep_vu[:2])
    # Tiêu đề biểu mẫu dài tới hơn 200 ký tự; Telegram giới hạn 4096 ký tự một
    # tin nên 10 kết quả chưa cắt là tràn tin nhắn.
    tom = title if len(title) <= 90 else title[:88] + "…"
    return (f"{stt}. {_dau_hieu_luc(eff_state)} `{form_key}`\n   {tom}"
            + (f"\n   _{nhan}_" if nhan else ""))


# ──────────────────────────────────────────────
# Hướng dẫn
# ──────────────────────────────────────────────
def huong_dan(session) -> KetQua:
    dem = search.dem_theo_nghiep_vu(session)
    tong = (
        session.query(LegalForm)
        .filter(LegalForm.is_business.is_(True))
        .count()
    )
    if not tong:
        return KetQua(
            "📭 Kho biểu mẫu còn trống.\n\n"
            "Chạy `python -m scripts.crawl_forms --source hopdong` rồi "
            "`python -m scripts.classify_forms` để nạp."
        )

    dong = [f"📄 *Biểu mẫu cho doanh nghiệp* — {tong} mẫu\n"]
    for ma, ten in NGHIEP_VU.items():
        n = dem.get(ma, 0)
        if n:
            dong.append(f"`{ma}` — {ten} ({n})")
    dong += [
        "",
        "*Cách dùng*",
        "`/bieumau hợp đồng lao động` — tìm theo từ khoá",
        "`/bieumau nhom lao_dong_bhxh` — xem cả nhóm",
        "`/bieumau hopdong-46696` — tải file",
    ]
    return KetQua("\n".join(dong))


# ──────────────────────────────────────────────
# Tìm
# ──────────────────────────────────────────────
def tim_bieu_mau(session, tu_khoa: str) -> KetQua:
    ket_qua = search.tim(tu_khoa, gioi_han=GIOI_HAN_KET_QUA)
    if not ket_qua:
        return KetQua(
            f"🔍 Không thấy biểu mẫu nào khớp *{tu_khoa}*.\n\n"
            "Gõ `/bieumau` để xem danh sách nhóm nghiệp vụ."
        )
    hl = {
        k: v for k, v in session.query(LegalForm.form_key, LegalForm.eff_state)
        .filter(LegalForm.form_key.in_([r.form_key for r in ket_qua])).all()
    }
    dong = [f"🔍 *{len(ket_qua)} biểu mẫu khớp* “{tu_khoa}”\n"]
    for i, r in enumerate(ket_qua, 1):
        dong.append(_dong_ket_qua(i, r.form_key, r.title, r.nghiep_vu,
                                  hl.get(r.form_key)))
    dong.append("\n🟢 còn hiệu lực · 🟡 cần kiểm tra · 🟠 có bản thay thế · "
                "🔴 hết hiệu lực · ⚪ chưa xác minh")
    dong.append("Tải file: `/bieumau <mã>`")
    return KetQua("\n".join(dong))


def liet_ke_nhom(session, ma_nhom: str) -> KetQua:
    ma = (ma_nhom or "").strip().lower()
    if ma not in NGHIEP_VU:
        return KetQua(
            f"❌ Không có nhóm `{ma_nhom}`.\n\n"
            "Nhóm hợp lệ: " + ", ".join(f"`{k}`" for k in NGHIEP_VU)
        )
    # Lọc trong Python chứ không LIKE trên cột JSON: "shtt" là chuỗi con của
    # nhiều thứ, và LIKE '%shtt%' sẽ khớp cả nhóm khác nếu về sau thêm mã dài hơn.
    rows = (
        session.query(LegalForm)
        .filter(LegalForm.is_business.is_(True))
        .order_by(LegalForm.updated_on.desc())
        .all()
    )
    thuoc_nhom = [f for f in rows if ma in _nghiep_vu_cua(f)]
    if not thuoc_nhom:
        return KetQua(f"📭 Nhóm *{NGHIEP_VU[ma]}* chưa có biểu mẫu nào.")

    dong = [f"📂 *{NGHIEP_VU[ma]}* — {len(thuoc_nhom)} mẫu\n"]
    for i, f in enumerate(thuoc_nhom[:GIOI_HAN_NHOM], 1):
        dong.append(_dong_ket_qua(i, f.form_key, f.title or "",
                                  _nghiep_vu_cua(f), f.eff_state))
    if len(thuoc_nhom) > GIOI_HAN_NHOM:
        dong.append(f"\n… và {len(thuoc_nhom) - GIOI_HAN_NHOM} mẫu nữa. "
                    "Thu hẹp bằng `/bieumau <từ khoá>`.")
    return KetQua("\n".join(dong))


# ──────────────────────────────────────────────
# Gửi file
# ──────────────────────────────────────────────
def chi_tiet_bieu_mau(session, form_key: str) -> KetQua:
    form = (
        session.query(LegalForm)
        .filter_by(form_key=(form_key or "").strip())
        .one_or_none()
    )
    if form is None:
        return KetQua(f"❌ Không có biểu mẫu `{form_key}`.\n\n"
                      "Tìm bằng `/bieumau <từ khoá>`.")

    can_cu = [r.doc_num for r in
              session.query(LegalFormRef).filter_by(form_key=form.form_key).all()]
    nhom = " · ".join(NGHIEP_VU.get(m, m) for m in _nghiep_vu_cua(form))

    dong = [f"📄 *{form.title}*", ""]
    # Hiệu lực đứng TRƯỚC mọi metadata khác: đây là thứ quyết định người dùng có
    # nên điền tờ giấy này hay không.
    if form.delisted_at:
        dong.append(f"🚫 *Nguồn đã gỡ biểu mẫu này* "
                    f"({form.delisted_at:%d/%m/%Y}) — không nên dùng để nộp.")
    trang_thai = form.eff_state or bm_eff.KHONG_RO
    dong.append(f"{_dau_hieu_luc(trang_thai)} *{bm_eff.NHAN[trang_thai]}*"
                + (f" _(tính đến {form.eff_state_as_of:%d/%m/%Y})_"
                   if form.eff_state_as_of else ""))
    if form.eff_note:
        dong.append(f"_{form.eff_note[:300]}_")
    if form.eff_replaced_by:
        try:
            ds = json.loads(form.eff_replaced_by)
        except ValueError:
            ds = []
        if ds:
            dong.append(f"➡️ Tìm mẫu mới ở: *{', '.join(ds[:3])}*")
    dong.append("")
    if form.source == SOURCE_HOP_DONG and form.form_type_code:
        dong.append(f"Nhóm hợp đồng: {ten_nhom_hop_dong(form.form_type_code)}")
    elif form.field_name:
        dong.append(f"Lĩnh vực: {form.field_name}")
    if nhom:
        dong.append(f"Nghiệp vụ: {nhom}")
    if can_cu:
        dong.append(f"Căn cứ: {', '.join(can_cu[:4])}")
    if form.updated_on:
        dong.append(f"Cập nhật: {form.updated_on:%d/%m/%Y}")
    dong.append(f"Nguồn: {form.url}")

    # Cảnh báo khi mẫu KHÔNG thuộc nhóm doanh nghiệp: người dùng vẫn tra được nếu
    # biết mã, nhưng phải biết mình đang cầm mẫu không dành cho mình.
    if form.is_business is False:
        dong.append("\n⚠️ Mẫu này không thuộc nhóm doanh nghiệp "
                    f"({form.audience or 'chưa rõ'}).")

    dinh_kem, bo_sung = _file_cua(form)
    if not dinh_kem:
        dong.append("\n⚠️ Chưa dựng được file. Chạy "
                    "`python -m scripts.build_forms` rồi thử lại.")
    return KetQua("\n".join(dong), file_dinh_kem=dinh_kem, file_bo_sung=bo_sung)


def _file_cua(form: LegalForm) -> tuple[str | None, list[str]]:
    """DOCX đứng trước PDF: biểu mẫu là để ĐIỀN, mà PDF thì không điền được."""
    ung_vien: list[Path] = []
    for duong_dan in (form.docx_path, form.pdf_path):
        if duong_dan and Path(duong_dan).exists():
            ung_vien.append(Path(duong_dan))
    if not ung_vien:
        thu_muc = thu_muc_dung(form.form_key)
        for duoi in (".docx", ".pdf"):
            p = thu_muc / f"{form.form_key}{duoi}"
            if p.exists():
                ung_vien.append(p)
    if not ung_vien:
        return None, []
    return str(ung_vien[0]), [str(p) for p in ung_vien[1:]]


# ──────────────────────────────────────────────
# Định tuyến
# ──────────────────────────────────────────────
def xu_ly(session, tham_so: list[str] | None) -> KetQua:
    """Định tuyến `/bieumau …` về đúng nhánh.

    Nhận diện mã biểu mẫu bằng TIỀN TỐ KHO ("bieumau-" / "hopdong-") chứ không
    bằng "có gạch nối": người dùng gõ "hợp đồng thuê - mượn" cũng có gạch nối,
    mà đó là câu tìm kiếm.
    """
    phan = [t for t in (tham_so or []) if t.strip()]
    if not phan:
        return huong_dan(session)

    if phan[0].lower() in ("nhom", "nhóm"):
        return liet_ke_nhom(session, phan[1] if len(phan) > 1 else "")

    if len(phan) == 1 and phan[0].startswith(("bieumau-", "hopdong-")):
        return chi_tiet_bieu_mau(session, phan[0])

    return tim_bieu_mau(session, " ".join(phan))


__all__ = [
    "KetQua", "GIOI_HAN_KET_QUA", "GIOI_HAN_NHOM",
    "huong_dan", "tim_bieu_mau", "liet_ke_nhom", "chi_tiet_bieu_mau", "xu_ly",
]
