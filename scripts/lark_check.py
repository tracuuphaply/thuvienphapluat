"""
Kiểm tra kết nối & quyền ghi vào Lark Drive.

Chạy:  python scripts/lark_check.py

Script trả lời đúng một câu hỏi: các file tải về sẽ nằm ở thư mục nào, và
người dùng có mở được thư mục đó không.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import LARK_APP_ID, LARK_ROOT_FOLDER_TOKEN  # noqa: E402
from src.storage.lark_drive import get_lark_client  # noqa: E402

HUONG_DAN = """
Cách cấu hình đúng:

  1. Mở Lark Drive → vào "Thư mục của tôi" → tạo (hoặc chọn) thư mục gốc,
     ví dụ: Legal_document_library
  2. Bấm chuột phải vào thư mục → Chia sẻ → tìm tên app (Legal Storage Bot)
     → cấp quyền "Có thể chỉnh sửa"
  3. Mở thư mục đó, copy đoạn mã trên URL:
        https://<tenant>.larksuite.com/drive/folder/FLDxxxxxxxxxxxx
                                                    ^^^^^^^^^^^^^^^ token
  4. Dán vào .env:  LARK_ROOT_FOLDER_TOKEN=FLDxxxxxxxxxxxx

Lý do bắt buộc bước này: Lark KHÔNG có API để chia sẻ một thư mục do app tạo.
Nếu để trống, app sẽ ghi vào "My Space" riêng của nó — thư mục tồn tại thật
nhưng không tài khoản người dùng nào mở được ("Bạn không có quyền truy cập").
"""


def main() -> int:
    print("=" * 60)
    print("Kiểm tra Lark Drive")
    print("=" * 60)
    print(f"LARK_APP_ID            : {LARK_APP_ID or '(trống)'}")
    print(f"LARK_ROOT_FOLDER_TOKEN : {LARK_ROOT_FOLDER_TOKEN or '(trống)'}")
    print()

    client = get_lark_client()
    access = client.check_access()

    if not access["ok"]:
        print(f"❌ {access['reason']}")
        print(HUONG_DAN)
        return 1

    print("✅ Đọc được thư mục gốc.")

    # Thử ghi thật — quyền đọc không đảm bảo có quyền tạo thư mục
    try:
        token = client.get_or_create_folder(LARK_ROOT_FOLDER_TOKEN, "_kiem_tra_ghi")
    except Exception as e:
        print(f"❌ Không tạo được thư mục con: {e}")
        print(HUONG_DAN)
        return 1

    print("✅ Ghi được vào thư mục gốc.")
    print()
    print(f"Kho lưu trữ : {access['folder_url']}")
    print(f"Thư mục test: {client.build_folder_url(token)}")
    print()
    print("Có thể xoá thư mục '_kiem_tra_ghi' trên Lark sau khi kiểm tra xong.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
