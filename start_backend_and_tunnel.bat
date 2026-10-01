@echo off
chcp 65001 >nul
title Khởi Động Backend & Cloudflare Tunnel - toolvideo.dgpelectric.top

echo ================================================================
echo   KHỞI ĐỘNG BACKEND & CLOUDFLARE TUNNEL (toolvideo.dgpelectric.top)
echo ================================================================
echo.

echo [1/2] Kiểm tra và khởi chạy Backend Server (Port 9123)...
netstat -ano | findstr :9123 | findstr LISTENING >nul 2>&1
if errorlevel 1 (
    echo [Backend] Đang tự động bật Backend Server (Port 9123)...
    if exist "%~dp0.venv\Scripts\python.exe" (
        start "DuyTris Backend (Port 9123)" /min "%~dp0.venv\Scripts\python.exe" "%~dp0run_flask.py"
    ) else (
        start "DuyTris Backend (Port 9123)" /min python "%~dp0run_flask.py"
    )
) else (
    echo [Backend] Backend Server đã đang chạy trên cổng 9123.
)

echo Đang chờ Backend khởi tạo dữ liệu trong 3 giây...
timeout /t 3 /nobreak >nul

echo [2/2] Khởi chạy Cloudflare Tunnel kết nối tên miền dgpelectric.top...
start "Cloudflare Tunnel (dgpelectric.top)" cmd /k "cloudflared --config "%~dp0tools\tunnel_config.yml" tunnel run aide-backend"

echo.
echo ================================================================
echo   ĐÃ KHỞI ĐỘNG XONG HỆ THỐNG DỊCH VỤ!
echo   - Backend Local:  http://localhost:9123
echo   - Tên miền ngoài: https://dgpelectric.top
echo   - Tên miền phụ:   https://toolvideo.dgpelectric.top
echo ================================================================
echo Cửa sổ điều khiển này sẽ tự đóng sau 5 giây.
echo (Các cửa sổ Backend và Cloudflare Tunnel sẽ tiếp tục chạy)
timeout /t 5 >nul
exit
