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


def _co_con(service, folder_id: str) -> bool:
    """Thư mục còn thứ gì bên trong không (kể cả file, không chỉ thư mục)?"""
    r = gdrive._retry_api_call(
        lambda: service.files().list(
            q=f"'{gdrive._escape_query_value(folder_id)}' in parents and trashed=false",
            fields="files(id)", pageSize=1,
        ).execute()
    )
    return bool(r.get("files"))


def don_thu_muc_rong(service, dry_run: bool) -> dict:
    """Đưa các nhánh gốc cũ đã rỗng vào thùng rác sau khi chuyển.

    Sau khi chuyển hết thư mục văn bản, 203 nhánh lĩnh vực cũ chỉ còn khung
    Năm/Tháng rỗng. Để lại thì cây gốc vẫn 230 nhánh, tức việc sắp xếp lại
    không giải quyết đúng thứ nó sinh ra để giải quyết.

    Duyệt từ trong ra: xoá Tháng rỗng trước, rồi Năm, rồi Lĩnh vực. Chỉ xoá khi
    ĐÃ KIỂM là rỗng — thư mục còn nội dung nghĩa là còn văn bản chưa chuyển, và
    xoá nó là mất dữ liệu thật.
    """
    goc = gdrive.ensure_root_folder()
    stats = {"xet": 0, "xoa": 0, "con_noi_dung": 0, "loi": 0}

    def liet_ke(cha: str) -> list[dict]:
        ds, tok = [], None
        while True:
            r = gdrive._retry_api_call(
                lambda: service.files().list(
                    q=(f"'{gdrive._escape_query_value(cha)}' in parents and "
                       f"mimeType='application/vnd.google-apps.folder' and trashed=false"),
                    fields="nextPageToken,files(id,name)", pageSize=1000,
                    pageToken=tok,
                ).execute()
            )
            ds += r.get("files", [])
            tok = r.get("nextPageToken")
            if not tok:
                return ds

    def xoa_neu_rong(fid: str, ten: str, muc: int) -> bool:
        """Trả True nếu đã xoá. Đệ quy trước để xoá từ trong ra."""
        for con in liet_ke(fid):
            xoa_neu_rong(con["id"], con["name"], muc + 1)
        stats["xet"] += 1
        if _co_con(service, fid):
            if muc == 1:
                stats["con_noi_dung"] += 1
            return False
        if dry_run:
            stats["xoa"] += 1
            return True
        try:
            # ĐƯA VÀO THÙNG RÁC, không files().delete(). delete() xoá vĩnh viễn
            # ngay lập tức; thùng rác giữ 30 ngày nên một phán đoán sai về
            # "rỗng" còn cứu lại được. Đây là dữ liệu trên Drive của người dùng,
            # không phải file tạm của hệ thống.
            gdrive._retry_api_call(
                lambda: service.files().update(
                    fileId=fid, body={"trashed": True}, fields="id",
                ).execute()
            )
            stats["xoa"] += 1
            return True
        except Exception as e:
            stats["loi"] += 1
            logger.warning("Không dọn được %s: %s", ten, e)
            return False

    for nhanh in liet_ke(goc):
        # Nhánh mới có mã hai chữ số ở đầu — tuyệt đối không đụng vào.
        if nhanh["name"][:2].isdigit():
            continue
        xoa_neu_rong(nhanh["id"], nhanh["name"], 1)

    return stats


TEN_KHO_CU = "00. Nhánh cũ — xoá tay được"


def gom_nhanh_cu(service, dry_run: bool) -> dict:
    """Gom các nhánh cũ không dọn được vào MỘT thư mục.

    Phạm vi `drive.file` cho ứng dụng đụng vào file do chính nó tạo. Thư mục
    lĩnh vực cũ do ứng dụng tạo nên DI CHUYỂN được, nhưng ĐƯA VÀO THÙNG RÁC thì
    không: Drive đòi quyền trên toàn bộ con, mà một số con nằm ngoài phạm vi
    (403 appNotAuthorizedToChild). `capabilities.canTrash` báo True vì nó nói về
    quyền của NGƯỜI DÙNG, không phải của ứng dụng.

    Không xoá được thì ít nhất đừng để chúng rải khắp gốc. Gom lại một chỗ để
    người dùng xoá một lần bằng giao diện Drive — quyền của họ cao hơn nên
    không vướng.
    """
    goc = gdrive.ensure_root_folder()
    r = gdrive._retry_api_call(
        lambda: service.files().list(
            q=(f"'{gdrive._escape_query_value(goc)}' in parents and "
               f"mimeType='application/vnd.google-apps.folder' and trashed=false"),
            fields="files(id,name)", pageSize=1000,
        ).execute()
    )
    cu = [f for f in r.get("files", [])
          if not f["name"][:2].isdigit() and f["name"] != TEN_KHO_CU]

    stats = {"tim_thay": len(cu), "gom": 0, "loi": 0}
    if not cu or dry_run:
        return stats

    kho = gdrive.ensure_folder(goc, TEN_KHO_CU)
    if not kho:
        stats["loi"] = len(cu)
        return stats

    for f in cu:
        try:
            gdrive._retry_api_call(
                lambda: service.files().update(
                    fileId=f["id"], addParents=kho, removeParents=goc,
                    fields="id",
                ).execute()
            )
            stats["gom"] += 1
        except Exception as e:
            stats["loi"] += 1
            logger.warning("Không gom được %s: %s", f["name"], e)
    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--don-thu-muc-rong", action="store_true",
                    help="Sau khi chuyển, dọn các thư mục lĩnh vực cũ đã rỗng")
    ap.add_argument("--gom-nhanh-cu", action="store_true",
                    help="Gom nhánh cũ không dọn được vào một thư mục")
    args = ap.parse_args()

    init_db()
    service = gdrive._get_service()
    if not service:
        print("Chưa cấu hình Google Drive.")
        return

    if args.gom_nhanh_cu:
        print("\n=== Gom nhánh cũ còn sót ==="
              + ("  (DRY RUN)" if args.dry_run else ""))
        st = gom_nhanh_cu(service, args.dry_run)
        for k in ("tim_thay", "gom", "loi"):
            print(f"  {k:12} {st[k]}")
        if st["gom"]:
            print(f"\n  Đã gom vào \"{TEN_KHO_CU}\". Xoá thư mục đó bằng giao "
                  f"diện Drive — quyền của bạn cao hơn quyền ứng dụng nên không "
                  f"vướng 403.")
        return

    if args.don_thu_muc_rong:
        print("\n=== Dọn nhánh gốc cũ đã rỗng ==="
              + ("  (DRY RUN)" if args.dry_run else ""))
        st = don_thu_muc_rong(service, args.dry_run)
        for k in ("xet", "xoa", "con_noi_dung", "loi"):
            print(f"  {k:16} {st[k]}")
        if st["con_noi_dung"]:
            print(f"\n  {st['con_noi_dung']} nhánh CÒN NỘI DUNG — không xoá. "
                  f"Chạy lại phần chuyển trước.")
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
