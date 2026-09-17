Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $Root "frontend")

$NpmCommand = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
if ($null -eq $NpmCommand) {
    throw "Node.js/npm was not found. Install Node.js and run setup again."
}

if (-not (Test-Path "node_modules")) {
    & $NpmCommand.Source ci
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install frontend packages."
    }
}

& $NpmCommand.Source run dev
