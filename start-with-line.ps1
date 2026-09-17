$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:NO_PROXY = "api.line.me,localhost,127.0.0.1"

function Read-SafeGuardSecret([string]$Prompt) {
    $secureValue = Read-Host $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureValue)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

Write-Host "SafeGuard LINE Alert Launcher" -ForegroundColor Cyan
Write-Host "Values are used only for this session and are not saved to the application or SQLite." -ForegroundColor DarkGray
Write-Host ""

if (-not $env:LINE_CHANNEL_SECRET) {
    $env:LINE_CHANNEL_SECRET = Read-SafeGuardSecret "Enter the reissued Channel secret"
}
while (-not $env:LINE_CHANNEL_ACCESS_TOKEN -or $env:LINE_CHANNEL_ACCESS_TOKEN.Length -lt 50) {
    if ($env:LINE_CHANNEL_ACCESS_TOKEN) {
        Write-Warning "Invalid access token. Do not enter the Channel ID or 32-character Channel secret."
    }
    $tokenValue = Read-SafeGuardSecret "Enter the complete Channel access token from the Messaging API tab"
    $tokenValue = $tokenValue.Trim()
    if ($tokenValue.StartsWith("Bearer ", [StringComparison]::OrdinalIgnoreCase)) {
        $tokenValue = $tokenValue.Substring(7).Trim()
    }
    $env:LINE_CHANNEL_ACCESS_TOKEN = $tokenValue
}
while ($env:LINE_TARGET_USER_ID -notmatch '^U[0-9a-fA-F]{32}$') {
    if ($env:LINE_TARGET_USER_ID) {
        Write-Warning "Invalid User ID. Enter the complete U plus 32-character value, not only U or the @ Official Account ID."
    }
    $env:LINE_TARGET_USER_ID = Read-Host "Enter the complete Your user ID (U plus 32 characters)"
}

$defaultPublicUrl = "http://192.168.1.104:5000"
if (-not $env:PUBLIC_BASE_URL) {
    $publicUrl = Read-Host "SafeGuard URL (press Enter to use $defaultPublicUrl)"
    $env:PUBLIC_BASE_URL = if ($publicUrl) { $publicUrl.TrimEnd('/') } else { $defaultPublicUrl }
}

$outerPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$innerPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $outerPython) {
    $python = $outerPython
}
elseif (Test-Path -LiteralPath $innerPython) {
    $python = $innerPython
}
else {
    Write-Host "Creating the Python virtual environment..." -ForegroundColor Yellow
    py -m venv .venv
    $python = $innerPython
    & $python -m pip install -r requirements.txt
}

Write-Host ""
Write-Host "SafeGuard is starting: http://127.0.0.1:5000" -ForegroundColor Green
Write-Host "Safety alerts: $($env:PUBLIC_BASE_URL)/system-status" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop the server." -ForegroundColor DarkGray
& $python app.py
