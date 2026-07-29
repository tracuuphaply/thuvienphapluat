"""
MOJ (Bộ Tư pháp) API client.

Endpoints (verified 2026-07-23):
  - POST /api/qtdc/public/doc/all  → document list with pagination
  - GET  /api/qtdc/public/doc/{id} → full document detail

Sort by issueDate desc for stable pagination. Dedupe by `id`.
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any

import httpx

from src.config import (
    BUSINESS_FIELD_CODES,
    BUSINESS_FIELDS,
    MOJ_BASE_URL,
    MOJ_PAGE_SIZE,
    MOJ_RATE_LIMIT_SECONDS,
    MOJ_WINDOW_DAYS,
)

logger = logging.getLogger(__name__)

# Persistent HTTP client with reasonable timeouts
_client = httpx.Client(
    base_url=MOJ_BASE_URL,
    timeout=httpx.Timeout(30.0, connect=10.0),
    headers={"Content-Type": "application/json", "Accept": "application/json"},
)


def fetch_doc_list(page: int = 1, page_size: int = MOJ_PAGE_SIZE) -> dict[str, Any]:
    """
    Fetch a page of documents from MOJ.
    POST /doc/all with sortBy=issueDate desc.
    """
    payload = {
        "pageSize": page_size,
        "pageNumber": page,
        "sortDirection": "desc",
        "sortBy": "issueDate",
    }
    resp = _client.post("/doc/all", json=payload)
    resp.raise_for_status()
    return resp.json()


def fetch_doc_detail(doc_id: str) -> dict[str, Any]:
    """
    Fetch full detail for a single document.
    GET /doc/{id} → fulltext HTML, references, effStatus, signer.
    """
    resp = _client.get(f"/doc/{doc_id}")
    resp.raise_for_status()
    return resp.json()


def _extract_field_codes(doc: dict) -> set[int]:
    """
    Extract field codes from a MOJ document response.
    Checks documentFields and documentMajors arrays.
    """
    codes: set[int] = set()
    for field_obj in doc.get("documentFields", []):
        fid = field_obj.get("id")
        if fid is not None:
            codes.add(int(fid))
    for major_obj in doc.get("documentMajors", []):
        mid = major_obj.get("id")
        if mid is not None:
            codes.add(int(mid))
    return codes


def is_business_document(doc: dict) -> bool:
    """Check if a document belongs to any business-related field."""
    doc_codes = _extract_field_codes(doc)
    return bool(doc_codes & BUSINESS_FIELD_CODES)


def get_field_name(doc: dict) -> str:
    """Get the primary business field name for a document."""
    doc_codes = _extract_field_codes(doc)
    matching = doc_codes & BUSINESS_FIELD_CODES
    if matching:
        code = min(matching)  # Pick the primary (lowest code)
        return BUSINESS_FIELDS.get(code, "Khác")
    return "Khác"


def parse_doc_summary(doc: dict) -> dict[str, Any]:
    """
    Parse a document from the list API into a normalized dict
    suitable for upsert_document().
    """
    data = doc.get("data", doc)  # Handle nested response format

    doc_type_obj = data.get("docType", {}) or {}
    eff_status_obj = data.get("effStatus", {}) or {}
    org_obj = data.get("organization", {}) or {}

    return {
        "doc_num": (data.get("docNum") or "").strip(),
        "title": (data.get("title") or "").strip(),
        "doc_type": doc_type_obj.get("name", ""),
        "issue_date": _parse_date(data.get("issueDate")),
        "eff_from": _parse_date(data.get("effFrom")),
        "eff_to": _parse_date(data.get("effTo")),
        "eff_status": eff_status_obj.get("name", ""),
        "agency_name": org_obj.get("name", "") or data.get("agencyName", ""),
        "signer": data.get("signer", ""),
        "field_name": get_field_name(data),
        "field_code": _get_primary_field_code(data),
        "source_moj": True,
        "moj_id": str(data.get("id", "")),
    }


def parse_doc_detail(detail_resp: dict) -> dict[str, Any]:
    """
    Parse full document detail including references and content.
    """
    data = detail_resp.get("data", detail_resp)
    summary = parse_doc_summary(data)

    # Extract references for the relationship graph
    references = []
    for ref in data.get("references", []):
        ref_data = ref if isinstance(ref, dict) else {}
        target_num = (ref_data.get("docNum") or ref_data.get("refDocNum") or "").strip()
        rel_type = (ref_data.get("type") or ref_data.get("relationType") or "Liên quan").strip()
        if target_num:
            references.append({
                "target_doc_num": target_num,
                "relation_type": rel_type,
            })

    # Extract full text content (HTML)
    fulltext_html = data.get("documentContent", "") or data.get("content", "")

    summary["references"] = references
    summary["fulltext_html"] = fulltext_html
    return summary


def scan_incremental(window_days: int = MOJ_WINDOW_DAYS) -> list[dict[str, Any]]:
    """
    Scan MOJ for business documents within a sliding window.
    Returns list of parsed document summaries (already filtered for business fields).

    Uses issueDate sorting + dedupe by id to handle unstable pagination.
    """
    cutoff = date.today() - timedelta(days=window_days)
    seen_ids: set[str] = set()
    results: list[dict[str, Any]] = []
    page = 1

    logger.info(
        "MOJ scan started: window=%d days, cutoff=%s", window_days, cutoff
    )

    while True:
        try:
            resp_json = fetch_doc_list(page=page)
        except httpx.HTTPStatusError as e:
            logger.error("MOJ API error on page %d: %s", page, e)
            break

        # Handle response format: { "data": [...], "totalItems": N }
        data = resp_json.get("data", [])
        if isinstance(data, dict):
            data = data.get("data", [])  # nested data key
        if not data:
            logger.info("MOJ scan: no more data at page %d", page)
            break

        past_window = False
        for doc in data:
            doc_data = doc.get("data", doc) if isinstance(doc, dict) else doc
            doc_id = str(doc_data.get("id", ""))

            # Dedupe
            if doc_id in seen_ids:
                continue
            seen_ids.add(doc_id)

            # Check if issue date is within window
            issue_date = _parse_date(doc_data.get("issueDate"))
            if issue_date and issue_date < cutoff:
                past_window = True
                continue

            # Filter for business fields
            if not is_business_document(doc_data):
                continue

            parsed = parse_doc_summary(doc_data)
            if parsed["doc_num"]:
                results.append(parsed)

        if past_window:
            logger.info(
                "MOJ scan: reached cutoff date at page %d, stopping", page
            )
            break

        page += 1
        time.sleep(MOJ_RATE_LIMIT_SECONDS)

    logger.info("MOJ scan complete: %d business documents found", len(results))
    return results


def _parse_date(value: Any) -> date | None:
    """Parse various date formats from MOJ API."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    s = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return date.fromisoformat(s[:10]) if "T" in s else __import__("datetime").datetime.strptime(s, fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def _get_primary_field_code(doc: dict) -> int | None:
    """Get the primary business field code."""
    codes = _extract_field_codes(doc) & BUSINESS_FIELD_CODES
    return min(codes) if codes else None


# ──────────────────────────────────────────────
# CLI entry point for testing
# ──────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=== MOJ API Test: Fetching business documents (30-day window) ===\n")
    docs = scan_incremental(window_days=7)  # Short window for testing
    for i, doc in enumerate(docs[:10], 1):
        print(f"{i}. [{doc['doc_type']}] {doc['doc_num']}")
        print(f"   {doc['title'][:80]}...")
        print(f"   Ngày: {doc['issue_date']} | Hiệu lực: {doc['eff_status']}")
        print(f"   Lĩnh vực: {doc['field_name']} | MOJ ID: {doc['moj_id']}")
        print()
    print(f"Tổng: {len(docs)} văn bản doanh nghiệp")
