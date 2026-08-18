"""
Hiệu lực của biểu mẫu — SUY TỪ CĂN CỨ, không đoán.

BIỂU MẪU KHÔNG CÓ HIỆU LỰC RIÊNG. Nó là phụ lục kèm theo một văn bản quy phạm, nên
nó sống chết theo văn bản đó: Thông tư 131/2025/TT-BTC bị thay thế thì biểu mẫu kèm
theo nó cũng thôi dùng được, dù trang TVPL vẫn hiện y nguyên. Đây là lý do phần này
tồn tại — TVPL KHÔNG nói biểu mẫu còn hiệu lực hay không, chỉ nói "Cập nhật:
18/08/2026", mà ngày cập nhật là ngày họ sửa trang, không phải ngày pháp lý.

TUYỆT ĐỐI KHÔNG MẶC ĐỊNH "CÒN HIỆU LỰC". Với tài liệu tuân thủ, khẳng định một biểu
mẫu đang dùng được mà không có căn cứ chính là bịa dữ kiện pháp lý — đúng nguyên tắc
mà src/legal/effectivity.py đặt ra cho văn bản. Căn cứ chưa có trong kho thì trạng
thái là "chưa xác minh được", không phải "còn hiệu lực".

THỨ TỆ NHẤT THẮNG. Một biểu mẫu có hai căn cứ, một còn hiệu lực một đã bị bãi bỏ, thì
nó là biểu mẫu đáng ngờ — không phải biểu mẫu tốt. Thứ tự: hết hiệu lực > có bản thay
thế > cần kiểm tra > chưa xác minh > còn hiệu lực.

`co_ban_thay_the` tách riêng khỏi `het_hieu_luc` vì nó mang thông tin HÀNH ĐỘNG ĐƯỢC:
số hiệu văn bản thay thế, tức là chỗ để đi tìm biểu mẫu mới. Với chủ doanh nghiệp, đó
là thứ hữu ích nhất trong cả module này.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import text

from src.legal import effectivity as eff_vb
from src.storage.models import LegalForm, LegalFormRef

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Trạng thái hiệu lực biểu mẫu — tập ĐÓNG
# ──────────────────────────────────────────────
CON_HIEU_LUC = "con_hieu_luc"
CO_BAN_THAY_THE = "co_ban_thay_the"
CAN_KIEM_TRA = "can_kiem_tra"
HET_HIEU_LUC = "het_hieu_luc"
KHONG_RO = "khong_ro"

#: Thứ tự ưu tiên — số nhỏ thắng. "Thứ tệ nhất thắng."
_UU_TIEN = {
    HET_HIEU_LUC: 0,
    CO_BAN_THAY_THE: 1,
    CAN_KIEM_TRA: 2,
    KHONG_RO: 3,
    CON_HIEU_LUC: 4,
}

NHAN = {
    CON_HIEU_LUC: "Còn hiệu lực",
    CO_BAN_THAY_THE: "Căn cứ đã có bản thay thế",
    CAN_KIEM_TRA: "Cần kiểm tra trước khi dùng",
    HET_HIEU_LUC: "Căn cứ đã hết hiệu lực",
    KHONG_RO: "Chưa xác minh được hiệu lực",
}

#: Trạng thái mà người dùng KHÔNG nên điền mà không kiểm lại.
CANH_BAO = frozenset({HET_HIEU_LUC, CO_BAN_THAY_THE, CAN_KIEM_TRA, KHONG_RO})

#: Quan hệ khiến văn bản căn cứ thôi là căn cứ dùng được.
_QUAN_HE_KHAI_TU = ("Thay thế", "Bãi bỏ")
#: Quan hệ khiến văn bản căn cứ đổi một phần — biểu mẫu có thể đã đổi theo.
_QUAN_HE_SUA = ("Sửa đổi, bổ sung",)


@dataclass
class KetQuaHieuLuc:
    state: str = KHONG_RO
    as_of: date | None = None
    ghi_chu: str = ""
    thay_the_boi: list[str] = field(default_factory=list)

    @property
    def nhan(self) -> str:
        return NHAN.get(self.state, NHAN[KHONG_RO])

    @property
    def can_canh_bao(self) -> bool:
        return self.state in CANH_BAO


def _van_ban_tac_dong(session, doc_num: str) -> tuple[list[str], list[str]]:
    """Số hiệu văn bản đã thay thế/bãi bỏ, và đã sửa đổi, văn bản `doc_num`.

    Đi theo chiều NGƯỢC của đồ thị: tìm văn bản nào TRỎ TỚI doc_num với quan hệ
    thay thế. `document_references.target_doc_num` là số hiệu trần nên khớp thẳng.
    """
    rows = session.execute(text("""
        SELECT r.relation_type, d.doc_num
        FROM document_references r
        JOIN documents d ON d.id = r.source_doc_id
        WHERE r.target_doc_num = :n
    """), {"n": doc_num}).fetchall()

    khai_tu, sua = [], []
    for quan_he, so_hieu in rows:
        if not so_hieu:
            continue
        if quan_he in _QUAN_HE_KHAI_TU and so_hieu not in khai_tu:
            khai_tu.append(so_hieu)
        elif quan_he in _QUAN_HE_SUA and so_hieu not in sua:
            sua.append(so_hieu)
    return khai_tu, sua


def suy_hieu_luc(session, form_key: str, as_of: date) -> KetQuaHieuLuc:
    """Hiệu lực của một biểu mẫu, suy từ toàn bộ căn cứ của nó.

    `as_of` là BẮT BUỘC và được lưu lại: "còn hiệu lực" không phải thuộc tính vĩnh
    viễn mà là khẳng định tại một thời điểm — cùng lý do với `eff_state_as_of` của
    bảng documents.
    """
    refs = session.query(LegalFormRef).filter_by(form_key=form_key).all()
    if not refs:
        return KetQuaHieuLuc(
            KHONG_RO, as_of,
            "Nguồn không ghi căn cứ pháp lý cho biểu mẫu này.",
        )

    ket: KetQuaHieuLuc | None = None
    thay_the_tat: list[str] = []
    ly_do: list[str] = []

    for ref in refs:
        if not ref.doc_key:
            ung = KetQuaHieuLuc(
                KHONG_RO, as_of,
                f"Căn cứ {ref.doc_num} chưa có trong kho nên không kiểm được hiệu lực.",
            )
        else:
            row = session.execute(text(
                "SELECT eff_state, eff_status FROM documents WHERE doc_key = :k"
            ), {"k": ref.doc_key}).fetchone()
            trang_thai_vb = (row[0] if row else None) or eff_vb.KHONG_RO

            khai_tu, sua = _van_ban_tac_dong(session, ref.doc_num)

            if trang_thai_vb == eff_vb.HET_TOAN_BO:
                ung = KetQuaHieuLuc(
                    HET_HIEU_LUC, as_of,
                    f"Căn cứ {ref.doc_num} đã hết hiệu lực toàn bộ.",
                    list(khai_tu),
                )
            elif khai_tu:
                ung = KetQuaHieuLuc(
                    CO_BAN_THAY_THE, as_of,
                    f"Căn cứ {ref.doc_num} đã bị {', '.join(khai_tu[:3])} "
                    f"thay thế hoặc bãi bỏ — tìm biểu mẫu mới ở văn bản đó.",
                    list(khai_tu),
                )
            elif trang_thai_vb in (eff_vb.HET_MOT_PHAN, eff_vb.CHUA_HIEU_LUC) or sua:
                chi_tiet = (f"đã bị {', '.join(sua[:3])} sửa đổi, bổ sung" if sua
                            else eff_vb.label(trang_thai_vb).lower())
                ung = KetQuaHieuLuc(
                    CAN_KIEM_TRA, as_of,
                    f"Căn cứ {ref.doc_num} {chi_tiet} — đối chiếu phụ lục bản mới "
                    f"trước khi dùng.",
                )
            elif trang_thai_vb == eff_vb.CON_HIEU_LUC:
                ung = KetQuaHieuLuc(
                    CON_HIEU_LUC, as_of, f"Căn cứ {ref.doc_num} còn hiệu lực."
                )
            else:
                ung = KetQuaHieuLuc(
                    KHONG_RO, as_of,
                    f"Kho chưa xác minh được hiệu lực của căn cứ {ref.doc_num}.",
                )

        thay_the_tat.extend(x for x in ung.thay_the_boi if x not in thay_the_tat)
        ly_do.append(ung.ghi_chu)
        if ket is None or _UU_TIEN[ung.state] < _UU_TIEN[ket.state]:
            ket = ung

    assert ket is not None
    # Giữ TOÀN BỘ lý do, không chỉ lý do thắng: biểu mẫu hai căn cứ mà một cái đã
    # chết thì người đọc cần thấy cả hai để tự quyết.
    ket.ghi_chu = " ".join(dict.fromkeys(ly_do))
    ket.thay_the_boi = thay_the_tat
    return ket


def tinh_hieu_luc(session, as_of: date | None = None,
                  chi_mau_kinh_doanh: bool = False) -> dict[str, int]:
    """Tính lại hiệu lực cho mọi biểu mẫu đã cào. Trả về đếm theo trạng thái.

    PHẢI CHẠY LẠI SAU MỖI LẦN CÀO VĂN BẢN, không phải một lần rồi thôi: hiệu lực
    biểu mẫu đổi khi VĂN BẢN CĂN CỨ đổi, mà văn bản thì được cào hằng ngày. Một cờ
    tính tháng trước là một khẳng định đã lỗi thời — xem src/main.py bước 9.
    """
    moc = as_of or date.today()
    q = session.query(LegalForm).filter(LegalForm.crawl_status == "OK")
    if chi_mau_kinh_doanh:
        q = q.filter(LegalForm.is_business.is_(True))

    dem: dict[str, int] = {}
    for form in q.all():
        kq = suy_hieu_luc(session, form.form_key, moc)
        form.eff_state = kq.state
        form.eff_state_as_of = moc
        form.eff_note = kq.ghi_chu[:1000]
        form.eff_replaced_by = (
            json.dumps(kq.thay_the_boi, ensure_ascii=False) if kq.thay_the_boi else None
        )
        # Trang công khai phải đăng lại: cờ hiệu lực nằm trên trang, đổi cờ mà
        # không đăng lại là để một khẳng định sai nằm trên mạng.
        form.published_hash = None
        dem[kq.state] = dem.get(kq.state, 0) + 1

    session.commit()
    logger.info("Tính hiệu lực %d biểu mẫu (mốc %s): %s", sum(dem.values()), moc, dem)
    return dem


__all__ = [
    "CON_HIEU_LUC", "CO_BAN_THAY_THE", "CAN_KIEM_TRA", "HET_HIEU_LUC", "KHONG_RO",
    "NHAN", "CANH_BAO", "KetQuaHieuLuc", "suy_hieu_luc", "tinh_hieu_luc",
]
