#!/bin/bash
# Cài lịch chạy hằng ngày bằng launchd (macOS).
#
# Vì sao launchd chứ không phải cron: cron KHÔNG chạy bù. Máy ngủ hoặc tắt vào
# đúng 6h sáng là mất hẳn ngày đó, không có cách nào biết. launchd với
# StartCalendarInterval sẽ chạy ngay khi máy thức dậy nếu đã lỡ mốc.
#
# Dùng:
#   ./scripts/install_scheduler.sh            # cài, mặc định 6h sáng
#   ./scripts/install_scheduler.sh 7 30       # cài, chạy 7h30
#   ./scripts/install_scheduler.sh --uninstall

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LABEL="vn.legalvault.daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ "${1:-}" = "--uninstall" ]; then
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Đã gỡ lịch chạy $LABEL"
    exit 0
fi

HOUR="${1:-6}"
MINUTE="${2:-0}"

mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT_DIR/data/logs"
chmod +x "$PROJECT_DIR/scripts/run_daily.sh"

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PROJECT_DIR/scripts/run_daily.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>$HOUR</integer>
        <key>Minute</key><integer>$MINUTE</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$PROJECT_DIR/data/logs/launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>$PROJECT_DIR/data/logs/launchd.err.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
PLIST_EOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "Đã cài $LABEL — chạy hằng ngày lúc $(printf '%02d:%02d' "$HOUR" "$MINUTE")"
echo "  plist:      $PLIST"
echo "  kiểm tra:   launchctl print gui/$(id -u)/$LABEL | head -20"
echo "  chạy ngay:  launchctl kickstart -k gui/$(id -u)/$LABEL"
echo "  gỡ:         ./scripts/install_scheduler.sh --uninstall"
