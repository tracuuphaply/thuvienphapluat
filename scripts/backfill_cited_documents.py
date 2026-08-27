"""
Bổ sung các văn bản đã được kho dẫn chiếu nhưng chưa có trong kho.

Kho chỉ chứa văn bản ban hành từ 2025-11-29 trở đi vì cửa sổ quét dựa trên
issueDate. Hệ quả: không có Luật Doanh nghiệp, Luật Đầu tư hay bất kỳ nghị định
nền tảng nào — trong khi hàng trăm văn bản trong kho đang "Căn cứ" vào chúng.
Danh sách văn bản đích còn thiếu chính là danh sách văn bản nền tảng cần bổ
sung, và đã xếp sẵn theo mức quan trọng: số lần được dẫn chiếu.

Cách lấy: KHÔNG dùng search_by_doc_num — endpoint /doc/all bỏ qua mọi tham số
lọc (keyword, docNum, searchText… đều trả về danh sách mặc định), nên tra theo
số hiệu luôn thất bại. Thay vào đó lấy thẳng `targetDocument.id` có sẵn trong
payload quan hệ của những văn bản đã có, rồi fetch chi tiết bằng id đó.

Chạy:
    python -m scripts.backfill_cited_documents --dry-run
    python -m scripts.backfill_cited_documents --limit 60
"""
import argparse
import json
import logging
import sys
import time
from pathlib import Path

from sqlalchemy import text

from src.config import DATA_DIR
from src.pipeline.text_processor import process_fulltext
from src.sources.moj_api import (
    fetch_doc_detail,
    parse_doc_detail,
    toan_van_co_noi_dung,
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
ID_CACHE = DATA_DIR / "moj_target_ids.json"


def missing_targets() -> dict[str, int]:
    """Số hiệu được dẫn chiếu mà kho chưa có → số lần được dẫn."""
    with get_session() as session:
        rows = session.execute(text("""
            SELECT r.target_doc_num, COUNT(*) AS n
            FROM document_references r
            WHERE NOT EXISTS (
                SELECT 1 FROM documents d WHERE d.doc_num = r.target_doc_num
            )
            GROUP BY r.target_doc_num
            ORDER BY n DESC
        """)).fetchall()
    return {r[0]: r[1] for r in rows}


def harvest_target_ids(sleep: float = 0.25, refresh: bool = False) -> dict[str, str]:
    """Gom moj_id của văn bản đích từ payload quan hệ của các văn bản đã có.

    Kết quả được lưu lại vì bước này tốn một vòng gọi API cho cả kho.
    """
    if ID_CACHE.exists() and not refresh:
        cached = json.loads(ID_CACHE.read_text(encoding="utf-8"))
        logger.info("Dùng lại %d id đích đã gom trước đó", len(cached))
        return cached

    with get_session() as session:
        moj_ids = [
            r[0] for r in session.execute(
                text("SELECT moj_id FROM documents WHERE moj_id IS NOT NULL")
            ).fetchall()
        ]

    found: dict[str, str] = {}
    for idx, moj_id in enumerate(moj_ids, 1):
        try:
            data = fetch_doc_detail(moj_id).get("data") or {}
        except Exception as e:
            logger.debug("bỏ qua %s: %s", moj_id, type(e).__name__)
            time.sleep(sleep)
            continue
        for ref in data.get("references") or []:
            target = ref.get("targetDocument") or {}
            num, tid = target.get("docNum"), target.get("id")
            if num and tid:
                found.setdefault(str(num).strip(), str(tid))
        if idx % 50 == 0:
            logger.info("  gom id: %d/%d văn bản, đã có %d id đích", idx, len(moj_ids), len(found))
        time.sleep(sleep)

    ID_CACHE.write_text(json.dumps(found, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Đã gom %d id đích, lưu vào %s", len(found), ID_CACHE)
    return found


def backfill_one(doc_num: str, moj_id: str) -> str:
    """Tải và nạp một văn bản theo moj_id."""
    detail = parse_doc_detail(fetch_doc_detail(moj_id))

    doc_data = {k: v for k, v in detail.items() if k not in _SKIP_KEYS and v not in (None, "")}
    doc_data["doc_num"] = doc_data.get("doc_num") or doc_num
    doc_data["source_moj"] = True
    doc_data["moj_id"] = moj_id
    doc_data.setdefault("title", doc_num)

    # `if fulltext:` là SAI ở đây: cổng trả khung HTML rỗng chứ không báo lỗi,
    # nên phép thử rỗng-hay-không luôn qua và văn bản bị ghi là đã có toàn văn.
    fulltext = detail.get("fulltext_html", "")
    if toan_van_co_noi_dung(fulltext):
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
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--refresh-ids", action="store_true", help="gom lại id đích từ đầu")
    ap.add_argument("--sleep", type=float, default=0.3)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    missing = missing_targets()
    print(f"Có {len(missing)} số hiệu được dẫn chiếu mà kho chưa có.")

    ids = harvest_target_ids(sleep=args.sleep, refresh=args.refresh_ids)
    workable = [(n, c, ids[n]) for n, c in missing.items() if n in ids]
    print(f"Trong đó {len(workable)} văn bản tra được moj_id → tải được.")
    for n, c, _ in workable[:10]:
        print(f"    {n:<20} được dẫn {c} lần")
    if args.dry_run:
        return 0

    stats = {"them_moi": 0, "cap_nhat": 0, "loi": 0}
    todo = workable[: args.limit]
    if len(workable) > args.limit:
        print(f"\n(giới hạn {args.limit}; còn {len(workable) - args.limit} văn bản chưa xử lý)")

    for idx, (doc_num, count, moj_id) in enumerate(todo, 1):
        try:
            result = backfill_one(doc_num, moj_id)
            stats[result] += 1
            logger.info("[%d/%d] %s (%d lần dẫn) → %s", idx, len(todo), doc_num, count, result)
        except Exception as e:
            stats["loi"] += 1
            logger.warning("[%d/%d] %s → %s: %s", idx, len(todo), doc_num, type(e).__name__, e)
        time.sleep(args.sleep)

    with get_session() as session:
        stats["noi_lai_canh"] = resolve_reference_targets(session)
        session.commit()

    print("\n=== KẾT QUẢ ===")
    for k, v in stats.items():
        print(f"  {k:<18} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
