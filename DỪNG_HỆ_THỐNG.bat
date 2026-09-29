@echo off
chcp 65001 >nul
title Dừng Hệ Thống DuyTris ToolVideo
cd /d "%~dp0"

echo =======================================================
echo    🛑 ĐANG DỪNG HỆ THỐNG DUYTRIS TOOLVIDEO
echo =======================================================

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "tools\system_manager.py" stop
) else (
    python "tools\system_manager.py" stop
)

echo.
pause
