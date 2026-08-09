#!/bin/bash
# Đầu mỗi quý: xếp hàng báo cáo tổng hợp ngành.
#
# Chỉ XẾP HÀNG, không sinh báo cáo. Agent hằng ngày rút hàng đợi, nên 17 báo
# cáo ngành rải ra vài ngày theo MAX_REPORTS_PER_DAY thay vì dồn một lần — và
# một lỗi LLM không làm hỏng lần chạy theo lịch.
#
# Không dùng `set -e`: xếp hàng hỏng thì vẫn phải ghi log kết thúc.
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

echo "=== Xếp hàng báo cáo quý, bắt đầu $(date) ==="
"$PY" -m scripts.enqueue_quarterly_reports
RC=$?
echo "=== Xong lúc $(date), mã thoát=$RC ==="
exit "$RC"
