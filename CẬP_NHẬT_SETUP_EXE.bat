@echo off
chcp 65001 >nul
title Cập Nhật & Build Setup EXE - DuyTris Downloader
cd /d "%~dp0"

echo =======================================================
echo    📦 ĐANG CẬP NHẬT VÀ BUILD DUYTRIS DOWNLOADER SETUP EXE
echo =======================================================

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "tools\system_manager.py" build
) else (
    python "tools\system_manager.py" build
)

echo.
pause
