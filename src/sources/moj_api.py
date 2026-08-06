"""
MOJ (Bộ Tư pháp) API client.

Endpoints (verified 2026-07-23):
  - POST /api/qtdc/public/doc/all  → document list with pagination
  - GET  /api/qtdc/public/doc/{id} → full document detail

Sort by issueDate desc for stable pagination. Dedupe by `id`.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, timedelta
from typing import Any

import httpx

from src.config import (
    BUSINESS_FIELD_CODES,
    BUSINESS_FIELDS,
    MOJ_BASE_URL,
    MOJ_FIELD_KEYWORDS,
    MOJ_MAX_PAGES,
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


def fetch_doc_list(
    page: int = 1,
    page_size: int = MOJ_PAGE_SIZE,
    keyword: str = "",
) -> dict[str, Any]:
    """
    Fetch a page of documents from MOJ.
    POST /doc/all with sortBy=issueDate desc.

    `keyword` filters server-side (khớp số hiệu hoặc tiêu đề) — dùng để tra cứu
    trực tiếp một văn bản thay vì phải duyệt hết danh sách.
    """
    payload: dict[str, Any] = {
        "pageSize": page_size,
        "pageNumber": page,
        "sortDirection": "desc",
        "sortBy": "issueDate",
    }
    if keyword:
        payload["keyword"] = keyword
    resp = _client.post("/doc/all", json=payload)
    resp.raise_for_status()
    return resp.json()


def _extract_items(resp_json: dict) -> list[dict]:
    """
    Lấy danh sách văn bản từ response của /doc/all.

    Gateway vbpl-bientap trả về {"data": {"total": N, "items": [...]}}; các bản
    cũ hơn trả thẳng {"data": [...]}. Hỗ trợ cả hai để không phụ thuộc phiên bản.
    """
    data = resp_json.get("data", [])
    if isinstance(data, dict):
        return data.get("items") or data.get("data") or []
    return data or []


def fetch_doc_detail(doc_id: str) -> dict[str, Any]:
    """
    Fetch full detail for a single document.
    GET /doc/{id} → fulltext HTML, references, effStatus, signer.
    """
    resp = _client.get(f"/doc/{doc_id}")
    resp.raise_for_status()
    return resp.json()


def _extract_field_names(doc: dict) -> list[str]:
    """
    Lấy tên các lĩnh vực của một văn bản MOJ.

    Gateway vbpl-bientap trả documentFields/documentMajors với `id` là UUID và
    `name` là tên lĩnh vực tiếng Việt, nên phải khớp theo tên chứ không theo mã.
    Lưu ý: hai mảng này chỉ có ở API chi tiết (/doc/{id}), API danh sách trả null.
    """
    names: list[str] = []
    for key in ("documentFields", "documentMajors"):
        for obj in doc.get(key) or []:
            if isinstance(obj, dict) and obj.get("name"):
                names.append(str(obj["name"]))
    return names


def _extract_field_codes(doc: dict) -> set[int]:
    """Ánh xạ tên lĩnh vực MOJ → mã lĩnh vực doanh nghiệp (BUSINESS_FIELDS)."""
    codes: set[int] = set()
    for name in _extract_field_names(doc):
        lowered = name.lower()
        for keyword, code in MOJ_FIELD_KEYWORDS.items():
            if keyword in lowered:
                codes.add(code)
    return codes


def is_business_document(doc: dict) -> bool:
    """
    Kiểm tra văn bản có thuộc lĩnh vực doanh nghiệp không.

    Chỉ dựa trên lĩnh vực khai báo; nếu văn bản không có thông tin lĩnh vực
    (API danh sách) thì trả False — việc lọc lúc đó do TVPL đảm nhiệm.
    """
    return bool(_extract_field_codes(doc) & BUSINESS_FIELD_CODES)


def title_looks_business(doc: dict) -> bool:
    """
    Tiền lọc rẻ tiền cho văn bản chỉ xuất hiện ở MOJ.

    API danh sách không trả lĩnh vực, mà gọi API chi tiết cho cả nghìn văn bản
    mỗi ngày thì quá tốn. Vì vậy lọc thô theo từ khoá trong tiêu đề trước, rồi
    mới xác nhận bằng lĩnh vực thật ở bước bổ sung chi tiết.
    """
    haystack = " ".join(
        str(doc.get(key) or "") for key in ("title", "doc_num", "docNum", "agency_name")
    ).lower()
    return any(keyword in haystack for keyword in MOJ_FIELD_KEYWORDS)


def get_field_name(doc: dict) -> str:
    """Get the primary business field name for a document."""
    doc_codes = _extract_field_codes(doc)
    matching = doc_codes & BUSINESS_FIELD_CODES
    if matching:
        code = min(matching)  # Pick the primary (lowest code)
        return BUSINESS_FIELDS.get(code, "Khác")
    # Không khớp lĩnh vực doanh nghiệp → giữ nguyên tên lĩnh vực gốc của MOJ
    names = _extract_field_names(doc)
    return names[0] if names else "Khác"


def _resolve_agency(doc_num: str, reported: str) -> str:
    """Cơ quan ban hành cuối cùng: hậu tố số hiệu thắng khi mâu thuẫn với nguồn."""
    derived = agency_from_doc_num(doc_num)
    if not derived:
        return reported
    if reported and reported != derived:
        logger.info(
            "Cơ quan ban hành của %s: nguồn ghi %r, suy từ số hiệu là %r — dùng %r",
            doc_num, reported, derived, derived,
        )
    return derived


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
        # `agencyName` là CƠ QUAN BAN HÀNH; `organization.name` chỉ là đơn vị
        # quản lý bản ghi trên hệ thống Bộ Tư pháp. Ưu tiên nhầm thứ tự khiến
        # mọi đạo Luật bị ghi là do một Bộ ban hành thay vì Quốc hội, và mọi
        # Nghị định do Bộ thay vì Chính phủ — sai dữ kiện pháp lý ngay ở bảng
        # kiểm hiệu lực của báo cáo. Với văn bản cấp tỉnh, `agencyName` còn cụ
        # thể hơn ("UBND Tỉnh Quảng Ngãi" so với chỉ "Quảng Ngãi").
        "agency_name": _resolve_agency(
            (data.get("docNum") or "").strip(),
            (data.get("agencyName") or "").strip() or org_obj.get("name", ""),
        ),
        "signer": data.get("signer", ""),
        "field_name": get_field_name(data),
        "field_code": _get_primary_field_code(data),
        "source_moj": True,
        "moj_id": str(data.get("id", "")),
    }


# referenceType của gateway vbpl-bientap → nhãn quan hệ tiếng Việt.
#
# Bảng cũ được đặt bằng suy đoán và đã gán sai nghiêm trọng: mã 3 (chiếm 82%
# tổng số cạnh) thực chất là "Căn cứ" nhưng bị ghi thành "Bãi bỏ", khiến hàng
# trăm văn bản cấp tỉnh trông như đang bãi bỏ luật Quốc hội.
#
# Bảng hiện tại được suy ra từ hai tín hiệu độc lập (scripts/probe_reference_types.py):
#   (a) động từ quan hệ đứng ngay trước số hiệu đích trong toàn văn văn bản nguồn
#   (b) tỷ lệ văn bản đích đã có effTo — quan hệ chấm dứt hiệu lực thì đích phải hết hiệu lực
#
#   mã 1  : (a) "bãi bỏ" 44% + "hết hiệu lực" 7%, n=174   (b) 66% đích hết hiệu lực
#   mã 3  : (a) "căn cứ" 84%, n=1188                      (b)  5% đích hết hiệu lực
#   mã 9  : (a) "căn cứ" 83%, n=41                        (b)  9% đích hết hiệu lực
#   mã 10 : (a) "sửa đổi, bổ sung" 95%, n=284             (b)  0% đích hết hiệu lực
#   mã 12 : (a) "thay thế" 75%, n=65                      (b) 95% đích hết hiệu lực
#
# Các mã 4, 5, 7, 8, 11 chưa đủ mẫu (n ≤ 11) nên KHÔNG đoán — chúng nhận nhãn
# "Chưa xác định" để lộ ra là chưa biết, thay vì bị gán nhầm một quan hệ có thật.
# Chạy lại script dò khi kho văn bản lớn hơn để chốt nốt các mã này.
REFERENCE_TYPE_LABELS: dict[int, str] = {
    1: "Bãi bỏ",
    3: "Căn cứ",
    9: "Căn cứ",
    10: "Sửa đổi, bổ sung",
    12: "Thay thế",
}

# Nhãn dùng khi gateway trả về mã chưa được kiểm chứng. Giữ lại mã gốc để dò tiếp.
UNVERIFIED_RELATION = "Chưa xác định"


def relation_label(reference_type: Any) -> str:
    """Nhãn quan hệ cho một referenceType; mã lạ trả về nhãn 'chưa xác định'."""
    if reference_type in REFERENCE_TYPE_LABELS:
        return REFERENCE_TYPE_LABELS[reference_type]
    return f"{UNVERIFIED_RELATION} (mã {reference_type})"


# Số hiệu văn bản QPPL mã hoá sẵn cơ quan ban hành, và đây là quy tắc pháp lý
# chứ không phải quy ước dữ liệu: Luật luôn do Quốc hội ban hành, Nghị định luôn
# do Chính phủ. Dữ liệu Bộ Tư pháp có chỗ ghi sai (Luật Xây dựng 135/2025/QH15
# bị ghi do "Bộ Xây dựng" ban hành), nên khi số hiệu và trường agencyName mâu
# thuẫn thì số hiệu thắng.
_AGENCY_BY_SUFFIX: tuple[tuple[re.Pattern[str], str], ...] = (
    # "28/2005/PL-UBTVQH11" (pháp lệnh) và "01/2018/UBTVQH14" đều là UBTVQH.
    (re.compile(r"/(PL-)?UBTVQH\d*\s*$", re.I), "Ủy ban Thường vụ Quốc hội"),
    (re.compile(r"/QH\d*\s*$", re.I), "Quốc hội"),
    (re.compile(r"/NĐ-CP\s*$", re.I), "Chính phủ"),
    (re.compile(r"/(QĐ|CT)-TTg\s*$", re.I), "Thủ tướng Chính phủ"),
)


def agency_from_doc_num(doc_num: str) -> str:
    """Cơ quan ban hành suy từ hậu tố số hiệu; rỗng nếu hậu tố không xác định."""
    text = (doc_num or "").strip()
    for pattern, agency in _AGENCY_BY_SUFFIX:
        if pattern.search(text):
            return agency
    return ""


def parse_doc_detail(detail_resp: dict) -> dict[str, Any]:
    """
    Parse full document detail including references and content.
    """
    data = detail_resp.get("data", detail_resp)
    summary = parse_doc_summary(data)

    # Extract references for the relationship graph.
    # Gateway trả {"targetDocument": {...}, "referenceType": <int>}; bản cũ trả
    # thẳng docNum/relationType nên hỗ trợ cả hai dạng.
    references = []
    for ref in data.get("references") or []:
        if not isinstance(ref, dict):
            continue
        target = ref.get("targetDocument") or {}
        target_num = (
            (target.get("docNum") if isinstance(target, dict) else "")
            or ref.get("docNum")
            or ref.get("refDocNum")
            or ""
        ).strip()
        rel_type = ref.get("type") or ref.get("relationType")
        if not rel_type:
            rel_type = relation_label(ref.get("referenceType"))
        if target_num:
            references.append({
                "target_doc_num": target_num,
                "relation_type": str(rel_type).strip(),
            })

    # Extract full text content (HTML) — gateway lồng trong documentContent.content
    content = data.get("documentContent")
    if isinstance(content, dict):
        fulltext_html = content.get("content") or ""
    else:
        fulltext_html = content or data.get("content") or ""

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

    while page <= MOJ_MAX_PAGES:
        try:
            resp_json = fetch_doc_list(page=page)
        except httpx.HTTPStatusError as e:
            logger.error("MOJ API error on page %d: %s", page, e)
            break

        data = _extract_items(resp_json)
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

            # API danh sách không trả lĩnh vực, nên KHÔNG lọc theo lĩnh vực ở đây.
            # Toàn bộ văn bản trong cửa sổ được giữ lại làm chỉ mục để đối chiếu
            # với TVPL (bước merge); việc lọc lĩnh vực cho văn bản chỉ-có-ở-MOJ
            # do merge_triggers đảm nhiệm sau khi đã bổ sung chi tiết.
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
    else:
        logger.warning(
            "MOJ scan: hit page cap (%d pages), window may be incomplete",
            MOJ_MAX_PAGES,
        )

    logger.info("MOJ scan complete: %d documents in %d-day window", len(results), window_days)
    return results


def _title_overlap(a: str, b: str) -> float:
    """Tỷ lệ từ chung giữa hai tiêu đề (0–1), dùng để chọn đúng văn bản."""
    tokens_a = {w for w in re.findall(r"\w+", a.lower()) if len(w) > 2}
    tokens_b = {w for w in re.findall(r"\w+", b.lower()) if len(w) > 2}
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / min(len(tokens_a), len(tokens_b))


def search_by_doc_num(doc_num: str, title_hint: str = "") -> dict[str, Any] | None:
    """
    Tra cứu một văn bản trên MOJ theo số hiệu.

    Dùng để bổ sung dữ liệu Bộ Tư pháp cho văn bản phát hiện từ TVPL nhưng nằm
    ngoài cửa sổ quét.

    Số hiệu cấp tỉnh trùng nhau giữa các địa phương ('40/2026/QĐ-UBND' có 31 văn
    bản khác nhau), nên khi có nhiều ứng viên thì dùng `title_hint` (tiêu đề từ
    TVPL) để chọn: bản khớp nhất phải vượt ngưỡng và phải cách biệt rõ so với
    bản nhì, nếu không thì bỏ qua còn hơn gán nhầm văn bản của tỉnh khác.

    CẢNH BÁO — hàm này hiện gần như luôn trả None. Endpoint /doc/all **bỏ qua
    mọi tham số lọc**: đã thử keyword, docNum, searchText, q, filter, text,
    soHieu — tất cả đều trả về đúng danh sách mặc định sắp theo issueDate desc.
    Vì vậy văn bản chỉ được tìm thấy khi tình cờ nằm trong 50 bản mới nhất.

    Muốn lấy một văn bản cụ thể, hãy dùng `targetDocument.id` có sẵn trong
    payload quan hệ rồi gọi `fetch_doc_detail(id)` — xem
    scripts/backfill_cited_documents.py.
    """
    from src.pipeline.deduplicator import normalize_doc_num

    if not doc_num:
        return None

    try:
        resp_json = fetch_doc_list(page=1, page_size=50, keyword=doc_num)
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        logger.warning("MOJ lookup failed for %s: %s", doc_num, e)
        return None

    target = normalize_doc_num(doc_num)
    matches = [
        item
        for item in _extract_items(resp_json)
        if normalize_doc_num(str(item.get("docNum") or "")) == target
    ]

    if not matches:
        return None
    if len(matches) == 1:
        return parse_doc_summary(matches[0])

    if not title_hint:
        logger.info(
            "MOJ lookup ambiguous for %s (%d matches, không có tiêu đề đối chiếu)",
            doc_num, len(matches),
        )
        return None

    scored = sorted(
        (
            (
                _title_overlap(
                    title_hint,
                    f"{item.get('title', '')} {item.get('agencyName', '')}",
                ),
                item,
            )
            for item in matches
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )
    best_score, best = scored[0]
    runner_up = scored[1][0]

    if best_score >= 0.45 and best_score - runner_up >= 0.15:
        logger.info(
            "MOJ lookup %s: chọn bản của '%s' (khớp %.0f%% so với %.0f%%)",
            doc_num, best.get("agencyName", "?"), best_score * 100, runner_up * 100,
        )
        return parse_doc_summary(best)

    logger.info(
        "MOJ lookup ambiguous for %s (%d matches, khớp cao nhất %.0f%% chưa đủ rõ)",
        doc_num, len(matches), best_score * 100,
    )
    return None


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
