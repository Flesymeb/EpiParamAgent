<#
.SYNOPSIS
Run the local MetaAgent workbench with backend and frontend in separate shells.

.EXAMPLE
.\run_workbench.ps1

.EXAMPLE
.\run_workbench.ps1 -BackendPort 8008 -FrontendPort 5174
#>

Param(
    [int]$BackendPort = 8008,
    [int]$FrontendPort = 5174
)

function Wait-LocalPort {
    Param(
        [int]$Port,
        [int]$TimeoutSeconds = 60
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($listening) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }

    return $false
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendScript = Join-Path $ScriptDir "run_workbench_backend.ps1"
$FrontendScript = Join-Path $ScriptDir "run_workbench_frontend.ps1"

Write-Host "Starting workbench backend and frontend..." -ForegroundColor Cyan

$env:NO_PROXY = "localhost,127.0.0.1,::1"
$env:no_proxy = $env:NO_PROXY

Get-NetTCPConnection -LocalPort $FrontendPort -ErrorAction SilentlyContinue |
    ForEach-Object {
        try {
            Stop-Process -Id $_.OwningProcess -Force -ErrorAction Stop
        } catch {
        }
    }

Start-Process pwsh -ArgumentList @(
    "-NoExit",
    "-File",
    $BackendScript,
    "-Port",
    "$BackendPort"
)

Start-Sleep -Seconds 2

Start-Process pwsh -ArgumentList @(
    "-NoExit",
    "-File",
    $FrontendScript,
    "-Port",
    "$FrontendPort"
)

$backendReady = Wait-LocalPort -Port $BackendPort -TimeoutSeconds 60
$frontendReady = Wait-LocalPort -Port $FrontendPort -TimeoutSeconds 120

$Url = "http://localhost:$FrontendPort"
if (-not $backendReady) {
    Write-Warning "Backend did not become ready on port $BackendPort within timeout."
}

if (-not $frontendReady) {
    Write-Warning "Frontend did not become ready on port $FrontendPort within timeout."
}

if ($backendReady -and $frontendReady) {
    Write-Host "Backend ready:  http://localhost:$BackendPort" -ForegroundColor Green
    Write-Host "Frontend ready: $Url" -ForegroundColor Green
    Write-Host "Opening $Url" -ForegroundColor Green
    Start-Process $Url
} else {
    Write-Host "Workbench was started, but at least one service is not ready yet." -ForegroundColor Yellow
    Write-Host "Backend:  http://localhost:$BackendPort" -ForegroundColor Yellow
    Write-Host "Frontend: http://localhost:$FrontendPort" -ForegroundColor Yellow
}
