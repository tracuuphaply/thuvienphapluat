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

# ──────────────────────────────────────────────
# MOJ (Bộ Tư pháp) API
# ──────────────────────────────────────────────
MOJ_BASE_URL = "https://vbpl.vn/api/qtdc/public"
MOJ_PAGE_SIZE = 100
MOJ_WINDOW_DAYS = int(os.getenv("MOJ_WINDOW_DAYS", "30"))
MOJ_RATE_LIMIT_SECONDS = 0.5  # 500ms between requests

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

# TVPL fields query string for GetWidget.ashx
TVPL_FIELDS_QUERY = ",".join(str(c) for c in sorted(BUSINESS_FIELD_CODES))
# → "1,2,3,4,6,7,8,9,10,14"
