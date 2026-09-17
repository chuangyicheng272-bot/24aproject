Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)

$outLog = Join-Path (Get-Location) "dev-server.out.log"
$errLog = Join-Path (Get-Location) "dev-server.err.log"

"Starting Next.js dev server at $(Get-Date -Format o)" | Out-File -FilePath $outLog -Encoding utf8
npm.cmd run dev -- --hostname 127.0.0.1 --port 3000 1>> $outLog 2>> $errLog
