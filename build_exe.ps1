$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Khong tim thay Python tai $Python"
}

# ── Clean previous build ──
$DistDir = Join-Path $ProjectRoot "dist"
$BuildDir = Join-Path $ProjectRoot "build"
Write-Host "[1/4] Cleaning previous build..."
if (Test-Path $DistDir) { Remove-Item -LiteralPath $DistDir -Recurse -Force -ErrorAction SilentlyContinue }
if (Test-Path $BuildDir) { Remove-Item -LiteralPath $BuildDir -Recurse -Force -ErrorAction SilentlyContinue }

# ── PyInstaller build ──
Write-Host "[2/4] Running PyInstaller..."
& $Python -m PyInstaller `
    --log-level WARN `
    --noconfirm `
    (Join-Path $ProjectRoot "toolvideo.spec")

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build that bai (exit code $LASTEXITCODE)."
}

$AppDir = Join-Path $DistDir "DuyTrisDownloader"
$Exe = Join-Path $AppDir "DuyTrisDownloader.exe"
if (-not (Test-Path $Exe)) {
    throw "Build completed but $Exe not found."
}
Write-Host "       EXE: $Exe"

# ── Copy FFmpeg binaries (required at runtime) ──
$FfmpegSrc = "C:\ffmpeg\bin"
$FfmpegDest = $AppDir

# If C:\ffmpeg\bin is not found, check if we have a local cli/ folder with ffmpeg
if (-not (Test-Path $FfmpegSrc)) {
    $LocalFfmpeg = Join-Path $ProjectRoot "cli"
    if (Test-Path $LocalFfmpeg) {
        $FfmpegSrc = $LocalFfmpeg
    }
}

# If still not found, download it automatically!
if (-not (Test-Path $FfmpegSrc) -or -not (Test-Path (Join-Path $FfmpegSrc "ffmpeg.exe"))) {
    Write-Host "FFmpeg not found in C:\ffmpeg\bin or local cli/ folder."
    Write-Host "Downloading FFmpeg automatically..."
    $TempFfmpegDir = Join-Path $env:TEMP "ffmpeg-download"
    if (Test-Path $TempFfmpegDir) { Remove-Item -LiteralPath $TempFfmpegDir -Recurse -Force -ErrorAction SilentlyContinue }
    New-Item -ItemType Directory -Path $TempFfmpegDir -Force | Out-Null
    
    # URL for a stable static ffmpeg build for Windows
    $FfmpegUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
    $ZipFile = Join-Path $TempFfmpegDir "ffmpeg.zip"
    
    try {
        Invoke-WebRequest -Uri $FfmpegUrl -OutFile $ZipFile -TimeoutSec 180
        Expand-Archive -Path $ZipFile -DestinationPath $TempFfmpegDir -Force
        $ExtractedExe = Get-ChildItem -Path $TempFfmpegDir -Filter "ffmpeg.exe" -Recurse | Select-Object -First 1
        if ($ExtractedExe) {
            $BinDir = $ExtractedExe.Directory.FullName
            $FfmpegSrc = $BinDir
            # Save a copy to the local project root's cli/ folder for future builds & local runs
            $LocalCli = Join-Path $ProjectRoot "cli"
            if (-not (Test-Path $LocalCli)) { New-Item -ItemType Directory -Path $LocalCli -Force | Out-Null }
            @("ffmpeg.exe", "ffprobe.exe") | ForEach-Object {
                $src = Join-Path $BinDir $_
                if (Test-Path $src) {
                    Copy-Item -LiteralPath $src -Destination $LocalCli -Force
                }
            }
        }
    } catch {
        Write-Host "WARNING: Failed to download FFmpeg automatically: $_"
    }
}

if (Test-Path $FfmpegSrc) {
    Write-Host "[3/4] Copying FFmpeg binaries..."
    @("ffmpeg.exe", "ffprobe.exe", "ffplay.exe") | ForEach-Object {
        $src = Join-Path $FfmpegSrc $_
        if (Test-Path $src) {
            Copy-Item -LiteralPath $src -Destination $FfmpegDest -Force
            Write-Host "       $_"
        }
    }
}

# ── Create portable ZIP ──
$ZipName = "DuyTrisDownloader_Portable.zip"
$ZipPath = Join-Path $DistDir $ZipName
Write-Host "[4/4] Creating portable ZIP..."
if (Test-Path $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
Compress-Archive -Path (Join-Path $AppDir "*") -DestinationPath $ZipPath -CompressionLevel Optimal
$ZipSize = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
Write-Host "       ZIP: $ZipPath ($ZipSize MB)"

# ── Summary ──
$AppSize = [math]::Round((Get-ChildItem -LiteralPath $AppDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
Write-Host ""
Write-Host "========================================"
Write-Host "  BUILD SUCCESSFUL!"
Write-Host "  App dir : $AppDir ($AppSize MB)"
Write-Host "  Portable: $ZipPath ($ZipSize MB)"
Write-Host ""
Write-Host "  To create SETUP.EXE, run:"
Write-Host "  .\installer\Build-Installer.ps1 -PortableZip '$ZipPath'"
Write-Host "========================================"
