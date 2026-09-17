Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    throw "Project .venv was not found. Run .\setup.cmd first."
}
if (-not (Test-Path ".\.venv\.setup-complete")) {
    throw "Project .venv setup is incomplete. Run .\setup.cmd and wait for it to finish."
}

& ".\.venv\Scripts\python.exe" -m backend.app
