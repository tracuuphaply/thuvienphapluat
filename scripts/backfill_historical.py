"""
Bổ sung văn bản lịch sử bằng cách phân trang lùi theo thời gian.

`scan_incremental` chỉ quét cửa sổ MOJ_WINDOW_DAYS gần nhất nên kho không bao
giờ có văn bản cũ hơn. Endpoint /doc/all lại phân trang được rất sâu và sắp theo
issueDate desc — trang 100 đã về tháng 1/2026, trang 200 về tháng 8/2025 — nên
chỉ cần lật trang cho tới khi chạm mốc thời gian mong muốn.

Prompt báo cáo yêu cầu "văn bản ban hành/có hiệu lực trong 24 tháng gần nhất",
nên mặc định lùi 24 tháng.

Chạy:
    python -m scripts.backfill_historical --dry-run
    python -m scripts.backfill_historical --until 2024-08-01
    python -m scripts.backfill_historical --until 2025-01-01 --max-pages 300
"""
import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta

from src.pipeline.text_processor import process_fulltext
from src.sources.moj_api import (
    _extract_items,
    _get_primary_field_code,
    fetch_doc_detail,
    fetch_doc_list,
    parse_doc_detail,
    parse_doc_summary,
    title_looks_business,
)
from src.storage.database import (
    get_session,
    insert_references,
    resolve_reference_targets,
    upsert_document,
)
from src.storage.file_store import save_document_metadata, save_moj_fulltext

logger = logging.getLogger(__name__)

_SKIP_KEYS = {"references", "fulltext_html"}


def _issue_date(item: dict) -> date | None:
    raw = str(item.get("issueDate") or "")[:10]
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def collect_candidates(until: date, max_pages: int, sleep: float) -> list[dict]:
    """Lật trang lùi dần cho tới khi vượt mốc `until`, giữ lại văn bản doanh nghiệp."""
    seen_ids: set[str] = set()
    candidates: list[dict] = []
    page = 1

    while page <= max_pages:
        try:
            items = _extract_items(fetch_doc_list(page=page, page_size=50))
        except Exception as e:
            logger.warning("trang %d lỗi %s — dừng", page, type(e).__name__)
            break
        if not items:
            logger.info("trang %d rỗng — hết dữ liệu", page)
            break

        dates = [d for d in (_issue_date(i) for i in items) if d]
        oldest = min(dates) if dates else None

        for item in items:
            doc_id = str(item.get("id") or "")
            if not doc_id or doc_id in seen_ids:
                continue
            seen_ids.add(doc_id)
            d = _issue_date(item)
            if d and d < until:
                continue
            # Lọc thô theo tiêu đề ở đây; lĩnh vực thật chỉ có ở API chi tiết
            # nên còn một vòng xác nhận nữa khi tải chi tiết.
            if title_looks_business(item):
                candidates.append(item)

        if page % 20 == 0 or page == 1:
            logger.info(
                "  trang %d | cũ nhất %s | đã chọn %d/%d",
                page, oldest, len(candidates), len(seen_ids),
            )
        if oldest and oldest < until:
            logger.info("trang %d đã vượt mốc %s — dừng", page, until)
            break
        page += 1
        time.sleep(sleep)

    return candidates


def ingest(item: dict, sleep: float) -> str:
    moj_id = str(item.get("id") or "")
    if not moj_id:
        return "thieu_id"

    detail = parse_doc_detail(fetch_doc_detail(moj_id))
    # Xác nhận lĩnh vực bằng dữ liệu chi tiết: lọc theo tiêu đề khớp cả
    # "chi phí", "học phí" nên phải kiểm lại bằng field_code thật.
    if not detail.get("field_code"):
        return "ngoai_linh_vuc"

    doc_data = {k: v for k, v in detail.items() if k not in _SKIP_KEYS and v not in (None, "")}
    doc_data.update(source_moj=True, moj_id=moj_id)
    doc_data.setdefault("doc_num", str(item.get("docNum") or "").strip())
    doc_data.setdefault("title", doc_data["doc_num"])
    if not doc_data["doc_num"]:
        return "thieu_so_hieu"

    fulltext = detail.get("fulltext_html", "")
    if fulltext:
        doc_data["fulltext_path"] = save_moj_fulltext(moj_id, fulltext)
        doc_data["has_fulltext"] = True
        processed = process_fulltext(
            doc_id=moj_id, html_content=fulltext, doc_num=doc_data["doc_num"]
        )
        if processed.get("clean_text_path"):
            doc_data["clean_text_path"] = processed["clean_text_path"]
            doc_data["chunks_path"] = processed["chunks_path"]
            doc_data["has_chunks"] = processed["chunk_count"] > 0

    with get_session() as session:
        doc, is_new = upsert_document(session, doc_data)
        session.flush()
        if detail.get("references"):
            insert_references(session, doc.id, detail["references"])
        session.commit()
        save_document_metadata({**doc_data, "id": doc.id})

    return "them_moi" if is_new else "cap_nhat"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", type=str, default="",
                    help="lùi tới ngày ban hành này (YYYY-MM-DD); mặc định 24 tháng")
    ap.add_argument("--max-pages", type=int, default=500)
    ap.add_argument("--limit", type=int, default=0, help="giới hạn số văn bản nạp")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.25)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    until = (
        date.fromisoformat(args.until) if args.until
        else date.today() - timedelta(days=730)
    )
    logger.info("Lùi tới ngày ban hành %s, tối đa %d trang", until, args.max_pages)

    candidates = collect_candidates(until, args.max_pages, args.sleep)
    print(f"\nTìm được {len(candidates)} văn bản ứng viên (đã lọc thô theo tiêu đề).")
    if args.dry_run:
        for c in candidates[:10]:
            print(f"    {str(c.get('docNum')):<22} {str(c.get('issueDate'))[:10]}")
        return 0

    todo = candidates[: args.limit] if args.limit else candidates
    stats: dict[str, int] = {}
    for idx, item in enumerate(todo, 1):
        try:
            result = ingest(item, args.sleep)
        except Exception as e:
            result = "loi"
            logger.debug("%s: %s", item.get("docNum"), e)
        stats[result] = stats.get(result, 0) + 1
        if idx % 50 == 0:
            logger.info("  %d/%d — %s", idx, len(todo), stats)
        time.sleep(args.sleep)

    with get_session() as session:
        stats["noi_lai_canh"] = resolve_reference_targets(session)
        session.commit()

    print("\n=== KẾT QUẢ ===")
    for k, v in sorted(stats.items()):
        print(f"  {k:<18} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
