"""
Đối chiếu mọi số hiệu văn bản trong báo cáo với kho dữ liệu.

Prompt cấm bịa số hiệu, nhưng cấm không phải là bảo đảm. Báo cáo gửi ra ngoài
cho doanh nghiệp mà trích dẫn một văn bản không tồn tại thì hỏng cả uy tín, nên
mỗi bản phải qua bước đối chiếu máy móc này trước khi xuất PDF.

Cổng này CHẶN đúng thứ cần chặn — số hiệu mô hình BỊA. Nhưng "không có trong
kho" không đồng nghĩa với "bịa": một quyết định mới thường bãi bỏ/sửa đổi văn
bản cũ và phải gọi tên chúng, mà kho chỉ chứa văn bản từ cuối 2025 nên không có
bản cũ. Số hiệu đó có thật, nằm ngay trong TOÀN VĂN của văn bản đang phân tích —
mô hình chép lại chứ không bịa. Tham số `extra_allowed` nhận đúng nhóm này: các
số hiệu ĐÃ XUẤT HIỆN trong nguồn mà mô hình được đọc (toàn văn văn bản nguồn +
mẫu prompt). Bên gọi phải dựng nhóm này TỪ NGUỒN, không bao giờ từ chính đầu ra
của mô hình — nếu không cổng tự vô hiệu hoá.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from src.config import DATABASE_URL

# Số hiệu VBQPPL Việt Nam: "112/2025/QH15", "85/2020/NĐ-CP", "95/2026/TT-BTC",
# "23/VBHN-VPQH". Cố ý không bắt dạng chỉ có số ("1468/QĐ-TTg" thì có bắt) để
# tránh nuốt nhầm ngày tháng hoặc số tiền.
_DOC_NUM_RE = re.compile(
    r"\b\d+[/-](?:\d{4}[/-])?[A-ZĐ][A-ZĐ0-9a-z\-]*\b"
)

# Những chuỗi trông giống số hiệu nhưng không phải, hay gặp trong văn bản.
_IGNORE = re.compile(r"^\d+[/-]\d{1,2}$")

#: Ký hiệu của GIẤY TỜ GIAO DỊCH, không phải của văn bản quy phạm pháp luật.
#: "01/HĐ-BHXH-2025" là SỐ HỢP ĐỒNG do hai bên tự đặt, không phải văn bản do cơ
#: quan nhà nước ban hành — không có gì để đối chiếu với kho, và chặn nó là chặn
#: oan. Chuyện này đã xảy ra thật: một bài hướng dẫn điền hợp đồng nêu ví dụ số
#: hợp đồng và bị cổng loại cả bài. Bài hướng dẫn ĐIỀN biểu mẫu thì đương nhiên
#: phải nêu ví dụ cách ghi số — đúng thứ nó tồn tại để dạy.
#:
#: Danh sách này CHỈ gồm ký hiệu không bao giờ là loại VBQPPL. Loại thật thì
#: vẫn phải qua cổng: QH, NĐ-CP, TT-BTC, QĐ-TTg, QĐ-UBND, VBHN-VPQH…
_KY_HIEU_GIAY_TO = (
    "HD",     # HĐ  — hợp đồng
    "PLHD",   # PLHĐ — phụ lục hợp đồng
    "BB",     # BB  — biên bản
    "TB",     # TB  — thông báo nội bộ (không phải TT của bộ)
    "GXN",    # GXN — giấy xác nhận
    "HDLD",   # HĐLĐ — hợp đồng lao động
    "HDKT",   # HĐKT — hợp đồng kinh tế
    "HDMB",   # HĐMB — hợp đồng mua bán
    "DN",     # ĐN  — đề nghị
)


def _la_giay_to_giao_dich(token: str) -> bool:
    """Token là số của một giấy tờ giao dịch chứ không phải số hiệu VBQPPL.

    So trên phần chữ NGAY SAU nhóm số đầu tiên, đã bỏ dấu — "01/HĐ-BHXH-2025"
    cho ra "HD", "15/HĐLĐ/2026" cho ra "HDLD".
    """
    m = re.match(r"^\d+[/-](?:\d{4}[/-])?([A-Za-zĐđ]+)", token)
    if not m:
        return False
    return fold_dau(m.group(1)).upper() in _KY_HIEU_GIAY_TO


@dataclass
class CitationReport:
    found: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.found) + len(self.missing)

    @property
    def ok(self) -> bool:
        return not self.missing

    def summary(self) -> str:
        if not self.total:
            return "Không trích dẫn số hiệu nào"
        if self.ok:
            return f"{self.total}/{self.total} số hiệu có thật"
        return (
            f"{len(self.missing)}/{self.total} số hiệu KHÔNG có trong kho: "
            + ", ".join(self.missing[:5])
            + ("…" if len(self.missing) > 5 else "")
        )


def extract_doc_nums(text: str) -> list[str]:
    """Mọi số hiệu văn bản xuất hiện trong văn bản, đã khử trùng."""
    seen: dict[str, None] = {}
    for raw in _DOC_NUM_RE.findall(text or ""):
        token = raw.strip().rstrip(".,;:")
        if _IGNORE.match(token) or _la_giay_to_giao_dich(token):
            continue
        seen.setdefault(token, None)
    return list(seen)


def _known_doc_nums(db_path: Path | None = None) -> set[str]:
    path = db_path or Path(
        DATABASE_URL.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
    )
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {row[0] for row in conn.execute("SELECT doc_num FROM documents")}
    finally:
        conn.close()


def fold_dau(s: str) -> str:
    """Gỡ dấu tiếng Việt khỏi số hiệu để so khớp.

    Mô hình sinh báo cáo hay đánh rơi dấu Đ: viết "168/2025/ND-CP" thay vì
    "168/2025/NĐ-CP". Đó là lỗi CHÉP, không phải bịa — số hiệu có thật trong kho,
    chỉ khác đúng cái dấu. Không gỡ dấu thì cổng chặn oan cả báo cáo.

    Đ/đ là ký tự riêng (U+0110/U+0111), NFD không tách được nên phải thay tay;
    các dấu tổ hợp khác (á→a…) thì NFD lo. Gỡ dấu KHÔNG gây khớp nhầm: số hiệu
    VBQPPL chỉ gồm chữ số + loại văn bản ASCII, chữ có dấu duy nhất là Đ, mà
    không có loại nào dùng "ND" để lẫn với "NĐ".
    """
    s = s.replace("Đ", "D").replace("đ", "d")
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


#: Tên cũ, giữ lại cho code và test đang import.
_fold_dau = fold_dau


def _norm_key(num: str) -> str:
    """Khoá so khớp: bỏ dấu tiếng Việt, hoa thường, và gộp dấu phân cách — để

    "89-2025-QH15", "89/2025/QH15" và "168/2025/ND-CP" ~ "168/2025/NĐ-CP" coi là
    một, tránh báo động giả.
    """
    return fold_dau(num).lower().replace("-", "/")


def check_citations(
    report_text: str,
    db_path: Path | None = None,
    extra_allowed: set[str] | None = None,
) -> CitationReport:
    """Đối chiếu số hiệu trong báo cáo với kho, cộng thêm nhóm được nguồn bảo chứng.

    `extra_allowed`: số hiệu có căn cứ trong NGUỒN mô hình đã đọc (toàn văn văn
    bản nguồn, mẫu prompt) nhưng chưa có bản ghi đầy đủ trong kho — điển hình là
    văn bản cũ bị bãi bỏ/sửa đổi. Chúng KHÔNG phải số bịa nên không được chặn.
    Bên gọi có trách nhiệm dựng nhóm này từ nguồn, không từ đầu ra mô hình.
    """
    normalized = {_norm_key(k): k for k in _known_doc_nums(db_path)}
    for k in (extra_allowed or ()):
        normalized.setdefault(_norm_key(k), k)

    result = CitationReport()
    for num in extract_doc_nums(report_text):
        if _norm_key(num) in normalized:
            result.found.append(num)
        else:
            result.missing.append(num)
    return result
