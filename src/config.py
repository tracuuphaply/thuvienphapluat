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
# Tải file .docx từ TVPL bằng Playwright (cần TVPL_USERNAME/PASSWORD)
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

# Ứng dụng OAuth (luồng Desktop app). Service account KHÔNG dùng được: Google
# cấp cho service account hạn mức lưu trữ 0 GB nên upload vào My Drive trả về
# 403 storageQuotaExceeded, và không xin thêm quota được.
GDRIVE_OAUTH_CLIENT_FILE = os.getenv(
    "GDRIVE_OAUTH_CLIENT_FILE",
    str(PROJECT_ROOT / "credentials" / "gdrive_oauth_client.json"),
)
GDRIVE_OAUTH_TOKEN_FILE = os.getenv(
    "GDRIVE_OAUTH_TOKEN_FILE",
    str(PROJECT_ROOT / "credentials" / "gdrive_token.json"),
)
# Chỉ xin drive.file — phạm vi không nhạy cảm, không cần Google thẩm định.
# Scope `drive` đầy đủ là phạm vi hạn chế, phải qua đánh giá an ninh CASA.
# Hệ quả: ứng dụng chỉ ghi được vào thư mục do chính nó tạo, nên thư mục gốc
# phải do ứng dụng tạo chứ không trỏ tới thư mục người dùng tạo tay.
GDRIVE_SCOPES = ("https://www.googleapis.com/auth/drive.file",)
GDRIVE_ROOT_FOLDER_NAME = os.getenv("GDRIVE_ROOT_FOLDER_NAME", "Kho văn bản pháp luật")

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

# Auto-delete local .docx files after upload to save disk space
AUTO_CLEANUP_LOCAL_FILES = os.getenv("AUTO_CLEANUP_LOCAL_FILES", "true").lower() in ("true", "1", "yes")

# Nơi lưu trữ chính. Trước đây suy từ việc có hay không LARK_APP_ID, nên chỉ cần
# ai đó điền khoá Lark vào .env là toàn bộ pipeline âm thầm đổi đích lưu trữ.
CLOUD_DRIVE_PROVIDER = os.getenv("CLOUD_DRIVE_PROVIDER", "lark").strip().lower()


def upload_closure_nodes() -> bool:
    """Có đẩy văn bản kéo về theo dẫn chiếu lên Drive không.

    Mặc định CÓ. Yêu cầu vận hành nói rõ mọi văn bản tải về đều phải lưu Drive
    trước, và văn bản nền chính là nhóm được nêu tên trong yêu cầu đó.

    Đặt UPLOAD_CLOSURE_NODES=false nếu muốn Drive chỉ chứa văn bản thuộc lĩnh
    vực doanh nghiệp — bao đóng dẫn chiếu có thể kéo về vài nghìn văn bản nền,
    mỗi văn bản 4 file. Đọc lúc gọi chứ không đóng băng lúc import, để đổi cấu
    hình không phải khởi động lại tiến trình chạy dài ngày.
    """
    return os.getenv("UPLOAD_CLOSURE_NODES", "true").strip().lower() in (
        "true", "1", "yes",
    )

# ──────────────────────────────────────────────
# LLM & Embeddings
#
# Trước đây các biến này chỉ được đọc bằng os.getenv rải rác trong
# src/rag/report_generator.py và src/rag/embeddings_api.py, không có ở đây lẫn
# .env.example. Người làm đúng theo HUONG_DAN_CHUYEN_GIAO.md nhận được một
# crawler chạy tốt và một bộ sinh báo cáo chết câm mà không có thông báo nào.
#
# Nhóm này là HÀM chứ không phải hằng số như phần còn lại của file, vì chúng
# phải đọc lại lúc gọi: tiến trình dài như bot Telegram cần đổi model mà không
# khởi động lại, và đóng băng lúc import thì mất luôn khả năng ép giá trị khi
# chạy thử. Đường dẫn và các trần ở trên thì ngược lại — chốt một lần lúc khởi
# động là đúng.
# ──────────────────────────────────────────────
# v98store là gateway tương thích OpenAI đang dùng thật; hai khoá còn lại để
# chuyển nhà cung cấp mà không phải sửa code.
def v98_api_key() -> str:
    return os.getenv("V98_API_KEY", "")


def openai_api_key() -> str:
    return os.getenv("OPENAI_API_KEY", "")


def gemini_api_key() -> str:
    return os.getenv("GEMINI_API_KEY", "")


def llm_api_key() -> str:
    """Khoá cho cả gọi chat lẫn nhúng, theo thứ tự ưu tiên đang dùng thật."""
    return v98_api_key() or openai_api_key() or gemini_api_key()


def openai_api_base() -> str:
    # Mặc định trỏ thẳng nhà cung cấp đang dùng. v98store đã đóng cửa (trả
    # service_migrated), dời sang cheapkeyai.shop — vẫn OpenAI-compatible.
    return os.getenv("OPENAI_API_BASE", "https://cheapkeyai.shop/v1")


def report_model() -> str:
    # gpt-4o không còn trên nhà cung cấp mới; claude-sonnet-5 là mặc định chạy
    # được. Đổi qua REPORT_MODEL nếu muốn model khác.
    return os.getenv("REPORT_MODEL", "claude-sonnet-5")


def report_max_tokens() -> int:
    """Báo cáo tiếng Việt 4–6 trang vượt xa 8000 token; thấp hơn là bị cắt."""
    return int(os.getenv("REPORT_MAX_TOKENS", "16000"))


def report_request_timeout() -> float:
    """Giây chờ MỘT lượt gọi mô hình.

    Báo cáo (a) nạp payload lớn (hàng chục insight) và model mạnh sinh 4–6 trang,
    trên proxy chậm có thể vượt 300s. Đặt rộng để không cắt oan một lượt đang
    chạy tốt; lỗi mạng thật thì tầng thử-lại lo.
    """
    return float(os.getenv("REPORT_REQUEST_TIMEOUT", "600"))


def summary_model() -> str:
    """Model cho bước ĐỌC (tóm tắt insight từng văn bản).

    Để trống = dùng chính REPORT_MODEL. Tách biến riêng vì bước tóm tắt gọi mô
    hình một lần cho MỖI văn bản, nên người vận hành có thể muốn dùng model rẻ
    hơn ở đây và giữ model mạnh cho bước tổng hợp báo cáo.
    """
    return os.getenv("SUMMARY_MODEL", "") or report_model()


def summary_max_tokens() -> int:
    """Bản tóm tắt một văn bản ngắn hơn báo cáo nhiều; 3000 token là dư."""
    return int(os.getenv("SUMMARY_MAX_TOKENS", "3000"))


def form_classifier_model() -> str:
    """Model phân loại biểu mẫu (tầng 3 của phễu).

    Để trống = dùng SUMMARY_MODEL. Đây là việc rẻ nhất trong hệ thống — đọc vài
    trăm chữ rồi trả một nhãn — nhưng chạy tới hàng nghìn lượt, nên phải đặt
    được model rẻ riêng thay vì kéo theo model sinh báo cáo.
    """
    return os.getenv("FORM_CLASSIFIER_MODEL", "") or summary_model()


def form_classifier_max_tokens() -> int:
    """Đầu ra là một khối JSON ngắn; 600 token là dư gấp nhiều lần."""
    return int(os.getenv("FORM_CLASSIFIER_MAX_TOKENS", "600"))


def cam_nang_model() -> str:
    """Model sinh thân bài Cẩm nang.

    Để trống = dùng REPORT_MODEL. Tách biến riêng vì bài Cẩm nang là văn xuôi
    cho người đọc phổ thông, không phải báo cáo pháp lý — người vận hành có thể
    muốn một model khác ở đây, và số lượt gọi bằng số biểu mẫu chứ không phải số
    báo cáo.
    """
    return os.getenv("CAM_NANG_MODEL", "") or report_model()


def cam_nang_max_tokens() -> int:
    """Bài 900-1.600 chữ tiếng Việt cộng khối JSON bọc ngoài.

    8000 là dư một khoảng an toàn: bài chạm trần bị LOẠI chứ không được cắt bớt
    rồi giao đi, nên đặt sát quá là biến một bài viết tốt thành một bài bỏ đi.
    """
    return int(os.getenv("CAM_NANG_MAX_TOKENS", "8000"))


def report_prompt_path() -> str:
    return os.getenv("REPORT_PROMPT_PATH", "")


def business_field_codes_override() -> str:
    """Danh sách mã lĩnh vực TVPL 'liên quan doanh nghiệp', dạng "1,2,6,10".

    Trống = dùng bộ mặc định trong src/legal/business_relevance.py. Đặt biến này
    để đổi định nghĩa "liên quan doanh nghiệp" mà không sửa code.
    """
    return os.getenv("BUSINESS_FIELD_CODES", "")


def report_central_only() -> bool:
    """Chỉ đưa văn bản CẤP TRUNG ƯƠNG vào báo cáo (bỏ văn bản cấp tỉnh).

    Mục tiêu báo cáo là cập nhật luật toàn quốc cho chủ doanh nghiệp; quyết định
    cấp tỉnh chỉ áp dụng ở một địa bàn nên mặc định loại. Đặt false để giữ lại
    văn bản cấp tỉnh thuộc lĩnh vực doanh nghiệp.
    """
    return os.getenv("REPORT_CENTRAL_ONLY", "true").strip().lower() not in (
        "0", "false", "no", "off")


def embedding_model_override() -> str:
    """Để trống = tự chọn theo khoá API đang có (xem embeddings_api)."""
    return os.getenv("EMBEDDING_MODEL", "")


def embedding_dim_override() -> str:
    return os.getenv("EMBEDDING_DIM", "")


def embedding_batch_size() -> int:
    return int(os.getenv("EMBEDDING_BATCH_SIZE", "64"))


# ──────────────────────────────────────────────
# Thu thập theo mốc cố định & bao đóng dẫn chiếu
# ──────────────────────────────────────────────
# Sàn quét cố định, không trôi theo ngày chạy như cửa sổ 30 ngày trước đây.
CLOSURE_SEED_FLOOR = os.getenv("CLOSURE_SEED_FLOOR", "2026-01-01")
# Quét lùi quá watermark một quãng: văn bản được đăng lên hệ thống muộn hơn ngày
# ban hành, nên cắt đúng watermark theo issueDate sẽ bỏ sót vĩnh viễn văn bản
# đăng chậm.
CRAWL_OVERLAP_DAYS = int(os.getenv("CRAWL_OVERLAP_DAYS", "45"))
CLOSURE_ENABLED = os.getenv("CLOSURE_ENABLED", "false").lower() in ("true", "1", "yes")
CLOSURE_MAX_FETCH_PER_RUN = int(os.getenv("CLOSURE_MAX_FETCH_PER_RUN", "300"))
# Luật tổ chức bộ máy bị mọi văn bản tỉnh "Căn cứ" (72/2025/QH15 bị dẫn 204 lần).
# Vẫn tải chúng về, nhưng không giãn nở tiếp từ chúng, nếu không bao đóng kéo về
# cả hệ thống pháp luật mà không thêm giá trị nào cho doanh nghiệp.
CLOSURE_HUB_INDEGREE = int(os.getenv("CLOSURE_HUB_INDEGREE", "200"))
CLOSURE_MAX_NODES = int(os.getenv("CLOSURE_MAX_NODES", "15000"))

# Trần độ sâu bao đóng. 0 = không giới hạn (mặc định, đúng lựa chọn đã chốt).
#
# Có van này vì độ sâu nay được tính đúng: trước đây mọi đích đều bị gán cứng
# depth = 1 nên không có cách nào chặn theo khoảng cách. Đặt 2 nếu chỉ cần văn
# bản mà văn bản mới dẫn chiếu tới và văn bản mà CHÚNG dẫn tới — đủ để nói
# "quy định nào đã đổi", trong khi cái đuôi sâu hơn mới là phần làm kho phình.
CLOSURE_MAX_DEPTH = int(os.getenv("CLOSURE_MAX_DEPTH", "0"))
# Dừng bao đóng khi đĩa còn dưới mức này. Đĩa đầy giữa lúc SQLite đang ghi
# có thể làm hỏng cơ sở dữ liệu; frontier nằm trong DB nên dừng rồi chạy
# tiếp được sau khi dọn chỗ.
MIN_FREE_DISK_GB = float(os.getenv("MIN_FREE_DISK_GB", "5"))

# ──────────────────────────────────────────────
# Chấm điểm tác động & báo cáo
# ──────────────────────────────────────────────
# Đổi công thức thì tăng version: kết quả cũ vẫn tra được để đối chiếu.
#
# TÊN CÓ CHỮ "BASE" LÀ CỐ Ý. Đây là phần gốc, KHÔNG phải giá trị lưu trong
# `document_industry_impact.scorer_version` — cột đó lưu bản đã nhúng tên model
# ("v1.0.0+text-embedding-3-small"). Lọc bằng giá trị gốc trần thì truy vấn trả
# về 0 dòng và biểu đồ, bảng điểm lặng lẽ biến mất, không có gì báo lỗi.
#
# Trước đây hằng số này mang tên IMPACT_SCORER_VERSION, nghe như đã đầy đủ, và
# tôi đã mắc bẫy chính nó khi viết scripts/demo_pdf_bieu_do.py. Đổi tên để lần
# sau ai với nhầm thì nhận ImportError ngay, thay vì nhận một báo cáo thiếu số
# liệu mà vẫn trông bình thường.
#
# Cần giá trị để so với DB thì dùng impact_scorer_version() bên dưới.
IMPACT_SCORER_BASE_VERSION = os.getenv("IMPACT_SCORER_VERSION", "v1.0.0")


def impact_scorer_version() -> str:
    """Phiên bản bộ chấm điểm ĐẦY ĐỦ — đúng giá trị lưu trong DB.

    Nhúng tên model nhúng vì EMBEDDING_MODEL đọc từ env nên có thể đổi thầm
    lặng; gắn vào version để điểm cũ và điểm mới không bao giờ bị lẫn.

    Đặt ở config chứ không ở scripts/: sáu chỗ trong hệ thống cần giá trị này,
    trong đó có src/rag/reports/jobs.py — tức mã thư viện đang import từ thư
    mục script, chỉ chạy được nhờ thư mục gốc nằm trong sys.path.

    Import bên trong hàm để tránh vòng lặp: embeddings_api import từ config.
    Hàm được gọi chỉ đọc biến môi trường, không có I/O, nên gọi bao nhiêu lần
    cũng được.
    """
    from src.rag.embeddings_api import active_embedding_model

    return f"{IMPACT_SCORER_BASE_VERSION}+{active_embedding_model()}"
MAX_REPORTS_PER_DAY = int(os.getenv("MAX_REPORTS_PER_DAY", "5"))
REPORT_B_COOLDOWN_DAYS = int(os.getenv("REPORT_B_COOLDOWN_DAYS", "7"))

# ──────────────────────────────────────────────
# Trang công khai
# ──────────────────────────────────────────────
PUBLIC_VAULT_BASE_URL = os.getenv("PUBLIC_VAULT_BASE_URL", "")
PUBLISH_VAULT_ENABLED = os.getenv("PUBLISH_VAULT_ENABLED", "false").lower() in (
    "true", "1", "yes",
)


# ──────────────────────────────────────────────
# File Storage Paths
# ──────────────────────────────────────────────
DATA_DIR = PROJECT_ROOT / "data"
TVPL_FILES_DIR = DATA_DIR / "tvpl"
MOJ_FILES_DIR = DATA_DIR / "moj"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
BACKUPS_DIR = DATA_DIR / "backups"
LOGS_DIR = DATA_DIR / "logs"

# Kho biểu mẫu. HTML gốc TVPL nằm riêng khỏi bản dựng lại: bản gốc chỉ là nguyên
# liệu nội bộ và KHÔNG được đăng công khai, bản dựng lại thì có — để nhầm hai
# thứ này vào một thư mục là sớm muộn cũng đẩy nhầm (xem README § Trang công khai).
FORMS_DIR = DATA_DIR / "forms"
FORMS_HTML_DIR = FORMS_DIR / "html"
FORMS_BUILD_DIR = FORMS_DIR / "build"

# Ensure directories exist
for d in [TVPL_FILES_DIR, MOJ_FILES_DIR, SNAPSHOTS_DIR, BACKUPS_DIR, LOGS_DIR,
          FORMS_HTML_DIR, FORMS_BUILD_DIR]:
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
