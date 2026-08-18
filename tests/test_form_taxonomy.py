"""Danh mục phân loại của hai kho biểu mẫu TVPL.

Bẫy lớn nhất ở đây là HAI BỘ MÃ LĨNH VỰC TRÙNG TÊN NHƯNG KHÁC SỐ. Trang biểu mẫu
dùng danh mục 47 nhóm, trang tìm văn bản dùng danh mục 27 nhóm; "Doanh nghiệp" là
mã 11 ở bên này và mã 1 ở bên kia. Lấy nhầm bộ mã sẽ không nổ ở đâu cả — chỉ là
biểu mẫu doanh nghiệp lặng lẽ bị xếp vào lĩnh vực An toàn thực phẩm. Các test dưới
đây khoá đúng chỗ đó lại.
"""
import pytest

from src.legal.form_taxonomy import (
    BIEU_MAU_FIELDS,
    BIEU_MAU_TYPES,
    HOP_DONG_CATEGORIES,
    HOP_DONG_CRAWL_CODES,
    HOP_DONG_ROOT_CODES,
    MA_NGHIEP_VU_KHAC,
    NGHIEP_VU,
    TONG_MAU_HOP_DONG,
    chuan_hoa_nghiep_vu,
    sang_ma_van_ban,
    ten_linh_vuc_bieu_mau,
    ten_nhom_hop_dong,
)
from src.legal.tvpl_fields import TEN_THEO_MA


class TestLinhVucBieuMau:
    def test_du_47_linh_vuc_ma_lien_mach(self):
        assert len(BIEU_MAU_FIELDS) == 47
        assert sorted(lv["ma"] for lv in BIEU_MAU_FIELDS) == list(range(1, 48))

    def test_khong_trung_ten(self):
        ten = [lv["ten"] for lv in BIEU_MAU_FIELDS]
        assert len(set(ten)) == len(ten)

    @pytest.mark.parametrize("ma", [None, 0, 48, 99, -1])
    def test_ma_la_roi_ve_linh_vuc_khac(self, ma):
        assert ten_linh_vuc_bieu_mau(ma) == "Lĩnh vực khác"


class TestLoaiMau:
    def test_thieu_ma_12_la_co_y(self):
        """Cây lọc TVPL nhảy từ 11 sang 13 — mã 12 là nhóm đã bỏ.

        "Sửa" thành dãy liên tục sẽ làm URL ?type=12 trả về rỗng và ?type=13
        (Mẫu công văn, 760 mẫu) không bao giờ được cào.
        """
        assert 12 not in BIEU_MAU_TYPES
        assert BIEU_MAU_TYPES[13] == "Mẫu công văn"
        assert len(BIEU_MAU_TYPES) == 12


class TestNhomHopDong:
    def test_phai_cao_ca_22_nhom_khong_phai_10_nhom_goc(self):
        """LỖI ĐÃ MẮC THẬT, VÀ PHÉP CỘNG LÀM NÓ TRÔNG ĐÚNG.

        Số trên cây lọc là CỘNG DỒN cả nhóm con, nhưng `?type=` chỉ trả mẫu của
        RIÊNG nhóm. Đo trực tiếp ngày 18/08/2026:

            cây ghi "Đất đai, nhà ở (108)"  →  ?type=1  trả về 26
            cây ghi "Tài sản khác (81)"     →  ?type=19 trả về 26
            cây ghi "Mua bán nhà đất (22)"  →  ?type=12 trả về 22  (nhóm lá)

        Cộng số CÂY của 10 nhóm gốc ra đúng 662 — nên bản đầu chỉ cào nhóm gốc và
        tin là đã phủ trọn, trong khi thực tế thiếu 137 mẫu (82 nhà đất + 55 tài
        sản). Chỉ tổng `so_mau_rieng` của cả 22 nhóm mới là con số dùng được.
        """
        assert sum(n["so_mau_rieng"] for n in HOP_DONG_CATEGORIES) == TONG_MAU_HOP_DONG
        assert len(HOP_DONG_CRAWL_CODES) == 22
        assert set(HOP_DONG_CRAWL_CODES) == {n["ma"] for n in HOP_DONG_CATEGORIES}

        goc = [n for n in HOP_DONG_CATEGORIES if n["cha"] is None]
        thieu = TONG_MAU_HOP_DONG - sum(n["so_mau_rieng"] for n in goc)
        assert thieu == 137, "cào theo nhóm gốc bỏ sót đúng 137 mẫu"

    def test_so_mau_cay_cua_nhom_cha_gom_ca_nhom_con(self):
        for cha in (1, 19):
            muc_cha = next(n for n in HOP_DONG_CATEGORIES if n["ma"] == cha)
            con = [n for n in HOP_DONG_CATEGORIES if n["cha"] == cha]
            assert muc_cha["so_mau_cay"] == muc_cha["so_mau_rieng"] + sum(
                n["so_mau_rieng"] for n in con
            )

    def test_nhom_con_dung_truoc_nhom_cha_trong_thu_tu_cao(self):
        """Để mẫu nhận nhãn cụ thể nhất nếu TVPL đổi cách gộp."""
        thu_tu = list(HOP_DONG_CRAWL_CODES)
        for n in HOP_DONG_CATEGORIES:
            if n["cha"] is not None:
                assert thu_tu.index(n["ma"]) < thu_tu.index(n["cha"])

    def test_nhom_goc_chi_dung_cho_muc_luc(self):
        goc = {n["ma"] for n in HOP_DONG_CATEGORIES if n["cha"] is None}
        assert set(HOP_DONG_ROOT_CODES) == goc
        assert len(HOP_DONG_ROOT_CODES) == 10

    def test_moi_nhom_con_tro_toi_nhom_goc_co_that(self):
        ma_hop_le = {n["ma"] for n in HOP_DONG_CATEGORIES}
        for n in HOP_DONG_CATEGORIES:
            if n["cha"] is not None:
                assert n["cha"] in ma_hop_le
                assert n["cha"] in HOP_DONG_ROOT_CODES

    def test_ma_2_va_8_khong_ton_tai(self):
        """Hai nhóm TVPL đã bỏ. Đánh số lại cho "đẹp" là làm lệch URL."""
        ma = {n["ma"] for n in HOP_DONG_CATEGORIES}
        assert 2 not in ma and 8 not in ma

    @pytest.mark.parametrize("ma", [None, 0, 2, 8, 99])
    def test_ma_la_roi_ve_khac(self, ma):
        assert ten_nhom_hop_dong(ma) == "Khác"


class TestAnhXaSangMaVanBan:
    def test_moi_ma_47_deu_anh_xa_duoc(self):
        for lv in BIEU_MAU_FIELDS:
            ma_vb, nguon = sang_ma_van_ban(lv["ma"])
            assert ma_vb in TEN_THEO_MA, f"lĩnh vực {lv['ma']} rơi ra ngoài 1–27"
            assert nguon in ("chac", "suy_dien")

    def test_doanh_nghiep_11_thanh_1_khong_phai_giu_nguyen_11(self):
        """Bẫy trung tâm: "Doanh nghiệp" = 11 ở biểu mẫu, = 1 ở văn bản.

        Giữ nguyên 11 sẽ xếp mọi biểu mẫu doanh nghiệp vào "Công nghệ thông tin"
        của danh mục văn bản.
        """
        assert sang_ma_van_ban(11) == (1, "chac")
        assert TEN_THEO_MA[1] == "Doanh nghiệp"

    def test_ma_la_roi_ve_linh_vuc_khac_va_luon_la_suy_dien(self):
        assert sang_ma_van_ban(99) == (27, "suy_dien")
        assert sang_ma_van_ban(None) == (27, "suy_dien")

    def test_suy_dien_khong_duoc_gan_nhan_chac(self):
        """Xăng dầu → Thương mại là đoán, không phải dữ kiện.

        Nhãn sai ở đây làm cả hệ thống đọc phỏng đoán như dữ kiện — đúng lỗi mà
        cột tvpl_field_source của bảng documents sinh ra để tránh.
        """
        assert sang_ma_van_ban(43)[1] == "suy_dien"   # Xăng dầu
        assert sang_ma_van_ban(27)[1] == "suy_dien"   # Phòng cháy chữa cháy
        assert sang_ma_van_ban(35)[1] == "chac"       # Thuế - Phí – Lệ phí


class TestNghiepVu:
    def test_tap_dong_12_nhom(self):
        assert len(NGHIEP_VU) == 12
        assert MA_NGHIEP_VU_KHAC in NGHIEP_VU

    def test_chuan_hoa_bo_ma_la_va_khu_trung(self):
        assert chuan_hoa_nghiep_vu(["thue_hoa_don", "bịa", "thue_hoa_don"]) == [
            "thue_hoa_don"
        ]

    def test_rong_thi_ve_khac_chu_khong_ve_rong(self):
        """Biểu mẫu không nhóm được vẫn phải tra được.

        Trả về [] nghĩa là mẫu biến mất khỏi mọi mục lục — mất hàng im lặng.
        """
        assert chuan_hoa_nghiep_vu([]) == [MA_NGHIEP_VU_KHAC]
        assert chuan_hoa_nghiep_vu(None) == [MA_NGHIEP_VU_KHAC]
        assert chuan_hoa_nghiep_vu(["không có thật"]) == [MA_NGHIEP_VU_KHAC]
