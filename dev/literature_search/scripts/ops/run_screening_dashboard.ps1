<#
.SYNOPSIS
Run the local Streamlit dashboard for screening runs.

.EXAMPLE
.\run_screening_dashboard.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi"

.EXAMPLE
.\run_screening_dashboard.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -Port 8502
#>

Param(
    [string]$ProjectDir = "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi",
    [int]$Port = 8501
)

$AppPath = Join-Path $ProjectDir "dev\literature_search\apps\screening_dashboard.py"

if (-not (Test-Path $AppPath)) {
    throw "Dashboard app not found: $AppPath"
}

Write-Host "Running screening dashboard..." -ForegroundColor Cyan
streamlit run $AppPath --server.port $Port
