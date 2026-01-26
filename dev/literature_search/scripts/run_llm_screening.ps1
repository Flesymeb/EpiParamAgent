$ErrorActionPreference = "Stop"


$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Resolve-Path (Join-Path $ScriptDir "..")

$ConfigName = $args[0]
if (-not $ConfigName) {
  $ConfigName = "V2"
}

$BatchSize = $args[1]
if (-not $BatchSize) {
  $BatchSize = 10
}

$SearchKey = $ConfigName.ToLower().Replace("v", "search_v")

$Input = Join-Path $ProjectDir ("langgraph_runs\\ground_truth\\{0}\\{0}_raw.csv" -f $SearchKey)
$Output = Join-Path $ProjectDir ("langgraph_runs\\ground_truth\\{0}\\test_screen\\{0}_screened_1.csv" -f $SearchKey)
$GroundTruth = Join-Path $ProjectDir ("langgraph_runs\\ground_truth\\{0}\\{0}_gt.csv" -f $SearchKey)

python (Join-Path $ScriptDir "screening_llm_batch.py") `
  --input $Input `
  --output $Output `
  --ground-truth $GroundTruth `
  --config $ConfigName `
  --auto-fulltext `
  --batch-size $BatchSize
