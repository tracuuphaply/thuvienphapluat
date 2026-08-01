"""
TVPL document downloader using Playwright.

Handles:
  - Login with TVPL account (keeps session/cookies)
  - Session persistence via storage_state.json (avoid re-login)
  - Navigate to document page
  - Click "Tải Văn bản tiếng Việt" (.docx) button
  - Handle 302 redirect to actual file
  - Save downloaded file to data/tvpl/{doc_id}.{ext}

Rate limited per NFR-04 to be polite to TVPL servers.

Upgrade v1.1:
  - Session persistence: saves cookies/localStorage to storage_state.json
  - Re-login only when session expires (detected via failed navigation)
  - Reduces login frequency by ~90%, avoids Cloudflare suspicion
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from src.config import (
    DATA_DIR,
    TVPL_BASE_URL,
    TVPL_FILES_DIR,
    TVPL_PASSWORD,
    TVPL_RATE_LIMIT_SECONDS,
    TVPL_USERNAME,
)

logger = logging.getLogger(__name__)

# Path to persist Playwright storage state (cookies + localStorage)
STORAGE_STATE_PATH = DATA_DIR / "tvpl_session.json"

# Cookie xuất từ trình duyệt thật của người dùng (xem HUONG_DAN_CHUYEN_GIAO §2.5).
# Dùng khi Cloudflare chặn trình duyệt tự động: cf_clearance gắn với IP + User-Agent
# của phiên đã vượt qua thử thách nên phải xuất từ chính máy sẽ chạy pipeline.
COOKIES_PATH = DATA_DIR / "tvpl_cookies.json"

# Tiêu đề trang khi Cloudflare chặn (tiếng Anh + bản địa hoá tiếng Việt)
_CHALLENGE_TITLES = (
    "just a moment",
    "chờ một chút",
    "attention required",
    "access denied",
)


def _is_challenge_title(title: str) -> bool:
    lowered = (title or "").lower()
    return any(marker in lowered for marker in _CHALLENGE_TITLES)


class TVPLBlockedError(RuntimeError):
    """Cloudflare chặn truy cập tự động — không văn bản nào tải được."""


# Ánh xạ sameSite từ định dạng extension sang định dạng Playwright
_SAME_SITE_MAP = {
    "no_restriction": "None",
    "unspecified": "Lax",
    "lax": "Lax",
    "strict": "Strict",
    "none": "None",
}


def normalize_cookies(raw: list[dict]) -> list[dict[str, Any]]:
    """
    Chuẩn hoá cookie xuất từ extension trình duyệt về định dạng Playwright.

    Cookie-Editor / EditThisCookie dùng `expirationDate` (float) và
    `sameSite: "no_restriction"`, còn Playwright cần `expires` và
    `sameSite: "None"` — nạp thẳng file xuất ra sẽ bị từ chối. Các khoá thừa
    (`hostOnly`, `session`, `storeId`, `id`) cũng phải loại bỏ.
    """
    cookies: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("name"):
            continue

        cookie: dict[str, Any] = {
            "name": item["name"],
            "value": str(item.get("value", "")),
            "domain": item.get("domain") or ".thuvienphapluat.vn",
            "path": item.get("path") or "/",
            "httpOnly": bool(item.get("httpOnly", False)),
            "secure": bool(item.get("secure", False)),
        }

        expires = item.get("expires", item.get("expirationDate"))
        # Cookie phiên (không có hạn) dùng -1 theo quy ước của Playwright
        cookie["expires"] = float(expires) if expires else -1

        same_site = _SAME_SITE_MAP.get(str(item.get("sameSite", "")).lower())
        if same_site:
            cookie["sameSite"] = same_site

        cookies.append(cookie)

    return cookies


class TVPLDownloader:
    """Manages a Playwright browser session for TVPL downloads."""

    def __init__(self) -> None:
        self._browser = None
        self._context = None
        self._page = None
        self._logged_in = False
        self._last_request_time = 0.0
        self._pw = None

    async def start(self) -> None:
        """Launch browser and create a context, restoring session if available."""
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )

        # Restore saved session if storage_state.json exists
        context_kwargs = {
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "viewport": {"width": 1280, "height": 800},
        }

        if STORAGE_STATE_PATH.exists():
            try:
                context_kwargs["storage_state"] = str(STORAGE_STATE_PATH)
                logger.info(
                    "Restoring TVPL session from %s", STORAGE_STATE_PATH
                )
            except Exception as e:
                logger.warning("Failed to load storage state: %s", e)

        self._context = await self._browser.new_context(**context_kwargs)

        # Nạp cookie xuất từ trình duyệt thật (nếu có) — cách duy nhất vượt được
        # Cloudflare khi chạy tự động.
        if COOKIES_PATH.exists():
            try:
                import json

                raw = json.loads(COOKIES_PATH.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    raw = raw.get("cookies", [])
                cookies = normalize_cookies(raw)
                await self._context.add_cookies(cookies)

                has_clearance = any(c["name"] == "cf_clearance" for c in cookies)
                logger.info(
                    "Loaded %d TVPL cookies from %s (cf_clearance: %s)",
                    len(cookies),
                    COOKIES_PATH,
                    "có" if has_clearance else "KHÔNG — nhiều khả năng vẫn bị chặn",
                )
            except Exception as e:
                logger.warning("Failed to load TVPL cookies: %s", e)

        self._page = await self._context.new_page()
        logger.info("Playwright browser started.")

    async def _goto(self, url: str, timeout: int = 45000) -> None:
        """
        Điều hướng tới một URL và chờ Cloudflare (nếu có) giải xong.

        Dùng 'domcontentloaded' chứ không phải 'networkidle': TVPL chạy quảng cáo
        và analytics liên tục nên mạng không bao giờ "idle" — chờ networkidle
        luôn timeout kể cả khi trang đã tải xong.
        """
        await self._page.goto(url, wait_until="domcontentloaded", timeout=timeout)

        # Thử thách Cloudflare tự giải trong vài giây nếu phiên hợp lệ
        for _ in range(6):
            if not _is_challenge_title(await self._page.title()):
                return
            await self._page.wait_for_timeout(2500)

        raise TVPLBlockedError(
            "Cloudflare đang chặn truy cập tự động vào thuvienphapluat.vn. "
            f"Xuất cookie từ trình duyệt thật ra {COOKIES_PATH} hoặc đặt "
            "TVPL_DOWNLOAD_ENABLED=false để chỉ dùng nguồn Bộ Tư pháp."
        )

    async def stop(self) -> None:
        """Save session state, then close browser and cleanup."""
        # Persist session before closing
        await self._save_session()

        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        self._logged_in = False
        logger.info("Playwright browser closed.")

    async def _save_session(self) -> None:
        """Save current browser cookies & localStorage to disk."""
        if self._context is None:
            return
        try:
            state = await self._context.storage_state()
            import json
            STORAGE_STATE_PATH.write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("TVPL session saved to %s", STORAGE_STATE_PATH)
        except Exception as e:
            logger.warning("Failed to save session state: %s", e)

    async def _is_session_valid(self) -> bool:
        """
        Quick check: navigate to TVPL homepage and see if we're logged in.
        Detects login state by looking for user profile elements.
        """
        try:
            await self._goto(TVPL_BASE_URL, timeout=30000)
            # If logged in, TVPL shows a user icon/name element
            logged_in_indicator = self._page.locator(
                '[class*="user-info"], [class*="avatar"], '
                'a[href*="logout"], a:has-text("Tài khoản"), '
                '[id*="userInfo"], [class*="logged-in"]'
            )
            is_valid = await logged_in_indicator.count() > 0
            if is_valid:
                logger.info("Existing TVPL session is still valid.")
            else:
                logger.info("TVPL session expired, re-login required.")
            return is_valid
        except TVPLBlockedError:
            raise
        except Exception as e:
            logger.warning("Session validation check failed: %s", e)
            return False

    async def login(
        self,
        username: str = TVPL_USERNAME,
        password: str = TVPL_PASSWORD,
    ) -> bool:
        """
        Login to TVPL with provided credentials.
        First checks if saved session is still valid; only re-logins if expired.
        Returns True if login successful.
        """
        if not username or not password:
            logger.warning("TVPL credentials not configured, skipping login.")
            return False

        if self._logged_in:
            logger.info("Already logged in to TVPL (this run).")
            return True

        # Check if the restored session is still valid
        if STORAGE_STATE_PATH.exists():
            if await self._is_session_valid():
                self._logged_in = True
                return True

        # Session expired or no saved state — do fresh login
        try:
            await self._rate_limit()
            await self._goto(f"{TVPL_BASE_URL}/page/login.aspx")

            # Fill login form — TVPL uses ASP.NET WebForms
            # The actual selectors may need adjustment based on current TVPL page structure
            email_input = self._page.locator(
                'input[type="email"], input[name*="Email"], input[id*="txtEmail"]'
            )
            password_input = self._page.locator(
                'input[type="password"], input[name*="Password"], input[id*="txtPassword"]'
            )

            if await email_input.count() > 0:
                await email_input.first.fill(username)
                await password_input.first.fill(password)

                # Click login button
                login_btn = self._page.locator(
                    'input[type="submit"], button[type="submit"], '
                    'a[id*="btnLogin"], input[id*="btnLogin"]'
                )
                await login_btn.first.click()
                await self._page.wait_for_load_state("networkidle")

                self._logged_in = True
                # Immediately save session so next run won't need to re-login
                await self._save_session()
                logger.info("TVPL login successful (fresh login, session saved).")
                return True
            else:
                logger.error("Could not find TVPL login form elements.")
                return False

        except TVPLBlockedError:
            raise
        except Exception as e:
            logger.error("TVPL login failed: %s", e)
            return False

    async def download_document(
        self,
        tvpl_url: str,
        doc_id: str,
    ) -> dict[str, Any]:
        """
        Navigate to a document page and download the Vietnamese version.

        Returns dict with file paths and success status:
          {
              "success": bool,
              "docx_path": str | None,
              "pdf_path": str | None,
              "error": str | None,
          }
        """
        result = {
            "success": False,
            "docx_path": None,
            "pdf_path": None,
            "error": None,
        }

        try:
            await self._rate_limit()

            # Navigate to document page
            await self._goto(tvpl_url)
            logger.info("Navigated to: %s", tvpl_url)

            # Wait for page to fully load
            await self._page.wait_for_timeout(2000)

            # Check if session was invalidated mid-run (redirect to login page)
            if "/login" in self._page.url.lower():
                logger.warning("Session invalidated mid-run, attempting re-login...")
                self._logged_in = False
                if STORAGE_STATE_PATH.exists():
                    STORAGE_STATE_PATH.unlink()
                if await self.login():
                    await self._goto(tvpl_url)
                    await self._page.wait_for_timeout(2000)
                else:
                    result["error"] = "Re-login failed"
                    return result

            # Try to download Vietnamese version
            docx_path = await self._try_download_vietnamese(doc_id)
            if docx_path:
                result["docx_path"] = str(docx_path)
                result["has_docx"] = True
                result["success"] = True
                logger.info("Downloaded .docx: %s", docx_path)

            # Try to download PDF version
            pdf_path = await self._try_download_pdf(doc_id)
            if pdf_path:
                result["pdf_path"] = str(pdf_path)
                result["has_pdf"] = True
                result["success"] = True
                logger.info("Downloaded PDF: %s", pdf_path)

        except TVPLBlockedError:
            raise
        except Exception as e:
            result["error"] = str(e)
            logger.error("Download failed for %s: %s", doc_id, e)

        return result

    async def _try_download_vietnamese(self, doc_id: str) -> Path | None:
        """
        Click the "Tải Văn bản tiếng Việt" button and save the file.
        The button triggers __doPostBack which redirects to the download URL.
        """
        try:
            # Look for the download tab first
            download_tab = self._page.locator(
                'a:has-text("Tải về"), a:has-text("Download"), '
                '[id*="tabDownload"], [class*="tab-download"]'
            )
            if await download_tab.count() > 0:
                await download_tab.first.click()
                await self._page.wait_for_timeout(1000)

            # Look for Vietnamese download link
            vn_link = self._page.locator(
                'a:has-text("Tải Văn bản tiếng Việt"), '
                'a:has-text("tiếng Việt"), '
                'a[id*="vietnameseHyperLink"], '
                'a[id*="VietLink"]'
            )

            if await vn_link.count() > 0:
                # Set up download handler
                async with self._page.expect_download(timeout=30000) as download_info:
                    await vn_link.first.click()

                download = await download_info.value
                save_path = TVPL_FILES_DIR / f"{doc_id}.docx"
                await download.save_as(str(save_path))
                return save_path

        except Exception as e:
            logger.debug("Vietnamese download attempt failed: %s", e)

        return None

    async def _try_download_pdf(self, doc_id: str) -> Path | None:
        """
        Try to download the PDF version of the document.
        TVPL embeds PDFs from files.thuvienphapluat.vn/uploads/FilePDFUpload/{id}.pdf
        """
        import httpx

        pdf_url = f"https://files.thuvienphapluat.vn/uploads/FilePDFUpload/{doc_id}.pdf"
        save_path = TVPL_FILES_DIR / f"{doc_id}.pdf"

        try:
            # Transfer cookies from Playwright to httpx for authenticated download
            cookies = await self._context.cookies()
            cookie_dict = {c["name"]: c["value"] for c in cookies}

            async with httpx.AsyncClient(cookies=cookie_dict, follow_redirects=True) as client:
                resp = await client.get(pdf_url)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    save_path.write_bytes(resp.content)
                    return save_path
        except Exception as e:
            logger.debug("PDF download attempt failed: %s", e)

        return None

    async def _rate_limit(self) -> None:
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < TVPL_RATE_LIMIT_SECONDS:
            wait = TVPL_RATE_LIMIT_SECONDS - elapsed
            logger.debug("Rate limiting: waiting %.1fs", wait)
            await asyncio.sleep(wait)
        self._last_request_time = time.time()


# ──────────────────────────────────────────────
# Convenience wrapper for synchronous usage
# ──────────────────────────────────────────────
def download_documents_sync(
    documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Synchronous wrapper to download multiple documents.
    Returns list of download results.
    """
    async def _run():
        downloader = TVPLDownloader()
        await downloader.start()
        results = []
        try:
            await downloader.login()
            for doc in documents:
                tvpl_url = doc.get("tvpl_url", "")
                tvpl_id = doc.get("tvpl_id", "")
                if tvpl_url and tvpl_id:
                    result = await downloader.download_document(tvpl_url, tvpl_id)
                    result["tvpl_id"] = tvpl_id
                    results.append(result)
        except TVPLBlockedError as e:
            # Cloudflare chặn ở cấp site: thử tiếp các văn bản còn lại chỉ tốn
            # thêm vài chục phút mà chắc chắn hỏng → dừng luôn, trả về phần đã tải.
            logger.error("Dừng tải TVPL: %s", e)
        finally:
            await downloader.stop()
        return results

    return asyncio.run(_run())
