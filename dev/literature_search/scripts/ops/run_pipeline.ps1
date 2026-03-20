<#
Usage examples:
  .\run_pipeline.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -Profile P13 -Topic serial_interval -IncludeGt -FixMissing -BatchSize 10 -BatchConcurrency 1 -AutoFulltext
  .\run_pipeline.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -Profile P8 -Topic reproduction_number -IncludeGt -FixMissing -BatchSize 20 -BatchConcurrency 3
#>

Param(
  [Parameter(Mandatory = $true)]
  [string]$ProjectDir,

  [Parameter(Mandatory = $true)]
  [string]$Profile,

  [string]$Topic = "",

  [switch]$IncludeGt,
  [switch]$FixMissing,

  [int]$BatchSize = 10,
  [int]$BatchConcurrency = 1,
  [switch]$AutoFulltext,
  [switch]$FulltextOnly
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PrepareScript = Join-Path $ScriptDir "run_prepare_raw.ps1"
$ScreeningEvalScript = Join-Path $ScriptDir "run_screening_eval.ps1"

$PrepareArgs = @{
  ProjectDir = $ProjectDir
  Profile = $Profile
  Topic = $Topic
}
if ($IncludeGt) {
  $PrepareArgs["IncludeGt"] = $true
}
if ($FixMissing) {
  $PrepareArgs["FixMissing"] = $true
}

$ScreeningArgs = @{
  ProjectDir = $ProjectDir
  Profile = $Profile
  Topic = $Topic
  BatchSize = $BatchSize
  BatchConcurrency = $BatchConcurrency
}
if ($AutoFulltext) {
  $ScreeningArgs["AutoFulltext"] = $true
}
if ($FulltextOnly) {
  $ScreeningArgs["FulltextOnly"] = $true
}

Write-Host "Step 1/2: prepare_raw" -ForegroundColor Cyan
& $PrepareScript @PrepareArgs

Write-Host "Step 2/2: screening_eval" -ForegroundColor Cyan
& $ScreeningEvalScript @ScreeningArgs
