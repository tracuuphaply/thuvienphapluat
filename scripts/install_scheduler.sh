#!/bin/bash
# Cài lịch chạy hằng ngày bằng launchd (macOS).
#
# Vì sao launchd chứ không phải cron: cron KHÔNG chạy bù. Máy ngủ hoặc tắt vào
# đúng 6h sáng là mất hẳn ngày đó, không có cách nào biết. launchd với
# StartCalendarInterval sẽ chạy ngay khi máy thức dậy nếu đã lỡ mốc.
#
# Cài HAI agent:
#   vn.legalvault.daily      cào + đồng bộ + rút hàng đợi báo cáo, mỗi ngày
#   vn.legalvault.quarterly  xếp hàng báo cáo tổng hợp ngành, đầu mỗi quý
#
# Agent hằng quý chỉ XẾP HÀNG, không sinh báo cáo — agent hằng ngày rút hàng
# đợi. Tách như vậy thì trần MAX_REPORTS_PER_DAY vẫn có tác dụng: 17 báo cáo
# ngành rải ra vài ngày thay vì dồn một lần.
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
QLABEL="vn.legalvault.quarterly"
QPLIST="$HOME/Library/LaunchAgents/$QLABEL.plist"

if [ "${1:-}" = "--uninstall" ]; then
    for l in "$LABEL" "$QLABEL"; do
        launchctl bootout "gui/$(id -u)/$l" 2>/dev/null || true
        rm -f "$HOME/Library/LaunchAgents/$l.plist"
    done
    echo "Đã gỡ $LABEL và $QLABEL"
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

# ── Agent hằng quý ──
#
# StartCalendarInterval nhận MỘT MẢNG dict: bốn mốc 1/1, 1/4, 1/7, 1/10. Một
# dict duy nhất chỉ đặt được một mốc, nên bản chỉ có Day+Month sẽ chạy đúng
# một quý mỗi năm chứ không phải bốn.
cat > "$QPLIST" <<QPLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$QLABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PROJECT_DIR/scripts/run_quarterly.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Month</key><integer>1</integer><key>Day</key><integer>1</integer><key>Hour</key><integer>7</integer></dict>
        <dict><key>Month</key><integer>4</integer><key>Day</key><integer>1</integer><key>Hour</key><integer>7</integer></dict>
        <dict><key>Month</key><integer>7</integer><key>Day</key><integer>1</integer><key>Hour</key><integer>7</integer></dict>
        <dict><key>Month</key><integer>10</integer><key>Day</key><integer>1</integer><key>Hour</key><integer>7</integer></dict>
    </array>
    <key>StandardOutPath</key>
    <string>$PROJECT_DIR/data/logs/launchd.quarterly.log</string>
    <key>StandardErrorPath</key>
    <string>$PROJECT_DIR/data/logs/launchd.quarterly.err.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
QPLIST_EOF

chmod +x "$PROJECT_DIR/scripts/run_quarterly.sh"
launchctl bootout "gui/$(id -u)/$QLABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$QPLIST"

echo "Đã cài $LABEL — chạy hằng ngày lúc $(printf '%02d:%02d' "$HOUR" "$MINUTE")"
echo "Đã cài $QLABEL — chạy 1/1, 1/4, 1/7, 1/10 lúc 07:00"
echo "  plist:      $PLIST"
echo "  kiểm tra:   launchctl print gui/$(id -u)/$LABEL | head -20"
echo "  chạy ngay:  launchctl kickstart -k gui/$(id -u)/$LABEL"
echo "  gỡ:         ./scripts/install_scheduler.sh --uninstall"
