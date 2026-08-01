"""
Configuration module — loads .env and defines constants.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ──────────────────────────────────────────────
# Database
# ──────────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite+aiosqlite:///{PROJECT_ROOT / 'data' / 'legal_docs.db'}",
)

# ──────────────────────────────────────────────
# TVPL (Thư viện Pháp luật)
# ──────────────────────────────────────────────
TVPL_USERNAME = os.getenv("TVPL_USERNAME", "")
TVPL_PASSWORD = os.getenv("TVPL_PASSWORD", "")
TVPL_RSS_URL = "https://thuvienphapluat.vn/rss.xml"
TVPL_BASE_URL = "https://thuvienphapluat.vn"
TVPL_RATE_LIMIT_SECONDS = float(os.getenv("TVPL_RATE_LIMIT_SECONDS", "7"))
# Tải file .docx/.pdf từ TVPL bằng Playwright (cần TVPL_USERNAME/PASSWORD)
TVPL_DOWNLOAD_ENABLED = os.getenv("TVPL_DOWNLOAD_ENABLED", "true").lower() in (
    "true", "1", "yes",
)
# Dùng Google Chrome thật qua cổng debug (CDP) thay vì Chromium của Playwright.
# Cloudflare của TVPL chặn Chromium do Playwright khởi chạy, kể cả headless=false;
# Chrome thật khởi chạy bình thường rồi gắn qua CDP thì vượt được.
TVPL_USE_CDP = os.getenv("TVPL_USE_CDP", "true").lower() in ("true", "1", "yes")
# Tài khoản TVPL có hạn mức tải/ngày (đo được ~45 lượt). Vượt hạn mức thì trang
# vẫn mở bình thường nhưng link tải biến mất, nên phải tự dừng thay vì thử tiếp.
TVPL_MAX_DOWNLOADS_PER_RUN = int(os.getenv("TVPL_MAX_DOWNLOADS_PER_RUN", "40"))
# Số lần liên tiếp không thấy link tải thì coi như đã hết hạn mức và dừng batch
TVPL_MISSING_LINK_STREAK = int(os.getenv("TVPL_MISSING_LINK_STREAK", "5"))
TVPL_CDP_PORT = int(os.getenv("TVPL_CDP_PORT", "9222"))
# Hồ sơ Chrome riêng cho pipeline — giữ phiên đăng nhập TVPL giữa các lần chạy,
# không đụng tới hồ sơ Chrome cá nhân của người dùng.
TVPL_CHROME_PROFILE_DIR = os.getenv(
    "TVPL_CHROME_PROFILE_DIR",
    str(PROJECT_ROOT / "data" / "chrome_profile"),
)
TVPL_CHROME_PATH = os.getenv("TVPL_CHROME_PATH", "")

# ──────────────────────────────────────────────
# MOJ (Bộ Tư pháp) API
# ──────────────────────────────────────────────
MOJ_BASE_URL = "https://vbpl-bientap-gateway.moj.gov.vn/api/qtdc/public"

MOJ_PAGE_SIZE = 100
MOJ_WINDOW_DAYS = int(os.getenv("MOJ_WINDOW_DAYS", "30"))
MOJ_RATE_LIMIT_SECONDS = 0.5  # 500ms between requests
# Safety cap so a broken cutoff can never paginate through all 170k+ documents
MOJ_MAX_PAGES = int(os.getenv("MOJ_MAX_PAGES", "40"))

# ──────────────────────────────────────────────
# Telegram
# ──────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")

# ──────────────────────────────────────────────
# Google Drive
# ──────────────────────────────────────────────
GDRIVE_SERVICE_ACCOUNT_FILE = os.getenv(
    "GDRIVE_SERVICE_ACCOUNT_FILE",
    str(PROJECT_ROOT / "credentials" / "gdrive_service_account.json"),
)
GDRIVE_ROOT_FOLDER_ID = os.getenv("GDRIVE_ROOT_FOLDER_ID", "")

# ──────────────────────────────────────────────
# Lark Drive
# ──────────────────────────────────────────────
LARK_APP_ID = os.getenv("LARK_APP_ID", "")
LARK_APP_SECRET = os.getenv("LARK_APP_SECRET", "")
LARK_ROOT_FOLDER_TOKEN = os.getenv("LARK_ROOT_FOLDER_TOKEN", "")
LARK_DOMAIN = os.getenv("LARK_DOMAIN", "open.larksuite.com")
# Mỗi văn bản được lưu trong một thư mục con riêng (chứa cả file TVPL và Bộ Tư pháp)
LARK_FOLDER_PER_DOC = os.getenv("LARK_FOLDER_PER_DOC", "true").lower() in (
    "true", "1", "yes",
)

# Auto-delete local docx/pdf files after upload to save disk space
AUTO_CLEANUP_LOCAL_FILES = os.getenv("AUTO_CLEANUP_LOCAL_FILES", "true").lower() in ("true", "1", "yes")


# ──────────────────────────────────────────────
# File Storage Paths
# ──────────────────────────────────────────────
DATA_DIR = PROJECT_ROOT / "data"
TVPL_FILES_DIR = DATA_DIR / "tvpl"
MOJ_FILES_DIR = DATA_DIR / "moj"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
BACKUPS_DIR = DATA_DIR / "backups"
LOGS_DIR = DATA_DIR / "logs"

# Ensure directories exist
for d in [TVPL_FILES_DIR, MOJ_FILES_DIR, SNAPSHOTS_DIR, BACKUPS_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────
# Business Field Codes (TVPL fields mapping)
# Mã lĩnh vực doanh nghiệp theo BRD §4.1
# ──────────────────────────────────────────────
BUSINESS_FIELDS: dict[int, str] = {
    1: "Doanh nghiệp",
    2: "Đầu tư",
    3: "Thương mại",
    4: "Xuất nhập khẩu",
    6: "Thuế - Phí - Lệ Phí",
    7: "Chứng khoán",
    8: "Bảo hiểm",
    9: "Kế toán - Kiểm toán",
    10: "Lao động - Tiền lương",
    14: "Sở hữu trí tuệ",
}

BUSINESS_FIELD_CODES: set[int] = set(BUSINESS_FIELDS.keys())

# Slug mapping for TVPL URL filtering
BUSINESS_FIELD_SLUGS: dict[str, int] = {
    "Doanh-nghiep": 1,
    "Dau-tu": 2,
    "Thuong-mai": 3,
    "Xuat-nhap-khau": 4,
    "Thue-Phi-Le-Phi": 6,
    "Chung-khoan": 7,
    "Bao-hiem": 8,
    "Ke-toan-Kiem-toan": 9,
    "Lao-dong-Tien-luong": 10,
    "So-huu-tri-tue": 14,
}

# ──────────────────────────────────────────────
# MOJ field matching
#
# API vbpl-bientap trả về lĩnh vực dưới dạng tên tiếng Việt (documentFields /
# documentMajors), không phải mã số như TVPL. Bảng dưới ánh xạ từ khoá trong tên
# lĩnh vực → mã lĩnh vực doanh nghiệp ở trên.
# ──────────────────────────────────────────────
MOJ_FIELD_KEYWORDS: dict[str, int] = {
    "doanh nghiệp": 1,
    "hộ kinh doanh": 1,
    "hợp tác xã": 1,
    "đầu tư": 2,
    "thương mại": 3,
    "công thương": 3,
    "cạnh tranh": 3,
    "xuất khẩu": 4,
    "nhập khẩu": 4,
    "hải quan": 4,
    "thuế": 6,
    "phí": 6,
    "lệ phí": 6,
    "chứng khoán": 7,
    "bảo hiểm": 8,
    "kế toán": 9,
    "kiểm toán": 9,
    "lao động": 10,
    "tiền lương": 10,
    "việc làm": 10,
    "sở hữu trí tuệ": 14,
}

# TVPL fields query string for GetWidget.ashx
TVPL_FIELDS_QUERY = ",".join(str(c) for c in sorted(BUSINESS_FIELD_CODES))
# → "1,2,3,4,6,7,8,9,10,14"
