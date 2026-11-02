# Public demo from this machine via a free Cloudflare quick tunnel.
# Requires VERIFAI_ACCESS_CODE (>= 8 chars) in .env and cloudflared installed.
#   powershell -ExecutionPolicy Bypass -File scripts\start_public_demo.ps1
# Stop: Ctrl+C in this window (the app server is stopped too).
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Python = 'C:\Users\PC\AppData\Local\Programs\Python\Python311\python.exe'
if (-not (Test-Path $Python)) { $Python = 'python' }
$Port = 8000

$codeLine = Get-Content .env -ErrorAction SilentlyContinue | Where-Object { $_ -match '^\s*VERIFAI_ACCESS_CODE\s*=\s*(.+)$' } | Select-Object -First 1
if (-not $env:VERIFAI_ACCESS_CODE -and -not $codeLine) { throw 'Thêm dòng VERIFAI_ACCESS_CODE=<mã ít nhất 8 ký tự> vào file .env trước.' }
$code = if ($env:VERIFAI_ACCESS_CODE) { $env:VERIFAI_ACCESS_CODE } else { ($codeLine -replace '^\s*VERIFAI_ACCESS_CODE\s*=\s*', '').Trim().Trim('"').Trim("'") }
if ($code.Length -lt 8) { throw 'VERIFAI_ACCESS_CODE phải có ít nhất 8 ký tự.' }

$env:VERIFAI_PUBLIC_MODE = '1'
$env:VERIFAI_DATA = Join-Path $Root 'data_demo'
$env:VERIFAI_SEED_DB = Join-Path $Root 'deploy\seed.sql'

Write-Host "Khởi động VerifAI tại http://127.0.0.1:$Port (dữ liệu demo: data_demo)"
$server = Start-Process -FilePath $Python -PassThru -NoNewWindow -ArgumentList @(
    '-m', 'uvicorn', 'backend:app', '--host', '127.0.0.1', '--port', "$Port",
    '--proxy-headers', '--forwarded-allow-ips', '127.0.0.1')
try {
    $ready = $false
    foreach ($i in 1..60) {
        Start-Sleep -Seconds 2
        try { Invoke-RestMethod "http://127.0.0.1:$Port/healthz" -TimeoutSec 2 | Out-Null; $ready = $true; break } catch {}
    }
    if (-not $ready) { throw 'Server không khởi động được; xem log phía trên.' }
    Write-Host ''
    Write-Host 'Đang mở Cloudflare Tunnel. Tìm dòng https://....trycloudflare.com bên dưới và gửi link đó.'
    Write-Host 'Đăng nhập: tên bất kỳ, mật khẩu = VERIFAI_ACCESS_CODE.'
    & cloudflared tunnel --url "http://127.0.0.1:$Port" --no-autoupdate
}
finally {
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
}
