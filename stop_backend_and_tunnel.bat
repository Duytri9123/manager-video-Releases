@echo off
chcp 65001 >nul
title Dừng Toàn Bộ Hệ Thống ToolVideo

echo ================================================================
echo    ĐANG DỪNG BACKEND VÀ CLOUDFLARE TUNNEL (toolvideo)...
echo ================================================================
echo.

echo [1/2] Đang dừng tiến trình Cloudflare Tunnel (toolvideo-backend)...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'cloudflared.exe' -and ($_.CommandLine -like '*toolvideo*' -or $_.CommandLine -like '*tunnel_config.yml*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

echo [2/2] Đang giải phóng cổng 9123 (Backend Server)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :9123 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo.
echo ================================================================
echo   ĐÃ DỪNG TOÀN BỘ HỆ THỐNG THÀNH CÔNG!
echo ================================================================
if not "%1"=="--silent" (
    timeout /t 3 >nul
)
