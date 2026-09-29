@echo off
chcp 65001 >nul
title Bật Hệ Thống DuyTris ToolVideo
cd /d "%~dp0"

echo =======================================================
echo    🚀 ĐANG KHỞI ĐỘNG HỆ THỐNG DUYTRIS TOOLVIDEO
echo =======================================================

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "tools\system_manager.py" start
) else (
    python "tools\system_manager.py" start
)

echo.
echo Nhấn phím bất kỳ để đóng cửa sổ này (Hệ thống vẫn tiếp tục chạy ngầm)...
pause >nul
