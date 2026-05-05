<#
.SYNOPSIS
Run the local MetaAgent workbench backend.

.EXAMPLE
.\run_workbench_backend.ps1

.EXAMPLE
.\run_workbench_backend.ps1 -Port 8008
#>

Param(
    [int]$Port = 8008
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$WorkbenchDir = Resolve-Path (Join-Path $ScriptDir "..\\..")
$BackendDir = Join-Path $WorkbenchDir "backend"

Write-Host "Running workbench backend..." -ForegroundColor Cyan
Set-Location $BackendDir

$env:NO_PROXY = "localhost,127.0.0.1,::1"
$env:no_proxy = $env:NO_PROXY

if (-not (Test-Path ".venv")) {
    uv venv .venv
}

uv sync
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port $Port
