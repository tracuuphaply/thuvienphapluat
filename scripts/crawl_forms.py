"""
Cào kho biểu mẫu pháp lý của Thư viện Pháp luật.

    python -m scripts.crawl_forms --source hopdong --dry-run       # xem trước, không ghi
    python -m scripts.crawl_forms --source hopdong --chi-hang-doi  # nạp hàng đợi rồi dừng
    python -m scripts.crawl_forms --source hopdong --tiep-tuc      # tải phần còn thiếu
    python -m scripts.crawl_forms --source hopdong                 # liệt kê + tải, một lượt
    python -m scripts.crawl_forms --source bieumau --field 11    # một lĩnh vực
    python -m scripts.crawl_forms --source bieumau               # cả whitelist
    python -m scripts.crawl_forms --source bieumau --limit 50    # thử một lô nhỏ

DÙNG `--tiep-tuc` CHO MỌI LƯỢT SAU LƯỢT ĐẦU. Giai đoạn liệt kê tốn ~40 lượt tải
và 5,5 phút cho kho hợp đồng, và nó chạy TRƯỚC việc cần làm — đo ngày 18/08/2026:
khi bộ cào chạm tới trang chi tiết đầu tiên thì Cloudflare đã dựng lại thử thách,
dù chính phiên Chrome đó mở được trang chi tiết ngay trước và ngay sau lượt chạy.
Hàng đợi đã nằm trong bảng `legal_forms` nên không cần liệt kê lại.

CẦN TÀI KHOẢN TVPL, dù ruột biểu mẫu hiện cả với khách vãng lai. Đường vãng lai
bị Cloudflare chặn sau ~40–70 trang chi tiết; đo ngày 18/08/2026, cùng 5 URL đang
bị chặn thì sau `login()` là 5/5 thông. Bộ cào mặc định đăng nhập —
`--khong-dang-nhap` để tắt. Vẫn cần Chrome thật: Cloudflare trả 403 cho mọi thứ
không phải điều hướng của trình duyệt.

Dừng-tiếp được ở hai tầng: hàng đợi trong DB, và HTML gốc ở data/forms/html/ được
bóc lại từ đĩa thay vì tải lại.

Biểu mẫu đổi chậm hơn văn bản nhiều — chạy HẰNG TUẦN là đủ, đừng nhét vào
run_daily.sh.
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from src.forms.relevance import BIEU_MAU_BUSINESS_FIELDS
from src.forms.store import (
    KetQuaLuu,
    ghi_hang_doi,
    hang_doi_con_lai,
    luu_bieu_mau,
    so_hieu_can_cu_chua_co,
)
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

    Đĩa là nguồn sự thật thứ hai cho việc chạy tiếp, cạnh hàng đợi trong DB. Lần
    chạy đầu bị Cloudflare cắt giữa chừng để lại 67 file HTML nhưng chỉ 55 dòng
    trong DB — mẻ commit cuối mất theo. Nhìn cả hai thì 12 trang đã tải không bị
    tải lại, vừa đỡ phí vừa không đẩy phiên tới gần ngưỡng chặn hơn.

    Đây cũng là đường sửa bộ bóc rồi chạy lại mà không đụng tới TVPL lần nào.
    """
    if lam_lai:
        return None
    p = duong_dan_html(item.form_key)
    if not p.exists():
        return None
    return tach_chi_tiet(p.read_text(encoding="utf-8"),
                         item.source, item.external_id)


async def _tai_chi_tiet(crawler: TVPLFormCrawler, muc: list, kq: KetQuaLuu,
                        lam_lai: bool) -> KetQuaLuu:
    """Tải trang chi tiết cho từng mục trong hàng đợi và ghi xuống DB."""
    hong = 0
    chuoi_bi_chan = 0
    tu_dia = 0
    session = SessionLocal()
    try:
        for i, it in enumerate(muc, 1):
            try:
                detail = _bo_qua_tai_lai(it, lam_lai)
                if detail is not None:
                    # KHÔNG reset chuỗi bị chặn ở đây. Bóc từ đĩa không chạm mạng
                    # nên nó KHÔNG phải bằng chứng là mạng đã thông — đo ngày
                    # 18/08/2026: mẫu nằm xen kẽ giữa các lượt bị chặn làm bộ đếm
                    # về 0 hai lần, và bộ cào đốt 9 lượt bị chặn thay vì dừng ở 5.
                    tu_dia += 1
                else:
                    detail = await crawler.lay_chi_tiet(it)
                    chuoi_bi_chan = 0
            except FormParseError as e:
                # Mẫu rỗng KHÔNG bị bỏ qua im lặng: ghi lại trạng thái để người
                # vận hành thấy được, và để lần chạy sau thử lại.
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
                        f"\n⛔ Bị Cloudflare chặn {chuoi_bi_chan} lần liên tiếp "
                        f"— DỪNG ở mẫu {i}/{len(muc)}.\n"
                        "   Phần đã tải được giữ nguyên. Vượt thử thách rồi chạy "
                        "lại với --tiep-tuc để đi thẳng vào phần còn thiếu.\n"
                        "   Cách vượt: docs/VAN_HANH.md § Bị Cloudflare chặn "
                        "giữa chừng."
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
            # Commit dày (10): lần chạy đầu bị cắt giữa chừng làm mất mẻ cuối, để
            # lại HTML trên đĩa mà không có dòng nào trong DB.
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

    if hong:
        print(f"\n{hong} mẫu không bóc được — xem crawl_status trong legal_forms.")
    return kq


async def _liet_ke(crawler: TVPLFormCrawler, source: str, field: int | None,
                   gioi_han: int | None) -> list:
    if source == SOURCE_HOP_DONG:
        return await crawler.duyet_hop_dong(gioi_han=gioi_han)
    if field:
        return await crawler.duyet_danh_sach(
            SOURCE_BIEU_MAU, field=field, gioi_han=gioi_han)

    muc: list = []
    for ma in BIEU_MAU_BUSINESS_FIELDS:
        muc.extend(await crawler.duyet_danh_sach(
            SOURCE_BIEU_MAU, field=ma, gioi_han=gioi_han))
        if gioi_han and len(muc) >= gioi_han:
            return muc[:gioi_han]
    return muc


async def _cao(source: str, field: int | None, gioi_han: int | None,
               dry_run: bool, lam_lai: bool = False,
               tiep_tuc: bool = False, chi_hang_doi: bool = False,
               dang_nhap: bool = True) -> KetQuaLuu:
    crawler = TVPLFormCrawler()
    kq = KetQuaLuu()

    # CHẠY TIẾP: lấy hàng đợi từ DB, BỎ HẲN giai đoạn liệt kê — xem docstring
    # module về việc 40 lượt tải liệt kê làm Cloudflare dựng lại thử thách trước
    # khi bộ cào kịp làm việc gì có ích.
    if tiep_tuc:
        session = SessionLocal()
        try:
            muc = hang_doi_con_lai(session, source)
        finally:
            session.close()
        if gioi_han:
            muc = muc[:gioi_han]
        print(f"Chạy tiếp: {len(muc)} mẫu còn thiếu, không lật lại trang liệt kê.")
        if not muc:
            print("Hàng đợi rỗng — chạy KHÔNG có --tiep-tuc để liệt kê lại kho.")
            return kq
        if await crawler.chuan_bi(dang_nhap):
            print("Đã đăng nhập TVPL — trang chi tiết không bị Cloudflare chặn.")
        try:
            return await _tai_chi_tiet(crawler, muc, kq, lam_lai)
        finally:
            await crawler.stop()

    if await crawler.chuan_bi(dang_nhap):
        print("Đã đăng nhập TVPL.")
    try:
        muc = await _liet_ke(crawler, source, field, gioi_han)
        print(f"Liệt kê được {len(muc)} biểu mẫu.")

        if dry_run:
            for it in muc[:20]:
                print(f"  {it.form_key:>16}  {it.title[:78]}")
            if len(muc) > 20:
                print(f"  … và {len(muc) - 20} mẫu nữa")
            return kq

        # Ghi hàng đợi xuống DB NGAY, trước khi tải trang chi tiết nào. Nếu lượt
        # chạy bị cắt thì lượt sau dùng --tiep-tuc là đủ, không phải liệt kê lại.
        session = SessionLocal()
        try:
            them = ghi_hang_doi(session, muc)
            session.commit()
            if them:
                print(f"Ghi {them} mục mới vào hàng đợi.")
        finally:
            session.close()

        if chi_hang_doi:
            # Nạp hàng đợi rồi DỪNG. Giai đoạn liệt kê hay làm Cloudflare dựng
            # lại thử thách, nên tách nó ra khỏi giai đoạn tải chi tiết là cách
            # rẻ nhất: vượt thử thách xong rồi chạy --tiep-tuc để dùng trọn
            # cf_clearance còn tươi cho việc tải trang chi tiết.
            print("\nĐã nạp hàng đợi. Vượt thử thách Cloudflare rồi chạy:\n"
                  f"  python -m scripts.crawl_forms --source {source} --tiep-tuc")
            return kq

        return await _tai_chi_tiet(crawler, muc, kq, lam_lai)
    finally:
        await crawler.stop()


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
    ap.add_argument("--khong-dang-nhap", action="store_true",
                    help="Cào ở chế độ vãng lai; bị Cloudflare chặn sau ~40-70 trang")
    ap.add_argument("--chi-hang-doi", action="store_true",
                    help="Chỉ liệt kê và nạp hàng đợi vào DB, không tải chi tiết")
    ap.add_argument("--tiep-tuc", action="store_true",
                    help="Lấy hàng đợi từ DB, bỏ giai đoạn liệt kê (nên dùng "
                         "cho mọi lượt sau lượt đầu)")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    if not args.dry_run:
        init_db()

    kq = asyncio.run(_cao(args.source, args.field, args.limit, args.dry_run,
                          args.lam_lai, args.tiep_tuc, args.chi_hang_doi,
                          not args.khong_dang_nhap))
    if not args.dry_run:
        print(f"\nXong: {kq.tom_tat()}")


if __name__ == "__main__":
    main()
