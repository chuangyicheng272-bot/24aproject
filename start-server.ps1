$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    py -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
Write-Host ""
Write-Host "SafeGuard 伺服器啟動中..." -ForegroundColor Green
Write-Host "本機：http://127.0.0.1:5000" -ForegroundColor Cyan
Write-Host "UWB API：http://127.0.0.1:5000/api/iot/uwb" -ForegroundColor Cyan
& ".\.venv\Scripts\python.exe" app.py
