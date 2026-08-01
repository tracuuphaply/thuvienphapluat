"""
Lark Drive (Feishu Drive) integration with folder caching.

Uses Lark OpenAPI to:
  - Obtain tenant_access_token using App ID & App Secret
  - Auto-discover root folder and tenant domain for correct URLs
  - Auto-create nested folder structure in Lark Drive: {field}/{year}/{month}
  - Upload .docx/.pdf files using Lark Drive upload_all API
  - Set public/tenant view permissions
  - Return clickable view links for Telegram notifications
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import httpx

from src.config import (
    DATA_DIR,
    LARK_APP_ID,
    LARK_APP_SECRET,
    LARK_DOMAIN,
    LARK_FOLDER_PER_DOC,
    LARK_ROOT_FOLDER_TOKEN,
)

logger = logging.getLogger(__name__)

# Cache for folder tokens
_CACHE_PATH = DATA_DIR / "lark_cache.json"
_folder_cache: dict[str, str] = {}  # key: "parent_token/folder_name" -> value: folder_token


def _load_cache() -> None:
    global _folder_cache
    if _CACHE_PATH.exists():
        try:
            _folder_cache = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
            logger.debug("Loaded Lark folder cache: %d entries", len(_folder_cache))
        except Exception:
            _folder_cache = {}


def _save_cache() -> None:
    try:
        _CACHE_PATH.write_text(
            json.dumps(_folder_cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("Failed to save Lark folder cache: %s", e)


_load_cache()


def _safe_name(name: str) -> str:
    """
    Chuẩn hoá tên thư mục/file cho Lark Drive.

    Số hiệu văn bản chứa dấu '/' (292/2026/NĐ-CP) nên phải thay bằng '_', nếu
    không Lark sẽ hiểu thành đường dẫn lồng nhau.
    """
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", str(name)).strip(" ._")
    return cleaned[:120] or "Khong_ro"


def _parse_year_month(value: Any) -> tuple[str, str] | tuple[None, None]:
    """
    Tách (năm, 'Thang_MM') từ một giá trị ngày để đặt tên thư mục.

    Chấp nhận YYYY-MM-DD, DD/MM/YYYY và cả chuỗi RFC 822 của RSS
    ('Mon, 21 Jul 2026 10:00:00 GMT'). Trả (None, None) nếu không nhận dạng được.
    """
    if not value:
        return None, None

    text = str(value).strip()

    match = re.search(r"(\d{4})-(\d{2})-\d{2}", text)
    if match:
        return match.group(1), f"Thang_{match.group(2)}"

    match = re.search(r"\d{1,2}/(\d{2})/(\d{4})", text)
    if match:
        return match.group(2), f"Thang_{match.group(1)}"

    match = re.search(
        r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d{4})",
        text,
    )
    if match:
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        return match.group(3), f"Thang_{months.index(match.group(2)) + 1:02d}"

    return None, None


class LarkDriveClient:
    """Lark/Feishu OpenAPI Drive client."""

    def __init__(self) -> None:
        self.app_id = LARK_APP_ID
        self.app_secret = LARK_APP_SECRET
        self.api_domain = LARK_DOMAIN or "open.larksuite.com"
        self.api_base_url = f"https://{self.api_domain}"
        self.root_folder_token = LARK_ROOT_FOLDER_TOKEN

        # Tenant domain for user-facing URLs (auto-discovered from API responses)
        self._tenant_domain: str = ""

        self._token = ""
        self._token_expires_at = 0.0

    def get_tenant_access_token(self) -> str:
        """Fetch or refresh tenant_access_token."""
        if not self.app_id or not self.app_secret:
            raise ValueError("LARK_APP_ID and LARK_APP_SECRET must be configured in .env")

        now = time.time()
        if self._token and now < self._token_expires_at - 60:
            return self._token

        url = f"{self.api_base_url}/open-apis/auth/v3/tenant_access_token/internal"
        resp = httpx.post(
            url,
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=15.0,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Failed to get Lark access token: {data.get('msg')}")

        self._token = data["tenant_access_token"]
        # token expires in ~7200 seconds
        self._token_expires_at = now + data.get("expire", 7200)
        logger.info("Obtained Lark tenant_access_token successfully.")
        return self._token

    def _headers(self) -> dict[str, str]:
        token = self.get_tenant_access_token()
        return {"Authorization": f"Bearer {token}"}

    def _note_domain(self, url: str) -> None:
        """
        Ghi nhận domain tenant từ bất kỳ URL nào Lark trả về.

        Link mở được cho người dùng nằm ở domain tenant
        (vd. ljp1vynvu13j.jp.larksuite.com), khác domain gọi API
        (open.larksuite.com) — lấy nhầm thì link gửi qua Telegram sẽ hỏng.
        """
        if self._tenant_domain or not url.startswith("https://"):
            return
        parts = url.split("/")
        if len(parts) >= 3 and parts[2]:
            self._tenant_domain = parts[2]
            logger.info("Discovered Lark tenant domain: %s", self._tenant_domain)

    def _discover_tenant_domain(self) -> str:
        """Auto-discover tenant domain from Lark API list-files response."""
        if self._tenant_domain:
            return self._tenant_domain

        # List root folder to extract tenant URL domain from the response
        headers = self._headers()
        url = (
            f"{self.api_base_url}/open-apis/drive/v1/files"
            f"?folder_token={LARK_ROOT_FOLDER_TOKEN}&page_size=1"
        )
        try:
            resp = httpx.get(url, headers=headers, timeout=15.0)
            for item in resp.json().get("data", {}).get("files", []):
                self._note_domain(item.get("url", ""))
                if self._tenant_domain:
                    return self._tenant_domain
        except Exception as e:
            logger.warning("Failed to auto-discover tenant domain: %s", e)

        # Fallback: dùng tạm domain API, KHÔNG cache — thư mục có thể đang rỗng,
        # lần gọi sau (khi đã có file) mới lấy được domain tenant thật.
        return self.api_domain

    def _discover_root_folder_token(self) -> str:
        """
        Trả về thư mục gốc để lưu văn bản.

        LARK_ROOT_FOLDER_TOKEN phải trỏ tới một thư mục do người dùng tạo trong
        Lark Drive và đã chia sẻ quyền chỉnh sửa cho app. Nếu để trống, API sẽ
        trả về "My Space" của chính con bot — thư mục này KHÔNG ai mở được
        (Lark không có API chia sẻ thư mục), nên phải cảnh báo rõ thay vì lặng
        lẽ ghi vào đó.
        """
        if self.root_folder_token:
            return self.root_folder_token

        headers = self._headers()
        url = f"{self.api_base_url}/open-apis/drive/explorer/v2/root_folder/meta"
        try:
            resp = httpx.get(url, headers=headers, timeout=15.0)
            data = resp.json()
            if data.get("code") == 0:
                token = data.get("data", {}).get("token", "")
                if token:
                    self.root_folder_token = token
                    logger.warning(
                        "LARK_ROOT_FOLDER_TOKEN chưa được cấu hình — đang dùng "
                        "My Space của app (%s). Người dùng sẽ KHÔNG mở được các "
                        "thư mục này. Hãy tạo thư mục trong Lark Drive, chia sẻ "
                        "quyền chỉnh sửa cho app rồi điền token vào .env.",
                        token,
                    )
                    return token
        except Exception as e:
            logger.warning("Failed to auto-discover root folder token: %s", e)

        return ""

    def check_access(self) -> dict[str, Any]:
        """
        Kiểm tra app có ghi được vào LARK_ROOT_FOLDER_TOKEN không.

        Trả {"ok": bool, "reason": str, "folder_url": str} — dùng cho script
        chẩn đoán và cho cảnh báo sớm khi chạy pipeline.
        """
        if not self.app_id or not self.app_secret:
            return {"ok": False, "reason": "Thiếu LARK_APP_ID / LARK_APP_SECRET", "folder_url": ""}

        if not LARK_ROOT_FOLDER_TOKEN:
            return {
                "ok": False,
                "reason": (
                    "LARK_ROOT_FOLDER_TOKEN đang để trống → file sẽ nằm trong "
                    "My Space của app và không ai truy cập được"
                ),
                "folder_url": "",
            }

        try:
            resp = httpx.get(
                f"{self.api_base_url}/open-apis/drive/v1/files",
                headers=self._headers(),
                params={"folder_token": LARK_ROOT_FOLDER_TOKEN, "page_size": "1"},
                timeout=20.0,
            )
            data = resp.json()
        except Exception as e:
            return {"ok": False, "reason": f"Lỗi gọi API Lark: {e}", "folder_url": ""}

        if data.get("code") != 0:
            return {
                "ok": False,
                "reason": (
                    f"Không đọc được thư mục ({data.get('msg')}). Hãy mở thư mục "
                    "trong Lark Drive → Chia sẻ → thêm app với quyền chỉnh sửa."
                ),
                "folder_url": "",
            }

        return {
            "ok": True,
            "reason": "OK",
            "folder_url": self.build_folder_url(LARK_ROOT_FOLDER_TOKEN),
        }

    def build_file_url(self, file_token: str) -> str:
        """Build a clickable user-facing URL for a Lark Drive file."""
        domain = self._discover_tenant_domain()
        return f"https://{domain}/file/{file_token}"

    def build_folder_url(self, folder_token: str) -> str:
        """Build a clickable user-facing URL for a Lark Drive folder."""
        domain = self._discover_tenant_domain()
        return f"https://{domain}/drive/folder/{folder_token}"


    def get_or_create_folder(self, parent_token: str, folder_name: str) -> str:
        """Find existing folder or create new one under parent_token.

        First checks local cache, then lists the parent folder's children
        to avoid creating duplicate folders when the cache is cleared.
        """
        cache_key = f"{parent_token}/{folder_name}"
        if cache_key in _folder_cache:
            return _folder_cache[cache_key]

        headers = self._headers()

        # Step 1: Search for existing folder by listing parent's children
        list_url = f"{self.api_base_url}/open-apis/drive/v1/files"
        params = {"folder_token": parent_token or "", "page_size": "200"}
        try:
            resp = httpx.get(list_url, headers=headers, params=params, timeout=20.0)
            data = resp.json()
            if data.get("code") == 0:
                for item in data.get("data", {}).get("files", []):
                    self._note_domain(item.get("url", ""))
                    if item.get("type") == "folder" and item.get("name") == folder_name:
                        folder_token = item["token"]
                        _folder_cache[cache_key] = folder_token
                        _save_cache()
                        logger.info("Found existing Lark folder: '%s' (token: %s)", folder_name, folder_token)
                        return folder_token
        except Exception as e:
            logger.warning("Failed to list parent folder %s: %s", parent_token, e)

        # Step 2: Folder not found, create it
        create_url = f"{self.api_base_url}/open-apis/drive/v1/files/create_folder"
        payload = {
            "name": folder_name,
            "folder_token": parent_token or "",
        }

        resp = httpx.post(create_url, headers=headers, json=payload, timeout=20.0)
        data = resp.json()

        if data.get("code") == 0:
            folder_token = data.get("data", {}).get("token", "")
            self._note_domain(data.get("data", {}).get("url", ""))
            if folder_token:
                _folder_cache[cache_key] = folder_token
                _save_cache()
                logger.info("Created Lark folder: '%s' (token: %s)", folder_name, folder_token)
                return folder_token

        # Không fallback về My Space của app: thư mục tạo ở đó không ai mở được,
        # và lỗi sẽ bị che mất cho tới khi người dùng bấm vào link hỏng.
        raise RuntimeError(
            f"Không tạo được thư mục Lark '{folder_name}' trong {parent_token or 'My Space'}: "
            f"{data.get('msg')} (code {data.get('code')}). "
            "Kiểm tra app đã được chia sẻ quyền chỉnh sửa vào LARK_ROOT_FOLDER_TOKEN chưa."
        )

    def get_path_folder_token(
        self,
        field_name: str,
        issue_date: str,
        doc_num: str = "",
        fallback_date: str = "",
    ) -> str:
        """
        Build or get nested folder token:
            Root / {Lĩnh vực} / {Năm} / {Tháng} / {Số hiệu VB}

        Thư mục con theo số hiệu gom mọi nguồn của cùng một văn bản (file .docx/
        .pdf tải từ TVPL và toàn văn + metadata từ Bộ Tư pháp) vào một chỗ.

        `fallback_date` (ngày đăng RSS / ngày thu thập) dùng khi chưa biết ngày
        ban hành — văn bản chỉ có trên TVPL không có ngày ban hành, xếp hết vào
        một thư mục "Chua_Phan_Loai" thì kho không còn duyệt được theo thời gian.
        """
        # Auto-discover root folder token if empty
        curr_token = self._discover_root_folder_token()

        year_str, month_str = _parse_year_month(issue_date)
        if year_str is None:
            year_str, month_str = _parse_year_month(fallback_date)
        if year_str is None:
            year_str, month_str = "Chua_Phan_Loai", "Chua_Phan_Loai"

        # Create nested folders
        curr_token = self.get_or_create_folder(curr_token, _safe_name(field_name or "Chung"))
        curr_token = self.get_or_create_folder(curr_token, year_str)
        curr_token = self.get_or_create_folder(curr_token, month_str)

        if LARK_FOLDER_PER_DOC and doc_num:
            curr_token = self.get_or_create_folder(curr_token, _safe_name(doc_num))

        return curr_token


    def upload_file(
        self,
        file_path: str | Path,
        parent_folder_token: str,
        file_name: str = "",
    ) -> dict[str, str]:
        """
        Upload a file to Lark Drive.

        `file_name` cho phép đặt lại tên hiển thị (vd. '292_2026_NĐ-CP.docx')
        thay vì tên file nội bộ theo ID.

        Returns dict: {"file_token": str, "view_link": str}
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        upload_name = _safe_name(file_name) if file_name else path.name
        file_size = path.stat().st_size
        token = self.get_tenant_access_token()

        url = f"{self.api_base_url}/open-apis/drive/v1/files/upload_all"

        headers = {
            "Authorization": f"Bearer {token}",
        }

        data = {
            "file_name": upload_name,
            "parent_type": "explorer",
            "parent_node": parent_folder_token,
            "size": str(file_size),
        }

        with open(path, "rb") as f:
            files = {"file": (upload_name, f, "application/octet-stream")}
            resp = httpx.post(url, headers=headers, data=data, files=files, timeout=120.0)

        res_json = resp.json()
        if res_json.get("code") != 0:
            logger.error("Lark file upload error for %s: %s", upload_name, res_json)
            raise RuntimeError(f"Lark file upload failed: {res_json.get('msg')}")

        file_token = res_json.get("data", {}).get("file_token", "")

        # Set permission to anyone with link / tenant can view
        self._set_file_permission(file_token)

        # Build user-facing URL with tenant domain (not API domain)
        view_link = self.build_file_url(file_token)
        logger.info("Uploaded to Lark Drive: %s -> %s", upload_name, view_link)

        return {
            "file_token": file_token,
            "view_link": view_link,
        }

    def _set_file_permission(self, file_token: str) -> None:
        """
        Cho phép mọi thành viên trong tổ chức mở file bằng link.

        Chỉ gửi đúng `link_share_entity`: các khoá kiểu cũ (`external_access`,
        `share_entity`…) và giá trị `anyone_usable` bị API v1 trả 400.
        """
        if not file_token:
            return
        try:
            token = self.get_tenant_access_token()
            url = f"{self.api_base_url}/open-apis/drive/v1/permissions/{file_token}/public?type=file"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            resp = httpx.patch(
                url,
                headers=headers,
                json={"link_share_entity": "tenant_readable"},
                timeout=10.0,
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.warning(
                    "Lark permission not applied for %s: %s", file_token, data.get("msg")
                )
        except Exception as e:
            logger.warning("Failed to set Lark file permission for %s: %s", file_token, e)


# Global instance
_lark_client: LarkDriveClient | None = None


def get_lark_client() -> LarkDriveClient:
    global _lark_client
    if _lark_client is None:
        _lark_client = LarkDriveClient()
    return _lark_client


def upload_document_files_lark(doc_data: dict[str, Any]) -> dict[str, Any]:
    """
    Đẩy toàn bộ dữ liệu của một văn bản lên Lark Drive.

    Mỗi văn bản có một thư mục riêng chứa dữ liệu của cả hai nguồn:
      - TVPL:       <số hiệu>.docx, <số hiệu>.pdf
      - Bộ Tư pháp: <số hiệu>_BoTuPhap.md (toàn văn đã làm sạch),
                    <số hiệu>_BoTuPhap.html (toàn văn gốc)

    Returns dict matching document link fields:
      {
          "lark_docx_link": str | None,
          "lark_pdf_link": str | None,
          "lark_fulltext_link": str | None,   # toàn văn từ Bộ Tư pháp
          "lark_folder_token": str | None,
          "lark_folder_url": str | None,      # clickable URL to the storage folder
          "gdrive_docx_link": str | None,     # for backward compatibility
          "gdrive_pdf_link": str | None,      # for backward compatibility
      }
    """
    client = get_lark_client()
    result: dict[str, Any] = {
        "lark_docx_link": None,
        "lark_pdf_link": None,
        "lark_fulltext_link": None,
        "lark_folder_token": None,
        "lark_folder_url": None,
        "gdrive_docx_link": None,
        "gdrive_pdf_link": None,
    }

    doc_num = str(doc_data.get("doc_num") or "")
    base = _safe_name(doc_num)

    # (khoá kết quả, đường dẫn local, tên hiển thị trên Lark)
    uploads = [
        ("lark_docx_link", doc_data.get("docx_path"), f"{base}.docx"),
        ("lark_pdf_link", doc_data.get("pdf_path"), f"{base}.pdf"),
        ("lark_fulltext_link", doc_data.get("clean_text_path"), f"{base}_BoTuPhap.md"),
        (None, doc_data.get("fulltext_path"), f"{base}_BoTuPhap.html"),
        (None, doc_data.get("metadata_path"), f"{base}_metadata.json"),
    ]
    uploads = [(k, p, n) for k, p, n in uploads if p and Path(p).exists()]

    if not uploads:
        return result

    field_name = doc_data.get("field_name", "")
    issue_date = str(doc_data.get("issue_date", ""))

    try:
        # Ngày dự phòng: ngày đăng RSS (lần chạy pipeline) hoặc ngày ghi vào DB
        fallback_date = str(
            doc_data.get("pub_date") or doc_data.get("created_at") or ""
        )
        folder_token = client.get_path_folder_token(
            field_name, issue_date, doc_num, fallback_date
        )
        result["lark_folder_token"] = folder_token
        result["lark_folder_url"] = client.build_folder_url(folder_token)

        for key, local_path, display_name in uploads:
            try:
                uploaded = client.upload_file(local_path, folder_token, display_name)
            except Exception as e:
                logger.warning("Lark upload failed for %s: %s", display_name, e)
                continue
            if key:
                result[key] = uploaded["view_link"]

        # Giữ tương thích ngược với các cột gdrive_* đang dùng ở nơi khác
        result["gdrive_docx_link"] = result["lark_docx_link"]
        result["gdrive_pdf_link"] = result["lark_pdf_link"]

    except Exception as e:
        logger.error("Lark Drive upload error for %s: %s", doc_data.get("doc_num"), e)

    return result


def get_lark_root_folder_url() -> str | None:
    """Get the URL to the Lark Drive root folder for browsing."""
    try:
        client = get_lark_client()
        root_token = client._discover_root_folder_token()
        if root_token:
            return client.build_folder_url(root_token)
    except Exception as e:
        logger.warning("Could not get Lark root folder URL: %s", e)
    return None
