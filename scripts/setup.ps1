Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$PythonCommand = Get-Command "python.exe" -ErrorAction SilentlyContinue
if ($null -eq $PythonCommand) {
    throw "Python was not found. Install Python 3.11 or 3.12 and run setup again."
}

$PythonExe = $PythonCommand.Source
$PythonVersion = & $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($PythonVersion -notin @("3.11", "3.12")) {
    throw "Unsupported Python $PythonVersion. Install Python 3.11 or 3.12."
}

$VenvPath = Join-Path $Root ".venv"
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"
$SetupMarker = Join-Path $VenvPath ".setup-complete"

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "Creating isolated Python environment at $VenvPath"
    & $PythonExe -m venv $VenvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create .venv."
    }
}

Write-Host "Installing backend packages inside .venv"
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upgrade pip inside .venv."
}
& $VenvPython -m pip install -r requirements.txt --progress-bar on --timeout 120 --retries 5
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install backend requirements."
}

$env:YOLO_CONFIG_DIR = Join-Path $Root ".ultralytics"
& $VenvPython -c "import flask, cv2, numpy, ultralytics, mediapipe, torch; print('Backend dependency check passed.'); print('Python:', __import__('sys').executable); print('CUDA:', torch.cuda.is_available())"
if ($LASTEXITCODE -ne 0) {
    throw "Backend dependency check failed."
}

if (Test-Path "frontend\package-lock.json") {
    $NpmCommand = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
    if ($null -eq $NpmCommand) {
        throw "Node.js/npm was not found. Install Node.js and run setup again."
    }
    Push-Location "frontend"
    try {
        & $NpmCommand.Source ci
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to install frontend packages."
        }
    }
    finally {
        Pop-Location
    }
}

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
}

if (-not (Test-Path "frontend\.env.local") -and (Test-Path "frontend\.env.example")) {
    Copy-Item "frontend\.env.example" "frontend\.env.local"
}

Set-Content -LiteralPath $SetupMarker -Value "Setup completed successfully." -Encoding Ascii

Write-Host "Setup complete. System Python and Conda base were not modified."
Write-Host "Backend: .\run-backend.cmd"
Write-Host "Frontend: .\run-frontend.cmd"
