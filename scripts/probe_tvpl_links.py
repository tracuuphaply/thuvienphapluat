"""
Dò các link tải trên trang văn bản TVPL.

Dùng khi:
  * cần tìm xem link PDF (nếu có) nằm ở đâu trong tab "Tải về";
  * TVPL đổi giao diện và selector trong tvpl_downloader.py không còn đúng.

Chạy:
    python scripts/probe_tvpl_links.py <URL văn bản TVPL> [URL thứ hai...]

Script tự khởi chạy Chrome đúng cách như pipeline (xem §2.5 tài liệu bàn giao),
tái dùng phiên đăng nhập trong data/chrome_profile, rồi liệt kê mọi link đang
hiển thị trong khu vực tải về.

Lưu ý: nếu vừa tải hàng loạt văn bản, TVPL có thể tạm chặn (trang hiện "Chờ một
chút…"). Đợi vài giờ rồi chạy lại.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.sources.tvpl_downloader import TVPLDownloader  # noqa: E402

PDF_SELECTORS = [
    "a:has-text('PDF')",
    "a[id*='pdf']",
    "a[id*='Pdf']",
    "a[href*='.pdf']",
    "iframe[src*='.pdf']",
    "embed[src*='.pdf']",
]


async def probe(urls: list[str]) -> None:
    downloader = TVPLDownloader()
    await downloader.start()
    try:
        await downloader.login()
        page = downloader._page

        for url in urls:
            print(f"\n===== {url[:90]} =====")
            await downloader._goto(url)
            print("Tiêu đề:", (await page.title())[:70])

            tab = page.locator("#aTabTaiVe")
            if await tab.count():
                await tab.click()
                await page.wait_for_timeout(2500)
                print("Đã mở tab 'Tải về'")
            else:
                print("⚠️  Không thấy tab 'Tải về' (#aTabTaiVe) — giao diện có thể đã đổi")

            print("--- link đang hiển thị có id ---")
            for el in await page.locator("a[id]").all():
                try:
                    if not await el.is_visible():
                        continue
                    text = (await el.inner_text() or "").strip().replace("\n", " ")[:45]
                    el_id = await el.get_attribute("id") or ""
                    if any(k in el_id.lower() for k in ("hyperlink", "download", "tai", "pdf", "doc")):
                        print(f"    id={el_id}\n        text={text}")
                except Exception:
                    continue

            print("--- dò PDF ---")
            found = False
            for selector in PDF_SELECTORS:
                count = await page.locator(selector).count()
                if not count:
                    continue
                el = page.locator(selector).first
                src = await el.get_attribute("href") or await el.get_attribute("src") or ""
                print(f"    {selector} → {count} phần tử | visible={await el.is_visible()}")
                print(f"        {src[:100]}")
                found = True
            if not found:
                print("    (không tìm thấy PDF trên trang này)")
    finally:
        await downloader.stop()


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    asyncio.run(probe(sys.argv[1:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
