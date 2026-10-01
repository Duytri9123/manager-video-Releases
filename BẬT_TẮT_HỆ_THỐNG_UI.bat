@echo off
chcp 65001 >nul
title DuyTris System Manager
cd /d "%~dp0"

if exist "setup.exe" (
    start "" "setup.exe" %*
) else (
    echo [THÔNG BÁO] Đang biên dịch setup.exe...
    call "tools\build_setup_manager.bat"
    if exist "setup.exe" start "" "setup.exe" %*
)
