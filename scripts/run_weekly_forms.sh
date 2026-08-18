#!/bin/bash
# Làm mới kho biểu mẫu — chạy HẰNG TUẦN, không nhét vào run_daily.sh.
#
# Biểu mẫu đổi chậm hơn văn bản rất nhiều: nó chỉ đổi khi có văn bản mới ban
# hành kèm phụ lục mới. Chạy hằng ngày là tải lại gần như y nguyên kho cũ, mà
# mỗi lượt tải thừa lại đẩy phiên tới gần ngưỡng chặn của Cloudflare hơn.
#
# Bốn bước, đúng thứ tự:
#   1. cào       — tải trang, lưu HTML gốc
#   2. phân loại — phễu ba tầng, quyết định mẫu nào phục vụ kinh doanh
#   3. dựng file — CHỈ dựng cho mẫu đã qua phễu, tránh đốt công vô ích
#   4. đăng      — sinh trang tra cứu công khai
#
# Dừng-tiếp được: bước 1 bóc lại từ HTML đã lưu nên chạy lại chỉ tải phần còn
# thiếu. Cloudflare chặn liên tiếp thì bộ cào tự dừng và lần chạy sau đi tiếp.

set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
source .venv/bin/activate

LOG_DIR="data/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/weekly_forms_$(date +%Y%m%d).log"

{
    echo "════════ $(date '+%Y-%m-%d %H:%M:%S') — làm mới kho biểu mẫu ════════"

    echo "── 1/4 Cào mẫu hợp đồng ──"
    python -m scripts.crawl_forms --source hopdong

    echo "── 2/4 Cào biểu mẫu theo lĩnh vực kinh doanh ──"
    python -m scripts.crawl_forms --source bieumau

    echo "── 3/4 Phễu lọc + dựng file ──"
    python -m scripts.classify_forms
    python -m scripts.build_forms

    echo "── 4/4 Sinh trang công khai ──"
    python -m scripts.publish_site

    echo "════════ xong lúc $(date '+%H:%M:%S') ════════"
} >> "$LOG" 2>&1

# Không dùng `set -e`: bước cào bị Cloudflare chặn là chuyện BÌNH THƯỜNG hằng
# tuần, và nó không được ngăn ba bước sau chạy trên phần dữ liệu đã có.
exit 0
