"""
Cào kho biểu mẫu pháp lý của Thư viện Pháp luật.

    python -m scripts.crawl_forms --source hopdong --dry-run     # chỉ liệt kê
    python -m scripts.crawl_forms --source hopdong               # trọn 662 mẫu
    python -m scripts.crawl_forms --source bieumau --field 11    # một lĩnh vực
    python -m scripts.crawl_forms --source bieumau               # cả whitelist
    python -m scripts.crawl_forms --source bieumau --limit 50    # thử một lô nhỏ

KHÔNG CẦN TÀI KHOẢN TVPL: ruột biểu mẫu hiện với khách vãng lai, khác hẳn bản
`.docx` của văn bản. Nhưng VẪN CẦN CHROME THẬT — Cloudflare trả 403 cho mọi thứ
không phải điều hướng của trình duyệt. Nếu bị chặn, xuất lại cookie ra
data/tvpl_cookies.json (xem HUONG_DAN_CHUYEN_GIAO §2.5) hoặc để TVPL_USE_CDP=true
cho nó tự bật Chrome bằng hồ sơ riêng của pipeline.

Dừng-tiếp được: HTML gốc của mỗi mẫu được ghi xuống data/forms/html/ trước khi
bóc, và bản ghi khoá theo `form_key`, nên chạy lại chỉ cào phần còn thiếu.

Biểu mẫu đổi chậm hơn văn bản nhiều — chạy HẰNG TUẦN là đủ, đừng nhét vào
run_daily.sh.
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from src.forms.relevance import BIEU_MAU_BUSINESS_FIELDS
from src.forms.store import KetQuaLuu, luu_bieu_mau, so_hieu_can_cu_chua_co
from src.rag.rag_indexer import hash_content
from src.sources.tvpl_downloader import TVPLBlockedError
from src.sources.tvpl_forms import TVPLFormCrawler, duong_dan_html
from src.sources.tvpl_forms_parse import (
    SOURCE_BIEU_MAU,
    SOURCE_HOP_DONG,
    FormParseError,
    tach_chi_tiet,
)
from src.storage.database import SessionLocal, init_db

logger = logging.getLogger(__name__)

#: Bị Cloudflare chặn liên tiếp ngần này lần thì DỪNG cả lượt chạy.
#:
#: LỖI ĐÃ XẢY RA THẬT ngày 18/08/2026: sau ~67 trang, Cloudflare chuyển sang chặn
#: cứng và bộ cào tiếp tục chạy hết danh sách, ghi ~600 bản ghi FAILED trong 40
#: phút mà không lấy được gì. Tệ hơn: mỗi lần thử lại càng làm phiên bị gắn cờ
#: nặng hơn. Chặn hàng loạt là tín hiệu phải DỪNG, không phải lỗi lẻ để đi tiếp —
#: cùng cơ chế với TVPL_MISSING_LINK_STREAK của bộ tải văn bản.
MAX_BLOCKED_STREAK = 5


def _bo_qua_tai_lai(item, lam_lai: bool):
    """Trang đã có trên đĩa → bóc lại tại chỗ, KHÔNG tải lại từ TVPL.

    Đĩa là nguồn sự thật cho việc chạy tiếp, không phải bảng DB. Lần chạy đầu bị
    Cloudflare cắt giữa chừng để lại 67 file HTML nhưng chỉ 55 dòng trong DB —
    mẻ commit cuối mất theo. Nếu chỉ nhìn DB thì 12 trang đã tải sẽ bị tải lại,
    vừa phí vừa đẩy phiên tới gần ngưỡng chặn hơn.

    Bóc lại từ đĩa cũng là đường sửa bộ bóc rồi chạy lại mà không đụng tới TVPL
    lần nào.
    """
    if lam_lai:
        return None
    p = duong_dan_html(item.form_key)
    if not p.exists():
        return None
    return tach_chi_tiet(p.read_text(encoding="utf-8"),
                         item.source, item.external_id)


async def _cao(source: str, field: int | None, gioi_han: int | None,
               dry_run: bool, lam_lai: bool = False) -> KetQuaLuu:
    crawler = TVPLFormCrawler()
    kq = KetQuaLuu()
    hong = 0
    chuoi_bi_chan = 0

    await crawler.start()
    try:
        if source == SOURCE_HOP_DONG:
            muc = await crawler.duyet_hop_dong(gioi_han=gioi_han)
        elif field:
            muc = await crawler.duyet_danh_sach(
                SOURCE_BIEU_MAU, field=field, gioi_han=gioi_han)
        else:
            muc = []
            for ma in BIEU_MAU_BUSINESS_FIELDS:
                muc.extend(await crawler.duyet_danh_sach(
                    SOURCE_BIEU_MAU, field=ma, gioi_han=gioi_han))
                if gioi_han and len(muc) >= gioi_han:
                    muc = muc[:gioi_han]
                    break

        print(f"Liệt kê được {len(muc)} biểu mẫu.")
        if dry_run:
            for it in muc[:20]:
                print(f"  {it.form_key:>16}  {it.title[:78]}")
            if len(muc) > 20:
                print(f"  … và {len(muc) - 20} mẫu nữa")
            return kq

        session = SessionLocal()
        try:
            tu_dia = 0
            for i, it in enumerate(muc, 1):
                try:
                    detail = _bo_qua_tai_lai(it, lam_lai)
                    if detail is not None:
                        tu_dia += 1
                    else:
                        detail = await crawler.lay_chi_tiet(it)
                    chuoi_bi_chan = 0
                except FormParseError as e:
                    # Mẫu rỗng KHÔNG bị bỏ qua im lặng: ghi lại trạng thái để
                    # người vận hành thấy được, và để lần chạy sau thử lại.
                    hong += 1
                    chuoi_bi_chan = 0
                    logger.warning("%s: %s", it.form_key, e)
                    luu_bieu_mau(session, it, crawl_status="EMPTY_BODY",
                                 crawl_error=str(e)[:500], ket_qua=kq)
                    continue
                except TVPLBlockedError as e:
                    chuoi_bi_chan += 1
                    hong += 1
                    luu_bieu_mau(session, it, crawl_status="FAILED",
                                 crawl_error=str(e)[:500], ket_qua=kq)
                    if chuoi_bi_chan >= MAX_BLOCKED_STREAK:
                        session.commit()
                        print(
                            f"\n⛔ Bị Cloudflare chặn {chuoi_bi_chan} lần liên "
                            f"tiếp — DỪNG ở mẫu {i}/{len(muc)}.\n"
                            "   Đã cào được phần trước, chạy lại lệnh này để đi "
                            "tiếp từ chỗ dừng.\n"
                            "   Nếu vẫn bị chặn: nghỉ 30–60 phút, xuất lại cookie "
                            "ra data/tvpl_cookies.json, hoặc tăng "
                            "TVPL_RATE_LIMIT_SECONDS."
                        )
                        return kq
                    logger.warning("%s: bị chặn (%d/%d liên tiếp)",
                                   it.form_key, chuoi_bi_chan, MAX_BLOCKED_STREAK)
                    continue
                except Exception as e:
                    hong += 1
                    chuoi_bi_chan = 0
                    logger.warning("%s: cào hỏng — %s", it.form_key, e)
                    luu_bieu_mau(session, it, crawl_status="FAILED",
                                 crawl_error=str(e)[:500], ket_qua=kq)
                    continue

                luu_bieu_mau(
                    session, it, detail,
                    body_hash=hash_content(detail.body_html),
                    body_chars=len(detail.body_html),
                    body_html_path=str(duong_dan_html(it.form_key)),
                    ket_qua=kq,
                )
                # Commit dày (10 thay vì 25): lần chạy đầu bị cắt giữa chừng
                # làm mất mẻ cuối, để lại HTML trên đĩa mà không có dòng nào
                # trong DB.
                if i % 10 == 0:
                    session.commit()
                    print(f"  … {i}/{len(muc)}")
            session.commit()

            if tu_dia:
                print(f"Bóc lại {tu_dia} mẫu từ HTML đã lưu trên đĩa "
                      f"(không tải lại TVPL).")

            con_thieu = so_hieu_can_cu_chua_co(session)
            if con_thieu:
                print(f"\n{len(con_thieu)} số hiệu căn cứ chưa có trong kho văn bản, "
                      f"ví dụ: {', '.join(con_thieu[:5])}")
        finally:
            session.close()
    finally:
        await crawler.stop()

    if hong:
        print(f"\n{hong} mẫu không bóc được — xem crawl_status trong legal_forms.")
    return kq


def main() -> None:
    ap = argparse.ArgumentParser(description="Cào biểu mẫu pháp lý từ TVPL")
    ap.add_argument("--source", choices=[SOURCE_HOP_DONG, SOURCE_BIEU_MAU],
                    default=SOURCE_HOP_DONG)
    ap.add_argument("--field", type=int, default=None,
                    help="Mã lĩnh vực 1–47, chỉ dùng với --source bieumau")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="Chỉ liệt kê, không tải trang chi tiết và không ghi DB")
    ap.add_argument("--lam-lai", action="store_true",
                    help="Cào lại cả mẫu đã có HTML trên đĩa")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    if not args.dry_run:
        init_db()

    kq = asyncio.run(_cao(args.source, args.field, args.limit,
                          args.dry_run, args.lam_lai))
    if not args.dry_run:
        print(f"\nXong: {kq.tom_tat()}")


if __name__ == "__main__":
    main()
