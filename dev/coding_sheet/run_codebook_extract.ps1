Param(
    [string]$Input = "..\\paper_pool\\pdfs",
    [string]$PmidList = "",
    [string]$Out = "output\\epi_extract",
    [ValidateSet("index","extract","both")]
    [string]$Stage = "both",
    [string]$Codebook = "configs\\codebook_epi.yaml"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Resolve-Path (Join-Path $ScriptDir ".")

$InputValue = $Input
if ($PmidList) {
    $InputValue = $PmidList
}

$InputPath = Resolve-Path (Join-Path $ProjectDir $InputValue)
$OutPath = Resolve-Path (Join-Path $ProjectDir $Out) -ErrorAction SilentlyContinue
if (-not $OutPath) {
    $OutPath = Join-Path $ProjectDir $Out
}

$ArgsList = @(
    "cli/extract_epi.py",
    "--input", $InputPath,
    "--out", $OutPath,
    "--stage", $Stage,
    "--codebook", (Join-Path $ProjectDir $Codebook)
)

Write-Host "Running: python $($ArgsList -join ' ')" -ForegroundColor Cyan
python @ArgsList
