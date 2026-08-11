"""Nhóm — dữ kiện pháp lý suy được: thứ bậc, địa bàn, hiệu lực.

Ba thứ này quyết định báo cáo nói đúng hay sai về mặt pháp lý:
  - xếp nhầm cấp → báo cáo dẫn một quyết định điều hành như thể là quy phạm
  - gán nhầm địa bàn → doanh nghiệp ở tỉnh A đọc quy định chỉ áp dụng ở tỉnh B
  - đoán bừa hiệu lực → khẳng định một văn bản đang áp dụng mà không có căn cứ
"""
from datetime import date

import pytest

from src.legal import effectivity
from src.legal.hierarchy import LEVEL_NON_NORMATIVE, classify
from src.legal.provinces import (
    PROVINCES,
    current_code,
    province_from_agency,
    province_name,
)


class TestThuBac:
    """Điều 4 Luật Ban hành VBQPPL 2025."""

    @pytest.mark.parametrize("doc_num,level,norm", [
        ("135/2025/QH15", 2, "luat"),
        ("91/2015/QH13", 2, "luat"),
        ("01/2018/UBTVQH14", 3, "phap_lenh"),
        ("28/2005/PL-UBTVQH11", 3, "phap_lenh"),
        ("32-LCT/HĐNN8", 3, "phap_lenh"),
        ("16/2003/L-CTN", 4, "lenh_ctn"),
        ("292/2026/NĐ-CP", 5, "nghi_dinh"),
        ("77/2026/NQ-CP", 5, "nghi_quyet_cp"),
        ("15/2026/QĐ-TTg", 6, "quyet_dinh_ttg"),
        ("44/2022/TT-BTC", 7, "thong_tu"),
        ("01/2020/TTLT-BTC-BNV", 7, "thong_tu_lien_tich"),
        ("12/2026/NQ-HĐND", 8, "nghi_quyet_hdnd"),
        ("40/2026/QĐ-UBND", 9, "quyet_dinh_ubnd"),
    ])
    def test_cap_dung_theo_hau_to(self, doc_num, level, norm):
        f = classify(doc_num)
        assert (f.hierarchy_level, f.doc_type_norm) == (level, norm)
        assert f.is_vbqppl

    def test_hien_phap_khong_co_so_hieu_van_ra_cap_1(self):
        """Hiến pháp trong kho có doc_num là "Không số" — phải lùi về doc_type."""
        f = classify("Không số", "Hiến pháp", "Quốc hội")
        assert f.hierarchy_level == 1

    def test_so_hieu_thang_agency_name_khi_mau_thuan(self):
        """Bộ Tư pháp ghi Luật Xây dựng 135/2025/QH15 do "Bộ Xây dựng" ban hành.

        Luật luôn do Quốc hội ban hành — đó là quy tắc pháp lý, không phải quy
        ước dữ liệu, nên số hiệu phải thắng.
        """
        f = classify("135/2025/QH15", "Luật", "Bộ Xây dựng")
        assert f.agency == "Quốc hội" and f.hierarchy_level == 2

    @pytest.mark.parametrize("doc_num,norm", [
        ("1968/QĐ-BTC", "quyet_dinh_ca_biet"),      # Bộ trưởng ra VBQPPL bằng thông tư
        ("43/2026/QĐ-CTUBND", "quyet_dinh_ca_biet"),  # Chủ tịch UBND, không phải UBND
        ("982/QĐ-TTPVHCC", "quyet_dinh_ca_biet"),
        ("01/2026/CT-UBND", "chi_thi"),              # chỉ thị bị loại từ Luật 2015
        ("54/VBHN-BCT", "van_ban_hop_nhat"),
        ("16-NQ/TW", "van_ban_dang"),
        ("410/TB-VPCP", "hanh_chinh"),
        ("28/CĐ-CT", "hanh_chinh"),
        ("265/KH-UBND", "hanh_chinh"),
    ])
    def test_khong_phai_vbqppl(self, doc_num, norm):
        f = classify(doc_num)
        assert f.doc_type_norm == norm
        assert not f.is_vbqppl
        assert f.hierarchy_level == LEVEL_NON_NORMATIVE

    def test_ban_du_thao_khong_phai_van_ban_da_ban_hanh(self):
        """TVPL đưa tiêu đề vào ô số hiệu với bản dự thảo."""
        f = classify("Dự thảo Luật thuế tài nguyên sửa đổi")
        assert f.doc_type_norm == "du_thao" and not f.is_vbqppl

    @pytest.mark.parametrize("doc_num", [
        "09/2026NQ-HĐND",   # thiếu dấu / trước NQ
        "12/2026/NQ_HĐND",  # gạch dưới thay gạch ngang
        "12/2026/NQ-HDND",  # mất dấu tiếng Việt
    ])
    def test_chiu_duoc_so_hieu_ban(self, doc_num):
        assert classify(doc_num).hierarchy_level == 8

    def test_thu_tu_luat_khop_mau_hep_truoc(self):
        """"/QĐ-TTg" và "/QĐ-UBND" phải khớp trước mẫu "/QĐ-" chung."""
        assert classify("15/2026/QĐ-TTg").hierarchy_level == 6
        assert classify("40/2026/QĐ-UBND").hierarchy_level == 9

    def test_cap_nho_hon_la_cao_hon(self):
        assert classify("135/2025/QH15").hierarchy_level < classify("292/2026/NĐ-CP").hierarchy_level
        assert classify("292/2026/NĐ-CP").hierarchy_level < classify("44/2022/TT-BTC").hierarchy_level
        assert classify("44/2022/TT-BTC").hierarchy_level < classify("40/2026/QĐ-UBND").hierarchy_level


class TestDiaBan:
    """Nghị quyết 202/2025/QH15 — sắp xếp đơn vị hành chính cấp tỉnh."""

    def test_dung_so_don_vi_theo_nghi_quyet(self):
        cities = [p for p in PROVINCES if p.is_city]
        merged = [p for p in PROVINCES if p.absorbed]
        assert len(PROVINCES) == 34
        assert len(cities) == 6 and len(PROVINCES) - len(cities) == 28
        assert len(merged) == 23
        assert len([p for p in merged if p.is_city]) == 4
        assert len(PROVINCES) - len(merged) == 11

    def test_tong_ten_cu_dung_63(self):
        """34 đơn vị hiện hành + 29 tên bị nhập = 63 tỉnh thành trước sắp xếp."""
        absorbed = sum(len(p.absorbed) for p in PROVINCES)
        assert absorbed == 29
        assert len(PROVINCES) + absorbed == 63

    def test_ma_tinh_khong_trung_nhau(self):
        codes = [p.code for p in PROVINCES]
        assert len(codes) == len(set(codes))

    @pytest.mark.parametrize("agency,raw,current", [
        ("UBND Thành phố Hồ Chí Minh", "ho-chi-minh", "ho-chi-minh"),
        ("HĐND Tỉnh Đồng Tháp", "dong-thap", "dong-thap"),
        ("HĐND tỉnh Bắc Kạn", "bac-kan", "thai-nguyen"),
        ("UBND tỉnh Bình Dương", "binh-duong", "ho-chi-minh"),
        ("HĐND tỉnh Thừa Thiên Huế", "hue", "hue"),
    ])
    def test_suy_tinh_tu_co_quan(self, agency, raw, current):
        assert province_from_agency(agency) == (raw, current)

    def test_bo_qua_tien_to_tinh_hay_thanh_pho(self):
        """Dữ liệu nguồn ghi "UBND Thành phố Đồng Nai" trong khi Đồng Nai là tỉnh.

        Khớp theo TÊN chứ không tin vào chữ "Tỉnh"/"Thành phố".
        """
        assert province_from_agency("UBND Thành phố Đồng Nai")[1] == "dong-nai"

    @pytest.mark.parametrize("agency", ["Bộ Tài chính", "Chính phủ", "Quốc hội", "", None])
    def test_co_quan_trung_uong_khong_co_dia_ban(self, agency):
        assert province_from_agency(agency) == (None, None)

    def test_khong_doan_khi_ten_la(self):
        """Gán nhầm địa bàn tệ hơn là để trống."""
        assert province_from_agency("UBND tỉnh Không Có Thật") == (None, None)

    def test_ten_cu_van_tra_ra_ten_cu(self):
        """Văn bản do Bình Dương ban hành phải hiển thị đúng "Bình Dương",

        nhưng tra cứu theo địa bàn hiện nay vẫn phải tìm thấy nó ở TP.HCM.
        """
        assert province_name("binh-duong") == "Bình Dương"
        assert current_code("binh-duong") == "ho-chi-minh"


class TestTuDienKhiGhi:
    """Dữ kiện phải được tính ở mọi đường ghi, không chỉ trong script backfill.

    Chỉ backfill một lần thì mọi văn bản cào về sau đó có các cột này rỗng và
    lặng lẽ rơi khỏi mọi bộ lọc theo cấp, địa bàn hay hiệu lực.
    """

    def test_van_ban_moi_tu_co_du_kien(self, master_session):
        from src.storage.database import upsert_document

        doc, is_new = upsert_document(master_session, {
            "doc_num": "40/2026/QĐ-UBND", "title": "Quyết định thử",
            "agency_name": "UBND Tỉnh Cà Mau", "doc_type": "Quyết định",
            "eff_status": "Còn hiệu lực",
        })
        assert is_new
        assert doc.hierarchy_level == 9
        assert doc.territorial_scope == "tinh"
        assert doc.province_code_current == "ca-mau"
        assert doc.eff_state == effectivity.CON_HIEU_LUC
        assert doc.eff_state_as_of is not None
        assert doc.public_slug and doc.public_slug.startswith("40-2026-qdd-ubnd--")
        assert doc.is_closure_node is False

    def test_doi_trang_thai_thi_co_hieu_luc_doi_theo(self, master_session):
        """eff_status nằm trong REFRESHABLE_FIELDS nên đổi được ở lần cào sau.

        Không tính lại eff_state thì hai cột nói ngược nhau.
        """
        from src.storage.database import upsert_document

        base = {"doc_num": "292/2026/NĐ-CP", "title": "Nghị định thử",
                "agency_name": "Chính phủ", "moj_id": "999"}
        upsert_document(master_session, {**base, "eff_status": "Còn hiệu lực"})
        master_session.flush()
        doc, is_new = upsert_document(
            master_session, {**base, "eff_status": "Hết hiệu lực toàn bộ"}
        )
        assert not is_new
        assert doc.eff_state == effectivity.HET_TOAN_BO

    def test_co_quan_lo_dien_sau_thi_dia_ban_duoc_dien(self, master_session):
        """Bản ghi từ TVPL chưa có cơ quan; MOJ về sau mới cho biết."""
        from src.storage.database import upsert_document

        upsert_document(master_session, {
            "doc_num": "07/2026/QĐ-UBND", "title": "X", "tvpl_id": "111",
        })
        master_session.flush()
        doc, _ = upsert_document(master_session, {
            "doc_num": "07/2026/QĐ-UBND", "title": "X", "tvpl_id": "111",
            "agency_name": "UBND Tỉnh Lai Châu",
        })
        assert doc.province_code_current == "lai-chau"


class TestHieuLuc:
    AS_OF = date(2026, 8, 7)

    def _r(self, status=None, eff_from=None, eff_to=None):
        return effectivity.resolve(status, eff_from, eff_to, self.AS_OF)

    @pytest.mark.parametrize("status,expected", [
        ("Còn hiệu lực", effectivity.CON_HIEU_LUC),
        ("Hết hiệu lực toàn bộ", effectivity.HET_TOAN_BO),
        ("Hết hiệu lực một phần", effectivity.HET_MOT_PHAN),
        ("Chưa có hiệu lực", effectivity.CHUA_HIEU_LUC),
        ("Chưa xác định", effectivity.KHONG_RO),
    ])
    def test_doc_dung_6_gia_tri_cua_nguon(self, status, expected):
        assert self._r(status).state == expected

    @pytest.mark.parametrize("empty", [None, "", "   "])
    def test_khong_co_trang_thai_va_khong_co_ngay_thi_khong_ro(self, empty):
        """Mặc định "còn hiệu lực" chính là bịa dữ kiện pháp lý.

        Đúng lỗi từng khiến 25% kho được khẳng định là luật hiện hành mà không
        có căn cứ nào.
        """
        assert self._r(empty).state == effectivity.KHONG_RO

    def test_chi_co_eff_from_qua_khu_van_khong_ket_luan_con_hieu_luc(self):
        """Văn bản có thể đã bị bãi bỏ mà nguồn chưa cập nhật eff_to."""
        assert self._r(None, eff_from=date(2020, 1, 1)).state == effectivity.KHONG_RO

    def test_eff_to_da_qua_thi_het_hieu_luc(self):
        assert self._r(None, eff_to=date(2025, 1, 1)).state == effectivity.HET_TOAN_BO

    def test_eff_from_tuong_lai_thi_chua_co_hieu_luc(self):
        assert self._r(None, eff_from=date(2027, 1, 1)).state == effectivity.CHUA_HIEU_LUC

    def test_ngay_thang_thang_trang_thai_da_cu(self):
        """Bảng trạng thái cập nhật thủ công nên hay trễ hơn mốc ngày."""
        r = self._r("Còn hiệu lực", eff_to=date(2025, 1, 1))
        assert r.state == effectivity.HET_TOAN_BO and r.source == "ngay_thang"

    def test_luon_kem_moc_tinh(self):
        """Cờ hiệu lực không có mốc là khẳng định sai kể từ hôm sau."""
        assert self._r("Còn hiệu lực").as_of == self.AS_OF

    def test_chi_het_toan_bo_moi_bi_loai(self):
        """Hết hiệu lực MỘT PHẦN vẫn là luật hiện hành ở phần chưa bị sửa."""
        assert effectivity.HET_TOAN_BO in effectivity.DEAD_STATES
        assert effectivity.HET_MOT_PHAN not in effectivity.DEAD_STATES
        assert effectivity.HET_MOT_PHAN in effectivity.WARN_STATES

    def test_nhan_hien_thi_khong_ro_noi_ro_la_chua_xac_minh(self):
        assert "Chưa xác minh" in effectivity.label(effectivity.KHONG_RO)
