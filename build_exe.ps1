param(
    [switch]$SkipPortableZip
)

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
# Always use slim/essential FFmpeg for bundling (NOT system full builds ~185 MB each)
$FfmpegDest = $AppDir
$LocalCli = Join-Path $ProjectRoot "cli"
$FfmpegSrc = $null

# 1. Prefer local cli/ folder (cached essential build from previous download)
if ((Test-Path (Join-Path $LocalCli "ffmpeg.exe")) -and (Test-Path (Join-Path $LocalCli "ffprobe.exe"))) {
    $FfmpegSrc = $LocalCli
    Write-Host "[3/4] Using FFmpeg essential build from cli/ folder"
}

# 2. Download essential build if not found locally
if (-not $FfmpegSrc) {
    Write-Host "[3/4] Downloading FFmpeg essential build (slim, ~40 MB vs 185 MB full)..."
    $TempFfmpegDir = Join-Path $env:TEMP "ffmpeg-essential"
    if (Test-Path $TempFfmpegDir) { Remove-Item -LiteralPath $TempFfmpegDir -Recurse -Force -ErrorAction SilentlyContinue }
    New-Item -ItemType Directory -Path $TempFfmpegDir -Force | Out-Null
    
    # Gyan.dev essential build: only commonly-used codecs (h264, aac, mp3, vpx)
    $FfmpegUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    $ZipFile = Join-Path $TempFfmpegDir "ffmpeg.zip"
    
    try {
        Invoke-WebRequest -Uri $FfmpegUrl -OutFile $ZipFile -TimeoutSec 300
        Expand-Archive -Path $ZipFile -DestinationPath $TempFfmpegDir -Force
        $ExtractedExe = Get-ChildItem -Path $TempFfmpegDir -Filter "ffmpeg.exe" -Recurse | Select-Object -First 1
        if (-not $ExtractedExe) {
            throw "ffmpeg.exe not found in downloaded archive"
        }
        $FfmpegSrc = $ExtractedExe.Directory.FullName
        # Cache in cli/ for future builds
        if (-not (Test-Path $LocalCli)) { New-Item -ItemType Directory -Path $LocalCli -Force | Out-Null }
        @("ffmpeg.exe", "ffprobe.exe") | ForEach-Object {
            $src = Join-Path $FfmpegSrc $_
            if (Test-Path $src) {
                Copy-Item -LiteralPath $src -Destination $LocalCli -Force
            }
        }
        Write-Host "       Cached to cli/ for future builds"
    } catch {
        throw "Failed to download FFmpeg essential build: $_"
    }
}

# Only copy ffmpeg.exe + ffprobe.exe (ffplay.exe is never used by the app)
Write-Host "       Copying ffmpeg.exe, ffprobe.exe..."
@("ffmpeg.exe", "ffprobe.exe") | ForEach-Object {
    $src = Join-Path $FfmpegSrc $_
    if (-not (Test-Path $src)) {
        throw "Missing $_ in source: $FfmpegSrc"
    }
    Copy-Item -LiteralPath $src -Destination $FfmpegDest -Force
    $sz = [math]::Round((Get-Item $src).Length / 1MB, 1)
    Write-Host "       $_ ($sz MB)"
}

# ── Create portable ZIP ──
$ZipPath = $null
$ZipSize = $null
if (-not $SkipPortableZip) {
    $ZipName = "DuyTrisDownloader_Portable.zip"
    $ZipPath = Join-Path $DistDir $ZipName
    Write-Host "[4/4] Creating portable ZIP..."
    if (Test-Path $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
    if (Get-Command tar.exe -ErrorAction SilentlyContinue) {
        # Windows tar creates the central directory reliably for this large bundle.
        & tar.exe -a -cf $ZipPath -C $DistDir "DuyTrisDownloader"
        if ($LASTEXITCODE -ne 0) {
            throw "tar.exe failed to create portable ZIP (exit code $LASTEXITCODE)."
        }
    } else {
        Compress-Archive -Path (Join-Path $AppDir "*") -DestinationPath $ZipPath -CompressionLevel Optimal
    }
    $ZipSize = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
    Write-Host "       ZIP: $ZipPath ($ZipSize MB)"
} else {
    Write-Host "[4/4] Skipping portable ZIP."
}

# ── Summary ──
$AppSize = [math]::Round((Get-ChildItem -LiteralPath $AppDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
Write-Host ""
Write-Host "========================================"
Write-Host "  BUILD SUCCESSFUL!"
Write-Host "  App dir : $AppDir ($AppSize MB)"
if ($ZipPath) { Write-Host "  Portable: $ZipPath ($ZipSize MB)" }
Write-Host ""
Write-Host "  To create SETUP.EXE, run:"
Write-Host "  powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\installer\Build-Installer.ps1"
Write-Host "========================================"
