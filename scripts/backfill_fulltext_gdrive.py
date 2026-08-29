"""
Bù bản toàn văn lên Google Drive cho những văn bản đã đăng mà còn thiếu.

    python -m scripts.backfill_fulltext_gdrive --dry-run
    python -m scripts.backfill_fulltext_gdrive --limit 5
    python -m scripts.backfill_fulltext_gdrive

VẤN ĐỀ. Trang văn bản công khai dẫn người đọc tới `moj_url` — cổng
`vbpl-bientap-gateway.moj.gov.vn/api/qtdc/public/doc/<id>`. Đó là một ENDPOINT
API: trình duyệt mở ra một khối JSON thô, không phải thứ để đọc. Người bấm vào để
đọc văn bản không đọc được gì.

CHỖ TRỚ TRÊU, và cũng là lối ra: TOÀN VĂN NẰM NGAY TRONG KHỐI JSON ĐÓ, ở
`data.documentContent.content`. Đo trên 2604/QĐ-UBND: 8.665 ký tự HTML. Nên đây
không phải ngõ cụt — chỉ là dữ liệu chưa được lấy về và dựng thành thứ đọc được.

BA NHÓM, đo ngày 19/08/2026 trên 4.201 văn bản đã đăng — 318 thiếu bản Drive:
    191  có moj_url, có file trên đĩa      → chỉ cần tải lên
     65  có moj_url, KHÔNG có file         → gọi API lấy toàn văn rồi tải lên
     44  có cả moj_url lẫn tvpl_url, có file → chỉ cần tải lên
     18  chỉ có tvpl_url, không có file    → BỎ QUA, không có nguồn để lấy

Script này xử nhóm 1–3. Nhóm 4 phải chờ đợt cào TVPL, và trang của chúng vẫn dẫn
về Thư viện Pháp luật — địa chỉ đó người thật mở bằng trình duyệt thì đọc được.

CHẠY LẠI ĐƯỢC: văn bản nào đã có `gdrive_fulltext_link` thì bỏ qua. Ghi kho theo
từng lô, và dừng sớm khi hỏng liên tiếp — cùng lý do như upload_forms_gdrive.
"""
from __future__ import annotations

import argparse
import logging
import re
import time
from pathlib import Path

from src.config import PROJECT_ROOT
from src.storage.database import get_session, init_db
from src.storage.models import Document

logger = logging.getLogger(__name__)

CO_LO = 20
NGHI_GIAY = 0.35
TRAN_HONG_LIEN_TIEP = 12
THU_MUC_TOAN_VAN = PROJECT_ROOT / "data" / "moj"

#: id trong URL cổng Bộ Tư pháp. KHÔNG đặt sàn độ dài: id thật là số ngắn
#: (`/doc/18113`), trong khi bản cũ của mẫu này đòi từ 16 ký tự và vì thế loại
#: 1.625/1.694 văn bản — 96% — mà không báo gì, chỉ in ra "không có nguồn để lấy".
_RE_MOJ_ID = re.compile(r"/doc/([0-9A-Za-z-]+)")


def moj_id(doc: Document) -> str:
    """id văn bản trên hệ thống Bộ Tư pháp: ưu tiên cột, sau đó rút từ URL.

    Bản cũ CHỈ rút từ URL, với lý do ghi trong docstring rằng "cột id có thể
    rỗng ở các bản ghi cũ". Lý do đó không đúng với kho thật: cả 1.625 văn bản
    đang thiếu bản Drive đều có sẵn cột `moj_id`. Đọc cột trước rồi mới rút URL
    thì đúng ở cả hai phía — và không phụ thuộc vào hình dạng URL, thứ đã thay
    đổi ít nhất một lần.
    """
    if (doc.moj_id or "").strip():
        return str(doc.moj_id).strip()
    m = _RE_MOJ_ID.search(doc.moj_url or "")
    return m.group(1) if m else ""


def lay_toan_van(doc: Document) -> Path | None:
    """Bảo đảm có file toàn văn trên đĩa; gọi API Bộ Tư pháp nếu chưa có.

    Trả về đường dẫn file, hoặc None khi không lấy được.
    """
    if doc.fulltext_path and Path(doc.fulltext_path).exists():
        return Path(doc.fulltext_path)

    mid = moj_id(doc)
    if not mid:
        return None

    from src.sources import moj_api

    try:
        chi_tiet = moj_api.fetch_doc_detail(mid)
        html = (moj_api.parse_doc_detail(chi_tiet) or {}).get("fulltext_html") or ""
    except Exception as e:                       # noqa: BLE001
        logger.warning("Gọi API hỏng cho %s: %s", doc.doc_num, e)
        return None

    # Ngưỡng ký tự, không phải `if html`: gateway có trả về chuỗi rỗng và cả
    # khung HTML trống. Lưu một file rỗng lên Drive rồi gọi đó là "toàn văn" thì
    # tệ hơn không có gì — nó bịt mất dấu hiệu còn thiếu.
    if len(re.sub(r"<[^>]+>", "", html).strip()) < 200:
        logger.warning("Toàn văn quá ngắn, bỏ qua: %s", doc.doc_num)
        return None

    THU_MUC_TOAN_VAN.mkdir(parents=True, exist_ok=True)
    p = THU_MUC_TOAN_VAN / f"{mid}.html"
    p.write_text(html, encoding="utf-8")
    doc.fulltext_path = str(p)
    return p


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="Đếm và phân nhóm, không chạy")
    ap.add_argument("--limit", type=int, help="Chỉ xử lý N văn bản đầu")
    args = ap.parse_args()

    from src.storage import gdrive

    init_db()
    with get_session() as session:
        # MỌI văn bản ĐÃ ĐĂNG, không chỉ văn bản quy phạm.
        #
        # Bộ lọc cũ là `is_vbqppl = 1`, hợp lý với ý định ban đầu nhưng để lọt
        # 230 văn bản đã đăng mà không phải quy phạm — công điện, thông báo,
        # chỉ thị, quyết định cá biệt. Trang của chúng vẫn trỏ về cổng API Bộ Tư
        # pháp, tức người bấm vào nhận một khối JSON thô, đúng vấn đề mà chính
        # script này sinh ra để chữa.
        #
        # Điều kiện đúng là "đã đăng", không phải "là quy phạm": hễ một trang
        # công khai tồn tại thì nó cần một bản đọc được ở đầu bên kia đường link.
        docs = (session.query(Document)
                .filter(Document.public_slug.isnot(None))
                .filter(Document.gdrive_fulltext_link.is_(None))
                .order_by(Document.doc_num)
                .all())

        co_moj = [d for d in docs if moj_id(d)]
        khong_nguon = [d for d in docs if not moj_id(d)]
        san_file = [d for d in co_moj
                    if d.fulltext_path and Path(d.fulltext_path).exists()]

        print(f"=== {len(docs)} văn bản đã đăng còn thiếu bản toàn văn trên Drive ===")
        print(f"  lấy được (có id Bộ Tư pháp) : {len(co_moj)}")
        print(f"      trong đó đã có file sẵn : {len(san_file)}")
        print(f"      phải gọi API để lấy     : {len(co_moj) - len(san_file)}")
        print(f"  KHÔNG có nguồn để lấy       : {len(khong_nguon)}"
              " (chỉ có link Thư viện Pháp luật — chờ đợt cào)")

        if args.limit:
            co_moj = co_moj[: args.limit]
        if args.dry_run or not co_moj:
            session.rollback()
            return

        xong = hong = lien_tiep = 0
        dung_som = False
        for i, d in enumerate(co_moj, 1):
            p = lay_toan_van(d)
            if not p:
                hong += 1
                lien_tiep += 1
            else:
                kq = gdrive.upload_document_files({
                    "doc_num": d.doc_num,
                    "title": d.title,
                    "issue_date": d.issue_date,
                    "tvpl_field_code": d.tvpl_field_code,
                    "fulltext_path": str(p),
                    "clean_text_path": d.clean_text_path,
                    "docx_path": d.docx_path,
                })
                if kq.get("gdrive_fulltext_link"):
                    d.gdrive_fulltext_link = kq["gdrive_fulltext_link"]
                    if kq.get("gdrive_docx_link"):
                        d.gdrive_docx_link = kq["gdrive_docx_link"]
                    d.gdrive_folder_id = kq.get("gdrive_folder_id")
                    # Trang phải dựng lại: mục Nguồn gốc đổi.
                    d.published_hash = None
                    xong += 1
                    lien_tiep = 0
                else:
                    hong += 1
                    lien_tiep += 1
                    logger.warning("Tải hỏng: %s", d.doc_num)

            if lien_tiep >= TRAN_HONG_LIEN_TIEP:
                session.commit()
                print(f"\nDỪNG SỚM: {lien_tiep} lượt hỏng liên tiếp — nhiều khả năng "
                      "đụng hạn mức ghi của Drive hoặc cổng Bộ Tư pháp đang chặn. "
                      "Chờ vài phút rồi chạy lại; văn bản đã xong sẽ được bỏ qua.")
                dung_som = True
                break
            if i % CO_LO == 0:
                session.commit()
                print(f"  {i}/{len(co_moj)} · xong {xong} · hỏng {hong}")
            time.sleep(NGHI_GIAY)
        session.commit()

    print("\n=== Kết quả ===")
    print(f"  đã có bản Drive  {xong}")
    print(f"  hỏng             {hong}")
    if dung_som:
        print("  DỪNG SỚM — chạy lại lệnh này để tiếp tục.")
    print("\nDựng lại trang công khai để mục Nguồn gốc trỏ về bản đọc được:")
    print("  python -m scripts.publish_site --out ~/Downloads/legal-vault-public/content")


if __name__ == "__main__":
    main()
