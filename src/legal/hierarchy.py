"""
Thứ bậc hiệu lực pháp lý và loại văn bản, suy từ số hiệu.

NGUỒN: Điều 4 Luật Ban hành văn bản quy phạm pháp luật năm 2025 (thông qua
19/02/2025, hiệu lực 01/4/2025). Luật này đã BỎ thẩm quyền ban hành VBQPPL của
chính quyền cấp xã, nên văn bản cấp xã ban hành sau 01/4/2025 không còn là VBQPPL.

VÌ SAO SUY TỪ SỐ HIỆU CHỨ KHÔNG TỪ agencyName: đây là quy tắc pháp lý, không
phải quy ước dữ liệu — Luật luôn do Quốc hội ban hành, Nghị định luôn do Chính
phủ. Dữ liệu Bộ Tư pháp có chỗ ghi sai (Luật Xây dựng 135/2025/QH15 bị ghi do
"Bộ Xây dựng" ban hành), nên khi số hiệu và agencyName mâu thuẫn thì số hiệu
thắng. Module này mở rộng đúng ý tưởng đã có sẵn ở moj_api._AGENCY_BY_SUFFIX,
gộp thành một bảng trả về đồng thời cơ quan, loại, cấp và phạm vi lãnh thổ.

Cấp 1 là cao nhất. Cấp 99 nghĩa là KHÔNG phải VBQPPL — công điện, thông báo,
kế hoạch, văn bản của Đảng, và cả bản dự thảo. Chúng vẫn được giữ trong kho làm
ngữ cảnh nhưng không được dùng làm căn cứ pháp lý trong báo cáo.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from src.legal.provinces import is_local_agency, province_from_agency

TRUNG_UONG = "trung_uong"
TINH = "tinh"
KHONG_XAC_DINH = "khong_xac_dinh"

# Cấp không phải VBQPPL. Dùng số lớn để mọi phép so sánh "cấp cao hơn" đều đúng
# mà không phải xử lý None ở từng chỗ.
LEVEL_NON_NORMATIVE = 99


@dataclass(frozen=True)
class LegalFacts:
    hierarchy_level: int
    doc_type_norm: str
    territorial_scope: str
    agency: str | None       # None = không suy được từ số hiệu, giữ agencyName
    is_vbqppl: bool


def _ascii_key(doc_num: str) -> str:
    """Số hiệu ở dạng ASCII hoa, dấu phân cách thống nhất.

    Dữ liệu nguồn có cả "/NQ-HĐND", "/NQ_HĐND" và "/NQ-HDND" cho cùng một loại.
    Chuẩn hoá một lần rồi khớp bằng mẫu ASCII, thay vì liệt kê từng biến thể bẩn.
    """
    text = (doc_num or "").translate(str.maketrans({"Đ": "D", "đ": "d"}))
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[_\s]+", "-", text).upper().strip()


# Thứ tự có ý nghĩa: mẫu hẹp phải đứng trước mẫu rộng. "/QD-TTG" phải được xét
# trước "/QD-" chung, nếu không Quyết định của Thủ tướng bị xếp nhầm cấp.
_RULES: tuple[tuple[re.Pattern[str], LegalFacts], ...] = (
    # ── Cấp 2: Bộ luật, luật, nghị quyết của Quốc hội ──
    (re.compile(r"/QH\d*$"),
     LegalFacts(2, "luat", TRUNG_UONG, "Quốc hội", True)),
    # ── Cấp 3: Pháp lệnh, nghị quyết của UBTVQH ──
    (re.compile(r"/(PL-)?UBTVQH\d*$"),
     LegalFacts(3, "phap_lenh", TRUNG_UONG, "Ủy ban Thường vụ Quốc hội", True)),
    # Hội đồng Nhà nước — tiền thân của UBTVQH trước Hiến pháp 1992.
    (re.compile(r"/H[DĐ]NN\d*$"),
     LegalFacts(3, "phap_lenh", TRUNG_UONG, "Hội đồng Nhà nước", True)),
    # ── Cấp 4: Lệnh, quyết định của Chủ tịch nước ──
    (re.compile(r"/(L|QD)-CTN$"),
     LegalFacts(4, "lenh_ctn", TRUNG_UONG, "Chủ tịch nước", True)),
    # ── Cấp 5: Nghị định, nghị quyết của Chính phủ ──
    (re.compile(r"/N[DĐ]-CP$"),
     LegalFacts(5, "nghi_dinh", TRUNG_UONG, "Chính phủ", True)),
    (re.compile(r"/NQ-CP$"),
     LegalFacts(5, "nghi_quyet_cp", TRUNG_UONG, "Chính phủ", True)),
    # ── Cấp 6: Quyết định của Thủ tướng ──
    (re.compile(r"/Q[DĐ]-TTG$"),
     LegalFacts(6, "quyet_dinh_ttg", TRUNG_UONG, "Thủ tướng Chính phủ", True)),
    # ── Cấp 7: Thông tư và thông tư liên tịch ──
    (re.compile(r"/TTLT-"),
     LegalFacts(7, "thong_tu_lien_tich", TRUNG_UONG, None, True)),
    (re.compile(r"/TT-"),
     LegalFacts(7, "thong_tu", TRUNG_UONG, None, True)),
    # ── Cấp 8: Nghị quyết của HĐND cấp tỉnh ──
    # Không đòi dấu "/" đứng trước: dữ liệu có "09/2026NQ-HĐND" thiếu dấu
    # phân cách. Không số hiệu hợp lệ nào kết thúc bằng NQ-HĐND mà lại không
    # phải nghị quyết HĐND, nên nới ở đây là an toàn.
    (re.compile(r"NQ-H[DĐ]ND$"),
     LegalFacts(8, "nghi_quyet_hdnd", TINH, None, True)),
    # ── Cấp 9: Quyết định của UBND cấp tỉnh ──
    # Quyết định của CHỦ TỊCH UBND là văn bản cá biệt, không phải VBQPPL —
    # phải xét trước mẫu /QD-UBND, nếu không nó lọt vào cấp 9.
    (re.compile(r"/Q[DĐ]-CTUBND$"),
     LegalFacts(LEVEL_NON_NORMATIVE, "quyet_dinh_ca_biet", TINH, None, False)),
    (re.compile(r"/Q[DĐ]-UBND"),
     LegalFacts(9, "quyet_dinh_ubnd", TINH, None, True)),

    # ── Không phải VBQPPL ──
    # Mọi quyết định còn lại ("1968/QĐ-BTC", "982/QĐ-TTPVHCC"). Điều 4 chỉ cho
    # Bộ trưởng và Thủ trưởng cơ quan ngang bộ ban hành VBQPPL dưới dạng THÔNG
    # TƯ; quyết định của họ là văn bản cá biệt. Xếp nhầm nhóm này vào cấp 7 sẽ
    # khiến báo cáo dẫn một quyết định điều hành như thể là quy phạm.
    (re.compile(r"/Q[DĐ]-"),
     LegalFacts(LEVEL_NON_NORMATIVE, "quyet_dinh_ca_biet", KHONG_XAC_DINH, None, False)),
    # Chỉ thị đã bị loại khỏi danh mục VBQPPL từ Luật 2015 và Luật 2025 giữ nguyên.
    (re.compile(r"/CT-"),
     LegalFacts(LEVEL_NON_NORMATIVE, "chi_thi", KHONG_XAC_DINH, None, False)),
    # Văn bản hợp nhất chỉ gộp nội dung đã có hiệu lực, tự nó không đặt ra quy phạm.
    (re.compile(r"/VBHN-"),
     LegalFacts(LEVEL_NON_NORMATIVE, "van_ban_hop_nhat", TRUNG_UONG, None, False)),
    # Văn bản của Đảng: "16-NQ/TW", "123-TB/VPTW". Không thuộc hệ thống VBQPPL
    # của Nhà nước dù có sức chi phối chính sách rất lớn.
    (re.compile(r"/(TW|VPTW)$"),
     LegalFacts(LEVEL_NON_NORMATIVE, "van_ban_dang", TRUNG_UONG, None, False)),
    # Hành chính điều hành: thông báo, công điện, kế hoạch, công văn, tờ trình.
    (re.compile(r"/(TB|C[DĐ]|KH|CV|TTr|BC)-"),
     LegalFacts(LEVEL_NON_NORMATIVE, "hanh_chinh", KHONG_XAC_DINH, None, False)),
)

# Loại văn bản đọc từ doc_type khi số hiệu không nói lên điều gì — trường hợp
# duy nhất đáng kể là Hiến pháp, vốn có doc_num là "Không số".
_BY_DOC_TYPE: dict[str, LegalFacts] = {
    "hiến pháp": LegalFacts(1, "hien_phap", TRUNG_UONG, "Quốc hội", True),
    "bộ luật": LegalFacts(2, "luat", TRUNG_UONG, "Quốc hội", True),
    "luật": LegalFacts(2, "luat", TRUNG_UONG, "Quốc hội", True),
    "pháp lệnh": LegalFacts(3, "phap_lenh", TRUNG_UONG, "Ủy ban Thường vụ Quốc hội", True),
    "lệnh": LegalFacts(4, "lenh_ctn", TRUNG_UONG, "Chủ tịch nước", True),
    "nghị định": LegalFacts(5, "nghi_dinh", TRUNG_UONG, "Chính phủ", True),
    "thông tư": LegalFacts(7, "thong_tu", TRUNG_UONG, None, True),
    "thông tư liên tịch": LegalFacts(7, "thong_tu_lien_tich", TRUNG_UONG, None, True),
    "văn bản hợp nhất": LegalFacts(
        LEVEL_NON_NORMATIVE, "van_ban_hop_nhat", TRUNG_UONG, None, False),
    # Tới được đây nghĩa là hậu tố không phải QĐ-TTg hay QĐ-UBND, tức không
    # thuộc dạng quyết định nào là VBQPPL theo Điều 4.
    "quyết định": LegalFacts(
        LEVEL_NON_NORMATIVE, "quyet_dinh_ca_biet", KHONG_XAC_DINH, None, False),
}

_UNKNOWN = LegalFacts(LEVEL_NON_NORMATIVE, "khong_xac_dinh", KHONG_XAC_DINH, None, False)

# Số hiệu là cả một câu tiếng Việt = bản dự thảo hoặc bản hệ thống hoá, TVPL đưa
# tiêu đề vào ô số hiệu. Không phải văn bản đã ban hành.
_LOOKS_LIKE_TITLE = re.compile(r"^\s*(Dự thảo|Dự án)\b", re.IGNORECASE)


def classify(doc_num: str, doc_type: str = "", agency_name: str = "") -> LegalFacts:
    """Thứ bậc, loại chuẩn hoá và phạm vi lãnh thổ của một văn bản.

    Ưu tiên số hiệu; chỉ lùi về doc_type khi số hiệu không mang thông tin
    (Hiến pháp ghi "Không số"), và lùi tiếp về cơ quan ban hành cho văn bản địa
    phương không rõ loại.
    """
    if _LOOKS_LIKE_TITLE.match(doc_num or ""):
        return LegalFacts(LEVEL_NON_NORMATIVE, "du_thao", KHONG_XAC_DINH, None, False)

    key = _ascii_key(doc_num)
    for pattern, facts in _RULES:
        if pattern.search(key):
            return facts

    by_type = _BY_DOC_TYPE.get((doc_type or "").strip().lower())
    if by_type:
        return by_type

    # Cơ quan địa phương nhưng số hiệu không theo mẫu nào đã biết: vẫn xác định
    # được phạm vi lãnh thổ, đó là thứ báo cáo cần nhất.
    if is_local_agency(agency_name):
        return LegalFacts(LEVEL_NON_NORMATIVE, "khong_xac_dinh", TINH, None, False)

    return _UNKNOWN


def resolve_province(agency_name: str) -> tuple[str | None, str | None]:
    """(mã tỉnh như văn bản ghi, mã tỉnh hiện hành)."""
    return province_from_agency(agency_name)
