Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\pip.exe" install -r requirements.txt

if (Test-Path "frontend\package-lock.json") {
    Push-Location "frontend"
    npm ci
    Pop-Location
}

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
}

if (-not (Test-Path "frontend\.env.local") -and (Test-Path "frontend\.env.example")) {
    Copy-Item "frontend\.env.example" "frontend\.env.local"
}

Write-Host "Setup complete."
Write-Host "Backend: .\.venv\Scripts\python.exe -m backend.app"
Write-Host "Frontend: cd frontend; npm run dev"
