@echo off
chcp 65001 >nul
echo ============================================================
echo   HỆ THỐNG CẬP NHẬT VĂN BẢN PHÁP LUẬT DOANH NGHIỆP — PHASE 1
echo   Cài đặt môi trường cho Windows
echo ============================================================
echo.

cd /d "%~dp0.."

:: 1. Kiểm tra Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [LỖI] Chưa tìm thấy Python trên máy!
    echo Vui lòng tải và cài đặt Python 3.11 trở lên tại https://www.python.org/
    echo Nhớ tích chọn "Add Python to PATH" khi cài đặt.
    pause
    exit /b 1
)

echo [1/5] Khởi tạo môi trường ảo (Virtual Environment)...
if not exist ".venv" (
    python -m venv .venv
)

echo [2/5] Kích hoạt venv và cài đặt dependencies...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -e .

echo [3/5] Cài đặt trình duyệt Playwright (Chromium)...
playwright install chromium

echo [4/5] Kiểm tra file cấu hình .env...
if not exist ".env" (
    echo Đang tạo file .env từ .env.example...
    copy .env.example .env
    echo [LƯU Ý] Hãy mở file .env và điền các thông tin credentials trước khi chạy!
)

echo [5/5] Khởi tạo Database (SQLite)...
python scripts\setup_db.py

echo.
echo ============================================================
echo   CÀI ĐẶT HOÀN TẤT!
echo ============================================================
echo Đọc hướng dẫn chi tiết tại file HUONG_DAN_CHUYEN_GIAO.md
echo.
pause
