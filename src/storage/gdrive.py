"""
Google Drive API integration with folder caching & retry logic.

Xác thực bằng OAuth (luồng Desktop app) chứ KHÔNG dùng service account:
Google cấp cho service account hạn mức lưu trữ 0 GB nên upload vào My Drive
luôn trả 403 storageQuotaExceeded. Với OAuth, file thuộc sở hữu người dùng
và hiện ngay trong My Drive của họ.

Chức năng:
  - Tự dựng cây thư mục: Gốc/{lĩnh vực}/{năm}/Thang_MM/{số hiệu}
  - Upload .docx/.pdf files
  - Return webViewLink for Telegram notifications
  - Share folders with company users

Upgrade v1.1:
  - Folder ID caching: saves folder_id map to gdrive_cache.json,
    reducing API calls by ~50% (avoids repeated folder search)
  - Exponential backoff retry for all API calls (via tenacity-style logic)
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from src.config import (
    DATA_DIR,
    GDRIVE_OAUTH_CLIENT_FILE,
    GDRIVE_OAUTH_TOKEN_FILE,
    GDRIVE_ROOT_FOLDER_ID,
    GDRIVE_ROOT_FOLDER_NAME,
    GDRIVE_SCOPES,
)

logger = logging.getLogger(__name__)

# Lazy-loaded Google API client
_service = None

# ──────────────────────────────────────────────
# Folder ID Cache
# ──────────────────────────────────────────────
_CACHE_PATH = DATA_DIR / "gdrive_cache.json"
_folder_cache: dict[str, str] = {}  # key: "parent_id/folder_name" → value: folder_id


def _load_cache() -> None:
    """Load folder ID cache from disk."""
    global _folder_cache
    if _CACHE_PATH.exists():
        try:
            _folder_cache = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
            logger.debug("Loaded GDrive folder cache: %d entries", len(_folder_cache))
        except (json.JSONDecodeError, ValueError):
            _folder_cache = {}


def _save_cache() -> None:
    """Persist folder ID cache to disk."""
    _CACHE_PATH.write_text(
        json.dumps(_folder_cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _cache_key(parent_id: str, folder_name: str) -> str:
    """Generate a cache key from parent + folder name."""
    return f"{parent_id}/{folder_name}"


def _escape_query_value(value: str) -> str:
    """Thoát ký tự cho ngôn ngữ truy vấn của Drive.

    Drive nhận điều kiện dạng name='...'; tên có dấu nháy đơn sẽ đóng chuỗi
    sớm và trả HTTP 400 "Invalid Value". Đã gặp thật với 3 văn bản mà số hiệu
    Bộ Tư pháp trả về bắt đầu bằng dấu nháy — "'18/2024/TT-BCT" — nên chúng
    không lên được Drive dù mọi văn bản khác đều xong.

    Thoát dấu chéo ngược TRƯỚC, nếu không thì dấu chéo do chính bước sau thêm
    vào lại bị thoát lần nữa.
    """
    return (value or "").replace("\\", "\\\\").replace("'", "\\'")


# Initialize cache at import time
_load_cache()


# ──────────────────────────────────────────────
# Retry with Exponential Backoff
# ──────────────────────────────────────────────
def _retry_api_call(func, *args, max_retries: int = 3, **kwargs) -> Any:
    """
    Execute a Google API call with exponential backoff retry.
    Retries on: HttpError 429/500/503, ConnectionError, TimeoutError.
    """
    from googleapiclient.errors import HttpError

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except HttpError as e:
            status = e.resp.status if hasattr(e, "resp") else 0
            if status in (429, 500, 503) and attempt < max_retries:
                wait = (2 ** attempt) + 0.5  # 1.5s, 2.5s, 4.5s
                logger.warning(
                    "GDrive API %d error (attempt %d/%d), retrying in %.1fs: %s",
                    status, attempt + 1, max_retries, wait, e,
                )
                time.sleep(wait)
                last_error = e
            else:
                raise
        except (ConnectionError, TimeoutError, OSError) as e:
            if attempt < max_retries:
                wait = (2 ** attempt) + 0.5
                logger.warning(
                    "GDrive network error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, max_retries, wait, e,
                )
                time.sleep(wait)
                last_error = e
            else:
                raise
    raise last_error  # Should not reach here, but safety net


# ──────────────────────────────────────────────
# Google Drive API Client
# ──────────────────────────────────────────────
class GoogleDriveAuthError(RuntimeError):
    """Chưa cấp quyền hoặc quyền đã mất hiệu lực."""


def load_credentials(allow_interactive: bool = False):
    """Thông tin xác thực OAuth, tự làm mới khi access token hết hạn.

    KHÔNG dùng service account: Google cấp cho service account hạn mức lưu trữ
    0 GB, nên upload vào My Drive cá nhân luôn trả 403 storageQuotaExceeded và
    không có cách nào xin thêm quota. Đó là lý do nhánh Drive cũ chưa từng chạy
    được và run_daily.sh luôn truyền --skip-gdrive.

    Với OAuth, file thuộc sở hữu người dùng và hiện ngay trong My Drive của họ.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token_file = Path(GDRIVE_OAUTH_TOKEN_FILE)
    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), list(GDRIVE_SCOPES))

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_credentials(creds)
            return creds
        except Exception as e:
            # invalid_grant = token bị thu hồi, đổi mật khẩu, hoặc màn hình chấp
            # thuận còn ở trạng thái Testing (refresh token hết hạn sau 7 ngày).
            raise GoogleDriveAuthError(
                f"Không làm mới được quyền Google Drive: {e}. "
                f"Chạy lại: python -m scripts.gdrive_check --authorize"
            ) from e

    if not allow_interactive:
        raise GoogleDriveAuthError(
            f"Chưa cấp quyền Google Drive (thiếu {token_file}). "
            f"Chạy: python -m scripts.gdrive_check --authorize"
        )

    client_file = Path(GDRIVE_OAUTH_CLIENT_FILE)
    if not client_file.exists():
        raise GoogleDriveAuthError(
            f"Thiếu file OAuth client: {client_file}. Tải từ Google Cloud Console → "
            f"Google Auth Platform → Clients → Create client → Desktop app."
        )

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client_file), list(GDRIVE_SCOPES))
    creds = flow.run_local_server(port=0)
    _save_credentials(creds)
    return creds


def _save_credentials(creds) -> None:
    path = Path(GDRIVE_OAUTH_TOKEN_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(creds.to_json(), encoding="utf-8")
    # Token là bí mật ngang mật khẩu — không để người khác trên máy đọc được.
    path.chmod(0o600)


def _get_service(allow_interactive: bool = False):
    """Lazily initialize the Google Drive API service."""
    global _service
    if _service is not None:
        return _service

    try:
        from googleapiclient.discovery import build

        creds = load_credentials(allow_interactive=allow_interactive)
        _service = build("drive", "v3", credentials=creds)
        logger.info("Google Drive API client initialized.")
        return _service
    except GoogleDriveAuthError as e:
        logger.warning("Google Drive: %s", e)
        return None
    except Exception as e:
        logger.error("Failed to initialize Google Drive API: %s", e)
        return None


def ensure_folder(parent_id: str, folder_name: str) -> str | None:
    """
    Find or create a folder under parent_id.
    Uses local cache to avoid redundant API calls.
    Returns the folder's ID, or None if Drive is not configured.
    """
    service = _get_service()
    if not service:
        return None

    # Check cache first
    key = _cache_key(parent_id, folder_name)
    if key in _folder_cache:
        cached_id = _folder_cache[key]
        logger.debug("GDrive folder cache hit: %s → %s", folder_name, cached_id)
        return cached_id

    # Cache miss — search via API (with retry)
    query = (
        f"name='{_escape_query_value(folder_name)}' and "
        f"'{_escape_query_value(parent_id)}' in parents and "
        f"mimeType='application/vnd.google-apps.folder' and "
        f"trashed=false"
    )
    results = _retry_api_call(
        lambda: service.files().list(q=query, fields="files(id, name)").execute()
    )
    files = results.get("files", [])

    if files:
        folder_id = files[0]["id"]
        # Update cache
        _folder_cache[key] = folder_id
        _save_cache()
        return folder_id

    # Create new folder (with retry)
    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = _retry_api_call(
        lambda: service.files().create(body=metadata, fields="id").execute()
    )
    folder_id = folder.get("id")
    logger.info("Created Google Drive folder: %s (%s)", folder_name, folder_id)

    # Update cache
    _folder_cache[key] = folder_id
    _save_cache()

    return folder_id


def _looks_like_placeholder(value: str) -> bool:
    """Giá trị mẫu chép từ .env.example, không phải id thật.

    Id thư mục Drive là chuỗi 28–44 ký tự [A-Za-z0-9_-], không có chữ tiếng Anh
    dễ đọc. Kiểm bằng mắt thì hiển nhiên, nhưng code cũ chỉ kiểm "khác rỗng" nên
    "1ABCxyz_your_folder_id_here" lọt qua và mọi lần upload báo 404 File not
    found — thông báo không hề gợi ý nguyên nhân thật.
    """
    lowered = value.strip().lower()
    return any(marker in lowered for marker in
               ("your", "xxx", "here", "example", "thay-bang", "thay_bang"))


def ensure_root_folder() -> str | None:
    """Thư mục gốc của kho, tạo mới nếu chưa có.

    Phạm vi drive.file chỉ cho ghi vào file và thư mục do CHÍNH ứng dụng tạo,
    nên không dùng lại được một thư mục người dùng tạo tay. Lần chạy đầu tự tạo
    rồi in id ra để ghi vào .env.
    """
    if GDRIVE_ROOT_FOLDER_ID and not _looks_like_placeholder(GDRIVE_ROOT_FOLDER_ID):
        return GDRIVE_ROOT_FOLDER_ID
    if GDRIVE_ROOT_FOLDER_ID:
        logger.warning(
            "GDRIVE_ROOT_FOLDER_ID=%r trông như giá trị mẫu — bỏ qua và tạo "
            "thư mục mới.", GDRIVE_ROOT_FOLDER_ID,
        )

    service = _get_service()
    if not service:
        return None
    try:
        folder = _retry_api_call(
            lambda: service.files()
            .create(
                body={
                    "name": GDRIVE_ROOT_FOLDER_NAME,
                    "mimeType": "application/vnd.google-apps.folder",
                },
                fields="id",
            )
            .execute()
        )
        logger.warning(
            "Đã tạo thư mục gốc %r trên Google Drive. Ghi vào .env:\n"
            "  GDRIVE_ROOT_FOLDER_ID=%s",
            GDRIVE_ROOT_FOLDER_NAME, folder["id"],
        )
        return folder["id"]
    except Exception as e:
        logger.error("Không tạo được thư mục gốc trên Google Drive: %s", e)
        return None


def _safe_name(name: str) -> str:
    """Tên an toàn cho thư mục/file trên Drive."""
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", (name or "").strip())
    return cleaned[:120] or "Khong_ro"


def _year_month(doc_data: dict[str, Any]) -> tuple[str, str]:
    """(năm, tháng) để xếp thư mục, có đường lùi khi thiếu ngày ban hành.

    Bản cũ thoát sớm khi thiếu issue_date nên văn bản không rõ ngày không bao
    giờ được upload — im lặng mất hẳn khỏi Drive. Lùi dần theo cùng thứ tự mà
    lark_drive._parse_year_month đã dùng.
    """
    for key in ("issue_date", "pub_date", "created_at"):
        value = doc_data.get(key)
        if value is None:
            continue
        year = getattr(value, "year", None)
        month = getattr(value, "month", None)
        if year and month:
            return str(year), f"Thang_{month:02d}"
    return "Chua_Phan_Loai", "Chua_Phan_Loai"


def ensure_folder_path(doc_data: dict[str, Any]) -> str | None:
    """Thư mục lá cho một văn bản: Gốc / Lĩnh vực / Năm / Tháng_MM / Số hiệu."""
    root = ensure_root_folder()
    if not root:
        return None

    year, month = _year_month(doc_data)
    parts = [
        _safe_name(doc_data.get("field_name") or "Chua_Phan_Loai"),
        year,
        month,
        _safe_name(doc_data.get("doc_num") or "Khong_so"),
    ]

    folder_id = root
    for part in parts:
        folder_id = ensure_folder(folder_id, part)
        if not folder_id:
            return None
    return folder_id


def upload_file(
    local_path: str | Path,
    folder_id: str,
    filename: str | None = None,
) -> dict[str, str] | None:
    """
    Upload a file to Google Drive with retry.
    Returns {"id": ..., "webViewLink": ...} or None.
    """
    service = _get_service()
    if not service:
        return None

    local_path = Path(local_path)
    if not local_path.exists():
        logger.error("File not found: %s", local_path)
        return None

    if filename is None:
        filename = local_path.name

    # Determine MIME type
    suffix = local_path.suffix.lower()
    mime_map = {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".pdf": "application/pdf",
        ".html": "text/html",
        ".md": "text/markdown",
        ".json": "application/json",
    }
    mime_type = mime_map.get(suffix, "application/octet-stream")

    try:
        from googleapiclient.http import MediaFileUpload

        metadata = {
            "name": filename,
            "parents": [folder_id],
        }
        media = MediaFileUpload(str(local_path), mimetype=mime_type)

        file = _retry_api_call(
            lambda: service.files()
            .create(body=metadata, media_body=media, fields="id, webViewLink")
            .execute()
        )

        # Make file accessible via link (anyone with link can view)
        _retry_api_call(
            lambda: service.permissions()
            .create(
                fileId=file["id"],
                body={"type": "anyone", "role": "reader"},
            )
            .execute()
        )

        logger.info(
            "Uploaded to Google Drive: %s → %s",
            filename,
            file.get("webViewLink"),
        )
        return {
            "id": file["id"],
            "webViewLink": file.get("webViewLink", ""),
        }

    except Exception as e:
        logger.error("Google Drive upload failed for %s: %s", filename, e)
        return None


def upload_document_files(doc_data: dict[str, Any]) -> dict[str, Any]:
    """Đẩy trọn hồ sơ một văn bản lên Google Drive.

    Mỗi văn bản một thư mục riêng gồm bốn file, để mở thư mục là đọc được đầy đủ
    mà không cần truy cập cơ sở dữ liệu — giống cách nhánh Lark đang làm:
      {số hiệu}.docx              bản biên tập TVPL (nếu tải được)
      {số hiệu}_BoTuPhap.html     toàn văn gốc từ Bộ Tư pháp
      {số hiệu}_BoTuPhap.md       toàn văn đã làm sạch
      {số hiệu}_metadata.json     hồ sơ dữ kiện

    Trả về cả `failed` để bên gọi biết file nào cần xếp vào hàng đợi thử lại,
    thay vì lặng lẽ coi như xong.
    """
    result: dict[str, Any] = {
        "gdrive_docx_link": None,
        "gdrive_fulltext_link": None,
        "gdrive_folder_id": None,
        "uploaded": [],
        "failed": [],
    }

    folder_id = ensure_folder_path(doc_data)
    if not folder_id:
        result["failed"] = ["folder"]
        return result

    result["gdrive_folder_id"] = folder_id
    safe = _safe_name(doc_data.get("doc_num") or "Khong_so")

    plan: list[tuple[str, Any, str, str]] = [
        ("docx", doc_data.get("docx_path"), f"{safe}.docx", "gdrive_docx_link"),
        ("fulltext", doc_data.get("fulltext_path"), f"{safe}_BoTuPhap.html",
         "gdrive_fulltext_link"),
        ("clean_text", doc_data.get("clean_text_path"), f"{safe}_BoTuPhap.md", ""),
        ("metadata", doc_data.get("metadata_path"), f"{safe}_metadata.json", ""),
    ]

    for kind, local_path, filename, link_key in plan:
        if not local_path or not Path(local_path).exists():
            continue
        uploaded = upload_file(local_path, folder_id, filename)
        if uploaded:
            result["uploaded"].append(kind)
            if link_key:
                result[link_key] = uploaded["webViewLink"]
        else:
            result["failed"].append(kind)

    return result


def invalidate_cache() -> None:
    """Clear the folder cache (use if folders are reorganized)."""
    global _folder_cache
    _folder_cache = {}
    if _CACHE_PATH.exists():
        _CACHE_PATH.unlink()
    logger.info("GDrive folder cache invalidated.")
