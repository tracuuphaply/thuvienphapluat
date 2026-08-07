"""
Hồ sơ ngành trong không gian embedding, và cách so một đoạn văn bản với chúng.

Bộ phân loại từ khoá một mình bỏ trắng hơn nửa kho: đo thực tế 22.071/43.413
đoạn cho ra danh sách ngành RỖNG. Đó là lý do định lượng để có tầng ngữ nghĩa,
chứ không phải vì "embedding thì hiện đại hơn".

Chi phí gần như bằng không: 21 ngành × ~13 câu = ~270 lượt nhúng một lần duy
nhất, còn vector của từng đoạn thì rag_indexer đã nhúng sẵn.

HAI HIỆU CHỈNH BẮT BUỘC, không phải tuỳ chọn:

  (a) TRỪ TÂM. Văn bản pháp luật tiếng Việt nhúng ra một cụm rất chặt — mọi đoạn
      đều mở đầu bằng "Căn cứ...", "Điều...", cùng một giọng hành chính. Cosine
      thô vì thế nằm gọn trong dải hẹp và không so sánh được giữa các ngành:
      đoạn nào cũng "khá giống" cả 21 hồ sơ. Trừ vector trung bình toàn kho làm
      lộ ra phần KHÁC BIỆT, vốn mới là tín hiệu.

  (b) CHUẨN HOÁ Z THEO TỪNG NGÀNH. Mỗi hồ sơ ngành có độ "rộng" khác nhau —
      ngành có từ khoá phổ biến sẽ gần mọi thứ hơn ngành hẹp. So cosine thô giữa
      các ngành là so hai thước đo khác đơn vị.

Cả (mean, sd) của từng ngành lẫn vector tâm đều được ĐÓNG BĂNG vào cơ sở dữ liệu
theo scorer_version — nhúng lại cùng một câu trên model đang trôi sẽ làm điểm số
đổi thầm lặng.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from src.obsidian.vsic import VSIC_LEVEL1

# Số đoạn có điểm cao nhất được lấy để đại diện cho cả văn bản.
#
# Trung bình trên MỌI đoạn là sai: một đạo luật 300 Điều nhắc tới ngân hàng ở 5
# Điều VẪN là văn bản liên quan ngân hàng, nhưng trung bình 300 đoạn pha loãng
# tín hiệu đó về 0. Cùng lý do mà score_industries() chỉ tính một lần cho mỗi
# từ khoá trong toàn văn.
TOP_K_CHUNKS = 5

# Trọng số giữa tầng từ khoá và tầng ngữ nghĩa khi hợp nhất.
LEXICON_WEIGHT = 0.45
EMBEDDING_WEIGHT = 0.55

# Nhiệt độ softmax. Thấp quá thì một ngành chiếm gần hết; cao quá thì 21 ngành
# gần như bằng nhau và con số mất ý nghĩa.
SOFTMAX_TEMPERATURE = 1.0


@dataclass(frozen=True)
class IndustryProfile:
    vsic_code: str
    name: str
    texts: tuple[str, ...]


def profile_texts(nganh: dict) -> tuple[str, ...]:
    """Các câu dùng để dựng hồ sơ một ngành.

    Từ khoá được bọc vào một câu hoàn chỉnh ("Quy định pháp luật về X") thay vì
    nhúng trần: model nhúng câu cho vector ổn định hơn nhiều so với nhúng một
    cụm danh từ rời, và câu này đặt từ khoá vào đúng ngữ cảnh pháp luật.
    """
    texts = [nganh["ten"], nganh["ten_ngan"]]
    texts += [f"Quy định pháp luật về {kw}." for kw in nganh["tu_khoa"]]
    return tuple(texts)


def all_profiles() -> list[IndustryProfile]:
    return [
        IndustryProfile(n["ma"], n["ten_ngan"], profile_texts(n))
        for n in VSIC_LEVEL1
    ]


# ──────────────────────────────────────────────
# Đại số vector — viết tay để không kéo thêm numpy vào phụ thuộc
# ──────────────────────────────────────────────
def mean_vector(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    n = len(vectors)
    dim = len(vectors[0])
    out = [0.0] * dim
    for v in vectors:
        for i in range(dim):
            out[i] += v[i]
    return [x / n for x in out]


def subtract(a: list[float], b: list[float]) -> list[float]:
    return [x - y for x, y in zip(a, b)]


def normalize(v: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v] if norm else v


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def zscore(value: float, mean: float, sd: float) -> float:
    """Chuẩn hoá; sd = 0 nghĩa là ngành đó không phân biệt được gì → trả 0."""
    return (value - mean) / sd if sd else 0.0


def softmax(scores: dict[str, float], temperature: float = SOFTMAX_TEMPERATURE) -> dict[str, float]:
    """Chuyển điểm thô thành phân phối cộng lại bằng 1."""
    if not scores:
        return {}
    top = max(scores.values())
    exps = {k: math.exp((v - top) / temperature) for k, v in scores.items()}
    total = sum(exps.values())
    return {k: v / total for k, v in exps.items()} if total else scores


def percentile_rank(value: float, sorted_values: list[float]) -> float:
    """Thứ hạng bách phân của `value` trong một dãy ĐÃ sắp tăng dần.

    Dùng phân vị chứ không min-max vì ba lý do: không phụ thuộc phân phối, diễn
    giải được thành câu người đọc hiểu ("top 5% văn bản tác động mạnh nhất tới
    ngành K"), và ỔN ĐỊNH khi kho lớn lên — min-max thì một đạo luật khổng lồ
    mới về sẽ co giãn lại toàn bộ điểm số cũ.
    """
    n = len(sorted_values)
    if n == 0:
        return 0.0
    lo, hi = 0, n
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_values[mid] <= value:
            lo = mid + 1
        else:
            hi = mid
    return 100.0 * lo / n
