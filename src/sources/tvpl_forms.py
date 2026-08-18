"""
Cào hai kho biểu mẫu của Thư viện Pháp luật.

  /bieumau   33.820 biểu mẫu, lọc theo 47 lĩnh vực
  /hopdong      662 mẫu hợp đồng, 22 nhóm (10 gốc + 12 con)

KHÔNG CẦN ĐĂNG NHẬP. Ruột biểu mẫu hiện đầy đủ với khách vãng lai — khác hẳn bản
`.docx` của văn bản. Nhờ vậy phần này không đụng tới hạn mức tải của tài khoản
công ty và không phải qua `login()`.

VẪN PHẢI QUA CHROME THẬT. Cloudflare trả 403 cho `fetch()` và `curl` kể cả khi
mang đủ cookie và User-Agent (đo ngày 18/08/2026), chỉ cho điều hướng của trình
duyệt thật đi qua. Vì vậy lớp này kế thừa `TVPLDownloader` để dùng lại nguyên bộ
khởi động CDP, nạp cookie, phát hiện thử thách Cloudflare và giới hạn tốc độ —
nó chỉ KHÔNG dùng phần đăng nhập và tải file của lớp cha.

Bóc dữ liệu nằm ở src/sources/tvpl_forms_parse.py, không nằm ở đây: phần đó phải
test được mà không có trình duyệt.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from urllib.parse import urlencode

from src.config import FORMS_HTML_DIR, TVPL_BASE_URL
from src.legal.form_taxonomy import HOP_DONG_CRAWL_CODES
from src.sources.tvpl_downloader import TVPLDownloader
from src.sources.tvpl_forms_parse import (
    SOURCE_BIEU_MAU,
    SOURCE_HOP_DONG,
    FormDetail,
    FormListItem,
    FormParseError,
    co_trang_sau,
    tach_chi_tiet,
    tach_danh_sach,
    tach_so_luong,
)

logger = logging.getLogger(__name__)

#: Chặn vòng lặp trang vô hạn khi TVPL luôn vẽ nút "Trang sau".
#: 33.820 mẫu / 20 mẫu mỗi trang = 1.691 trang cho kho lớn nhất khi không lọc.
MAX_PAGES = 1800

MAX_PER_PAGE = 20


# ──────────────────────────────────────────────
# Dựng URL — hàm thuần, test được không cần mạng
# ──────────────────────────────────────────────
def url_bieu_mau(field: int = 0, page: int = 1, loai: int = 0,
                 organ: int = 0, q: str = "") -> str:
    """URL trang liệt kê /bieumau.

    CẠM BẪY ĐÃ ĐO. Thanh phân trang của chính TVPL phát ra dạng
    `?q=&type=0&field=11,organ0&page=1` — dạng đó KHÔNG áp bộ lọc: nó trả về đủ
    33.820 mẫu chứ không phải 875 mẫu lĩnh vực Doanh nghiệp, và ô chọn lĩnh vực
    trên trang vẫn hiện "Tất cả". Chép lại dạng đó là cào nhầm toàn kho mà không
    có dấu hiệu gì báo sai.

    Dạng đúng — do chính nút "Tìm kiếm" của trang sinh ra — tách `field` và
    `organ` thành hai tham số riêng.
    """
    return f"{TVPL_BASE_URL}/bieumau?" + urlencode({
        "type": loai, "field": field, "organ": organ, "q": q, "page": page,
    })


def url_hop_dong(loai: int = 0, page: int = 1, q: str = "") -> str:
    """URL trang liệt kê /hopdong. `loai=0` là xem tất cả 662 mẫu."""
    tham_so = {"q": q, "page": page}
    if loai:
        tham_so["type"] = loai
    return f"{TVPL_BASE_URL}/hopdong?" + urlencode(tham_so)


def duong_dan_html(form_key: str) -> Path:
    return FORMS_HTML_DIR / f"{form_key}.html"


# ──────────────────────────────────────────────
# Bộ cào
# ──────────────────────────────────────────────
class TVPLFormCrawler(TVPLDownloader):
    """Cào biểu mẫu. Dùng `start()` / `stop()` của lớp cha, bỏ qua `login()`."""

    async def lay_html(self, url: str) -> str:
        """Tải một trang và trả về HTML. Ném TVPLBlockedError khi Cloudflare chặn."""
        await self._rate_limit()
        await self._goto(url)
        return await self._page.content()

    async def duyet_danh_sach(
        self,
        source: str,
        loai: int = 0,
        field: int = 0,
        gioi_han: int | None = None,
    ) -> list[FormListItem]:
        """Lật hết các trang liệt kê của một bộ lọc, trả về danh sách mục.

        Dừng khi hết nút "Trang sau", khi một trang không còn mục mới, hoặc khi
        đủ `gioi_han`. Điều kiện "không còn mục mới" là chốt thật sự: TVPL trả về
        trang cuối cùng lặp lại khi `page` vượt quá số trang có thật, nên chỉ dựa
        vào nút "Trang sau" là lặp vô hạn.
        """
        ket_qua: list[FormListItem] = []
        da_thay: set[str] = set()
        tong: int | None = None

        for trang in range(1, MAX_PAGES + 1):
            url = (url_bieu_mau(field=field, page=trang, loai=loai)
                   if source == SOURCE_BIEU_MAU
                   else url_hop_dong(loai=loai, page=trang))
            html = await self.lay_html(url)

            if tong is None:
                tong = tach_so_luong(html)
                logger.info("%s (loai=%s, field=%s): TVPL báo %s mẫu",
                            source, loai, field, tong)

            moi = [it for it in tach_danh_sach(html) if it.form_key not in da_thay]
            if not moi:
                break
            for it in moi:
                # Lĩnh vực và nhóm không có trên trang liệt kê — chúng CHÍNH LÀ
                # bộ lọc vừa dùng để mở trang. Điền ở đây thay vì đoán lại từ
                # tiêu đề sau này.
                if source == SOURCE_BIEU_MAU:
                    it.field_code = field or None
                    it.form_type_code = loai or None
                else:
                    it.form_type_code = loai or None
                da_thay.add(it.form_key)
            ket_qua.extend(moi)

            if gioi_han and len(ket_qua) >= gioi_han:
                return ket_qua[:gioi_han]
            if not co_trang_sau(html):
                break

        if tong is not None and len(ket_qua) < tong:
            # Không ném lỗi: bộ lọc nhóm cha/con của /hopdong và mẫu bị gỡ giữa
            # chừng đều làm lệch hợp lệ. Nhưng phải NÓI ra, vì im lặng ở đây
            # nghĩa là kho thiếu mà trông như đã cào xong.
            logger.warning(
                "%s (loai=%s, field=%s): lấy được %d/%d mẫu — thiếu %d",
                source, loai, field, len(ket_qua), tong, tong - len(ket_qua),
            )
        return ket_qua

    async def duyet_hop_dong(self, gioi_han: int | None = None) -> list[FormListItem]:
        """Toàn bộ 662 mẫu hợp đồng, đi hết CẢ 22 nhóm.

        Không dùng `loai=0` (xem tất cả) vì trang đó cũng phải lật 34 trang mà
        không cho biết mẫu thuộc nhóm nào — nhóm chính là thứ dùng để gắn nghiệp
        vụ.

        PHẢI ĐI HẾT 22 NHÓM, KHÔNG PHẢI 10 NHÓM GỐC. Số trên cây lọc là cộng dồn
        cả nhóm con, nhưng `?type=` chỉ trả mẫu của RIÊNG nhóm: cây ghi "Đất đai,
        nhà ở (108)" mà ?type=1 trả về 26. Cộng số trên cây ra đúng 662 nên cách
        làm sai vẫn trông thuyết phục — thực tế thiếu 137 mẫu. Xem
        src/legal/form_taxonomy.py.
        """
        gop: dict[str, FormListItem] = {}
        for ma_nhom in HOP_DONG_CRAWL_CODES:
            for it in await self.duyet_danh_sach(SOURCE_HOP_DONG, loai=ma_nhom):
                # Mẫu của nhóm con KHÔNG xuất hiện lại ở nhóm cha nên thực tế
                # không có trùng; `setdefault` chỉ là chốt an toàn, và thứ tự
                # HOP_DONG_CRAWL_CODES đặt nhóm con trước nhóm cha để nếu TVPL
                # đổi cách gộp thì mẫu vẫn nhận nhãn cụ thể nhất.
                gop.setdefault(it.form_key, it)
            if gioi_han and len(gop) >= gioi_han:
                break
        ds = list(gop.values())
        return ds[:gioi_han] if gioi_han else ds

    async def lay_chi_tiet(self, item: FormListItem,
                           luu_html: bool = True) -> FormDetail:
        """Tải trang chi tiết, lưu HTML gốc, bóc dữ liệu.

        HTML gốc được ghi xuống đĩa TRƯỚC khi bóc, kể cả khi bóc hỏng: đó là thứ
        duy nhất cho phép sửa bộ bóc rồi chạy lại mà không phải cào lại TVPL.
        """
        html = await self.lay_html(item.url)
        if luu_html:
            duong_dan_html(item.form_key).write_text(html, encoding="utf-8")
        return tach_chi_tiet(html, item.source, item.external_id)


async def luu_fixture(urls: dict[str, str], thu_muc: Path) -> list[str]:
    """Tải vài trang về làm fixture test. Chỉ dùng khi dựng/ sửa bộ bóc.

    Tách khỏi luồng cào chính vì nó ghi vào tests/, không ghi vào data/.
    """
    thu_muc.mkdir(parents=True, exist_ok=True)
    crawler = TVPLFormCrawler()
    da_luu: list[str] = []
    await crawler.start()
    try:
        for ten, url in urls.items():
            html = await crawler.lay_html(url)
            (thu_muc / f"{ten}.html").write_text(html, encoding="utf-8")
            da_luu.append(f"{ten}.html ({len(html):,} ký tự)")
            logger.info("Đã lưu fixture %s (%d ký tự)", ten, len(html))
    finally:
        await crawler.stop()
    return da_luu


def chay_dong_bo(coro):
    """Chạy một coroutine của module này từ code đồng bộ."""
    return asyncio.run(coro)


__all__ = [
    "MAX_PAGES", "MAX_PER_PAGE",
    "TVPLFormCrawler", "FormParseError",
    "url_bieu_mau", "url_hop_dong", "duong_dan_html",
    "luu_fixture", "chay_dong_bo",
]
