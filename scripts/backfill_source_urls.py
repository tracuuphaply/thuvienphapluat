"""
Điền các trường định danh cho văn bản đã có trong kho.

Ba việc, đều thuần suy diễn từ dữ liệu sẵn có — không gọi mạng:

  1. `moj_url` — hiện rỗng trên toàn bộ 1015 văn bản, khiến mọi note Obsidian
     render "[Bộ Tư pháp]()" với link trống. Đây là chặn cứng của trang công
     khai: không ghi được nguồn thì không đăng được.
  2. `public_slug` — tên file vault và đường dẫn URL. Số hiệu trần đụng nhau
     giữa các tỉnh nên note sau ghi đè note trước.
  3. `moj_id_index` — nhập cặp số hiệu → id MOJ từ file cache cũ
     data/moj_target_ids.json và từ chính các văn bản đã có.

Chạy:
    python -m scripts.backfill_source_urls --dry-run
    python -m scripts.backfill_source_urls
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter

from src.config import DATA_DIR
from src.sources.moj_api import doc_source_url
from src.storage.database import get_session, init_db, remember_moj_id
from src.storage.file_store import save_document_metadata
from src.storage.models import Document
from src.storage.public_slug import make_public_slug

logger = logging.getLogger(__name__)

LEGACY_ID_CACHE = DATA_DIR / "moj_target_ids.json"

# Cột nội bộ không đưa vào hồ sơ đi kèm file trên Drive.
_SKIP_IN_METADATA = {"id", "_sa_instance_state", "event_type", "obsidian_hash",
                     "obsidian_path", "published_hash"}


def _metadata_payload(doc: Document) -> dict:
    return {
        col.name: getattr(doc, col.name)
        for col in Document.__table__.columns
        if col.name not in _SKIP_IN_METADATA
    }


def backfill(dry_run: bool) -> Counter:
    # Khởi tạo sẵn để dòng nào bằng 0 vẫn hiện ra. Ẩn đi thì người đọc không
    # phân biệt được "chạy xong, không có gì để làm" với "bước này không chạy".
    stats: Counter = Counter({
        "tong_van_ban": 0,
        "moj_url_da_dien": 0,
        "moj_url_bo_qua_khong_co_moj_id": 0,
        "public_slug_da_dien": 0,
        "slug_dung_nhau": 0,
        "moj_id_index_them": 0,
        "moj_id_index_tu_cache": 0,
        "metadata_da_ghi_lai": 0,
    })

    with get_session() as session:
        docs = session.query(Document).order_by(Document.id).all()
        stats["tong_van_ban"] = len(docs)

        # public_slug phải duy nhất. make_public_slug() chỉ suy từ chính văn bản
        # nên về nguyên tắc không đụng, nhưng nếu dữ liệu bẩn làm hai văn bản ra
        # cùng slug thì phải phát hiện chứ không được ghi đè im lặng.
        seen_slugs: dict[str, str] = {}

        for doc in docs:
            if doc.moj_id and not doc.moj_url:
                url = doc_source_url(doc.moj_id)
                if url:
                    if not dry_run:
                        doc.moj_url = url
                    stats["moj_url_da_dien"] += 1
            elif not doc.moj_id:
                stats["moj_url_bo_qua_khong_co_moj_id"] += 1

            slug = make_public_slug(doc.doc_num, doc.doc_key or doc.doc_num)
            if slug in seen_slugs and seen_slugs[slug] != doc.doc_key:
                logger.error(
                    "Slug đụng nhau: %r dùng cho cả %r và %r — bỏ qua bản sau",
                    slug, seen_slugs[slug], doc.doc_key,
                )
                stats["slug_dung_nhau"] += 1
            else:
                seen_slugs[slug] = doc.doc_key
                if doc.public_slug != slug:
                    if not dry_run:
                        doc.public_slug = slug
                    stats["public_slug_da_dien"] += 1

            if doc.moj_id and not dry_run:
                if remember_moj_id(session, doc.doc_num, doc.moj_id, "detail"):
                    stats["moj_id_index_them"] += 1

            # data/metadata/*.json là hồ sơ đi kèm file trên Drive, được ghi lúc
            # cào và không cập nhật lại. Bỏ qua bước này thì bản trên Drive vẫn
            # thiếu link nguồn dù cơ sở dữ liệu đã đủ.
            if not dry_run:
                if save_document_metadata(_metadata_payload(doc)):
                    stats["metadata_da_ghi_lai"] += 1

        # File cache cũ giữ 717 cặp thu được bằng cách quét lại toàn kho — nhập
        # vào bảng để khỏi phải quét lần nữa.
        if LEGACY_ID_CACHE.exists() and not dry_run:
            try:
                cache = json.loads(LEGACY_ID_CACHE.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("Không đọc được %s: %s", LEGACY_ID_CACHE, e)
                cache = {}
            for doc_num, moj_id in (cache or {}).items():
                if remember_moj_id(session, doc_num, str(moj_id), "reference"):
                    stats["moj_id_index_tu_cache"] += 1

        if dry_run:
            session.rollback()

    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Chỉ đếm, không ghi gì vào cơ sở dữ liệu")
    args = parser.parse_args()

    init_db()
    stats = backfill(args.dry_run)

    print("\n=== Kết quả ===" + ("  (DRY RUN — chưa ghi gì)" if args.dry_run else ""))
    for key in sorted(stats):
        print(f"  {key:38} {stats[key]:>6}")

    if stats["slug_dung_nhau"]:
        print("\nCó slug đụng nhau — xem log ở trên trước khi dùng trang công khai.")
        sys.exit(1)


if __name__ == "__main__":
    main()
