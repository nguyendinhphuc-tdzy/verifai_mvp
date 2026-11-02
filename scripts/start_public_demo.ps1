# Public demo from this machine via a free Cloudflare quick tunnel.
# Requires VERIFAI_ACCESS_CODE (>= 8 chars) in .env and cloudflared installed.
#   powershell -ExecutionPolicy Bypass -File scripts\start_public_demo.ps1
# Stop: Ctrl+C in this window (the app server is stopped too).
# Keep this file ASCII-only: Windows PowerShell 5.1 reads BOM-less UTF-8 as ANSI.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Python = 'C:\Users\PC\AppData\Local\Programs\Python\Python311\python.exe'
if (-not (Test-Path $Python)) { $Python = 'python' }
$Port = 8000

$codeLine = Get-Content .env -ErrorAction SilentlyContinue | Where-Object { $_ -match '^\s*VERIFAI_ACCESS_CODE\s*=\s*(.+)$' } | Select-Object -First 1
if (-not $env:VERIFAI_ACCESS_CODE -and -not $codeLine) { throw 'Them dong VERIFAI_ACCESS_CODE=<ma it nhat 8 ky tu> vao file .env truoc.' }
$code = if ($env:VERIFAI_ACCESS_CODE) { $env:VERIFAI_ACCESS_CODE } else { ($codeLine -replace '^\s*VERIFAI_ACCESS_CODE\s*=\s*', '').Trim().Trim('"').Trim("'") }
if ($code.Length -lt 8) { throw 'VERIFAI_ACCESS_CODE phai co it nhat 8 ky tu.' }

$env:VERIFAI_PUBLIC_MODE = '1'
$env:VERIFAI_DATA = Join-Path $Root 'data_demo'
$env:VERIFAI_SEED_DB = Join-Path $Root 'deploy\seed.sql'

Write-Host "Khoi dong VerifAI tai http://127.0.0.1:$Port (du lieu demo: data_demo)"
$server = Start-Process -FilePath $Python -PassThru -NoNewWindow -ArgumentList @(
    '-m', 'uvicorn', 'backend:app', '--host', '127.0.0.1', '--port', "$Port",
    '--proxy-headers', '--forwarded-allow-ips', '127.0.0.1')
try {
    $ready = $false
    foreach ($i in 1..60) {
        Start-Sleep -Seconds 2
        try { Invoke-RestMethod "http://127.0.0.1:$Port/healthz" -TimeoutSec 2 | Out-Null; $ready = $true; break } catch {}
    }
    if (-not $ready) { throw 'Server khong khoi dong duoc; xem log phia tren.' }
    Write-Host ''
    Write-Host 'Dang mo Cloudflare Tunnel. Tim dong https://....trycloudflare.com ben duoi va gui link do.'
    Write-Host 'Dang nhap: ten bat ky, mat khau = VERIFAI_ACCESS_CODE.'
    # Use a private, empty config: a user-level ~/.cloudflared/config.yml from
    # another project may hold ingress rules (e.g. a catch-all http_status:404)
    # that would hijack this quick tunnel. HTTP/2 over TCP is steadier than QUIC
    # on home networks.
    $cfg = Join-Path $env:TEMP 'verifai-cloudflared.yml'
    Set-Content -Path $cfg -Value 'no-autoupdate: true' -Encoding ascii
    & cloudflared tunnel --config $cfg --protocol http2 --url "http://127.0.0.1:$Port"
}
finally {
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
}
