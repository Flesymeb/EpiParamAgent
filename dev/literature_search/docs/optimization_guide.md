# 检索策略优化建议

## 当前问题分析

### 性能指标（run_20260113_001117）

- **召回率**: 48.42% ❌（目标 ≥80%）
- **精确率**: 52.87% ⚠️（目标 ≥60%）
- **F1 分数**: 50.55% ❌（目标 ≥70%）

### 核心问题

#### 1. **查询过度限制**（最严重）

当前 5 个 queries 都要求**3 个条件同时满足**：

```
Query 1: (serial interval术语) AND (COVID-19) AND (household/close contacts)
Query 2: (serial interval术语) AND (COVID-19) AND (contact tracing/investigation)
Query 3: (serial interval术语) AND (COVID-19) AND (transmission/dynamics) → 0结果
Query 4: (serial interval术语) AND (COVID-19) AND (symptom onset)
Query 5: (serial interval术语) AND (COVID-19) AND (epidemiologic model)
```

**问题**：遗漏了大量**标题中明确提到 serial interval 但没有这些特定场景的文献**

**遗漏案例**：

- PMID 32987541: "Estimating the time interval between transmission generations when **negative values** occur in the **serial interval** data"（标题中有 serial interval，但没有 household/contact tracing 关键词）
- PMID 32537527: "The impact of **serial interval** on a modified-Incidence Decay model"（建模相关，但不含 epidemiologic model 精确词）

#### 2. **缺少核心简单查询**

没有最基本的 2-term 查询：

```
("serial interval" OR "generation time") AND (COVID-19 OR SARS-CoV-2)
```

这是最重要的查询，应该排在第 1 位！

#### 3. **Long phrase 问题仍存在**

虽然修复了`_quote()`方法，但当前 run 仍用了旧代码：

- `"time between symptom onset"` → 4 个词，应拆分为 AND
- `"symptom-onset interval"` → 带连字符，应移除

#### 4. **查询数量不足**

只有 5 个 queries（其中 1 个返回 0 结果），覆盖度不够。

#### 5. **缺少 Title/Abstract 限定**

PubMed 支持`[tiab]`字段标签，可以提高相关性：

```
"serial interval"[tiab] AND COVID-19
```

## 优化方案

### ✅ 已完成的改进

1. **增加查询数量上限**: `max_queries_per_provider: 10` （从原 12 调整）
2. **修复 phrase 处理**:
   - 4+词短语自动拆分为 AND
   - 移除多词短语中的连字符
3. **优化 LLM prompt**: 要求生成渐进式查询（先简单后复杂）

### 📋 建议的新查询策略

**理想的 10 个查询顺序**：

```python
# === CORE QUERIES (核心，2-term) ===
1. ("serial interval" OR "generation time") AND (COVID-19 OR SARS-CoV-2)
2. ("serial interval"[tiab]) AND (COVID-19 OR SARS-CoV-2 OR 2019-nCoV)
3. ("generation time"[tiab] OR "generation interval") AND COVID-19

# === SPECIFIC CONTEXTS (特定场景，3-term) ===
4. ("serial interval" OR "generation time") AND COVID-19 AND ("contact tracing" OR "transmission chain")
5. ("serial interval" OR "generation time") AND COVID-19 AND ("household transmission" OR "household")
6. ("serial interval") AND COVID-19 AND ("reproduction number" OR R0 OR Rt)

# === METHODOLOGICAL (方法学) ===
7. ("serial interval") AND COVID-19 AND ("Bayesian" OR "maximum likelihood" OR "parametric")
8. ("generation time") AND COVID-19 AND ("renewal equation" OR "epidemic model")

# === OUTCOME FOCUS (结果导向) ===
9. ("serial interval" OR "generation time") AND COVID-19 AND ("presymptomatic" OR "asymptomatic")
10. ("onset to onset" OR "symptom onset interval") AND COVID-19
```

### 🔧 需要手动调整的地方

如果 LLM 仍生成过度限制的查询，可以手动编辑 `queries.json`：

```bash
# 运行后立即检查
cd langgraph_runs/<最新run目录>/cache
cat queries.json

# 如果发现问题，手动修改为上述10个查询，然后：
# 不需要重新运行，直接在PubMed验证
```

### 📊 预期改进

| 指标    | 当前   | 预期       | 改进    |
| ------- | ------ | ---------- | ------- |
| 召回率  | 48.42% | **75-85%** | +30-35% |
| 精确率  | 52.87% | **55-65%** | +2-12%  |
| F1 分数 | 50.55% | **65-75%** | +15-25% |

**原因**：

1. 核心 2-term 查询会捕获所有标题中明确提到 serial interval 的文献
2. 增加到 10 个查询，覆盖更多同义词组合
3. [tiab]标签提高相关性，减少噪音

## 立即行动

### 方案 A：重新运行（推荐）

```bash
cd MetaAgent-Epi/dev/literature_search
langgraph dev  # 启动Web UI
# 输入相同的research question
# 查看新生成的10个queries是否符合"先简单后复杂"策略
```

### 方案 B：手动验证关键查询

在 PubMed 网站测试核心查询：

```
https://pubmed.ncbi.nlm.nih.gov/

Query 1: ("serial interval" OR "generation time") AND (COVID-19 OR SARS-CoV-2) AND (2020:2024[pdat])
```

应该返回 **150-200** 篇结果（vs 当前总共 87 篇）

### 方案 C：批量评估多次运行

```bash
# 运行3次，对比结果
for i in {1..3}; do
    langgraph dev --run-once
    sleep 5
done

# 批量评估
Get-ChildItem "langgraph_runs/run_*" | Sort-Object LastWriteTime -Descending | Select-Object -First 3 | ForEach-Object {
    python scripts/evaluate_retrieval.py $_.FullName
}
```

## 监控指标

每次运行后检查：

1. **queries.json**: 是否有简单的 2-term 核心查询
2. **metrics_screen.json**: provider_totals 中每个 query 的 total 值
3. **评估结果**: 召回率是否 ≥75%

## 故障排查

### 如果召回率仍 <60%：

1. 检查 year_filter 是否过滤掉了早期文献
2. 验证 ground truth 中的文献是否确实包含 serial interval 相关内容
3. 考虑添加 MeSH 术语：`"Disease Transmission, Infectious"[Mesh]`

### 如果精确率很低(<50%）：

1. 增加特定场景约束（contact tracing, household）的比重
2. 使用[tiab]标签限制在标题/摘要
3. 考虑启用`include_medline_only: true`（仅高质量期刊）

## 参考

- Ground truth 分析: [searchA.csv](langgraph_runs/ground_truth/searchA.csv) - 95 篇
- 当前最佳 run: [run_20260113_001117](langgraph_runs/run_20260113_001117/) - 48.42% recall
- 评估脚本: `python scripts/evaluate_retrieval.py <run_dir> --details`
