"""
Đối chiếu mọi số hiệu văn bản trong báo cáo với kho dữ liệu.

Prompt cấm bịa số hiệu, nhưng cấm không phải là bảo đảm. Báo cáo gửi ra ngoài
cho doanh nghiệp mà trích dẫn một văn bản không tồn tại thì hỏng cả uy tín, nên
mỗi bản phải qua bước đối chiếu máy móc này trước khi xuất PDF.
"""
from __future__ import annotations

import re
import sqlite3
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
        if _IGNORE.match(token):
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


def check_citations(report_text: str, db_path: Path | None = None) -> CitationReport:
    """Đối chiếu số hiệu trong báo cáo với bảng documents."""
    known = _known_doc_nums(db_path)
    # So khớp không phân biệt hoa thường và dấu phân cách để không báo động giả
    # với "89-2025-QH15" so với "89/2025/QH15".
    normalized = {k.lower().replace("-", "/"): k for k in known}

    result = CitationReport()
    for num in extract_doc_nums(report_text):
        if num.lower().replace("-", "/") in normalized:
            result.found.append(num)
        else:
            result.missing.append(num)
    return result
