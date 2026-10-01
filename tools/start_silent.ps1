# Khoi chay ngam Backend va Cloudflare Tunnel cho ToolVideo
$baseDir = Split-Path -Parent $PSScriptRoot
if (-not $baseDir) {
    $baseDir = "E:\duytristool\toolvideo"
}

$pythonExe = Join-Path $baseDir ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python"
}

$tunnelConfig = Join-Path $baseDir "tools\tunnel_config.yml"

# 1. Khoi chay Backend Server (Port 9123) neu chua chay
$beRunning = $false
try {
    $client = New-Object System.Net.Sockets.TcpClient
    $async = $client.BeginConnect("127.0.0.1", 9123, $null, $null)
    if ($async.AsyncWaitHandle.WaitOne(400) -and $client.Connected) { $beRunning = $true }
    $client.Close()
} catch {}
if (-not $beRunning) {
    try {
        $conn = Get-NetTCPConnection -LocalPort 9123 -State Listen -ErrorAction SilentlyContinue
        if ($conn) { $beRunning = $true }
    } catch {}
}

if (-not $beRunning) {
    Start-Process -FilePath $pythonExe `
        -ArgumentList "`"$baseDir\run_flask.py`"" `
        -WorkingDirectory $baseDir `
        -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

# 2. Khoi chay Cloudflare Tunnel neu chua chay
$cfRunning = $false
try {
    $p = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'cloudflared.exe' }
    if ($p) { $cfRunning = $true }
} catch {}

if (-not $cfRunning) {
    $cfExe = Join-Path $baseDir "tools\cloudflared.exe"
    if (-not (Test-Path $cfExe)) {
        $cfExe = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
    }
    if (-not (Test-Path $cfExe)) {
        $cfExe = "cloudflared"
    }
    Start-Process -FilePath $cfExe `
        -ArgumentList "--config `"$tunnelConfig`" tunnel run aide-backend" `
        -WorkingDirectory $baseDir `
        -WindowStyle Hidden
}
