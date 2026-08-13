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
