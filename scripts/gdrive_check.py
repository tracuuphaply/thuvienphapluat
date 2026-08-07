"""
Kiểm tra kết nối Google Drive trước khi bật nó làm nơi lưu trữ chính.

Đối xứng với scripts/lark_check.py. Chạy cái này TRƯỚC khi đổi
CLOUD_DRIVE_PROVIDER=gdrive, nếu không lỗi cấu hình chỉ lộ ra giữa một lượt cào
và văn bản sẽ nằm lại hàng đợi mà không ai biết.

    python -m scripts.gdrive_check --authorize   # lần đầu, mở trình duyệt
    python -m scripts.gdrive_check               # các lần sau, kiểm im lặng

Hai lỗi hay gặp mà script này bắt được:

  1. Màn hình chấp thuận còn ở trạng thái "Testing" → refresh token hết hạn sau
     đúng 7 ngày và pipeline chạy hằng ngày sẽ chết câm. Phải vào Google Auth
     Platform → tab Audience → PUBLISH APP.
  2. Trỏ GDRIVE_ROOT_FOLDER_ID tới thư mục tạo tay → ghi vào báo lỗi, vì phạm vi
     drive.file chỉ cho ghi vào thư mục do chính ứng dụng tạo. Để trống biến này
     và script sẽ tự tạo thư mục gốc.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config import (
    GDRIVE_OAUTH_CLIENT_FILE,
    GDRIVE_OAUTH_TOKEN_FILE,
    GDRIVE_ROOT_FOLDER_ID,
    GDRIVE_SCOPES,
)
from src.storage import gdrive

logger = logging.getLogger(__name__)

# Refresh token do ứng dụng chưa publish cấp sẽ hết hạn sau 7 ngày. Cảnh báo
# sớm hơn mốc đó để còn kịp xử lý trước khi lượt cào hằng ngày gãy.
TESTING_TOKEN_LIFETIME = timedelta(days=7)


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")


def check(authorize: bool) -> int:
    print("=== Kiểm tra kết nối Google Drive ===\n")

    print("1. File cấu hình")
    client = Path(GDRIVE_OAUTH_CLIENT_FILE)
    if client.exists():
        _ok(f"OAuth client: {client}")
    else:
        _fail(f"Thiếu OAuth client: {client}")
        print("     Google Cloud Console → Google Auth Platform → tab Clients")
        print("     → Create client → Desktop app → Download JSON")
        return 1
    print(f"  · phạm vi quyền: {', '.join(GDRIVE_SCOPES)}")

    print("\n2. Xác thực")
    try:
        creds = gdrive.load_credentials(allow_interactive=authorize)
    except gdrive.GoogleDriveAuthError as e:
        _fail(str(e))
        return 1
    _ok(f"Đã có quyền, token lưu tại {GDRIVE_OAUTH_TOKEN_FILE}")

    if not creds.refresh_token:
        _fail("Không có refresh token — mỗi lần chạy sẽ phải cấp quyền lại")
        return 1
    _ok("Có refresh token (chạy nền được)")

    print("\n3. Trạng thái publish của màn hình chấp thuận")
    # Không có API công khai nào trả về trạng thái này, nên suy gián tiếp từ
    # hạn dùng của token: ứng dụng còn ở Testing thì Google chỉ cấp 7 ngày.
    expiry = getattr(creds, "expiry", None)
    print("  · Google không có API trả về trạng thái publish, phải tự kiểm bằng mắt:")
    print("    Google Auth Platform → tab Audience → phải hiện 'In production'.")
    print("    Còn 'Testing' thì refresh token hết hạn sau đúng 7 ngày.")
    if expiry:
        remaining = expiry.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)
        print(f"  · access token hiện tại còn {remaining.total_seconds()/60:.0f} phút "
              "(bình thường, khác với refresh token)")

    print("\n4. Thư mục gốc")
    root = gdrive.ensure_root_folder()
    if not root:
        _fail("Không tạo/tìm được thư mục gốc")
        return 1
    if GDRIVE_ROOT_FOLDER_ID:
        _ok(f"Dùng thư mục có sẵn: {root}")
    else:
        _ok(f"Vừa tạo thư mục gốc: {root}")
        print(f"     Ghi vào .env:  GDRIVE_ROOT_FOLDER_ID={root}")

    print("\n5. Thử ghi rồi xoá")
    service = gdrive._get_service()
    tmp = Path(GDRIVE_OAUTH_TOKEN_FILE).parent / "_gdrive_check.txt"
    tmp.write_text("kiem tra ket noi\n", encoding="utf-8")
    try:
        uploaded = gdrive.upload_file(tmp, root, "_kiem_tra_ket_noi.txt")
        if not uploaded:
            _fail("Upload thất bại — xem log ở trên")
            return 1
        _ok(f"Ghi được: {uploaded['webViewLink']}")
        service.files().delete(fileId=uploaded["id"]).execute()
        _ok("Xoá được file thử")
    except Exception as e:
        _fail(f"Lỗi khi thử ghi/xoá: {e}")
        return 1
    finally:
        tmp.unlink(missing_ok=True)

    print("\n=== Kết nối Google Drive sẵn sàng ===")
    print("Bật bằng cách đặt trong .env:  CLOUD_DRIVE_PROVIDER=gdrive")
    return 0


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorize", action="store_true",
                        help="Mở trình duyệt để cấp quyền lần đầu")
    args = parser.parse_args()
    sys.exit(check(args.authorize))


if __name__ == "__main__":
    main()
