# Hệ thống Cập nhật Văn bản Pháp luật Doanh nghiệp — Phase 1

> "Não Pháp luật" Gatlas — Tự động theo dõi, tải, lưu trữ và thông báo văn bản pháp luật mới thuộc lĩnh vực doanh nghiệp.

## Tính năng chính

- **Quét tự động** từ 2 nguồn: Thư viện Pháp luật (TVPL) + Bộ Tư pháp (MOJ API)
- **Lọc 10 lĩnh vực** doanh nghiệp: Doanh nghiệp, Đầu tư, Thương mại, Thuế, Lao động...
- **Tải file biên tập** `.docx` từ TVPL (qua Google Chrome + CDP, xem HUONG_DAN §2.5)
- **Lấy toàn văn + đồ thị quan hệ** từ MOJ API
- **Upload Google Drive** tự động phân thư mục theo Lĩnh vực/Năm/Tháng
- **Thông báo Telegram** hằng ngày kèm link Google Drive
- **Chống trùng lặp** (dedupe) giữa 2 nguồn theo số hiệu văn bản

## Cài đặt

```bash
# 1. Clone & cd vào project
cd thuvienphapluat

# 2. Tạo virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Cài dependencies
pip install -e .

# 4. Cài Playwright browsers (cho TVPL downloader)
playwright install chromium

# 5. Copy & điền thông tin credentials
cp .env.example .env
# → Sửa .env với thông tin thực

# 6. Khởi tạo database
python scripts/setup_db.py
```

## Sử dụng

```bash
# Chạy full pipeline (cần TVPL credentials + Telegram + GDrive)
python -m src.main

# Dry run: xem preview Telegram message mà không gửi
python -m src.main --dry-run

# Chỉ chạy MOJ (không cần đăng nhập TVPL)
python -m src.main --moj-only --dry-run

# Bỏ qua Google Drive upload
python -m src.main --skip-gdrive --dry-run

# Test riêng MOJ API
python -m src.sources.moj_api

# Test riêng TVPL RSS
python -m src.sources.tvpl_rss

# Backup database + files
python -m src.utils.backup
```

## Cấu trúc dự án

```
thuvienphapluat/
├── src/
│   ├── main.py                   # Entry point pipeline
│   ├── config.py                 # Cấu hình & hằng số
│   ├── sources/
│   │   ├── tvpl_rss.py           # Parse RSS TVPL
│   │   ├── tvpl_downloader.py    # Playwright login + download
│   │   └── moj_api.py            # MOJ API client
│   ├── pipeline/
│   │   └── deduplicator.py       # Normalize docNum + merge
│   ├── storage/
│   │   ├── models.py             # SQLAlchemy ORM
│   │   ├── database.py           # DB connection + CRUD
│   │   ├── file_store.py         # Local file management
│   │   └── gdrive.py             # Google Drive API
│   ├── notification/
│   │   └── telegram_bot.py       # Telegram digest
│   └── utils/
│       └── backup.py             # Backup utility
├── scripts/
│   ├── setup_db.py               # DB initialization
│   └── run_daily.sh              # Cron wrapper
├── data/                         # Runtime data (gitignored)
├── .env.example                  # Credential template
└── pyproject.toml                # Dependencies
```

## Credentials cần thiết

| Credential | Mục đích | Cách tạo |
|---|---|---|
| TVPL account | Đăng nhập tải file .docx | Tài khoản của công ty luật |
| Telegram Bot Token | Gửi thông báo hằng ngày | Tạo qua @BotFather trên Telegram |
| Google Drive Service Account | Upload file lên Drive | Google Cloud Console → Service Account |
