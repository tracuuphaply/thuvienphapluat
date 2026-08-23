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


class TestKieuVanBan:
    """Chế độ `kieu="van_ban"` — nguồn là html_to_clean_text, không phải renderer."""

    def test_giu_nguyen_so_khoan_khong_giao_cho_trinh_duyet_danh_lai(self):
        """Đây là bất biến QUAN TRỌNG NHẤT của chế độ này.

        "2. Đối tượng áp dụng…" là KHOẢN 2 của một điều luật. Dựng thành
        <ol><li> là giao số thứ tự cho trình duyệt đánh lại, mà html_to_clean_text
        đặt mỗi khoản vào một khối riêng nên mỗi khoản thành một <ol> mới bắt đầu
        từ 1 — Khoản 2 hiện ra thành "1.". Trên một trang tra cứu pháp luật, hiện
        sai số khoản là nói sai nội dung luật.
        """
        md = "1. Khoản một.\n\n2. Khoản hai.\n\n3. Khoản ba."
        ra = sang_html(md, kieu="van_ban")
        assert "<ol" not in ra and "<li" not in ra
        for n in ("1.", "2.", "3."):
            assert f"<p>{n} Khoản" in ra

    def test_bieu_mau_van_dung_danh_sach_nhu_cu(self):
        """Chế độ mặc định KHÔNG đổi: ở biểu mẫu danh sách là danh sách thật."""
        ra = sang_html("1. Một\n2. Hai")
        assert "<ol>" in ra and ra.count("<li>") == 2

    def test_gop_cac_khoi_hang_bang_lien_nhau_thanh_mot_bang(self):
        """`</tr>` bị thay bằng hai dòng xuống, nên một bảng ra thành nhiều khối.

        Không gộp thì mọi bảng phụ lục vỡ thành chuỗi bảng một hàng xếp chồng.
        """
        md = "| A | B\n\n| 1 | 2\n\n| 3 | 4"
        ra = sang_html(md, kieu="van_ban")
        assert ra.count("<table") == 1
        assert ra.count("<tr>") == 3

    def test_thoi_gop_khi_het_bang(self):
        """Gộp phải DỪNG ở đoạn văn, không nuốt luôn bảng ở cuối trang."""
        md = "| A | B\n\nMột đoạn văn.\n\n| 1 | 2"
        ra = sang_html(md, kieu="van_ban")
        assert ra.count("<table") == 2
        assert "<p>Một đoạn văn.</p>" in ra

    def test_ba_gach_thanh_duong_ke_chu_khong_phai_chu(self):
        ra = sang_html("Trên\n\n---\n\nDưới", kieu="van_ban")
        assert "<hr>" in ra and "---" not in ra

    def test_ba_gach_o_bieu_mau_van_la_chu(self):
        """Chế độ biểu mẫu không đổi — `<hr>` không nằm trong tập cú pháp của nó."""
        assert "<hr>" not in sang_html("Trên\n\n---\n\nDưới")

    def test_van_thoat_html_nhu_moi_khi(self):
        """An toàn là điều kiện, không phải tính năng — chế độ mới không mở lối."""
        ra = sang_html("<script>alert(1)</script>\n\n| <b>x</b> | y", kieu="van_ban")
        assert "<script" not in ra.lower()
        assert "&lt;b&gt;x&lt;/b&gt;" in ra

    def test_luon_tien_duoc_du_nhanh_co_lech_nhau(self):
        """Hàm phải KẾT THÚC với mọi đầu vào, kể cả khi các nhánh lệch nhau.

        Nhánh đoạn văn là nhánh cuối; nếu điều kiện của nó và của một nhánh phía
        trên không khớp thì có dòng bị mọi nhánh từ chối và `i` đứng yên. Dựng
        lại được bằng cách sửa một dòng ở nhánh đường kẻ ngang: bản dựng treo,
        không lỗi, không đầu ra — trong trình duyệt là một thẻ đứng máy.
        """
        for md in ("---", "-----", "---\n---", "|", "| \n\n---\n\n| a",
                   "\n\n---\n\ncuối"):
            for kieu in ("van_ban", "bieu_mau"):
                sang_html(md, kieu=kieu)   # treo là test không bao giờ về

    def test_dam_co_khoang_trang_sat_trong_van_dung_duoc(self):
        """`<b>Quy định… </b>` của nguồn ra thành `**Quy định… **`.

        Mẫu chặt đòi ký tự KHÔNG TRẮNG ngay trước `**`, nên bản trước không khớp
        và dấu sao hiện nguyên ra màn hình. Đo trên 004/2025/TT-BNV: cả ba dòng
        tiêu đề đều dính.
        """
        ra = sang_html("**Quy định mức lương **", kieu="van_ban")
        assert "<strong>Quy định mức lương</strong>" in ra
        assert "*" not in ra

    def test_bo_dau_sao_khong_bao_gio_ghep_duoc(self):
        """`<b>` của nguồn bao qua NHIỀU thẻ khối → dấu mở và dấu đóng ở hai đoạn.

        Markdown không có cặp nào bắc qua đoạn, nên chúng không bao giờ ghép
        được. Giữ lại là rải `**` khắp mọi văn bản.
        """
        ra = sang_html("**\n\nBỘ NỘI VỤ\n\nTHÔNG TƯ **", kieu="van_ban")
        assert "*" not in ra
        assert "<p>BỘ NỘI VỤ</p>" in ra and "THÔNG TƯ" in ra

    def test_doan_chi_con_dau_sao_thi_bo_han(self):
        """Không để lại <p></p> rỗng — một ô trống rải giữa văn bản trông như lỗi."""
        ra = sang_html("Trên\n\n*\n\nDưới", kieu="van_ban")
        assert "<p></p>" not in ra
        assert ra.count("<p>") == 2

    def test_bieu_mau_khong_bi_don_dau_sao(self):
        """Chế độ biểu mẫu KHÔNG dọn: ở đó dấu sao lẻ là chữ thật của tờ mẫu."""
        assert "*" in sang_html("Ghi chú: (*) bắt buộc")
