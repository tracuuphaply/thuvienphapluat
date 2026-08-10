#!/bin/bash
# Chạy pipeline hằng ngày. Được gọi bởi launchd (xem scripts/install_scheduler.sh).
#
# Không dùng `set -e`: bước sao lưu PHẢI chạy kể cả khi pipeline hỏng — bản cũ
# dùng `set -euo pipefail` nên pipeline lỗi là bỏ luôn backup, đúng lúc cần nó nhất.
# Log do setup_logging() ghi thẳng vào data/logs/pipeline.log, không cần tee.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

mkdir -p "$PROJECT_DIR/data/logs"
cd "$PROJECT_DIR" || exit 1

# Nạp .env vào môi trường SHELL.
#
# python-dotenv nạp .env cho tiến trình Python, nhưng script này tự đọc hai công
# tắc CLOSURE_ENABLED và REPORT_WORKER_ENABLED bằng cú pháp ${VAR:-false} — mà
# launchd chạy với môi trường trống, nên chúng luôn rỗng và hai bước đó bị bỏ
# qua ÂM THẦM: script vẫn chạy hết, vẫn thoát mã 0, vẫn ghi "Pipeline xong".
#
# Chỉ lấy dòng KEY=VALUE, bỏ chú thích và dòng trống. Không dùng `source` trần:
# .env chứa giá trị có dấu cách và ký tự đặc biệt (khoá API, tên thư mục tiếng
# Việt), source sẽ diễn giải chúng như lệnh.
if [ -f "$PROJECT_DIR/.env" ]; then
    while IFS= read -r line; do
        case "$line" in
            ''|'#'*) continue ;;
            *=*) export "${line%%=*}"="${line#*=}" ;;
        esac
    done < "$PROJECT_DIR/.env"
fi

if [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
else
    PY="python3"
fi

echo "=== Pipeline bắt đầu lúc $(date) ==="

# 1. Cào và xử lý văn bản mới, đẩy luôn lên mây.
#
#    Bản cũ truyền --skip-gdrive vô điều kiện, từ thời nhánh Google Drive chưa
#    chạy được vì dùng service account (hạn mức 0 GB). Nhưng từ khi có bộ điều
#    phối cloud_drive, cờ đó bỏ qua CẢ Lark — nghĩa là lần chạy hằng ngày chưa
#    bao giờ đẩy file lên mây, trong khi yêu cầu vận hành là mọi văn bản tải về
#    phải lưu mây trước. Đích lưu trữ nay chọn bằng CLOUD_DRIVE_PROVIDER.
"$PY" -m src.main
PIPELINE_RC=$?
echo "--- pipeline kết thúc, mã thoát=$PIPELINE_RC ---"

# 2. Đồng bộ Obsidian Vault + RAG index.
#    run_pipeline() KHÔNG tự làm bước này (nó nằm trong nhánh --upload-only),
#    nên chỉ chạy src.main thì vault vĩnh viễn không được cập nhật.
if [ "$PIPELINE_RC" -eq 0 ]; then
    # 2b. Bao đóng dẫn chiếu — kéo về văn bản mà nhóm mới dẫn chiếu tới, kể cả
    #     bản đã bị bãi bỏ. Chạy TRƯỚC đồng bộ để văn bản vừa kéo về cũng vào
    #     index trong cùng một lượt. Tự tắt khi CLOSURE_ENABLED=false.
    if [ "${CLOSURE_ENABLED:-false}" = "true" ]; then
        "$PY" -m scripts.run_closure || echo "Bao đóng lỗi, đi tiếp."
    fi

    "$PY" -m src.main --sync-vault-only
    "$PY" -m src.main --sync-rag-only

    # 2c. Rút hàng đợi báo cáo. Tách khỏi pipeline cào có chủ đích: một lỗi LLM
    #     không được phép đánh dấu cả lần cào là hỏng.
    if [ "${REPORT_WORKER_ENABLED:-false}" = "true" ]; then
        "$PY" -m scripts.run_report_worker || echo "Bộ sinh báo cáo lỗi, đi tiếp."
    fi
else
    echo "Bỏ qua bao đóng và đồng bộ vault/RAG vì pipeline lỗi."
fi

# 3. Sao lưu — chạy bất kể pipeline thành công hay không.
"$PY" -m src.utils.backup

echo "=== Pipeline xong lúc $(date) ==="
exit "$PIPELINE_RC"
