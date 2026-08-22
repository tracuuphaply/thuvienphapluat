"""Bộ render Markdown tối giản.

Thân biểu mẫu là chữ CÀO TỪ NGUỒN NGOÀI, nên nhóm test đầu tiên là an toàn: không
có đường nào cho thẻ HTML trong nguồn đi xuyên qua. Các nhóm sau kiểm đúng tập cú
pháp mà `src/forms/renderer.py` thật sự phát ra.
"""
from src.publish.md_toi_gian import sang_html


class TestAnToan:
    def test_the_html_trong_nguon_bi_thoat(self):
        ra = sang_html("<script>alert(1)</script>")
        assert "<script>" not in ra
        assert "&lt;script&gt;" in ra

    def test_thoat_truoc_khi_ap_cu_phap(self):
        """Đảo thứ tự là mở đường: `**<b>x</b>**` sẽ nhả thẻ b thật ra ngoài."""
        ra = sang_html("**<b>x</b>**")
        assert "<strong>" in ra          # cú pháp markdown vẫn chạy
        assert "<b>" not in ra           # nhưng thẻ trong nguồn thì không

    def test_thoat_dau_va(self):
        assert "&amp;" in sang_html("Công ty A & B")

    def test_thuoc_tinh_su_kien_khong_song_sot(self):
        ra = sang_html('<img src=x onerror="alert(1)">')
        assert "onerror" not in ra or "&lt;img" in ra
        assert "<img" not in ra


class TestDoanVan:
    def test_doan_thanh_the_p(self):
        assert sang_html("Xin chào") == "<p>Xin chào</p>"

    def test_dong_trong_ngan_hai_doan(self):
        ra = sang_html("Đoạn một\n\nĐoạn hai")
        assert ra.count("<p>") == 2

    def test_ngat_dong_trong_doan_duoc_giu(self):
        """Dòng chấm chấm để điền tay phải giữ đúng chỗ xuống dòng — gộp lại
        thành một dòng dài là làm hỏng bố cục tờ mẫu."""
        ra = sang_html("Họ và tên:.........\nSinh năm:.........")
        assert ra.count("<p>") == 1
        assert "<br>" in ra


class TestBang:
    MAU = "| Họ tên | Chức vụ |\n|---|---|\n| Nguyễn A | Giám đốc |"

    def test_dung_thead_va_tbody(self):
        ra = sang_html(self.MAU)
        assert "<thead>" in ra and "<th>Họ tên</th>" in ra
        assert "<td>Nguyễn A</td>" in ra

    def test_bang_cuon_ngang_duoc(self):
        """Bảng biểu mẫu rất rộng; không bọc thì cả trang trượt ngang."""
        assert 'class="cuon"' in sang_html(self.MAU)

    def test_o_rong_van_ra_o(self):
        """luoi_bang() để ô gộp thành ô rỗng — không được nuốt mất cột."""
        ra = sang_html("| a | b |\n|---|---|\n|  | x |")
        assert ra.count("<td>") == 2

    def test_bang_khong_co_dong_phan_cach(self):
        ra = sang_html("| a | b |\n| c | d |")
        assert "<thead>" not in ra
        assert ra.count("<tr>") == 2


class TestDanhSachVaNoiTuyen:
    def test_gach_dau_dong_thanh_ul(self):
        ra = sang_html("- một\n- hai")
        assert ra.startswith("<ul>") and ra.count("<li>") == 2

    def test_so_thanh_ol(self):
        assert sang_html("1. một\n2. hai").startswith("<ol>")

    def test_dam_va_nghieng(self):
        assert "<strong>Căn cứ:</strong>" in sang_html("**Căn cứ:** abc")
        assert "<em>ghi chú</em>" in sang_html("*ghi chú*")

    def test_dam_khong_bi_nghieng_an_mat(self):
        """Xử lý nghiêng trước đậm thì `**x**` ra `<em>*x*</em>`."""
        ra = sang_html("**x**")
        assert ra == "<p><strong>x</strong></p>"

    def test_dau_sao_le_khong_thanh_the(self):
        ra = sang_html("Ghi chú * chưa đóng")
        assert "<em>" not in ra

    def test_ma_giu_nguyen_van(self):
        assert "<code>01/2007/QH12</code>" in sang_html("`01/2007/QH12`")


class TestRong:
    def test_chuoi_rong(self):
        assert sang_html("") == ""

    def test_toan_dong_trong(self):
        assert sang_html("\n\n\n") == ""
