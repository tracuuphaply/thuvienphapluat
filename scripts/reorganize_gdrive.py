"""
Sắp xếp lại cây thư mục Drive theo danh mục lĩnh vực của Thư viện Pháp luật.

Cây cũ lấy tầng 1 từ `field_name` của Bộ Tư pháp — văn bản tự do, 203 nhánh gốc
cho 4.466 văn bản, trong đó 75 nhánh chứa đúng một file. Cây mới dùng 27 lĩnh
vực TVPL nên có biên cố định.

    python -m scripts.reorganize_gdrive --dry-run
    python -m scripts.reorganize_gdrive --limit 50     # thử một lô nhỏ
    python -m scripts.reorganize_gdrive
    python -m scripts.reorganize_gdrive --don-thu-muc-rong

DI CHUYỂN, KHÔNG TẢI LẠI. Drive cho đổi cha của một thư mục bằng một lời gọi
`files.update(addParents=..., removeParents=...)`. Tải lại 4 file mỗi văn bản
tốn gấp 4 lần thời gian VÀ sinh id file mới, mà id cũ đang nằm trong
`documents.gdrive_docx_link` — mọi link đã phát ra sẽ chết.

CHA CŨ LẤY TỪ CACHE, không hỏi API. `data/gdrive_cache.json` ánh xạ
"{id cha}/{tên}" → "{id con}" cho mọi thư mục hệ thống đã tạo, nên nghịch đảo nó
là ra cha của từng thư mục. Hỏi API thì tốn thêm một lời gọi mỗi thư mục, tức
gấp đôi thời gian chạy.
"""
from __future__ import annotations

import argparse
import json
import logging
import time

from src.config import MOJ_RATE_LIMIT_SECONDS
from src.storage import gdrive
from src.storage.database import get_session, init_db
from src.storage.models import Document

logger = logging.getLogger(__name__)


def cha_theo_con(cache: dict[str, str]) -> dict[str, str]:
    """id thư mục → id thư mục cha, nghịch đảo từ cache."""
    out: dict[str, str] = {}
    for khoa, con in cache.items():
        cha, _, _ten = khoa.partition("/")
        out[con] = cha
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--don-thu-muc-rong", action="store_true",
                    help="Sau khi chuyển, xoá các thư mục lĩnh vực cũ đã rỗng")
    args = ap.parse_args()

    init_db()
    service = gdrive._get_service()
    if not service:
        print("Chưa cấu hình Google Drive.")
        return

    cache = dict(gdrive._folder_cache)
    cha_cua = cha_theo_con(cache)

    stats = {"xet": 0, "da_dung_cho": 0, "chuyen": 0, "loi": 0,
             "khong_biet_cha": 0}

    with get_session() as session:
        docs = (session.query(Document)
                .filter(Document.gdrive_folder_id.isnot(None))
                .order_by(Document.id).all())
        if args.limit:
            docs = docs[:args.limit]

        print(f"\n=== Sắp xếp lại {len(docs)} thư mục văn bản ==="
              + ("  (DRY RUN)" if args.dry_run else ""))

        for doc in docs:
            stats["xet"] += 1
            doc_data = {c.name: getattr(doc, c.name)
                        for c in Document.__table__.columns}

            cha_cu = cha_cua.get(doc.gdrive_folder_id)
            if not cha_cu:
                # Thư mục không do lần chạy nào của hệ thống tạo, hoặc cache đã
                # mất. Bỏ qua chứ không đoán: chuyển nhầm cha là làm mất thư mục
                # trong một cây 7.000 nhánh.
                stats["khong_biet_cha"] += 1
                continue

            if args.dry_run:
                # Không tạo thư mục mới khi chạy thử — chỉ cần biết tên đích.
                moi = gdrive._safe_name(gdrive.linh_vuc_thu_muc(doc_data))
                cu = next((k.partition("/")[2] for k, v in cache.items()
                           if v == cha_cu), "?")
                if stats["chuyen"] < 10 and moi not in cu:
                    print(f"    {doc.doc_num:<22} → {moi}")
                stats["chuyen"] += 1
                continue

            try:
                cha_moi = gdrive.ensure_folder_path_parent(doc_data)
                if not cha_moi:
                    stats["loi"] += 1
                    continue
                if cha_moi == cha_cu:
                    stats["da_dung_cho"] += 1
                    continue

                gdrive._retry_api_call(
                    lambda: service.files().update(
                        fileId=doc.gdrive_folder_id,
                        addParents=cha_moi, removeParents=cha_cu,
                        fields="id",
                    ).execute()
                )
                cha_cua[doc.gdrive_folder_id] = cha_moi
                stats["chuyen"] += 1
                if stats["chuyen"] % 50 == 0:
                    logger.info("Đã chuyển %d/%d", stats["chuyen"], len(docs))
                time.sleep(MOJ_RATE_LIMIT_SECONDS)
            except Exception as e:
                stats["loi"] += 1
                logger.warning("Không chuyển được %s: %s", doc.doc_num, e)

    print("\n=== Kết quả ===")
    for k in ("xet", "chuyen", "da_dung_cho", "khong_biet_cha", "loi"):
        print(f"  {k:18} {stats[k]}")
    if args.dry_run:
        print("\n  Chạy thật: python -m scripts.reorganize_gdrive")


if __name__ == "__main__":
    main()
