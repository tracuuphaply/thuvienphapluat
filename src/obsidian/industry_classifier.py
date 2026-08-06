"""
Rule-based industry classification for legal documents.
"""
import re
from typing import List

from src.obsidian.config_obsidian import INDUSTRY_MAP

# Điểm tối thiểu để gán một ngành. Tiêu đề và lĩnh vực nói lên chủ đề văn bản
# rõ hơn nhiều so với một lần từ khoá xuất hiện đâu đó trong toàn văn.
TITLE_WEIGHT = 3
FIELD_WEIGHT = 3
CONTENT_WEIGHT = 1
MIN_SCORE = 3

# Từ khoá ngắn dễ khớp nhầm khi nằm trong từ ghép khác nghĩa. Chỉ tính điểm khi
# KHÔNG đứng cạnh các từ trong danh sách loại trừ.
#   "điện"  → "bưu điện", "điện tử", "điện thoại", "công điện"
#   "nước"  → "nhà nước", "trong nước", "nước ngoài"
#   "mạng"  → "mạng lưới"
AMBIGUOUS_KEYWORDS: dict[str, tuple[str, ...]] = {
    "điện": ("bưu điện", "điện tử", "điện thoại", "công điện", "điện báo", "điện văn"),
    "nước": ("nhà nước", "trong nước", "nước ngoài", "ngoài nước", "cả nước", "toàn nước"),
    "mạng": ("mạng lưới", "tính mạng"),
    "khí": ("không khí", "khí hậu", "khí tượng"),
    "dữ liệu": ("dữ liệu báo cáo", "dữ liệu thống kê"),
}

_WORD_BOUNDARY_CACHE: dict[str, re.Pattern] = {}


def _pattern(keyword: str) -> re.Pattern:
    """Regex khớp từ khoá theo ranh giới từ, có nhớ đệm."""
    if keyword not in _WORD_BOUNDARY_CACHE:
        _WORD_BOUNDARY_CACHE[keyword] = re.compile(
            rf"(?<!\w){re.escape(keyword)}(?!\w)", re.UNICODE
        )
    return _WORD_BOUNDARY_CACHE[keyword]


def _count_matches(keyword: str, text: str) -> int:
    """Số lần từ khoá xuất hiện thật sự, đã trừ các cụm dễ nhầm."""
    if not text:
        return 0
    hits = len(_pattern(keyword).findall(text))
    if not hits:
        return 0
    for trap in AMBIGUOUS_KEYWORDS.get(keyword, ()):
        hits -= text.count(trap)
    return max(0, hits)


def score_industries(
    title: str, field_name: str, content: str = None
) -> dict[str, int]:
    """Điểm khớp của từng ngành, để soi vì sao một văn bản được gán ngành nào."""
    title_lower = (title or "").lower()
    field_lower = (field_name or "").lower()
    content_lower = (content or "").lower()

    scores: dict[str, int] = {}
    for industry, keywords in INDUSTRY_MAP.items():
        score = 0
        for kw in keywords:
            score += _count_matches(kw, title_lower) * TITLE_WEIGHT
            score += _count_matches(kw, field_lower) * FIELD_WEIGHT
            # Toàn văn chỉ tính một lần cho mỗi từ khoá: một văn bản dài nhắc
            # "xây dựng" 50 lần không vì thế mà thuộc ngành xây dựng hơn.
            score += min(1, _count_matches(kw, content_lower)) * CONTENT_WEIGHT
        if score:
            scores[industry] = score
    return scores


def classify_industries(title: str, field_name: str, content: str = None) -> List[str]:
    """
    Classify a document into one or more industries based on keywords.

    Bản cũ dùng `if kw in search_text` trên chuỗi nối title+field+content nên
    một lần xuất hiện bất kỳ đâu là gán ngành, và không có ranh giới từ:
    "điện" khớp cả "bưu điện", "nước" khớp "nhà nước". Kết quả là ngành
    "Năng lượng & Môi trường" ôm 97/314 văn bản chủ yếu vì chữ "nhà nước".
    """
    scores = score_industries(title, field_name, content)
    return sorted(ind for ind, score in scores.items() if score >= MIN_SCORE)
