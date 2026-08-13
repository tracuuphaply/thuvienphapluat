"""Ngắt dòng tiếng Việt trong PDF báo cáo.

Lỗi đã gặp thật: bảng lộ trình 5 cột ngắt "51/2024/TT-NHNN Điều 6" thành
"…Điều" ở dòng trên và "6" ở dòng dưới — tách một cụm định danh pháp lý đọc như
bị cắt. Quy tắc soạn thảo tiếng Việt: giữ liền từ định danh thứ tự với số của
nó, và chữ số với đơn vị.
"""
from src.utils.report_pdf import _ngat_dong_tieng_viet

NBSP = " "
ZWSP = "​"


class TestGiuLien:
    def test_dieu_khoan_diem_giu_lien_voi_so(self):
        assert _ngat_dong_tieng_viet("Điều 6") == f"Điều{NBSP}6"
        assert _ngat_dong_tieng_viet("khoản 3") == f"khoản{NBSP}3"
        assert _ngat_dong_tieng_viet("Chương 2") == f"Chương{NBSP}2"

    def test_dieu_khoan_kep(self):
        # "Điều 19 khoản 6" — cả hai cặp đều phải giữ liền
        out = _ngat_dong_tieng_viet("Điều 19 khoản 6")
        assert out == f"Điều{NBSP}19 khoản{NBSP}6"

    def test_so_va_don_vi_giu_lien(self):
        assert _ngat_dong_tieng_viet("10 tỷ đồng") == f"10{NBSP}tỷ đồng"
        assert _ngat_dong_tieng_viet("30 ngày") == f"30{NBSP}ngày"
        assert _ngat_dong_tieng_viet("24 tháng") == f"24{NBSP}tháng"

    def test_ngay_thang_nam_giu_lien_voi_so(self):
        assert _ngat_dong_tieng_viet("ngày 24/7/2026") == f"ngày{NBSP}24/7/2026"

    def test_khong_dung_toi_so_hieu(self):
        # Số hiệu KHÔNG bị chèn ký tự ẩn (font dựng ZWSP ra khoảng trắng thấy được)
        for sh in ("108/2026/TT-BTC", "168/2025/NĐ-CP", "28/2005/PL-UBTVQH11"):
            out = _ngat_dong_tieng_viet(sh)
            assert out == sh, out
            assert ZWSP not in out

    def test_phan_tram_da_lien_thi_khong_doi(self):
        # "70%" đã dính, không có khoảng trắng nên không cần xử lý
        assert _ngat_dong_tieng_viet("tăng 70% mỗi năm") == "tăng 70% mỗi năm"

    def test_khong_dung_van_ban_thuong(self):
        s = "Doanh nghiệp phải nộp báo cáo lao động hằng năm."
        assert _ngat_dong_tieng_viet(s) == s


class TestQuaInline:
    def test_inline_ap_dung_ngat_dong(self):
        from src.utils.report_pdf import _inline
        out = _inline("Theo **Điều 6** của luật")
        assert f"Điều{NBSP}6" in out
        assert "<b>" in out  # markup vẫn còn
