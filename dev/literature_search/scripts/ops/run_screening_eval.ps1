<#
Usage examples:
  .\run_screening_eval.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -ConfigName P10 -Topic serial_interval -BatchSize 10 -BatchConcurrency 3 -AutoFulltext
  .\run_screening_eval.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -ConfigName P10 -Topic reproduction_number -BatchSize 10 -BatchConcurrency 3 -FulltextOnly
  .\run_screening_eval.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -ConfigName P4 -Topic fatality -BatchSize 30 -BatchConcurrency 3 -AutoFulltext
#>

Param(
  [Parameter(Mandatory = $true)]
  [string]$ProjectDir,

  [Parameter(Mandatory = $true)]
  [string]$ConfigName,

  [string]$Topic = "serial_interval",

  [int]$BatchSize = 10,
  [int]$BatchConcurrency = 1,
  [switch]$AutoFulltext,
  [switch]$FulltextOnly
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
$Out = Join-Path $TopicDir ("{0}\project_{1}_screened.csv" -f $ConfigKey, $ConfigNum)

if (-not (Test-Path $Raw)) {
  throw "Missing raw file: $Raw"
}
if (-not (Test-Path $Gt)) {
  throw "Missing ground-truth file: $Gt"
}

Write-Host "Running screening..." -ForegroundColor Cyan
$ArgsList = @(
  (Join-Path $CliDir "screening_llm_batch.py"),
  "--input", $Raw,
  "--output", $Out,
  "--ground-truth", $Gt,
  "--config", $ConfigName,
  "--batch-size", $BatchSize,
  "--batch-concurrency", $BatchConcurrency
)
if ($FulltextOnly) {
  $ArgsList += "--fulltext-only"
} elseif ($AutoFulltext) {
  $ArgsList += "--auto-fulltext"
}
python @ArgsList

Write-Host "Running evaluation..." -ForegroundColor Cyan
python (Join-Path $CliDir "screening_evaluation.py") screening-performance `
  --ground-truth "$Gt" `
  --screened-results "$Out"
