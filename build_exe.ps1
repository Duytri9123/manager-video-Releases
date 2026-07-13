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

# Paths for config cleaning
$ConfigYml = Join-Path $ProjectRoot "config.yml"
$ConfigBackup = Join-Path $ProjectRoot "config.yml.bak"
$ConfigExample = Join-Path $ProjectRoot "config.example.yml"

try {
    # ── Clean API keys in config.yml ──
    if (Test-Path $ConfigYml) {
        Write-Host "[0/5] Backing up local config.yml and cleaning API keys..."
        Copy-Item -LiteralPath $ConfigYml -Destination $ConfigBackup -Force
        
        if (Test-Path $ConfigExample) {
            Copy-Item -LiteralPath $ConfigExample -Destination $ConfigYml -Force
            Write-Host "       config.yml has been cleaned using template."
        }
    }

    # ── Clean previous build ──
    $DistDir = Join-Path $ProjectRoot "dist"
    $BuildDir = Join-Path $ProjectRoot "build"
    $OutputDir = Join-Path $ProjectRoot "output"
    Write-Host "[1/5] Cleaning previous build..."
    if (Test-Path $DistDir) { Remove-Item -LiteralPath $DistDir -Recurse -Force -ErrorAction SilentlyContinue }
    if (Test-Path $BuildDir) { Remove-Item -LiteralPath $BuildDir -Recurse -Force -ErrorAction SilentlyContinue }
    if (Test-Path $OutputDir) {
        Get-ChildItem -Path $OutputDir -Filter "*.exe" | Remove-Item -Force -ErrorAction SilentlyContinue
        Get-ChildItem -Path $OutputDir -Filter "*.zip" | Remove-Item -Force -ErrorAction SilentlyContinue
    }

    # ── PyArmor obfuscation ──
    Write-Host "[2/5] Running PyArmor obfuscation..."
    $PyArmorScript = Join-Path (Join-Path $ProjectRoot "cli") "obfuscate_modules.py"
    if (Test-Path $PyArmorScript) {
        & $Python $PyArmorScript
        if ($LASTEXITCODE -ne 0) {
            Write-Host "       PyArmor fallback OK (non-fatal)"
        }
    } else {
        Write-Host "       PyArmor script not found, skipping"
    }

    # ── PyInstaller build ──
    Write-Host "[3/5] Running PyInstaller..."
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

    # ── Copy FFmpeg binaries ──
    $FfmpegDest = $AppDir
    $LocalCli = Join-Path $ProjectRoot "cli"
    $FfmpegSrc = $null

    if ((Test-Path (Join-Path $LocalCli "ffmpeg.exe")) -and (Test-Path (Join-Path $LocalCli "ffprobe.exe"))) {
        $FfmpegSrc = $LocalCli
        Write-Host "[4/5] Using FFmpeg essential build from cli/ folder"
    }

    if (-not $FfmpegSrc) {
        Write-Host "[4/5] Downloading FFmpeg essential build..."
        $TempFfmpegDir = Join-Path $env:TEMP "ffmpeg-essential"
        if (Test-Path $TempFfmpegDir) { Remove-Item -LiteralPath $TempFfmpegDir -Recurse -Force -ErrorAction SilentlyContinue }
        New-Item -ItemType Directory -Path $TempFfmpegDir -Force | Out-Null
        
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
            if (-not (Test-Path $LocalCli)) { New-Item -ItemType Directory -Path $LocalCli -Force | Out-Null }
            @("ffmpeg.exe", "ffprobe.exe") | ForEach-Object {
                $src = Join-Path $FfmpegSrc $_
                if (Test-Path $src) {
                    Copy-Item -LiteralPath $src -Destination $LocalCli -Force
                }
            }
        } catch {
            throw "Failed to download FFmpeg: $_"
        }
    }

    Write-Host "       Copying ffmpeg.exe, ffprobe.exe..."
    @("ffmpeg.exe", "ffprobe.exe") | ForEach-Object {
        $src = Join-Path $FfmpegSrc $_
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
        Write-Host "[5/5] Creating portable ZIP..."
        if (Test-Path $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
        if (Get-Command tar.exe -ErrorAction SilentlyContinue) {
            & tar.exe -a -cf $ZipPath -C $DistDir "DuyTrisDownloader"
        } else {
            Compress-Archive -Path (Join-Path $AppDir "*") -DestinationPath $ZipPath -CompressionLevel Optimal
        }
        $ZipSize = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
        Write-Host "       ZIP: $ZipPath ($ZipSize MB)"
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

} finally {
    # ── Restore local config.yml ──
    if (Test-Path $ConfigBackup) {
        Write-Host "       Restoring local config.yml from backup..."
        Copy-Item -LiteralPath $ConfigBackup -Destination $ConfigYml -Force
        Remove-Item -LiteralPath $ConfigBackup -Force
    }
}
