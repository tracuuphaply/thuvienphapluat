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

if [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
else
    PY="python3"
fi

echo "=== Pipeline bắt đầu lúc $(date) ==="

# 1. Cào và xử lý văn bản mới
"$PY" -m src.main --skip-gdrive
PIPELINE_RC=$?
echo "--- pipeline kết thúc, mã thoát=$PIPELINE_RC ---"

# 2. Đồng bộ Obsidian Vault + RAG index.
#    run_pipeline() KHÔNG tự làm bước này (nó nằm trong nhánh --upload-only),
#    nên chỉ chạy src.main thì vault vĩnh viễn không được cập nhật.
if [ "$PIPELINE_RC" -eq 0 ]; then
    "$PY" -m src.main --sync-vault-only
    "$PY" -m src.main --sync-rag-only
else
    echo "Bỏ qua đồng bộ vault/RAG vì pipeline lỗi."
fi

# 3. Sao lưu — chạy bất kể pipeline thành công hay không.
"$PY" -m src.utils.backup

echo "=== Pipeline xong lúc $(date) ==="
exit "$PIPELINE_RC"
