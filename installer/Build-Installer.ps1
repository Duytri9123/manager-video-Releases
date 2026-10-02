param(
    [string]$AppDir = (Join-Path $PSScriptRoot '..\dist\DuyTrisDownloader'),
    [string]$OutputExe = (Join-Path $PSScriptRoot '..\output\DuyTrisDownloader_Setup.exe')
)

$ErrorActionPreference = 'Stop'

$AppDir = (Resolve-Path -LiteralPath $AppDir).Path
$OutputExe = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputExe)
$IssPath = Join-Path $PSScriptRoot 'DuyTrisDownloader.iss'
$RequiredFiles = @('DuyTrisDownloader.exe', 'ffmpeg.exe', 'ffprobe.exe')

foreach ($name in $RequiredFiles) {
    $path = Join-Path $AppDir $name
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Missing required installer file: $path"
    }
}

$CompilerCandidates = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
    'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
    'C:\Program Files\Inno Setup 6\ISCC.exe',
    (Join-Path $env:LOCALAPPDATA 'Programs\Antigravity IDE\resources\app\node_modules\innosetup\bin\ISCC.exe')
)
$ISCC = $CompilerCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

if (-not $ISCC) {
    throw 'Inno Setup 6 was not found. Install it with: winget install --id JRSoftware.InnoSetup --exact'
}

$GeneratedOutput = Join-Path $PSScriptRoot '..\output\setup.exe'

if (Test-Path -LiteralPath $GeneratedOutput) {
    Remove-Item -LiteralPath $GeneratedOutput -Force
}

$appSizeMb = [Math]::Round((Get-ChildItem -LiteralPath $AppDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
Write-Host "Building standard Windows installer from $appSizeMb MB of application files..."
& $ISCC $IssPath
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup build failed (exit code $LASTEXITCODE)."
}

if (-not (Test-Path -LiteralPath $GeneratedOutput)) {
    throw "Installer was not created: $GeneratedOutput"
}

if ($GeneratedOutput -ne $OutputExe) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputExe) | Out-Null
    Move-Item -LiteralPath $GeneratedOutput -Destination $OutputExe -Force
}

$output = Get-Item -LiteralPath $OutputExe
Write-Host ("Created standard installer: {0} ({1:N1} MB)" -f $output.FullName, ($output.Length / 1MB))
