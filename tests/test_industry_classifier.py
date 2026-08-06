"""Phân loại ngành — đầu vào của báo cáo theo ngành và của MOC trong vault.

Lỗi gốc: `if kw in search_text` trên chuỗi nối title+field+content. Không có
ranh giới từ nên "điện" khớp cả "bưu điện"/"điện tử", "nước" khớp "nhà nước";
và một lần xuất hiện bất kỳ đâu là gán ngành. Hệ quả: "Sản xuất và phân phối điện, khí đốt"
ôm 97/314 văn bản chủ yếu nhờ chữ "nhà nước".
"""
import pytest

from src.obsidian.config_obsidian import INDUSTRY_MAP
from src.obsidian.industry_classifier import (
    MIN_SCORE,
    classify_industries,
    score_industries,
)


class TestRanhGioiTu:
    @pytest.mark.parametrize("title", [
        "Quyết định về quản lý nhà nước trong lĩnh vực hành chính",
        "Thông tư quy định về hoạt động bưu điện và chuyển phát",
        "Nghị định về thương mại điện tử xuyên biên giới",
    ])
    def test_khong_gan_nang_luong_vi_tu_ghep(self, title):
        """'nhà nước', 'bưu điện', 'điện tử' không làm văn bản thuộc ngành năng lượng."""
        assert "Sản xuất và phân phối điện, khí đốt" not in classify_industries(title, "", "")

    def test_van_nhan_ra_dien_that(self):
        assert "Sản xuất và phân phối điện, khí đốt" in classify_industries(
            "Nghị định về phát triển điện lực và năng lượng tái tạo", "Năng lượng", ""
        )

    def test_khong_gan_cntt_vi_mang_luoi(self):
        assert "Thông tin và truyền thông" not in classify_industries(
            "Quyết định về quy hoạch mạng lưới giao thông đường bộ", "", ""
        )


class TestTrongSo:
    def test_tieu_de_nang_hon_toan_van(self):
        trong_tieu_de = score_industries("Quy định về khám bệnh chữa bệnh", "", "")
        trong_toan_van = score_industries("Quy định chung", "", "… khám bệnh …")
        assert trong_tieu_de["Y tế và trợ giúp xã hội"] > trong_toan_van.get("Y tế và trợ giúp xã hội", 0)

    def test_mot_lan_nhac_trong_toan_van_khong_du_gan_nganh(self):
        """Văn bản dài nhắc thoáng qua một từ khoá không vì thế mà thuộc ngành đó."""
        assert classify_industries("Quyết định hành chính", "", "… trường học …") == []

    def test_lap_lai_trong_toan_van_khong_cong_don_vo_han(self):
        it = score_industries("x", "", "xây dựng")
        nhieu = score_industries("x", "", "xây dựng " * 50)
        assert it == nhieu, "nhắc 50 lần không làm văn bản thuộc ngành hơn"

    def test_nguong_duoc_ap_dung(self):
        for nganh, diem in score_industries("Quyết định hành chính", "", "… thuốc …").items():
            if diem < MIN_SCORE:
                assert nganh not in classify_industries("Quyết định hành chính", "", "… thuốc …")


class TestDaNganh:
    def test_mot_van_ban_thuoc_nhieu_nganh(self):
        got = classify_industries(
            "Quyết định phê duyệt quy hoạch xây dựng chợ thương mại", "Xây dựng", ""
        )
        assert "Xây dựng" in got
        assert len(got) >= 2

    def test_ket_qua_duoc_sap_xep_on_dinh(self):
        t = "Quy định về xây dựng và thương mại"
        assert classify_industries(t, "", "") == sorted(classify_industries(t, "", ""))

    def test_moi_nganh_tra_ve_deu_hop_le(self):
        got = classify_industries("Quy định về ngân hàng, tín dụng và cho vay", "Tài chính", "")
        for nganh in got:
            assert nganh in INDUSTRY_MAP


class TestDauVaoBatThuong:
    @pytest.mark.parametrize("args", [
        ("", "", ""), (None, None, None), ("", None, None),
    ])
    def test_khong_no_voi_dau_vao_rong(self, args):
        assert classify_industries(*args) == []

    def test_khong_no_voi_ky_tu_dac_biet(self):
        assert classify_industries("!@#$%^&*()", "///", "\n\t") == []


class TestDanhMucVSIC:
    """Danh mục ngành phải khớp Quyết định 27/2018/QĐ-TTg, cấp 1 (A–U)."""

    def test_du_21_nganh_cap_1(self):
        from src.obsidian.vsic import VSIC_LEVEL1
        assert len(VSIC_LEVEL1) == 21

    def test_ma_nganh_lien_tuc_tu_A_den_U(self):
        from src.obsidian.vsic import VSIC_LEVEL1
        assert [n["ma"] for n in VSIC_LEVEL1] == list("ABCDEFGHIJKLMNOPQRSTU")

    def test_ten_chinh_thuc_viet_hoa_va_khong_rong(self):
        from src.obsidian.vsic import VSIC_LEVEL1
        for n in VSIC_LEVEL1:
            assert n["ten"] == n["ten"].upper(), f'{n["ma"]}: tên chính thức phải viết hoa'
            assert n["ten_ngan"] and n["tu_khoa"], n["ma"]

    def test_khong_con_dau_bi_tach_khi_trich_tu_pdf(self):
        """Trích từ PDF hay để lại 'NGHI ỆP', 'N ƯỚC' — phải đã ghép lại."""
        from src.obsidian.vsic import VSIC_LEVEL1
        for n in VSIC_LEVEL1:
            for frag in ("NGHI ỆP", "N ƯỚC", "HO ẠT", "C Ơ", " Ơ", " Ư"):
                assert frag not in n["ten"], f'{n["ma"]}: còn dấu bị tách — {n["ten"]}'

    def test_tra_cuu_ma_va_ten_chinh_thuc(self):
        from src.obsidian.vsic import code_of, official_name
        assert code_of("Xây dựng") == "F"
        assert official_name("Xây dựng") == "XÂY DỰNG"
        assert code_of("ngành không có") == ""

    def test_ten_ngan_la_khoa_cua_INDUSTRY_MAP(self):
        from src.obsidian.vsic import INDUSTRY_MAP, VSIC_LEVEL1
        assert set(INDUSTRY_MAP) == {n["ten_ngan"] for n in VSIC_LEVEL1}
