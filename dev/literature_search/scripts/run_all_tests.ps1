# 运行三个研究主题的筛选测试脚本
# 使用方法: .\run_all_tests.ps1

Write-Host "=" * 80 -ForegroundColor Cyan
Write-Host "开始测试三个研究主题的文献筛选" -ForegroundColor Cyan
Write-Host "=" * 80 -ForegroundColor Cyan
Write-Host ""

# 确认环境
Write-Host "当前目录: $PWD" -ForegroundColor Yellow
Write-Host "Python环境: $(python --version 2>&1)" -ForegroundColor Yellow
Write-Host ""

# ==================== Search V1: Serial Interval ====================
Write-Host "`n[1/3] Search V1 - Serial Interval" -ForegroundColor Green
Write-Host "=" * 80

$v1_input = "..\langgraph_runs\ground_truth\search_v1\search_v1_raw.csv"
$v1_output = "..\langgraph_runs\ground_truth\search_v1\search_v1_screened.csv"
$v1_gt = "..\langgraph_runs\ground_truth\search_v1\search_v1_gt.csv"

Write-Host "Input: $v1_input (95 papers)"
Write-Host "Ground Truth: $v1_gt (54 papers)"
Write-Host "Output: $v1_output"
Write-Host ""

python screen_with_llm_batch.py `
    --input $v1_input `
    --output $v1_output `
    --ground-truth $v1_gt `
    --config V1 `
    --batch-size 30

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n✓ Search V1 筛选完成!" -ForegroundColor Green
    Write-Host "结果保存到: $v1_output" -ForegroundColor Green
} else {
    Write-Host "`n✗ Search V1 筛选失败!" -ForegroundColor Red
    exit 1
}

# ==================== Search V2: Variants ====================
Write-Host "`n`n[2/3] Search V2 - COVID-19 Variants" -ForegroundColor Green
Write-Host "=" * 80

$v2_input = "..\langgraph_runs\ground_truth\search_v2\search_v2_raw.csv"
$v2_output = "..\langgraph_runs\ground_truth\search_v2\search_v2_screened_test.csv"
$v2_gt = "..\langgraph_runs\ground_truth\search_v2\search_v2_gt.csv"

Write-Host "Input: $v2_input (99 papers)"
Write-Host "Ground Truth: $v2_gt (24 papers)"
Write-Host "Output: $v2_output"
Write-Host ""

python screen_with_llm_batch.py `
    --input $v2_input `
    --output $v2_output `
    --ground-truth $v2_gt `
    --config V2 `
    --batch-size 30

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n✓ Search V2 筛选完成!" -ForegroundColor Green
    Write-Host "结果保存到: $v2_output" -ForegroundColor Green
} else {
    Write-Host "`n✗ Search V2 筛选失败!" -ForegroundColor Red
    exit 1
}

# ==================== Search V3: Superspreading ====================
Write-Host "`n`n[3/3] Search V3 - Superspreading Events" -ForegroundColor Green
Write-Host "=" * 80

$v3_input = "..\langgraph_runs\ground_truth\search_v3\search_v3_raw.csv"
$v3_output = "..\langgraph_runs\ground_truth\search_v3\search_v3_screened.csv"
$v3_gt = "..\langgraph_runs\ground_truth\search_v3\search_v3_gt.csv"

Write-Host "Input: $v3_input (243 papers)"
Write-Host "Ground Truth: $v3_gt (17 papers)"
Write-Host "Output: $v3_output"
Write-Host ""

python screen_with_llm_batch.py `
    --input $v3_input `
    --output $v3_output `
    --ground-truth $v3_gt `
    --config V3 `
    --batch-size 30

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n✓ Search V3 筛选完成!" -ForegroundColor Green
    Write-Host "结果保存到: $v3_output" -ForegroundColor Green
} else {
    Write-Host "`n✗ Search V3 筛选失败!" -ForegroundColor Red
    exit 1
}

# ==================== 总结 ====================
Write-Host "`n`n" + "=" * 80 -ForegroundColor Cyan
Write-Host "所有测试完成!" -ForegroundColor Cyan
Write-Host "=" * 80 -ForegroundColor Cyan
Write-Host ""

Write-Host "筛选结果文件:" -ForegroundColor Yellow
Write-Host "  V1 (Serial Interval):   $v1_output"
Write-Host "  V2 (Variants):          $v2_output"
Write-Host "  V3 (Superspreading):    $v3_output"
Write-Host ""

Write-Host "详细日志文件:" -ForegroundColor Yellow
$logDir = "..\langgraph_runs\ground_truth\screening_logs"
if (Test-Path $logDir) {
    $latestLogs = Get-ChildItem $logDir -Filter "*.txt" | Sort-Object LastWriteTime -Descending | Select-Object -First 3
    foreach ($log in $latestLogs) {
        Write-Host "  $($log.Name)"
    }
}
Write-Host ""

Write-Host "下一步: 查看筛选日志和评估指标" -ForegroundColor Green
Write-Host "  日志中包含详细的 Recall, Precision, Specificity 等指标"
Write-Host ""
