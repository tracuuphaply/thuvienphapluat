@echo off
chcp 65001 >nul
:: Daily runner for Windows Task Scheduler / Manual execution

cd /d "%~dp0.."

set LOG_DIR=data\logs
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do if not defined YYYYMMDD set YYYYMMDD=%%I
set TODAY=%YYYYMMDD:~0,4%-%YYYYMMDD:~4,2%-%YYYYMMDD:~6,2%
set LOG_FILE=%LOG_DIR%\%TODAY%.log

echo === Pipeline started at %date% %time% === >> "%LOG_FILE%"

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

:: Run daily pipeline
python -m src.main --skip-gdrive >> "%LOG_FILE%" 2>&1

:: Run daily backup
python -m src.utils.backup >> "%LOG_FILE%" 2>&1

echo === Pipeline finished at %date% %time% === >> "%LOG_FILE%"
