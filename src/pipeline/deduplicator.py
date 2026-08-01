"""
Deduplicator — normalizes doc_num and matches documents across sources.

Cross-source matching uses normalized doc_num as the primary key.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from src.config import BUSINESS_FIELDS


# Số hiệu văn bản Việt Nam, ví dụ:
#   292/2026/NĐ-CP · 41/2026/TT-BCT · 1889/QĐ-BCT · 23/2026/VBHN-TT-BTC
# Cấu trúc: <số>[chữ cái]/[<năm>/]<ký hiệu bắt đầu bằng chữ cái>[-<ký hiệu>…]
# Bắt buộc đoạn cuối phải bắt đầu bằng chữ cái để không nuốt nhầm ngày (22/07/2026).
_DOC_NUM_RE = re.compile(
    r"\b("
    # Dạng phổ biến: 292/2026/NĐ-CP, 1889/QĐ-BCT
    r"\d{1,6}[A-Za-zĐđ]{0,3}"
    r"/(?:\d{4}/)?"
    r"[A-Za-zĐđÀ-ỹ][A-Za-zĐđÀ-ỹ0-9]*"
    r"(?:[-–][A-Za-zĐđÀ-ỹ0-9.]+)*"
    r"|"
    # Dạng văn bản Đảng: 123-TB/VPTW, 16-NQ/TW
    r"\d{1,6}-[A-Za-zĐđÀ-ỹ][A-Za-zĐđÀ-ỹ0-9]*"
    r"/[A-Za-zĐđÀ-ỹ][A-Za-zĐđÀ-ỹ0-9.\-]*"
    r")"
)


def extract_doc_num(title: str) -> str:
    """
    Tách số hiệu văn bản ra khỏi tiêu đề TVPL.

    TVPL đặt tiêu đề dạng "<Loại VB> <số hiệu> <trích yếu>", nên số hiệu luôn là
    cụm đầu tiên khớp mẫu. Lấy cụm đầu tiên để tránh bắt nhầm số hiệu của văn bản
    được dẫn chiếu trong trích yếu.

    Examples:
        'Nghị định 292/2026/NĐ-CP hướng dẫn Luật…'   → '292/2026/NĐ-CP'
        'Quyết định 1889/QĐ-BCT về Chương trình…'    → '1889/QĐ-BCT'
        'Circular No. 41/2026/TT-BCT dated July 22…' → '41/2026/TT-BCT'
        'Luật Doanh nghiệp 2020'                     → ''  (không có số hiệu)
    """
    if not title:
        return ""
    match = _DOC_NUM_RE.search(title)
    return match.group(1).strip() if match else ""


def normalize_doc_num(raw: str) -> str:
    """
    Normalize a Vietnamese legal document number for matching.

    Examples:
        '12/2026/NĐ-CP'  →  '12/2026/ND-CP'
        ' 12/2026/NĐ-CP ' →  '12/2026/ND-CP'
        '12/2026/ND-CP'   →  '12/2026/ND-CP'
    """
    if not raw:
        return ""

    s = raw.strip()

    # Remove Vietnamese diacritical marks but keep base characters
    # NĐ → ND, etc.
    nfkd = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in nfkd if not unicodedata.combining(c))

    # Uppercase for consistent matching
    s = s.upper()

    # Normalize whitespace
    s = re.sub(r"\s+", " ", s).strip()

    # Remove extra spaces around slashes and dashes
    s = re.sub(r"\s*/\s*", "/", s)
    s = re.sub(r"\s*-\s*", "-", s)

    return s


def merge_triggers(
    tvpl_items: list[dict[str, Any]],
    moj_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Merge document triggers from TVPL and MOJ into unified candidates.

    Uses normalized doc_num as the merge key. When both sources have the
    same document, fields from MOJ take priority for structured data,
    while TVPL provides the tvpl_url and tvpl_id.

    Returns a list of merged dicts ready for upsert_document().
    """
    # Index MOJ items by normalized doc_num
    moj_index: dict[str, dict] = {}
    for item in moj_items:
        key = normalize_doc_num(item.get("doc_num", ""))
        if key:
            moj_index[key] = item

    merged: dict[str, dict] = {}

    # Process TVPL items first
    for tvpl_item in tvpl_items:
        # TVPL RSS title = "<Loại VB> <số hiệu> <trích yếu>" → tách lấy số hiệu.
        # Văn bản không có số hiệu (vd. "Luật Doanh nghiệp 2020") dùng nguyên
        # tiêu đề làm khoá để vẫn theo dõi được, thay vì bị bỏ qua.
        title = (tvpl_item.get("title", "") or "").strip()
        raw_num = extract_doc_num(title) or title
        key = normalize_doc_num(raw_num)
        if not key:
            continue

        field_code = tvpl_item.get("field_code")
        entry = {
            "doc_num": raw_num,
            "title": title,  # Will be enriched by MOJ
            "source_tvpl": True,
            "tvpl_id": tvpl_item.get("tvpl_id"),
            "tvpl_url": tvpl_item.get("tvpl_url"),
            "field_code": field_code,
            "pub_date": tvpl_item.get("pub_date"),
            # Tên lĩnh vực suy từ slug URL — quyết định thư mục lưu trên Drive,
            # nên phải có sẵn kể cả khi văn bản không khớp được với Bộ Tư pháp.
            "field_name": BUSINESS_FIELDS.get(field_code) if field_code else None,
        }

        # If MOJ also has this document, merge
        if key in moj_index:
            moj_data = moj_index.pop(key)
            entry.update({
                "doc_num": moj_data.get("doc_num") or entry["doc_num"],
                "title": moj_data.get("title") or entry["title"],
                "doc_type": moj_data.get("doc_type"),
                "issue_date": moj_data.get("issue_date"),
                "eff_from": moj_data.get("eff_from"),
                "eff_to": moj_data.get("eff_to"),
                "eff_status": moj_data.get("eff_status"),
                "agency_name": moj_data.get("agency_name"),
                "signer": moj_data.get("signer"),
                # API danh sách MOJ không có lĩnh vực nên luôn trả "Khác" —
                # không để nó ghi đè lĩnh vực suy từ slug TVPL.
                "field_name": moj_data.get("field_name")
                if moj_data.get("field_code")
                else entry["field_name"] or moj_data.get("field_name"),
                "field_code": moj_data.get("field_code") or entry["field_code"],
                "source_moj": True,
                "moj_id": moj_data.get("moj_id"),
            })

        merged[key] = entry

    # Add remaining MOJ-only items.
    # Danh sách MOJ được quét không lọc lĩnh vực (API danh sách không trả lĩnh
    # vực), nên ở đây phải lọc thô theo tiêu đề — nếu không sẽ nạp toàn bộ văn
    # bản cả nước. Lĩnh vực thật được xác nhận lại sau khi lấy chi tiết.
    from src.sources.moj_api import title_looks_business

    for key, moj_data in moj_index.items():
        if key not in merged and title_looks_business(moj_data):
            moj_data["_needs_field_check"] = True
            merged[key] = moj_data

    return list(merged.values())
