"""
Đếm từ khoá trong văn bản tiếng Việt, có ranh giới từ và trừ bẫy từ ghép.

Phần này vốn nằm trong src/obsidian/industry_classifier.py và ra đời từ một lỗi
thật: bản đầu dùng `if keyword in text` nên "điện" khớp cả "bưu điện", "nước"
khớp "nhà nước" — ngành "Năng lượng & Môi trường" ôm 97/314 văn bản chủ yếu vì
chữ "nhà nước". Nay bộ đếm ràng buộc cũng cần đúng cơ chế đó ("phải" phải trừ
"bên phải"), nên tách ra dùng chung thay vì chép lại và để hai bản trôi khác nhau.
"""
from __future__ import annotations

import re

# Từ khoá ngắn dễ khớp nhầm khi nằm trong từ ghép khác nghĩa. Chỉ tính điểm khi
# KHÔNG nằm trong các cụm ở đây.
AMBIGUOUS_KEYWORDS: dict[str, tuple[str, ...]] = {
    "điện": ("bưu điện", "điện tử", "điện thoại", "công điện", "điện báo", "điện văn"),
    "nước": ("nhà nước", "trong nước", "nước ngoài", "ngoài nước", "cả nước", "toàn nước"),
    "mạng": ("mạng lưới", "tính mạng"),
    "khí": ("không khí", "khí hậu", "khí tượng"),
    "dữ liệu": ("dữ liệu báo cáo", "dữ liệu thống kê"),
    # "phải" là từ ràng buộc dày đặc nhất (38,4% số đoạn) nên bẫy của nó ảnh
    # hưởng lớn nhất tới điểm số. Đo trên kho thật: "bên phải" 140 đoạn,
    # "tay phải" 6; các cụm còn lại chưa xuất hiện nhưng giữ lại vì kho sẽ lớn lên.
    "phải": ("bên phải", "phía phải", "tay phải", "lẽ phải", "phải chăng",
             "trái phải", "cánh phải"),
}

_WORD_BOUNDARY_CACHE: dict[str, re.Pattern] = {}


def pattern_for(keyword: str) -> re.Pattern:
    """Regex khớp từ khoá theo ranh giới từ, có nhớ đệm."""
    if keyword not in _WORD_BOUNDARY_CACHE:
        _WORD_BOUNDARY_CACHE[keyword] = re.compile(
            rf"(?<!\w){re.escape(keyword)}(?!\w)", re.UNICODE
        )
    return _WORD_BOUNDARY_CACHE[keyword]


def count_matches(keyword: str, text: str) -> int:
    """Số lần từ khoá xuất hiện thật sự, đã trừ các cụm dễ nhầm.

    Văn bản truyền vào phải đã thường hoá (lower) — hàm không tự làm để bên gọi
    thường hoá một lần rồi đếm nhiều từ khoá, thay vì lặp lại trên mỗi từ.
    """
    if not text:
        return 0
    hits = len(pattern_for(keyword).findall(text))
    if not hits:
        return 0
    for trap in AMBIGUOUS_KEYWORDS.get(keyword, ()):
        hits -= text.count(trap)
    return max(0, hits)
