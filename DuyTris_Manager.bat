@echo off
chcp 65001 >nul
title DuyTris System & Setup EXE Manager
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "tools\system_manager.py"
) else (
    python "tools\system_manager.py"
)
pause
