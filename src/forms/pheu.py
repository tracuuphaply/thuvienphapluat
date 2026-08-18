"""
Chạy phễu ba tầng trên các biểu mẫu đã cào và ghi kết luận xuống DB.

THỨ TỰ CÓ LÝ DO. Phễu chạy TRƯỚC bước dựng file, không phải sau: dựng DOCX + PDF
cho cả 17.385 mẫu rồi mới biết 13.000 mẫu trong đó là báo cáo nội bộ của cơ quan
nhà nước thì đã đốt phần lớn công vô ích.

Tầng 3 chỉ chạy trên phần tầng 1+2 không kết luận được, và chỉ chạy MỘT LẦN cho
mỗi nội dung: `luu_bieu_mau()` xoá nhãn cũ khi `body_hash` đổi, nên mẫu đã phân
loại rồi sẽ bị bỏ qua ở lần chạy sau. Đó là toàn bộ cơ chế cache — không có bảng
riêng nào cả.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from src.forms import classifier
from src.forms.relevance import KetQuaQuyTac, la_linh_vuc_kinh_doanh, quyet_dinh_quy_tac
from src.legal.form_taxonomy import (
    CO_QUAN_NHA_NUOC,
    DOANH_NGHIEP,
    chuan_hoa_nghiep_vu,
    ten_linh_vuc_bieu_mau,
)
from src.sources.tvpl_forms_parse import (
    SOURCE_HOP_DONG,
    FormParseError,
    chu_trong_ruot,
    tach_chi_tiet,
)
from src.storage.models import LegalForm, LegalFormRef

logger = logging.getLogger(__name__)

NGUON_QUY_TAC = "quy_tac"
NGUON_LLM = "llm"

LY_DO_NGOAI_LINH_VUC = "ngoai_linh_vuc_kinh_doanh"
LY_DO_KHONG_PHAI_DN = "nguoi_dien_khong_phai_doanh_nghiep"
LY_DO_CHUA_CO_RUOT = "chua_co_ruot_mau"


@dataclass
class ThongKePheu:
    tang1_loai: int = 0
    tang2_giu: int = 0
    tang2_loai: int = 0
    tang3_goi: int = 0
    tang3_giu: int = 0
    tang3_loai: int = 0
    bo_qua_da_phan_loai: int = 0
    khong_doc_duoc_ruot: int = 0
    loi_mo_hinh: int = 0

    @property
    def giu(self) -> int:
        return self.tang2_giu + self.tang3_giu

    @property
    def loai(self) -> int:
        return self.tang1_loai + self.tang2_loai + self.tang3_loai

    def tom_tat(self) -> str:
        return (
            f"giữ {self.giu} / loại {self.loai}  "
            f"(tầng 1 loại {self.tang1_loai}; "
            f"tầng 2 giữ {self.tang2_giu}, loại {self.tang2_loai}; "
            f"tầng 3 gọi {self.tang3_goi} → giữ {self.tang3_giu}, "
            f"loại {self.tang3_loai})  "
            f"bỏ qua {self.bo_qua_da_phan_loai} đã phân loại, "
            f"{self.khong_doc_duoc_ruot} không đọc được ruột, "
            f"{self.loi_mo_hinh} lỗi mô hình"
        )


def doc_ruot_mau(form: LegalForm) -> str:
    """Chữ trong ruột biểu mẫu, đọc lại từ trang HTML đã lưu.

    Đọc lại thay vì lưu thêm một bản chữ riêng: bản HTML đầy đủ là thứ duy nhất
    cho phép sửa bộ bóc rồi chạy lại mà không cào lại TVPL, còn một bản chữ song
    song chỉ là chỗ thứ hai để hai bên lệch nhau.
    """
    if not form.body_html_path:
        return ""
    p = Path(form.body_html_path)
    if not p.exists():
        return ""
    try:
        chi_tiet = tach_chi_tiet(
            p.read_text(encoding="utf-8"), form.source, form.external_id
        )
    except FormParseError:
        return ""
    return chu_trong_ruot(chi_tiet.body_html)


def _ghi_ket_luan(form: LegalForm, audience: str, nguon: str, tin_cay: float,
                  ly_do: str, nghiep_vu: list[str]) -> None:
    form.audience = audience
    form.audience_source = nguon
    form.audience_confidence = tin_cay
    form.audience_reason = ly_do[:500]
    form.nghiep_vu = json.dumps(chuan_hoa_nghiep_vu(nghiep_vu), ensure_ascii=False)
    form.is_business = audience == DOANH_NGHIEP
    form.excluded_reason = None if form.is_business else LY_DO_KHONG_PHAI_DN


def _nghiep_vu_mac_dinh(form: LegalForm) -> list[str]:
    """Nhóm nghiệp vụ suy từ nguồn khi tầng 2 kết luận mà không hỏi mô hình.

    Mẫu hợp đồng thì nghiệp vụ là "hop_dong" — chắc chắn, không cần đoán. Biểu
    mẫu thì để "khac" và chờ tầng 3 hoặc người duyệt gắn nhãn: đoán nghiệp vụ từ
    lĩnh vực là suy đoán chồng suy đoán (ánh xạ 47→27 đã là suy đoán rồi).
    """
    return ["hop_dong"] if form.source == SOURCE_HOP_DONG else []


def _can_cu_cua(session, form_key: str) -> list[str]:
    return [
        r.doc_num
        for r in session.query(LegalFormRef).filter_by(form_key=form_key).limit(4)
    ]


def chay_pheu(session, gioi_han: int | None = None, chay_lai: bool = False,
              dung_mo_hinh: bool = True,
              goi_mo_hinh=classifier.call_report_llm) -> ThongKePheu:
    """Phân loại các biểu mẫu chưa có nhãn. Trả về thống kê từng tầng.

    `dung_mo_hinh=False` chạy được hai tầng đầu khi chưa có khoá API — hữu ích
    để hiệu chuẩn quy tắc mà không tốn tiền, và để hệ thống vẫn nhúc nhích khi
    nhà cung cấp mô hình chết (đã xảy ra một lần, xem README).
    """
    tk = ThongKePheu()
    q = session.query(LegalForm).filter(LegalForm.crawl_status == "OK")
    if not chay_lai:
        q = q.filter(LegalForm.audience.is_(None))
    if gioi_han:
        q = q.limit(gioi_han)

    for form in q.all():
        if form.audience and not chay_lai:
            tk.bo_qua_da_phan_loai += 1
            continue

        # Tầng 1 — chỉ áp cho /bieumau. Mẫu hợp đồng không có lĩnh vực và gần
        # như toàn bộ phục vụ giao dịch kinh doanh, nên vào thẳng tầng 2.
        if form.source != SOURCE_HOP_DONG and not la_linh_vuc_kinh_doanh(form.field_code):
            form.audience = None
            form.is_business = False
            form.excluded_reason = f"{LY_DO_NGOAI_LINH_VUC}:{form.field_code}"
            tk.tang1_loai += 1
            continue

        ruot = doc_ruot_mau(form)
        if not ruot:
            tk.khong_doc_duoc_ruot += 1
            form.is_business = None
            form.excluded_reason = LY_DO_CHUA_CO_RUOT
            continue

        # Tầng 2
        qt: KetQuaQuyTac = quyet_dinh_quy_tac(form.title or "", ruot)
        if qt.chac_chan:
            _ghi_ket_luan(form, qt.audience, NGUON_QUY_TAC, 1.0, qt.ly_do(),
                          _nghiep_vu_mac_dinh(form))
            if qt.audience == DOANH_NGHIEP:
                tk.tang2_giu += 1
            else:
                tk.tang2_loai += 1
            continue

        if not dung_mo_hinh:
            continue

        # Tầng 3
        try:
            kq = classifier.phan_loai(
                form.title or "",
                ruot,
                can_cu=_can_cu_cua(session, form.form_key),
                linh_vuc=ten_linh_vuc_bieu_mau(form.field_code) if form.field_code else "",
                goi_mo_hinh=goi_mo_hinh,
            )
        except Exception as e:
            # Không gán nhãn khi mô hình hỏng: một mẫu chưa phân loại sẽ được
            # thử lại lần sau, còn một nhãn bịa thì nằm lại vĩnh viễn.
            tk.loi_mo_hinh += 1
            logger.warning("%s: phân loại hỏng — %s", form.form_key, e)
            continue

        tk.tang3_goi += 1
        _ghi_ket_luan(form, kq.audience, NGUON_LLM, kq.confidence, kq.ly_do,
                      kq.nghiep_vu or _nghiep_vu_mac_dinh(form))
        if kq.audience == DOANH_NGHIEP:
            tk.tang3_giu += 1
        else:
            tk.tang3_loai += 1

    session.commit()
    return tk


__all__ = [
    "ThongKePheu", "NGUON_QUY_TAC", "NGUON_LLM",
    "LY_DO_NGOAI_LINH_VUC", "LY_DO_KHONG_PHAI_DN", "LY_DO_CHUA_CO_RUOT",
    "CO_QUAN_NHA_NUOC", "doc_ruot_mau", "chay_pheu",
]
