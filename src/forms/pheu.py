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
    CA_NHAN,
    CO_QUAN_NHA_NUOC,
    DOANH_NGHIEP,
    chuan_hoa_nghiep_vu,
    ten_linh_vuc_bieu_mau,
)
from src.sources.tvpl_forms_parse import (
    SOURCE_BIEU_MAU,
    SOURCE_HOP_DONG,
    FormParseError,
    chu_trong_ruot,
    tach_chi_tiet,
)
from src.storage.models import LegalForm, LegalFormRef

logger = logging.getLogger(__name__)

NGUON_QUY_TAC = "quy_tac"
NGUON_LLM = "llm"
NGUON_MAC_DINH = "mac_dinh_nguon"

#: Khi HAI TẦNG QUY TẮC KHÔNG DÁM KẾT LUẬN thì mặc định theo KHO, không phải một
#: mặc định chung.
#:
#: LỖI ĐÃ MẮC: bản đầu để mọi mẫu không kết luận được rơi vào hư vô, chờ tầng 3.
#: Người dùng tắt tầng 3 (không có quota mô hình) nên 548/662 mẫu hợp đồng biến
#: mất vĩnh viễn — cào đủ 662 mà trang công khai chỉ có 105.
#:
#: Mặc định phải NGƯỢC NHAU giữa hai kho, vì bản chất hai kho ngược nhau:
#:   /hopdong  662 mẫu, gần như toàn bộ là giao dịch dân sự - thương mại. Quy tắc
#:             ở đây dùng để LOẠI trường hợp rõ ràng của nhà nước (hợp đồng làm
#:             việc với viên chức, nhà ở công vụ Bộ Quốc phòng). Không loại được
#:             thì GIỮ.
#:   /bieumau  33.820 mẫu, phần lớn là báo cáo nội bộ của cơ quan nhà nước. Ở đây
#:             phải có BẰNG CHỨNG mới giữ, nếu không kho ngập mẫu Kho bạc.
MAC_DINH_THEO_KHO = {
    SOURCE_HOP_DONG: DOANH_NGHIEP,
    SOURCE_BIEU_MAU: None,
}

#: Bao nhiêu điểm dấu hiệu nhà nước thì ĐỦ để chặn "mặc định theo kho".
#:
#: HAI, không phải một. Đo trên 662 mẫu hợp đồng: 47 mẫu có ĐÚNG MỘT lần nhắc —
#: gần như luôn là dòng chứng thực ("Chứng thực tại Uỷ ban nhân dân xã…") hoặc
#: một chữ "ngân sách nhà nước" trong điều khoản thanh toán, chứ không phải cơ
#: quan là một BÊN KÝ. Chặn ở mức một là loại nhầm cả "Hợp đồng huỷ bỏ hợp đồng
#: uỷ quyền" — hợp đồng dân sự thuần.
#:
#: Ở mức hai thì 10 mẫu bị chặn, và cả 10 đều đúng là việc của nhà nước: hợp
#: đồng chi trả trợ cấp qua Kho bạc, hợp đồng dịch vụ sự nghiệp dùng ngân sách,
#: hợp đồng của nhà trường. Vài ca ở biên (hỗ trợ doanh nghiệp nhỏ và vừa bằng
#: ngân sách) là đúng loại việc mà tầng 3 sinh ra để đọc.
NGUONG_BANG_CHUNG_NHA_NUOC = 2

LY_DO_NGOAI_LINH_VUC = "ngoai_linh_vuc_kinh_doanh"
LY_DO_KHONG_PHAI_DN = "nguoi_dien_khong_phai_doanh_nghiep"
LY_DO_CHUA_CO_RUOT = "chua_co_ruot_mau"


@dataclass
class ThongKePheu:
    tang1_loai: int = 0
    tang2_giu: int = 0
    tang2_ca_nhan: int = 0
    tang2_loai: int = 0
    tang3_goi: int = 0
    tang3_giu: int = 0
    tang3_loai: int = 0
    mac_dinh_giu: int = 0
    bo_qua_da_phan_loai: int = 0
    khong_doc_duoc_ruot: int = 0
    loi_mo_hinh: int = 0

    @property
    def giu(self) -> int:
        return self.tang2_giu + self.tang3_giu + self.mac_dinh_giu

    @property
    def loai(self) -> int:
        return self.tang1_loai + self.tang2_loai + self.tang3_loai

    def tom_tat(self) -> str:
        return (
            f"giữ {self.giu} / loại {self.loai}  "
            f"(tầng 1 loại {self.tang1_loai}; "
            f"tầng 2 giữ {self.tang2_giu}, loại {self.tang2_loai}; "
            f"tầng 3 gọi {self.tang3_goi} → giữ {self.tang3_giu}, "
            f"loại {self.tang3_loai}; "
            f"mặc định theo kho giữ {self.mac_dinh_giu})  "
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
                  ly_do: str, nghiep_vu: list[str],
                  cho_doanh_nghiep: bool | None = None,
                  cho_ca_nhan: bool | None = None,
                  nghiep_vu_ca_nhan: list[str] | None = None) -> None:
    """Ghi kết luận. Hai cờ đối tượng ĐỘC LẬP, cùng bật được.

    `cho_doanh_nghiep` / `cho_ca_nhan` để None thì suy từ `audience` — giữ đúng
    hành vi cũ cho mọi đường gọi chưa biết đến cá nhân (tầng 3, mặc định theo
    kho). Chỉ tầng 2 mới truyền hai cờ thật, vì chỉ nó chấm đủ ba bộ dấu hiệu.
    """
    if cho_doanh_nghiep is None:
        cho_doanh_nghiep = audience == DOANH_NGHIEP
    if cho_ca_nhan is None:
        cho_ca_nhan = audience == CA_NHAN

    form.audience = audience
    form.audience_source = nguon
    form.audience_confidence = tin_cay
    form.audience_reason = ly_do[:500]
    form.nghiep_vu = json.dumps(chuan_hoa_nghiep_vu(nghiep_vu), ensure_ascii=False)
    form.is_business = cho_doanh_nghiep
    form.is_individual = cho_ca_nhan
    if cho_ca_nhan:
        form.nghiep_vu_ca_nhan = json.dumps(
            chuan_hoa_nghiep_vu(nghiep_vu_ca_nhan, ca_nhan=True), ensure_ascii=False)
    # `excluded_reason` chỉ có nghĩa khi mẫu KHÔNG phục vụ ai trong hai bên —
    # trước đây nó ghi "không phải doanh nghiệp" cho cả mẫu cá nhân, mà mẫu cá
    # nhân thì không bị loại, nó chỉ phục vụ bên khác.
    form.excluded_reason = (None if (cho_doanh_nghiep or cho_ca_nhan)
                            else LY_DO_KHONG_PHAI_DN)


def _nghiep_vu_mac_dinh(form: LegalForm) -> list[str]:
    """Nhóm nghiệp vụ suy từ nguồn khi tầng 2 kết luận mà không hỏi mô hình.

    Mẫu hợp đồng thì nghiệp vụ là "hop_dong" — chắc chắn, không cần đoán. Biểu
    mẫu thì để "khac" và chờ tầng 3 hoặc người duyệt gắn nhãn: đoán nghiệp vụ từ
    lĩnh vực là suy đoán chồng suy đoán (ánh xạ 47→27 đã là suy đoán rồi).
    """
    return ["hop_dong"] if form.source == SOURCE_HOP_DONG else []


#: Lĩnh vực /bieumau → nhóm sự kiện đời người, CHỈ những ánh xạ một-một rõ ràng.
#: Lĩnh vực nào phục vụ nhiều nhóm sự kiện thì KHÔNG có mặt ở đây — để "khác" và
#: chờ tầng 3 hoặc người duyệt, đúng lý do _nghiep_vu_mac_dinh() không đoán nhóm
#: nghiệp vụ từ lĩnh vực: đoán chồng suy đoán thì sai mà không ai biết.
#: Ví dụ lĩnh vực 35 "Thuế – Phí – Lệ phí" chứa cả thuế TNCN lẫn lệ phí trước bạ
#: nhà đất — hai nhóm sự kiện khác nhau, không chọn hộ được.
_LINH_VUC_SANG_SU_KIEN: dict[int, str] = {
    39: "ho_tich",
    20: "hon_nhan_gia_dinh",
    13: "nha_dat_ca_nhan",
    2:  "bhxh_bhyt_huu_tri",
    22: "khieu_nai_to_tung",
    42: "vi_pham_hanh_chinh",
    18: "giao_duc_hoc_tap",
    47: "y_te_kham_benh",
    8:  "chinh_sach_xa_hoi",
    45: "xuat_nhap_canh",
}


def _nghiep_vu_ca_nhan_mac_dinh(form: LegalForm) -> list[str]:
    """Nhóm sự kiện đời người suy từ lĩnh vực, chỉ khi ánh xạ là một-một."""
    ma = _LINH_VUC_SANG_SU_KIEN.get(form.field_code)
    return [ma] if ma else []


def _xoa_ket_luan(form: LegalForm, ly_do: str | None = None) -> None:
    """Trả biểu mẫu về trạng thái CHƯA PHÂN LOẠI.

    Hai cờ về `None`, KHÔNG phải `False`. Đây là hai trạng thái khác nhau và sự
    khác nhau đó có việc để làm:
        None   chưa ai quyết — tầng 3 chạy sau sẽ quyết, chạy lại thì thử lại
        False  đã quyết là không phục vụ bên đó — không cần hỏi mô hình nữa
    Gộp chúng làm một là biến "chưa hỏi" thành "đã trả lời không", và mẫu đó vĩnh
    viễn không được tầng 3 đọc. Test `test_bieu_mau_khong_ket_luan_duoc_thi_
    KHONG_giu` chốt đúng chỗ này.
    """
    form.audience = None
    form.audience_source = None
    form.audience_confidence = None
    form.audience_reason = None
    form.is_business = None
    form.is_individual = None
    form.nghiep_vu_ca_nhan = None
    form.excluded_reason = ly_do


def _duoc_mac_dinh_theo_kho(form: LegalForm, qt: KetQuaQuyTac) -> bool:
    """Mặc định theo kho có được áp cho mẫu này không.

    ĐIỀU KIỆN XÉT `diem_loai`, không xét "đã kết luận là nhà nước chưa". "Mặc
    định theo kho" nghĩa là *không có bằng chứng ngược lại*, mà hai cái tên cơ
    quan trong ruột mẫu thì đúng là bằng chứng — kể cả khi chưa đủ mạnh để tự nó
    kết luận (ngưỡng kết luận là 3). Xem NGUONG_BANG_CHUNG_NHA_NUOC vì sao là 2.

    LỖI ĐÃ ĐO: "HỢP ĐỒNG TRÁCH NHIỆM CHI TRẢ TRỢ CẤP ƯU ĐÃI NGƯỜI CÓ CÔNG" có
    "kho bạc nhà nước" và "uỷ ban nhân dân" trong ruột — hai điểm, dưới ngưỡng
    kết luận 3 — nên nó rơi xuống nhánh mặc định và được nhận thành mẫu doanh
    nghiệp. Chú thích ở nhánh đó vốn đã ghi "trừ khi có dấu hiệu rõ ràng của cơ
    quan nhà nước", nhưng mã chưa bao giờ kiểm điều kiện ấy.

    MỘT hàm cho cả hai nhánh gọi (tầng 2 kết luận, và tầng 3 tắt) — trước đây
    quy tắc nằm ở hai chỗ và một chỗ quên.
    """
    return (qt.diem_loai < NGUONG_BANG_CHUNG_NHA_NUOC
            and MAC_DINH_THEO_KHO.get(form.source) is not None)


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
            form.is_individual = False
            form.excluded_reason = f"{LY_DO_NGOAI_LINH_VUC}:{form.field_code}"
            tk.tang1_loai += 1
            continue

        ruot = doc_ruot_mau(form)
        if not ruot:
            tk.khong_doc_duoc_ruot += 1
            form.is_business = None
            form.is_individual = None
            form.excluded_reason = LY_DO_CHUA_CO_RUOT
            continue

        # Tầng 2
        qt: KetQuaQuyTac = quyet_dinh_quy_tac(form.title or "", ruot)
        if qt.chac_chan:
            # MẶC ĐỊNH THEO KHO LÀ SÀN, KHÔNG PHẢI ĐƯỜNG LÙI CUỐI CÙNG.
            #
            # LỖI ĐÃ ĐO khi thêm bộ dấu hiệu cá nhân: 85/662 mẫu hợp đồng MẤT cờ
            # doanh nghiệp. Lý do — trước đây chúng rơi xuống nhánh "mặc định
            # theo kho" (hợp đồng → doanh nghiệp) vì tầng 2 không kết luận được.
            # Thêm tín hiệu cá nhân làm tầng 2 kết luận được, thế là chúng đi
            # nhánh khác và nhánh đó chỉ bật cờ nào có ĐỦ ĐIỂM. "Hợp đồng mua bán
            # nhà ở" có điểm cá nhân mà không đủ điểm doanh nghiệp → mất cờ cũ.
            #
            # Nhưng mặc định theo kho không có nghĩa "khi bí thì đoán": nó có
            # nghĩa "kho /hopdong toàn giao dịch, không chứng minh được NGƯỢC LẠI
            # thì giữ". Bằng chứng ngược lại duy nhất là dấu hiệu NHÀ NƯỚC — chứ
            # tìm thấy thêm dấu hiệu cá nhân thì không phủ định gì cả.
            # Sàn chỉ áp khi KHÔNG CÓ CHÚT bằng chứng nhà nước nào — `diem_loai
            # == 0`, không phải "chưa đủ điểm kết luận là nhà nước".
            # Đo được: "HỢP ĐỒNG TRÁCH NHIỆM CHI TRẢ TRỢ CẤP ƯU ĐÃI NGƯỜI CÓ
            # CÔNG" có "kho bạc nhà nước" và "uỷ ban nhân dân" trong ruột — hai
            # điểm, dưới ngưỡng kết luận 3 — nên `audience` là None, và nếu sàn
            # chỉ né mỗi kết luận CO_QUAN_NHA_NUOC thì nó nhận luôn mẫu này thành
            # mẫu doanh nghiệp. Mặc định theo kho nghĩa là "không có bằng chứng
            # ngược lại", mà hai tên cơ quan trong ruột thì đúng là bằng chứng.
            cho_dn = qt.cho_doanh_nghiep
            if not cho_dn and _duoc_mac_dinh_theo_kho(form, qt):
                cho_dn = MAC_DINH_THEO_KHO[form.source] == DOANH_NGHIEP

            _ghi_ket_luan(form, qt.audience, NGUON_QUY_TAC, 1.0, qt.ly_do(),
                          _nghiep_vu_mac_dinh(form),
                          cho_doanh_nghiep=cho_dn,
                          cho_ca_nhan=qt.cho_ca_nhan,
                          nghiep_vu_ca_nhan=_nghiep_vu_ca_nhan_mac_dinh(form))
            if cho_dn:
                tk.tang2_giu += 1
            if qt.cho_ca_nhan:
                tk.tang2_ca_nhan += 1
            if not (cho_dn or qt.cho_ca_nhan):
                tk.tang2_loai += 1
            continue

        if not dung_mo_hinh:
            mac_dinh = (MAC_DINH_THEO_KHO.get(form.source)
                        if _duoc_mac_dinh_theo_kho(form, qt) else None)
            if not mac_dinh:
                # XOÁ KẾT LUẬN CŨ khi lần này không kết luận được — về `None`,
                # tức "chưa phân loại", chứ không phải "đã loại".
                # LỖI ĐÃ ĐO: nhánh này vốn `continue` thẳng, nên chạy lại phễu
                # KHÔNG BAO GIỜ gỡ được cờ đã gắn sai — mẫu giữ nguyên nhãn của
                # lần chạy trước và mọi lần chạy lại sau đó đều vô hiệu. Sửa quy
                # tắc rồi chạy lại mà kho không đổi là loại lỗi im lặng tệ nhất:
                # nó làm người sửa tin rằng quy tắc mới không có tác dụng.
                _xoa_ket_luan(form, LY_DO_KHONG_PHAI_DN)
            if mac_dinh:
                # Ghi rõ nguồn là "mặc định theo kho", KHÔNG phải "quy tắc" —
                # đây là giả định về bản chất kho, không phải bằng chứng về mẫu.
                _ghi_ket_luan(
                    form, mac_dinh, NGUON_MAC_DINH, 0.0,
                    "Hai tầng quy tắc không kết luận. Mặc định theo kho: mẫu hợp "
                    "đồng là văn bản giao dịch nên coi là phục vụ kinh doanh, trừ "
                    "khi có dấu hiệu rõ ràng của cơ quan nhà nước.",
                    _nghiep_vu_mac_dinh(form))
                tk.mac_dinh_giu += 1
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
    "ThongKePheu", "NGUON_QUY_TAC", "NGUON_LLM", "NGUON_MAC_DINH",
    "MAC_DINH_THEO_KHO",
    "LY_DO_NGOAI_LINH_VUC", "LY_DO_KHONG_PHAI_DN", "LY_DO_CHUA_CO_RUOT",
    "CO_QUAN_NHA_NUOC", "doc_ruot_mau", "chay_pheu",
]
