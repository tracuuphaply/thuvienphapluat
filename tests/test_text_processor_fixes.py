"""Hai lỗi trong xử lý toàn văn phát hiện khi rà soát hệ thống.

- Thực thể số HTML ngoài dải hợp lệ (&#9999999999;) làm chr() ném ValueError →
  cả văn bản bị đánh FAILED, mất toàn bộ toàn văn.
- Đoạn liền mạch dài quá trần không có \\n\\n thì không bị cắt → một chunk quá cỡ,
  về sau bị cắt cụt lúc nhúng vector.
"""
from src.pipeline.text_processor import chunk_legal_text, html_to_clean_text


class TestHtmlEntity:
    def test_thuc_the_ngoai_dai_khong_crash(self):
        out = html_to_clean_text("Trước &#9999999999; giữa &#x110000; sau")
        # không ném; giữ được phần chữ, bỏ thực thể rác
        assert "Trước" in out and "giữa" in out and "sau" in out

    def test_thuc_the_hop_le_van_giai_ma(self):
        # &#273; = 'đ', &#x111; = 'đ'
        out = html_to_clean_text("m&#273;t &#x111;i")
        assert "mđt" in out and "đi" in out


class TestCatDoanQuaDai:
    def test_doan_lien_mach_dai_bi_cat_theo_tran(self):
        # Một đoạn duy nhất, không cấu trúc Điều/Chương, không \n\n, dài gấp 3 trần.
        text = "x" * 6000
        chunks = chunk_legal_text(text, "99/2026/NĐ-CP",
                                  max_chunk_size=2000, min_chunk_size=100)
        assert chunks, "phải ra ít nhất một chunk"
        assert all(c["char_count"] <= 2000 for c in chunks), \
            [c["char_count"] for c in chunks]
        # không mất chữ: tổng độ dài (bỏ heading gắn vào) xấp xỉ đầu vào
        assert sum(c["char_count"] for c in chunks) >= 6000


class TestBoRuotHeadStyleScript:
    """`<head>`, `<style>`, `<script>` — gỡ THẺ thôi là chưa đủ, phải bỏ cả RUỘT.

    Bản Bộ Tư pháp tải từ kho là một trang HTML đủ `<head>`. Bước "gỡ mọi thẻ
    còn lại" chỉ xoá thẻ, giữ nguyên chữ nằm giữa — nên ba dòng đầu của bản làm
    sạch 01/2012/QĐ-TTg ra thành "Document Content" rồi hai luật CSS, và chúng
    hiện nguyên như vậy trên trang ngay dưới mục "Nội dung".

    Không chỉ hỏng hiển thị: `clean_text` là đầu vào của bước cắt chunk và nhúng
    vector, nên mấy dòng CSS ấy đang được nhúng như thể là nội dung pháp luật.
    """

    def test_bo_css_trong_style(self):
        ra = html_to_clean_text(
            "<html><head><style>body { font-family: Arial; margin: 20px; }</style>"
            "</head><body><p>Điều 1. Nội dung thật</p></body></html>")
        assert "font-family" not in ra and "margin" not in ra
        assert "Điều 1. Nội dung thật" in ra

    def test_bo_tieu_de_trang(self):
        ra = html_to_clean_text(
            "<html><head><title>Document Content</title></head>"
            "<body><p>THỦ TƯỚNG CHÍNH PHỦ</p></body></html>")
        assert "Document Content" not in ra
        assert "THỦ TƯỚNG CHÍNH PHỦ" in ra

    def test_bo_ma_javascript(self):
        ra = html_to_clean_text("<p>Trước</p><script>var x = 1; alert('x');</script><p>Sau</p>")
        assert "alert" not in ra and "var x" not in ra
        assert "Trước" in ra and "Sau" in ra

    def test_bo_chu_thich_html(self):
        ra = html_to_clean_text("<p>Trước</p><!-- ghi chú nội bộ --><p>Sau</p>")
        assert "ghi chú nội bộ" not in ra

    def test_the_khong_dong_van_khong_lot(self):
        """HTML hỏng: `<style>` không có thẻ đóng thì cắt tới hết chuỗi."""
        assert "font-family" not in html_to_clean_text(
            "<p>Trước</p><style>body { font-family: Arial; }")

    def test_style_nhieu_dong(self):
        ra = html_to_clean_text(
            "<style>\n  body { margin: 0; }\n  p { padding: 0; }\n</style><p>Nội dung</p>")
        assert "margin" not in ra and "padding" not in ra and "Nội dung" in ra
