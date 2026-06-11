$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Khong tim thay Python tai $Python"
}

& $Python -m PyInstaller `
    --log-level WARN `
    --noconfirm `
    (Join-Path $ProjectRoot "toolvideo.spec")

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build that bai (exit code $LASTEXITCODE)."
}

$Exe = Join-Path $ProjectRoot "dist\DuyTrisDownloader\DuyTrisDownloader.exe"
Write-Host ""
Write-Host "Build thanh cong: $Exe"
