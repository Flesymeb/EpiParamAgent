<#
.SYNOPSIS
Run the local MetaAgent workbench frontend.

.EXAMPLE
.\run_workbench_frontend.ps1

.EXAMPLE
.\run_workbench_frontend.ps1 -Port 5174
#>

Param(
    [int]$Port = 5174
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$WorkbenchDir = Resolve-Path (Join-Path $ScriptDir "..\\..")
$FrontendDir = Join-Path $WorkbenchDir "frontend"

Write-Host "Running workbench frontend..." -ForegroundColor Cyan
Set-Location $FrontendDir

$env:NO_PROXY = "localhost,127.0.0.1,::1"
$env:no_proxy = $env:NO_PROXY

if (-not (Test-Path "node_modules")) {
    npm install
}

npm run build
python -m http.server $Port -d dist --bind localhost
