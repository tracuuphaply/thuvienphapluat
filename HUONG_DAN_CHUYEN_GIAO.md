# 📘 HƯỚNG DẪN CHUYỂN GIAO & VẬN HÀNH HỆ THỐNG
## Hệ thống Cập nhật Văn bản Pháp luật Doanh nghiệp (Phase 1)

> **Dành cho:** Đồng nghiệp nhận chuyển giao & vận hành hệ thống  
> **Hỗ trợ hệ điều hành:** Windows 10/11, Linux, macOS  
> **Phiên bản:** 1.0 (Full Package)  

---

## 📑 MỤC LỤC
1. [Tổng quan & Yêu cầu Hệ thống](#1-tổng-quan--yêu-cầu-hệ-thống)
2. [Hướng dẫn chuẩn bị Credentials (Bắt buộc)](#2-hướng-dẫn-chuẩn-bị-credentials-bắt-buộc)
   - [2.1. Telegram Bot Token & Chat ID](#21-telegram-bot-token--chat-id)
   - [2.2. Tài khoản Thư viện Pháp luật (TVPL)](#22-tài-khoản-thư-viện-pháp-luật-tvpl)
   - [2.3. Google Drive API (Service Account Key)](#23-google-drive-api-service-account-key)
3. [Hướng dẫn Cài đặt Môi trường](#3-hướng-dẫn-cài-đặt-môi-trường)
   - [Dành cho Windows](#dành-cho-windows)
   - [Dành cho Linux / macOS](#dành-cho-linux--macos)
4. [Cấu hình file `.env`](#4-cấu-hình-file-env)
5. [Hướng dẫn Chạy & Kiểm thử Hệ thống](#5-hướng-dẫn-chạy--kiểm-thử-hệ-thống)
6. [Thiết lập Lịch chạy Tự động Hàng ngày (Scheduler)](#6-thiết-lập-lịch-chạy-tự-động-hàng-ngày-scheduler)
7. [Xử lý Sự cố Thường gặp (Troubleshooting)](#7-xử-lý-sự-cố-thường-gặp-troubleshooting)

---

## 1. TỔNG QUAN & YÊU CẦU HỆ THỐNG

Hệ thống hoạt động tự động hàng ngày để phát hiện văn bản quy phạm pháp luật mới thuộc **10 lĩnh vực doanh nghiệp**, tải bản biên tập `.docx` từ TVPL, lấy toàn văn + quan hệ dẫn chiếu từ Bộ Tư pháp (MOJ), đẩy lên Lark Drive (hoặc Google Drive) theo cây thư mục Lĩnh vực/Năm/Tháng/Số hiệu, và gửi thông báo qua Telegram.

### Yêu cầu phần mềm trên máy tính vận hành:
* **Hệ điều hành:** Windows 10/11 (khuyên dùng) hoặc Linux / macOS.
* **Python:** Phiên bản **3.11** trở lên (Tải tại [python.org](https://www.python.org/)).  
  *(Lưu ý trên Windows: Nhớ tích chọn **"Add Python to PATH"** khi cài đặt).*
* **Google Chrome** — bắt buộc nếu muốn tải file `.docx` từ TVPL. Chromium do
  Playwright cài **không dùng được** cho việc này (bị Cloudflare chặn), chi tiết ở §2.5.
* **Playwright + Chromium:** vẫn cài như bình thường, dùng làm phương án dự phòng.

---

## 2. HƯỚNG DẪN CHUẨN BỊ CREDENTIALS (BẮT BUỘC)

Trước khi chạy chương trình, bạn cần có **3 nhóm thông tin** sau:

### 2.1. Telegram Bot Token & Chat ID
Nhận thông báo văn bản mới hàng ngày trực tiếp vào nhóm Telegram của công ty.

1. **Tạo Bot:**
   * Mở ứng dụng Telegram, tìm kiếm bot tên `@BotFather`.
   * Gửi lệnh `/newbot` $\rightarrow$ Nhập tên hiển thị (VD: `Gatlas Legal Bot`) $\rightarrow$ Nhập username kết thúc bằng `bot` (VD: `gatlas_legal_bot`).
   * `@BotFather` sẽ gửi lại bạn một **API Token** (Ví dụ: `7123456789:AAEfghIJKlmnoPQrsTUVwxyz...`). Lưu mã này lại.
2. **Lấy Chat ID nhóm nhận tin:**
   * Tạo một nhóm Telegram mới (hoặc dùng nhóm sẵn có) và **thêm Bot vừa tạo vào nhóm**.
   * Thêm bot `@userinfobot` hoặc `@raw_data_bot` vào nhóm để xem **Group Chat ID** (thường bắt đầu bằng dấu trừ, ví dụ: `-1001234567890`).
   * Hoặc gửi 1 tin nhắn bất kỳ vào nhóm, sau đó mở trình duyệt truy cập:  
     `https://api.telegram.org/bot<TOKEN_CỦA_BẠN>/getUpdates`  
     Tìm chuỗi `"chat":{"id": -100xxxxxxxxx}` để lấy Chat ID.

---

### 2.2. Tài khoản Thư viện Pháp luật (TVPL)
Tài khoản này dùng để đăng nhập tự động và tải file biên tập `.docx` từ `thuvienphapluat.vn`. TVPL không phát hành bản PDF tải được nên hệ thống chỉ lấy `.docx` — bản này đã chứa đầy đủ nội dung văn bản.

* **Yêu cầu:** Tài khoản TVPL trả phí (Pro/VIP) của công ty luật.
* **Cần chuẩn bị:** `Email/Tên đăng nhập` + `Mật khẩu`.

---

### 2.3. Google Drive API (Service Account Key)
Dùng để tự động tải các file `.docx` đã thu thập lên thư mục Google Drive của công ty và lấy đường link phân quyền xem trực tiếp.

1. **Tạo Google Cloud Project & Bật API:**
   * Truy cập [Google Cloud Console](https://console.cloud.google.com/).
   * Tạo một Project mới (đặt tên ví dụ: `Gatlas Legal Drive`).
   * Vào mục **APIs & Services** $\rightarrow$ **Library** $\rightarrow$ Tìm kiếm `Google Drive API` $\rightarrow$ Bấm **Enable**.
2. **Tạo Service Account & Tải JSON Key:**
   * Vào **APIs & Services** $\rightarrow$ **Credentials** $\rightarrow$ Bấm **Create Credentials** $\rightarrow$ Chọn **Service Account**.
   * Đặt tên Service Account (VD: `gdrive-bot`) $\rightarrow$ Bấm **Create and Continue** $\rightarrow$ Bấm **Done**.
   * Bấm vào Service Account vừa tạo $\rightarrow$ Chuyển sang tab **Keys** $\rightarrow$ Bấm **Add Key** $\rightarrow$ Chọn **Create new key** $\rightarrow$ Chọn định dạng **JSON** $\rightarrow$ Bấm **Create**.
   * Một file JSON sẽ tự động tải về máy. Hãy đổi tên file này thành `gdrive_service_account.json` và lưu vào thư mục `credentials/` trong dự án.
3. **Chia sẻ quyền truy cập Thư mục Google Drive:**
   * Mở file JSON vừa tải, tìm dòng `"client_email"` (ví dụ: `gdrive-bot@gatlas-legal.iam.gserviceaccount.com`).
   * Vào Google Drive của bạn, **tạo 1 Thư mục gốc** (VD: `Kho_Van_Ban_Phap_Luat`).
   * Phải chuột vào Thư mục đó $\rightarrow$ Chọn **Share (Chia sẻ)** $\rightarrow$ Dán địa chỉ `client_email` ở trên vào $\rightarrow$ Cấp quyền **Editor (Người chỉnh sửa)**.
   * Lấy **Folder ID** trên đường dẫn trình duyệt:  
     Ví dụ URL: `https://drive.google.com/drive/folders/1ABCxyz_90123456789` $\rightarrow$ Folder ID là `1ABCxyz_90123456789`.

---

### 2.4. Lark Drive / Feishu Drive (Lưu trữ trên Lark)
Nếu công ty bạn sử dụng **Lark Suite (hoặc Feishu)** làm không gian làm việc chính:

1. **Tạo Custom App trên Lark Developer Console:**
   * Truy cập [Lark Developer Console](https://open.larksuite.com/app) (hoặc [Feishu Open Platform](https://open.feishu.cn/app)).
   * Bấm **Create Custom App** $\rightarrow$ Đặt tên (VD: `Legal Storage Bot`).
   * Vào mục **Credentials & Basic Info** $\rightarrow$ Lấy **App ID** (dạng `cli_xxxxxxxx`) và **App Secret**.
2. **Cấp quyền truy cập Drive (Permissions):**
   * Vào mục **Permissions & Scopes** $\rightarrow$ Thêm các quyền:
     - `drive:drive` (Xem/sửa file Drive)
     - `drive:file` (Tải lên file)
2b. **Bật tính năng Bot (BẮT BUỘC) rồi Release:**
   * **Add Features** → **Bot** → **Enable**.
   * **Version Management & Release** → **Create Version** → **Release** → chờ admin duyệt.
   * Lý do: ô tìm kiếm trong cửa sổ chia sẻ thư mục của Lark Drive **chỉ tìm được
     người dùng và bot**, không tìm được app thuần. App chưa bật Bot sẽ không bao
     giờ xuất hiện khi bạn gõ tên nó ở bước 3.
   * Kiểm tra nhanh: gọi `GET /open-apis/bot/v3/info`; nếu trả
     `{"code": 11205, "msg": "app do not have bot"}` là chưa bật.
   * Ở phần **Availability**, chọn **All members** (hoặc thêm sẵn người sẽ dùng) —
     bot chỉ hiện với tài khoản nằm trong phạm vi availability.
3. **Tạo thư mục gốc và CHIA SẺ CHO APP (bước bắt buộc):**
   * Mở Lark Drive → **Thư mục của tôi** (My Space) → **Mới** → **Thư mục** →
     đặt tên, ví dụ `Kho_Van_Ban_Phap_Luat`.
   * Chuột phải vào thư mục → **Chia sẻ** → gõ tên app (VD `Legal Storage Bot`)
     → chọn app trong danh sách → đặt quyền **Có thể chỉnh sửa** (Can edit) →
     **Xong**.
   * ⚠️ **Không được bỏ qua bước chia sẻ.** Lark **không có API để chia sẻ thư
     mục**, nên nếu app tự tạo thư mục trong không gian riêng của nó, thư mục vẫn
     tồn tại nhưng mọi tài khoản người dùng đều nhận lỗi *"Bạn không có quyền truy
     cập vào thư mục"*. Thư mục phải do người dùng tạo rồi chia sẻ ngược lại cho app.
   * ⚠️ Quyền **"Chỉ xem"** (Can view) không đủ — app cần tạo thư mục con và tải file lên.
4. **Lấy Root Folder Token:**
   * Mở thư mục vừa tạo, xem URL:
     `https://<tenant>.larksuite.com/drive/folder/FLDxxxxxxxxxxxx`
     → phần `FLDxxxxxxxxxxxx` chính là **Folder Token**.
5. **Cấu hình file `.env`:**
   * Điền `LARK_APP_ID`, `LARK_APP_SECRET`, `LARK_ROOT_FOLDER_TOKEN`.
6. **Kiểm tra lại trước khi chạy pipeline:**
   ```bash
   python scripts/lark_check.py
   ```
   Script báo `✅ Ghi được vào thư mục gốc` là đạt. Nếu báo lỗi, làm lại bước 3.

**Cấu trúc lưu trữ kết quả** — mỗi văn bản một thư mục riêng, chứa dữ liệu cả hai nguồn:

```
Kho_Van_Ban_Phap_Luat/
└── Doanh nghiệp/            ← lĩnh vực
    └── 2026/
        └── Thang_07/
            └── 292_2026_NĐ-CP/        ← số hiệu văn bản
                ├── 292_2026_NĐ-CP.docx          (TVPL)
                ├── 292_2026_NĐ-CP_BoTuPhap.md   (toàn văn Bộ Tư pháp, đã làm sạch)
                ├── 292_2026_NĐ-CP_BoTuPhap.html (toàn văn gốc)
                └── 292_2026_NĐ-CP_metadata.json (metadata hợp nhất 2 nguồn)
```

---

### 2.5. Tải file .docx từ TVPL — yêu cầu Google Chrome

TVPL đặt sau Cloudflare. Kết quả kiểm chứng (2026-08):

| Cách truy cập | Kết quả |
|---|---|
| `httpx` / `requests` | ❌ HTTP 403 |
| Chromium của Playwright (headless) | ❌ Trang *"Chờ một chút…"* |
| Chromium của Playwright (hiện cửa sổ) | ❌ Trang *"Chờ một chút…"* |
| Playwright khởi chạy Chrome thật (`channel="chrome"`) | ❌ Trang *"Chờ một chút…"* |
| **Chrome thật chạy độc lập + gắn qua CDP** | ✅ **Vào được, tải được file** |

Điểm mấu chốt: Cloudflare không chặn Chrome, nó chặn **trình duyệt do công cụ tự
động khởi chạy**. Nên pipeline khởi chạy Google Chrome như một tiến trình bình
thường (`--remote-debugging-port`), rồi mới gắn vào điều khiển qua giao thức CDP.

**Yêu cầu:** máy chạy pipeline phải cài **Google Chrome** (không phải Chromium,
không phải Edge). Đường dẫn mặc định được dò tự động trên Windows/macOS/Linux;
nếu cài ở chỗ khác thì khai báo `TVPL_CHROME_PATH` trong `.env`.

**Hồ sơ Chrome riêng:** pipeline dùng thư mục `data/chrome_profile`, tách hẳn khỏi
Chrome cá nhân của bạn (không đọc lịch sử, không đụng tài khoản Google của bạn).
Phiên đăng nhập TVPL được lưu ở đây nên chỉ đăng nhập một lần, các lần sau dùng
lại — mỗi văn bản chỉ mất ~6 giây thay vì ~20 giây.

> ⚠️ Chrome phải được **tắt êm** sau mỗi lần chạy thì cookie mới kịp ghi ra đĩa.
> Pipeline đã xử lý việc này; đừng tắt máy đột ngột giữa lúc đang chạy, nếu không
> lần sau phải đăng nhập lại (vẫn tự động, chỉ chậm hơn).

**Nếu máy không có Chrome:** pipeline tự quay về Chromium và sẽ bị Cloudflare
chặn — lúc đó chỉ còn toàn văn từ Bộ Tư pháp (`_BoTuPhap.md`/`.html`), hệ thống
vẫn chạy bình thường. Muốn tắt hẳn bước tải để chạy nhanh hơn:

```
TVPL_DOWNLOAD_ENABLED=false
```

#### Hạn mức tải của tài khoản TVPL

Đo thực tế (2026-08-01): tải liên tục được **44 file** rồi dừng hẳn — từ đó trở đi
trang văn bản vẫn mở bình thường nhưng **link tải biến mất**. Đây là hạn mức
tải/ngày của tài khoản, không phải lỗi kỹ thuật và không phải do Cloudflare.

Hệ thống xử lý việc này bằng hai lớp:

| Biến | Mặc định | Tác dụng |
|---|---|---|
| `TVPL_MAX_DOWNLOADS_PER_RUN` | 40 | Dừng chủ động trước khi chạm hạn mức |
| `TVPL_MISSING_LINK_STREAK` | 5 | 5 văn bản liên tiếp mất link → dừng, báo rõ lý do |

**Vận hành hàng ngày không bị ảnh hưởng**: mỗi ngày chỉ có khoảng 10–20 văn bản
mới, còn xa hạn mức. Chỉ khi nạp bù lần đầu (hàng trăm văn bản) mới chạm trần —
lúc đó chạy `backfill_tvpl_files.py` vài ngày liên tiếp, mỗi ngày một mẻ.

Muốn tải nhiều hơn mỗi ngày thì phải nâng cấp gói tài khoản TVPL.

#### Tải bù cho văn bản đã có trong database

```bash
python scripts/backfill_tvpl_files.py            # tất cả văn bản còn thiếu file
python scripts/backfill_tvpl_files.py --limit 10 # chạy thử 10 văn bản
```

File tải xong được đẩy thẳng vào đúng thư mục Lark Drive của văn bản đó.

---

### 2.6. (Dự phòng) Dùng cookie khi không cài được Chrome

Chỉ cần đến cách này nếu máy vận hành **không thể cài Google Chrome**. Cách này
phải làm thủ công định kỳ, nên ưu tiên cách ở §2.5.

#### Bước 1 — Đăng nhập bằng trình duyệt

Mở Chrome/Edge **trên chính máy sẽ chạy pipeline**, vào
[thuvienphapluat.vn](https://thuvienphapluat.vn), đăng nhập tài khoản trong `.env`
(`TVPL_USERNAME`).

Mở thử một trang văn bản bất kỳ và bấm **Tải Văn bản tiếng Việt** để chắc chắn
tài khoản tải được file. Nếu trình duyệt thật cũng không tải được thì cookie
không cứu được — vấn đề nằm ở tài khoản chứ không phải Cloudflare.

#### Bước 2 — Cài extension xuất cookie

Dùng **Cookie-Editor** (khuyến nghị — còn hoạt động trên Chrome/Edge/Firefox):
[Chrome Web Store](https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm)

> *EditThisCookie* viết theo Manifest V2 nên đã bị Chrome ngừng hỗ trợ; nếu bạn
> vẫn còn cài được thì dùng cũng được, định dạng xuất ra tương đương.

#### Bước 3 — Xuất cookie

1. Đang mở tab `thuvienphapluat.vn` (bắt buộc — extension chỉ xuất cookie của
   tên miền đang mở).
2. Bấm biểu tượng Cookie-Editor trên thanh công cụ.
3. Bấm nút **Export** (góc dưới bên phải) → chọn **JSON**.
4. Nội dung đã được copy vào clipboard.

#### Bước 4 — Lưu file

Tạo file `data/tvpl_cookies.json` trong thư mục dự án và dán nội dung vừa copy vào.

* **Windows:** mở Notepad → dán → *Save As* → chọn đúng thư mục `data`, đặt tên
  `tvpl_cookies.json`, mục *Save as type* chọn **All Files** (nếu để *Text
  Documents* Notepad sẽ tự thêm đuôi `.txt` và pipeline không đọc được).
* **macOS/Linux:** `pbpaste > data/tvpl_cookies.json`

Nội dung đúng trông như thế này (một mảng JSON):

```json
[
  {
    "domain": ".thuvienphapluat.vn",
    "expirationDate": 1785600000.5,
    "httpOnly": false,
    "name": "cf_clearance",
    "path": "/",
    "sameSite": "no_restriction",
    "secure": true,
    "value": "abc123..."
  }
]
```

Không cần chỉnh sửa gì thêm — pipeline tự chuyển đổi định dạng của extension
(`expirationDate` → `expires`, `no_restriction` → `None`) sang định dạng
Playwright yêu cầu.

#### Bước 5 — Kiểm tra

Chạy thử một văn bản:

```bash
python -m src.main --limit 1
```

Trong log tìm dòng:

```
Loaded 12 TVPL cookies from .../data/tvpl_cookies.json (cf_clearance: có)
```

* `cf_clearance: có` + có dòng `Downloaded .docx` → thành công.
* `cf_clearance: KHÔNG` → xuất lại cookie khi đang mở đúng tab TVPL. Đây là
  cookie Cloudflare cấp sau khi vượt thử thách; thiếu nó thì chắc chắn vẫn bị chặn.

#### Lưu ý vận hành

* Cookie `cf_clearance` gắn với **IP + User-Agent** của phiên đã vượt thử thách.
  Đổi mạng (Wi-Fi sang 4G, VPN bật/tắt) là mất hiệu lực ngay.
* Hạn dùng thường **vài giờ đến vài ngày**. Khi log báo
  `Cloudflare đang chặn truy cập tự động` thì lặp lại bước 3–4.
* File này chứa phiên đăng nhập của bạn — đã được `.gitignore` loại trừ, **không
  gửi qua chat/email** cho người khác.
* Vì phải làm thủ công định kỳ, nếu không thực sự cần file `.docx` gốc thì nên
  đặt `TVPL_DOWNLOAD_ENABLED=false` và dùng toàn văn từ Bộ Tư pháp.
* Lưu ý: cách này **chỉ hữu ích khi trình duyệt của bạn thực sự có `cf_clearance`**.
  Nếu Cloudflare chưa từng ra thử thách cho bạn thì cookie đó không tồn tại và
  không có gì để mượn — lúc đó bắt buộc dùng cách Chrome + CDP ở §2.5.

---

## 3. HƯỚNG DẪN CÀI ĐẶT MÔI TRƯỜNG

### Dành cho Windows (Dễ nhất - 1 Click):
1. Giải nén thư mục dự án `thuvienphapluat`.
2. Mở thư mục `scripts` và **nhấp kép chuột vào file `setup.bat`**.
3. Tự động quá trình sẽ:
   * Tạo môi trường ảo Python (`.venv`).
   * Cài đặt đầy đủ các thư viện cần thiết.
   * Tải trình duyệt tự động Chromium cho Playwright.
   * Tạo sẵn file `.env` mẫu và khởi tạo Database SQLite.

### Dành cho Linux / macOS:
Mở Terminal tại thư mục dự án và chạy các lệnh sau:
```bash
# 1. Tạo môi trường ảo Python
python3 -m venv .venv
source .venv/bin/activate

# 2. Cài đặt dependencies
pip install -e .

# 3. Cài đặt trình duyệt Playwright
playwright install chromium

# 4. Tạo file cấu hình .env
cp .env.example .env

# 5. Khởi tạo Database SQLite
python scripts/setup_db.py
```

---

## 4. CẤU HÌNH FILE `.ENV`

Mở file `.env` nằm ở thư mục gốc của dự án bằng bất kỳ trình soạn thảo văn bản nào (Notepad, VS Code, v.v.) và điền đầy đủ các giá trị đã chuẩn bị ở **Mục 2**:

```env
# === Database (Mặc định dùng SQLite cục bộ, không cần sửa) ===
DATABASE_URL=sqlite:///data/legal_docs.db

# === 1. Tài khoản TVPL (Thư viện Pháp luật) ===
TVPL_USERNAME=taikhoan_congty@gmail.com
TVPL_PASSWORD=matkhau_tvpl_o_day

# === 2. Telegram Bot ===
TELEGRAM_BOT_TOKEN=7123456789:AAEfghIJKlmnoPQrsTUVwxyz...
TELEGRAM_CHAT_ID=-1001234567890
TELEGRAM_ADMIN_CHAT_ID=-1001234567890

# === 3. Google Drive ===
GDRIVE_SERVICE_ACCOUNT_FILE=credentials/gdrive_service_account.json
GDRIVE_ROOT_FOLDER_ID=1ABCxyz_90123456789

# === Cấu hình Lịch trình & Tốc độ ===
TVPL_RATE_LIMIT_SECONDS=7
MOJ_WINDOW_DAYS=30
DAILY_RUN_HOUR=6
```

---

## 5. HƯỚNG DẪN CHẠY & KIỂM THỬ HỆ THỐNG

### 🛠️ Cách 1: Chạy thử nghiệm xem trước (Dry-Run — Không gửi Telegram thực)
Dùng để kiểm tra xem hệ thống cào dữ liệu có hoạt động tốt không mà không làm nhiễu nhóm Telegram:

* **Trên Windows:**
  Mở CMD / PowerShell trong thư mục dự án và chạy:
  ```cmd
  .venv\Scripts\activate.bat
  python -m src.main --dry-run --skip-gdrive
  ```
* **Trên Linux / macOS:**
  ```bash
  source .venv/bin/activate
  python -m src.main --dry-run --skip-gdrive
  ```

### 🚀 Cách 2: Chạy chính thức toàn bộ Pipeline (Full Run)
Hệ thống sẽ cào văn bản mới, lấy toàn văn từ Bộ Tư pháp, tải file `.docx` từ TVPL,
upload lên Lark Drive (hoặc Google Drive nếu chưa cấu hình Lark) và gửi bản tin
vào nhóm Telegram:

* **Trên Windows:**
  ```cmd
  .venv\Scripts\activate.bat
  python -m src.main
  ```
* **Trên Linux / macOS:**
  ```bash
  source .venv/bin/activate
  python -m src.main
  ```

### 🔁 Cách 3: Upload bù khi bước upload từng hỏng

Khi lần chạy trước lấy được dữ liệu nhưng upload thất bại (chưa cấu hình
`LARK_ROOT_FOLDER_TOKEN`, mất mạng, hết hạn token…), không cần quét lại nguồn:

```bash
python -m src.main --upload-only
```

Lệnh này chỉ xử lý các văn bản trong DB chưa có `lark_folder_token`, dùng lại dữ
liệu đã có sẵn dưới `data/`.

### 🧪 Các cờ khác

| Cờ | Tác dụng |
|---|---|
| `--dry-run` | In thử bản tin Telegram, không gửi thật |
| `--skip-gdrive` | Bỏ qua toàn bộ bước upload |
| `--moj-only` | Chỉ quét Bộ Tư pháp, không đụng TVPL |
| `--limit N` | Chỉ xử lý N văn bản mới đầu tiên (chạy thử cho nhanh) |
| `--upload-only` | Chỉ upload bù, không quét nguồn |

---

## 6. THIẾT LẬP LỊCH CHẠY TỰ ĐỘNG HÀNG NGÀY (SCHEDULER)

Để hệ thống tự động thức dậy chạy vào **06:00 sáng mỗi ngày**:

### 💻 Trên Windows (Dùng Task Scheduler):
1. Nhấn phím `Windows + R`, gõ `taskschd.msc` và ấn Enter.
2. Tại cột bên phải, chọn **Create Basic Task...**
3. **Name:** Đặt tên `Gatlas Legal Update Pipeline` $\rightarrow$ Next.
4. **Trigger:** Chọn `Daily` $\rightarrow$ Next $\rightarrow$ Đặt thời gian `06:00:00 AM` $\rightarrow$ Next.
5. **Action:** Chọn `Start a program` $\rightarrow$ Next.
6. **Program/script:** Bấm Browse chọn đường dẫn đến file:  
   `C:\duong-dan-du-an\thuvienphapluat\scripts\run_daily.bat`
7. **Start in (optional):** Điền đường dẫn thư mục gốc dự án:  
   `C:\duong-dan-du-an\thuvienphapluat\`
8. Bấm **Finish** để hoàn tất.

### 🐧 Trên Linux / macOS (Dùng Crontab):
Mở terminal và gõ `crontab -e`, thêm dòng sau:
```cron
0 6 * * * /duong-dan-du-an/thuvienphapluat/scripts/run_daily.sh
```

---

## 7. XỬ LÝ SỰ CỐ THƯỜNG GẶP (TROUBLESHOOTING)

| Hiện tượng | Nguyên nhân | Cách khắc phục |
|---|---|---|
| `[LỖI] Chưa tìm thấy Python` | Máy Windows chưa cài Python hoặc chưa tích chọn "Add Python to PATH". | Tải bản Python 3.11+ chính thức, khi cài tích chọn ô "Add python.exe to PATH". |
| `FileNotFoundError: credentials/gdrive_service_account.json` | Chưa copy file key JSON của Google Drive vào đúng vị trí. | Tải file JSON từ Google Cloud Console, đổi tên thành `gdrive_service_account.json` và lưu vào thư mục `credentials/`. |
| `Telegram send failed: 401 Unauthorized` | Sai `TELEGRAM_BOT_TOKEN`. | Kiểm tra lại chuỗi Token được cấp từ `@BotFather`. |
| `Playwright Error: Executable doesn't exist` | Chưa cài đặt trình duyệt Chromium cho Playwright. | Chạy lệnh `playwright install chromium` trong môi trường ảo `.venv`. |
| Không tải được file `.docx` từ TVPL | Sai tài khoản TVPL hoặc hết hạn gói trả phí. | Kiểm tra lại username/password trong `.env` và đăng nhập thử thủ công trên web TVPL. |

---
*Tài liệu sẵn sàng bàn giao cho nhân sự vận hành.*
