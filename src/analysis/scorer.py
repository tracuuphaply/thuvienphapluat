"""
Chấm mức độ tác động của một văn bản lên 21 ngành VSIC.

CÔNG THỨC, phỏng theo RegData:

    impact_raw(j) = số_ràng_buộc(văn bản) × liên_quan(j) × trọng_số_thứ_bậc

trong đó `liên_quan(j)` hợp nhất hai tín hiệu độc lập: điểm từ khoá (rẻ, tái lập
tuyệt đối, nhưng bỏ trắng 51% số đoạn) và cosine embedding so với hồ sơ ngành
(bù đúng phần bỏ trắng đó).

HAI LOẠI PHẦN TRĂM — đây là quyết định thiết kế quan trọng nhất của module này,
và trộn lẫn chúng là kiểu hỏng kinh điển.

`impact_raw` không bị chặn trên: một Luật 300 Điều có hàng nghìn ràng buộc có
trọng số, một Quyết định 3 Điều có bốn. Chia thẳng ra phần trăm sẽ nói "Luật
Doanh nghiệp = 100%, còn lại ≈ 0%" — đúng về số học, vô dụng về nghiệp vụ.

    impact_pct_doc       tổng 21 ngành = 100%
                         trả lời: "văn bản này tác động tới AI?"
                         dùng: bảng trong báo cáo phân tích văn bản mới

    impact_pct_industry  phân vị so với toàn bộ văn bản, riêng cho từng ngành
                         trả lời: "ngành j nên quan tâm văn bản này TỚI MỨC NÀO?"
                         dùng: chọn ngành sinh báo cáo, ngưỡng chống ngập

GIỚI HẠN PHẢI GHI VÀO BÁO CÁO: chỉ số này đo CƯỜNG ĐỘ QUY PHẠM hướng vào một
ngành, KHÔNG đo CHI PHÍ KINH TẾ. RegData nói rõ điều đó về chính nó. Thiếu câu
này thì con số sẽ bị đọc thành thứ nó không phải.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.analysis import centroids
from src.legal.hierarchy import LEVEL_NON_NORMATIVE

# Một điều cấm trong Luật không cùng sức nặng với một điều cấm trong quyết định
# cấp tỉnh. Cấp 99 (không phải VBQPPL) gần như bị triệt tiêu chứ không loại hẳn
# — chúng vẫn là tín hiệu chính sách, chỉ không phải căn cứ pháp lý.
HIERARCHY_WEIGHT: dict[int, float] = {
    1: 1.0, 2: 1.0, 3: 0.9, 4: 0.9, 5: 0.8,
    6: 0.7, 7: 0.6, 8: 0.4, 9: 0.4,
    LEVEL_NON_NORMATIVE: 0.1,
}


@dataclass
class IndustryScore:
    vsic_code: str
    relevance_lexicon: float = 0.0
    relevance_embedding: float = 0.0
    relevance_fused: float = 0.0
    impact_raw: float = 0.0
    impact_pct_doc: float = 0.0
    impact_pct_industry: float = 0.0


@dataclass
class DocumentImpact:
    doc_key: str
    doc_num: str
    restriction_weighted: float = 0.0
    scores: dict[str, IndustryScore] = field(default_factory=dict)

    def top(self, n: int = 3) -> list[IndustryScore]:
        return sorted(self.scores.values(), key=lambda s: -s.impact_pct_doc)[:n]


def hierarchy_weight(level: int | None) -> float:
    if level is None:
        return HIERARCHY_WEIGHT[LEVEL_NON_NORMATIVE]
    return HIERARCHY_WEIGHT.get(int(level), HIERARCHY_WEIGHT[LEVEL_NON_NORMATIVE])


def fuse_relevance(lexicon: dict[str, float], embedding: dict[str, float]) -> dict[str, float]:
    """Hợp nhất hai tín hiệu liên quan ngành.

    Khi một tầng không có dữ liệu (chưa nhúng vector, hoặc từ khoá không khớp gì)
    thì tầng còn lại được dùng nguyên trọng số, thay vì bị chia đôi và tụt điểm
    một cách vô cớ.
    """
    # SẮP XẾP, không để nguyên set: thứ tự lặp một set chuỗi đổi giữa các tiến
    # trình vì Python ngẫu nhiên hoá hash. Thứ tự cộng khác nhau làm tổng dấu
    # phẩy động lệch ở chữ số cuối, và điểm số hết tái lập — đúng thứ mà cả
    # thiết kế này nhắm tới. Đo thật: 2/16.905 dòng lệch ở chữ số thứ 15.
    codes = sorted(set(lexicon) | set(embedding))
    out: dict[str, float] = {}
    # Kiểm bằng "dict có phần tử không", KHÔNG bằng "có giá trị khác 0 không":
    # {"K": 0.0} nghĩa là tầng đó ĐÃ chạy và chấm 0 điểm — một thông tin thật —
    # còn {} mới là tầng đó không cho ra gì. Lẫn hai thứ này thì một ngành bị
    # chấm 0 sẽ khiến cả tầng bị coi như vắng mặt.
    has_lex = bool(lexicon)
    has_emb = bool(embedding)

    for code in codes:
        if has_lex and has_emb:
            out[code] = (centroids.LEXICON_WEIGHT * lexicon.get(code, 0.0)
                         + centroids.EMBEDDING_WEIGHT * embedding.get(code, 0.0))
        elif has_lex:
            out[code] = lexicon.get(code, 0.0)
        else:
            out[code] = embedding.get(code, 0.0)
    return out


def score_document(
    doc_key: str,
    doc_num: str,
    restriction_weighted: float,
    relevance_lexicon: dict[str, float],
    relevance_embedding: dict[str, float],
    hierarchy_level: int | None,
) -> DocumentImpact:
    """Điểm tác động của một văn bản lên từng ngành.

    `impact_pct_industry` chưa tính được ở đây vì nó là phân vị so với TOÀN BỘ
    kho — phải chờ chấm xong hết rồi mới xếp hạng (xem `assign_percentiles`).
    """
    impact = DocumentImpact(
        doc_key=doc_key, doc_num=doc_num, restriction_weighted=restriction_weighted
    )
    fused = fuse_relevance(relevance_lexicon, relevance_embedding)
    weight = hierarchy_weight(hierarchy_level)

    raw_total = 0.0
    # fused đã được dựng theo thứ tự đã sắp, nên tổng này cộng cùng thứ tự ở
    # mọi lần chạy.
    for code, rel in fused.items():
        raw = restriction_weighted * rel * weight
        raw_total += raw
        impact.scores[code] = IndustryScore(
            vsic_code=code,
            relevance_lexicon=relevance_lexicon.get(code, 0.0),
            relevance_embedding=relevance_embedding.get(code, 0.0),
            relevance_fused=rel,
            impact_raw=raw,
        )

    for score in impact.scores.values():
        score.impact_pct_doc = (100.0 * score.impact_raw / raw_total) if raw_total else 0.0

    return impact


def assign_percentiles(
    impacts: list[DocumentImpact],
    reference_keys: set[str] | None = None,
) -> dict[str, list[float]]:
    """Gán `impact_pct_industry` cho mọi văn bản, theo từng ngành.

    Phải chạy một lượt trên cả tập: phân vị chỉ có nghĩa khi so với một phân
    phối. Trả về phân phối đã dùng, để lưu lại và giải thích được con số về sau.

    `reference_keys` giới hạn PHÂN PHỐI THAM CHIẾU, không giới hạn tập được
    gán điểm. Mọi văn bản vẫn nhận phân vị, nhưng phân vị đó so với nhóm nào là
    một quyết định phải nói rõ.

    Vì sao cần: bao đóng dẫn chiếu đưa vào kho 3.443 văn bản nền — phần lớn
    ngắn, cấp tỉnh, đã hết hiệu lực, tức điểm thấp. Gộp chúng vào phân phối thì
    một văn bản ở phân vị 50 trong 1.053 văn bản nghiệp vụ nhảy lên phân vị 89
    trong 4.466, dù bản thân nó không đổi gì. Ngưỡng ≥ 80 chọn ngành cho báo
    cáo (c) sẽ kích hoạt cho gần như mọi thứ — đúng bệnh ngập báo cáo mà
    C_MIN_SHARE sinh ra để chặn, quay lại bằng cửa khác.

    Câu hỏi mà chỉ số này trả lời là "ngành i nên quan tâm văn bản này tới mức
    nào so với các văn bản KHÁC CÓ THỂ SINH BÁO CÁO", nên nhóm tham chiếu đúng
    là văn bản nghiệp vụ, không phải văn bản ngữ cảnh.
    """
    by_industry: dict[str, list[float]] = {}
    for impact in impacts:
        if reference_keys is not None and impact.doc_key not in reference_keys:
            continue
        for code, score in impact.scores.items():
            by_industry.setdefault(code, []).append(score.impact_raw)

    for values in by_industry.values():
        values.sort()

    for impact in impacts:
        for code, score in impact.scores.items():
            # Ngành không có mặt trong nhóm tham chiếu thì không có phân phối để
            # so. Để 0 chứ không lấy phân phối của ngành khác, và cũng không
            # ném lỗi giữa một lượt chấm cả kho.
            phan_phoi = by_industry.get(code)
            score.impact_pct_industry = (
                centroids.percentile_rank(score.impact_raw, phan_phoi)
                if phan_phoi else 0.0
            )

    return by_industry
