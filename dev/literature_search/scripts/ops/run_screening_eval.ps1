<#
Usage examples:
  .\run_screening_eval.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -Profile P10 -Topic serial_interval -BatchSize 10 -BatchConcurrency 3 -AutoFulltext
  .\run_screening_eval.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -Profile P10 -Topic reproduction_number -BatchSize 10 -BatchConcurrency 3 -FulltextOnly
  .\run_screening_eval.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -Profile P4 -Topic fatality -BatchSize 30 -BatchConcurrency 3 -AutoFulltext
  # Two-phase workflow (no-abstract papers last):
  .\run_screening_eval.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -Profile P4 -Topic fatality -BatchSize 30 -BatchConcurrency 3 -SkipNoAbstract
  .\run_screening_eval.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -Profile P4 -Topic fatality -BatchSize 10 -BatchConcurrency 3 -ResumeFulltext
#>

Param(
  [Parameter(Mandatory = $true)]
  [string]$ProjectDir,

  [Parameter(Mandatory = $true)]
  [string]$Profile,

  [string]$Topic = "",

  [int]$BatchSize = 10,
  [int]$BatchConcurrency = 1,
  [switch]$AutoFulltext,
  [switch]$FulltextOnly,
  [switch]$SkipNoAbstract,
  [switch]$ResumeFulltext
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$CliDir = Join-Path $ScriptDir "..\\cli"
$ModuleDir = Resolve-Path (Join-Path $ScriptDir "..\\..")
$LocalPython = Join-Path $ModuleDir ".venv\\Scripts\\python.exe"
$PythonExe = if (Test-Path $LocalPython) { $LocalPython } else { "python" }

Write-Host "Running screening..." -ForegroundColor Cyan
$ArgsList = @(
  (Join-Path $CliDir "screening_llm_batch.py"),
  "--project-root", $ProjectDir,
  "--profile", $Profile,
  "--batch-size", $BatchSize,
  "--batch-concurrency", $BatchConcurrency
)
if ($Topic) {
  $ArgsList += @("--topic", $Topic)
}
if ($FulltextOnly) {
  $ArgsList += "--fulltext-only"
} elseif ($AutoFulltext) {
  $ArgsList += "--auto-fulltext"
} elseif ($SkipNoAbstract) {
  $ArgsList += "--skip-no-abstract"
} elseif ($ResumeFulltext) {
  $ArgsList += "--resume-fulltext"
}
& $PythonExe @ArgsList

Write-Host "Running evaluation..." -ForegroundColor Cyan
$EvalArgs = @(
  (Join-Path $CliDir "screening_evaluation.py"),
  "screening-performance",
  "--project-root", $ProjectDir,
  "--profile", $Profile
)
if ($Topic) {
  $EvalArgs += @("--topic", $Topic)
}
& $PythonExe @EvalArgs
