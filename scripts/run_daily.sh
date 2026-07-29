#!/bin/bash
# Daily pipeline runner — designed for crontab
# Crontab entry:  0 6 * * * /path/to/thuvienphapluat/scripts/run_daily.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/data/logs"
LOG_FILE="$LOG_DIR/$(date +%Y-%m-%d).log"

mkdir -p "$LOG_DIR"

cd "$PROJECT_DIR"

# Activate virtual environment if exists
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

echo "=== Pipeline started at $(date) ===" >> "$LOG_FILE"

# Run the pipeline (MOJ-only if no TVPL credentials configured)
python -m src.main --skip-gdrive 2>&1 | tee -a "$LOG_FILE"

# Run backup after pipeline
python -m src.utils.backup 2>&1 | tee -a "$LOG_FILE"

echo "=== Pipeline finished at $(date) ===" >> "$LOG_FILE"
