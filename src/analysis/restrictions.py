"""
Đếm "từ ràng buộc" — thước đo cường độ quy phạm của một điều khoản.

PHƯƠNG PHÁP GỐC: RegData của QuantGov/Mercatus Center đếm 5 modal tiếng Anh
(shall, must, may not, prohibited, required) ở mức tiểu mục, rồi nhân với xác
suất liên quan ngành để ra "số ràng buộc áp lên ngành j". Kho này có sẵn đúng
granularity cần thiết: chunk tách theo Điều.

VÌ SAO CÓ TRỌNG SỐ CÒN REGDATA THÌ KHÔNG. Năm modal tiếng Anh đều đơn nghĩa và
tần suất tương đương. Tiếng Việt thì không — đo trên 45.932 đoạn của kho:

    phải             38,4% số đoạn
    có trách nhiệm   14,8%
    không được        6,5%
    chỉ được          2,4%
    cấm               2,0%
    bắt buộc          1,8%
    nghiêm cấm        0,4%

Chênh 94 lần giữa "phải" và "nghiêm cấm". Đếm không trọng số thì "phải" nuốt
toàn bộ tín hiệu, mà "phải" lại là từ đa nghĩa nhất trong nhóm.

Đếm bằng lexicon dùng chung nên "phải" tự động trừ "bên phải", "tay phải".
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.analysis.lexicon import count_matches

# Trọng số theo mức độ cưỡng chế của mệnh đề, không theo tần suất.
RESTRICTION_TERMS: dict[str, float] = {
    # Cấm tuyệt đối
    "nghiêm cấm": 3.0,
    "cấm": 3.0,
    # Giới hạn hành vi
    "không được phép": 2.0,
    "không được": 2.0,
    "chỉ được": 2.0,
    "bắt buộc": 2.0,
    "buộc phải": 2.0,
    # Nghĩa vụ chung
    "phải": 1.0,
    "có trách nhiệm": 1.0,
    "có nghĩa vụ": 1.0,
    # Ràng buộc định lượng — đặt ra giới hạn cụ thể nên vẫn là ràng buộc thật,
    # nhưng nhẹ hơn vì thường đi kèm một nghĩa vụ đã được đếm ở trên.
    "chậm nhất": 0.5,
    "không quá": 0.5,
    "tối thiểu": 0.5,
}

# "không được phép" chứa "không được", "nghiêm cấm" chứa "cấm" — đếm cả hai là
# tính trùng một mệnh đề. Cụm dài được đếm trước rồi trừ khỏi cụm ngắn.
_SUBSUMED: dict[str, tuple[str, ...]] = {
    "không được": ("không được phép",),
    "cấm": ("nghiêm cấm",),
}


@dataclass
class RestrictionCount:
    weighted: float = 0.0
    total_terms: int = 0
    matched: dict[str, int] = field(default_factory=dict)


def count_restrictions(text: str) -> RestrictionCount:
    """Số ràng buộc có trọng số trong một đoạn văn bản.

    Trả về cả chi tiết từng từ để con số cuối cùng kiểm toán được — một tỷ lệ
    phần trăm không kèm đầu vào thì không bảo vệ được khi khách chất vấn.
    """
    result = RestrictionCount()
    if not text:
        return result

    lowered = text.lower()
    raw: dict[str, int] = {}
    for term in RESTRICTION_TERMS:
        n = count_matches(term, lowered)
        if n:
            raw[term] = n

    for term, subsumers in _SUBSUMED.items():
        if term in raw:
            raw[term] = max(0, raw[term] - sum(raw.get(s, 0) for s in subsumers))
            if not raw[term]:
                del raw[term]

    for term, n in raw.items():
        result.weighted += RESTRICTION_TERMS[term] * n
        result.total_terms += n
    result.matched = raw
    return result
