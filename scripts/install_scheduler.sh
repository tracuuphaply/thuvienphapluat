#!/bin/bash
# Cài lịch chạy hằng ngày bằng launchd (macOS).
#
# Vì sao launchd chứ không phải cron: cron KHÔNG chạy bù. Máy ngủ hoặc tắt vào
# đúng 6h sáng là mất hẳn ngày đó, không có cách nào biết. launchd với
# StartCalendarInterval sẽ chạy ngay khi máy thức dậy nếu đã lỡ mốc.
#
# Cài BA agent:
#   vn.legalvault.daily      cào + đồng bộ + rút hàng đợi báo cáo, mỗi ngày
#   vn.legalvault.weeklyforms làm mới kho biểu mẫu, mỗi Chủ nhật
#   vn.legalvault.quarterly  xếp hàng báo cáo tổng hợp ngành, đầu mỗi quý
#
# Biểu mẫu tách khỏi agent hằng ngày vì nó đổi chậm hơn văn bản rất nhiều: chạy
# hằng ngày là tải lại gần như y nguyên kho cũ, mà mỗi lượt tải thừa lại đẩy
# phiên tới gần ngưỡng chặn của Cloudflare hơn.
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
FLABEL="vn.legalvault.weeklyforms"
FPLIST="$HOME/Library/LaunchAgents/$FLABEL.plist"

if [ "${1:-}" = "--uninstall" ]; then
    for l in "$LABEL" "$QLABEL" "$FLABEL"; do
        launchctl bootout "gui/$(id -u)/$l" 2>/dev/null || true
        rm -f "$HOME/Library/LaunchAgents/$l.plist"
    done
    echo "Đã gỡ $LABEL, $QLABEL và $FLABEL"
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

# ── Agent biểu mẫu, hằng tuần ──
#
# Weekday 0 = Chủ nhật, 5h sáng: trước agent hằng ngày một tiếng để trang công
# khai sinh ra trong ngày đã có kho biểu mẫu mới nhất.
cat > "$FPLIST" <<FPLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$FLABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PROJECT_DIR/scripts/run_weekly_forms.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key><integer>0</integer>
        <key>Hour</key><integer>5</integer>
        <key>Minute</key><integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$PROJECT_DIR/data/logs/launchd.forms.log</string>
    <key>StandardErrorPath</key>
    <string>$PROJECT_DIR/data/logs/launchd.forms.err.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
FPLIST_EOF

chmod +x "$PROJECT_DIR/scripts/run_weekly_forms.sh"
launchctl bootout "gui/$(id -u)/$FLABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$FPLIST"

echo "Đã cài $LABEL — chạy hằng ngày lúc $(printf '%02d:%02d' "$HOUR" "$MINUTE")"
echo "Đã cài $QLABEL — chạy 1/1, 1/4, 1/7, 1/10 lúc 07:00"
echo "Đã cài $FLABEL — làm mới kho biểu mẫu, Chủ nhật 05:00"
echo "  plist:      $PLIST"
echo "  kiểm tra:   launchctl print gui/$(id -u)/$LABEL | head -20"
echo "  chạy ngay:  launchctl kickstart -k gui/$(id -u)/$LABEL"
echo "  gỡ:         ./scripts/install_scheduler.sh --uninstall"
