@echo off
setlocal
cd /d "%~dp0\.."

echo =======================================================
echo    BUILDING DUYTRIS SETUP MANAGER (setup.exe)
echo =======================================================
echo.

set "CSC=C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" (
    set "CSC=C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"
)

if not exist "%CSC%" (
    echo [ERROR] Cannot find csc.exe compiler.
    exit /b 1
)

echo [1/1] Compiling tools\SetupManager.cs to setup.exe ...
"%CSC%" /target:winexe /optimize+ /platform:anycpu /win32icon:img\logo.ico /out:setup.exe tools\SetupManager.cs

if errorlevel 1 (
    echo.
    echo [ERROR] Compilation failed.
    exit /b 1
)

echo.
echo =======================================================
echo    SUCCESS: Created setup.exe
echo =======================================================
endlocal
