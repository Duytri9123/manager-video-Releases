@echo off
chcp 65001 >nul
title DuyTris Downloader

echo.
echo  ==========================================
echo   DuyTris Downloader - Khoi dong...
echo  ==========================================
echo.

:: Uu tien dung Python trong .venv
set VENV_PY=%~dp0.venv\Scripts\python.exe

if exist "%VENV_PY%" (
    echo  [OK] Dung Python tu .venv
    "%VENV_PY%" "%~dp0run_flask.py" %*
    goto end
)

:: Thu py (Windows Python Launcher)
where py >nul 2>&1
if %errorlevel% == 0 (
    echo  [OK] Dung py launcher
    py "%~dp0run_flask.py" %*
    goto end
)

:: Thu python3
where python3 >nul 2>&1
if %errorlevel% == 0 (
    echo  [OK] Dung python3
    python3 "%~dp0run_flask.py" %*
    goto end
)

:: Thu python
where python >nul 2>&1
if %errorlevel% == 0 (
    echo  [OK] Dung python
    python "%~dp0run_flask.py" %*
    goto end
)

echo.
echo  [LOI] Khong tim thay Python!
echo  Cai dat Python tai: https://www.python.org/downloads/
echo  Hoac kich hoat .venv: .venv\Scripts\activate
echo.
pause
exit /b 1

:end
if %errorlevel% neq 0 (
    echo.
    echo  [LOI] Ung dung bi loi. Xem thong bao o tren.
    pause
)
