# .\run_prepare_raw.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -Profile P11 -Topic serial_interval -IncludeGt -FixMissing
<#
Usage examples:
  .\run_prepare_raw.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -Profile P10 -Topic serial_interval -IncludeGt -FixMissing
  .\run_prepare_raw.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -Profile P11 -Topic reproduction_number -IncludeGt
  .\run_prepare_raw.ps1 -ProjectDir "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi" -Profile P4 -Topic fatality -IncludeGt -FixMissing
#>

Param(
  [Parameter(Mandatory = $true)]
  [string]$ProjectDir,

  [Parameter(Mandatory = $true)]
  [string]$Profile,

  [string]$Topic = "",

  [switch]$IncludeGt,
  [switch]$FixMissing
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$CliDir = Join-Path $ScriptDir "..\\cli"
$ModuleDir = Resolve-Path (Join-Path $ScriptDir "..\\..")
$LocalPython = Join-Path $ModuleDir ".venv\\Scripts\\python.exe"
$PythonExe = if (Test-Path $LocalPython) { $LocalPython } else { "python" }

$ArgsList = @(
  (Join-Path $CliDir "screening_prepare_raw.py"),
  "--project-root", $ProjectDir,
  "--profile", $Profile
)
if ($Topic) {
  $ArgsList += @("--topic", $Topic)
}
if ($IncludeGt) {
  $ArgsList += "--include-gt"
}
if ($FixMissing) {
  $ArgsList += "--fix-missing"
}

Write-Host "Running prepare-raw..." -ForegroundColor Cyan
& $PythonExe @ArgsList
