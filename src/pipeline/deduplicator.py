"""
Deduplicator — normalizes doc_num and matches documents across sources.

Cross-source matching uses normalized doc_num as the primary key.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any


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
        # TVPL RSS title is typically the doc number
        raw_num = tvpl_item.get("title", "")
        key = normalize_doc_num(raw_num)
        if not key:
            continue

        entry = {
            "doc_num": raw_num.strip(),
            "title": raw_num.strip(),  # Will be enriched by MOJ
            "source_tvpl": True,
            "tvpl_id": tvpl_item.get("tvpl_id"),
            "tvpl_url": tvpl_item.get("tvpl_url"),
            "field_code": tvpl_item.get("field_code"),
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
                "field_name": moj_data.get("field_name"),
                "field_code": moj_data.get("field_code") or entry["field_code"],
                "source_moj": True,
                "moj_id": moj_data.get("moj_id"),
            })

        merged[key] = entry

    # Add remaining MOJ-only items
    for key, moj_data in moj_index.items():
        if key not in merged:
            merged[key] = moj_data

    return list(merged.values())
