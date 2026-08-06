"""Phân loại ngành — đầu vào của báo cáo theo ngành và của MOC trong vault.

Lỗi gốc: `if kw in search_text` trên chuỗi nối title+field+content. Không có
ranh giới từ nên "điện" khớp cả "bưu điện"/"điện tử", "nước" khớp "nhà nước";
và một lần xuất hiện bất kỳ đâu là gán ngành. Hệ quả: "Năng lượng & Môi trường"
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
        assert "Năng lượng & Môi trường" not in classify_industries(title, "", "")

    def test_van_nhan_ra_dien_that(self):
        assert "Năng lượng & Môi trường" in classify_industries(
            "Nghị định về phát triển điện lực và năng lượng tái tạo", "Năng lượng", ""
        )

    def test_khong_gan_cntt_vi_mang_luoi(self):
        assert "Công nghệ thông tin" not in classify_industries(
            "Quyết định về quy hoạch mạng lưới giao thông đường bộ", "", ""
        )


class TestTrongSo:
    def test_tieu_de_nang_hon_toan_van(self):
        trong_tieu_de = score_industries("Quy định về khám bệnh chữa bệnh", "", "")
        trong_toan_van = score_industries("Quy định chung", "", "… khám bệnh …")
        assert trong_tieu_de["Y tế & Dược phẩm"] > trong_toan_van.get("Y tế & Dược phẩm", 0)

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
        assert "Xây dựng & Bất động sản" in got
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
