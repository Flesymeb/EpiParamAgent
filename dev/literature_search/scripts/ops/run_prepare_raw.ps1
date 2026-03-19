# .\run_prepare_raw.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -ConfigName P11 -Topic serial_interval -IncludeGt -FixMissing
<#
Usage examples:
  .\run_prepare_raw.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -ConfigName P10 -Topic serial_interval -IncludeGt -FixMissing
  .\run_prepare_raw.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -ConfigName P11 -Topic reproduction_number -IncludeGt
  .\run_prepare_raw.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -ConfigName P4 -Topic fatality -IncludeGt -FixMissing
#>

Param(
  [Parameter(Mandatory = $true)]
  [string]$ProjectDir,

  [Parameter(Mandatory = $true)]
  [string]$ConfigName,

  [string]$Topic = "serial_interval",

  [switch]$IncludeGt,
  [switch]$FixMissing
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$CliDir = Join-Path $ScriptDir "..\\cli"

$ConfigKey = $ConfigName.Trim().ToLower()
$ConfigNum = ($ConfigName -replace '[^0-9]', '')
if (-not $ConfigNum) {
  throw "ConfigName must include a number (e.g. P10, P11, P4)."
}

$BaseDir = Join-Path $ProjectDir "evaluation\screening\GT_1\GT_export"
$TopicCandidates = @(
  $Topic,
  ($Topic -replace '\s+', '_'),
  ($Topic -replace '-', '_')
) | Select-Object -Unique

$TopicDir = $null
foreach ($Candidate in $TopicCandidates) {
  $CandidateDir = Join-Path $BaseDir $Candidate
  if (Test-Path $CandidateDir) {
    $TopicDir = $CandidateDir
    break
  }
}
if (-not $TopicDir) {
  $TopicDir = Join-Path $BaseDir ($TopicCandidates[0])
}

$Raw = Join-Path $TopicDir ("{0}\project_{1}_raw.csv" -f $ConfigKey, $ConfigNum)
$Gt = Join-Path $TopicDir ("{0}\project_{1}_groundtruth.csv" -f $ConfigKey, $ConfigNum)
$Out = $Raw

if (-not (Test-Path $Raw)) {
  throw "Missing raw file: $Raw"
}
if (-not (Test-Path $Gt)) {
  throw "Missing ground-truth file: $Gt"
}

$ArgsList = @(
  (Join-Path $CliDir "screening_prepare_raw.py"),
  "--raw-input", $Raw,
  "--ground-truth", $Gt,
  "--output", $Out
)
if ($IncludeGt) {
  $ArgsList += "--include-gt"
}
if ($FixMissing) {
  $ArgsList += "--fix-missing"
}

Write-Host "Running prepare-raw..." -ForegroundColor Cyan
python @ArgsList
