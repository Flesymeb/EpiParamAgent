# JSON 参数速查表

## 完整参数模板（复制粘贴即用）

```json
{
  "research_question": "你的研究问题",
  "domain": "infectious_disease",
  "workdir": "langgraph_runs/my_test",
  "providers": ["pubmed"],
  "params": {
    "use_scoping": true,
    "scoping_providers": ["tavily"],
    "scoping_max_results": 5,
    "scoping_max_items": 8,
    "scoping_max_chars": 1600,
    "pubmed_year_range": "2020:2024",
    "pubmed_retmax": 500,
    "pubmed_per_query_limit": 100,
    "max_queries": 12,
    "use_llm_queries": true,
    "include_single_terms": false,
    "apply_wildcards": true
  }
}
```

---

## 参数快速参考

### 核心参数（最常用）

| 参数                | 值             | 说明                         |
| ------------------- | -------------- | ---------------------------- |
| `pubmed_year_range` | `"2020:2024"`  | 限定年份范围                 |
| `pubmed_retmax`     | `200` - `1000` | 总检索数量                   |
| `max_queries`       | `3` - `12`     | 查询数量                     |
| `use_llm_queries`   | `true`/`false` | LLM 生成查询（false 更稳定） |

### 日期限制（5 种方式任选其一）

```json
// 方式 1：精确日期范围（推荐用于COVID-19等特定时期研究）
"pubmed_date_range": "2020/1/1-2020/10/22"

// 方式 2：年份范围
"pubmed_year_range": "2020-2024"

// 方式 3：单年
"pubmed_year_range": "2020-2020"

// 方式 4：最小年份
"pubmed_min_year": 2020

// 方式 5：最小+最大
"pubmed_min_year": 2020,
"pubmed_max_year": 2024
```

**日期格式说明**：

- 使用**短横线** `-` 或**冒号** `:` 都可以（内部会自动转换）
- 精确日期：`2020/1/1-2020/10/22` 或 `2020/01/01-2020/10/22`
- 年份范围：`2020-2024` 或 `2020:2024`
- 单个日期：`2020/1/1` 或年份 `2020`

### 速度优化（快速测试）

```json
{
  "params": {
    "pubmed_retmax": 50,
    "max_queries": 3,
    "use_llm_queries": false,
    "use_scoping": false
  }
}
```

### 完整检索（大规模研究）

```json
{
  "params": {
    "use_scoping": true,
    "pubmed_retmax": 1000,
    "max_queries": 12,
    "use_llm_queries": true
  }
}
```

---

## domain 值速查

| domain               | 中文   | 示例研究             |
| -------------------- | ------ | -------------------- |
| `infectious_disease` | 传染病 | COVID-19, 流感, HIV  |
| `chronic_disease`    | 慢性病 | 糖尿病, 高血压, COPD |
| `environmental_epi`  | 环境   | 空气污染, 气候变化   |
| `cancer_epi`         | 癌症   | 肺癌, 结直肠癌       |
| `nutritional_epi`    | 营养   | 膳食因素, 肥胖       |
| `genetic_epi`        | 遗传   | 基因-环境交互        |
| `social_epi`         | 社会   | 社会经济地位         |
| `epidemiology`       | 通用   | 不确定时使用         |

---

## 常见配置组合

### 1. COVID-19 早期研究（2020 年 1-10 月精确日期）

```json
{
  "research_question": "COVID-19 serial interval meta-analysis",
  "domain": "infectious_disease",
  "params": {
    "pubmed_date_range": "2020/1/1-2020/10/22",
    "pubmed_retmax": 200,
    "max_queries": 6,
    "use_llm_queries": false
  }
}
```

### 2. 近 5 年大规模检索

```json
{
  "research_question": "Air pollution and cardiovascular disease",
  "domain": "environmental_epi",
  "params": {
    "pubmed_year_range": "2019:2024",
    "pubmed_retmax": 800,
    "max_queries": 12
  }
}
```

### 3. 快速验证（最小配置）

```json
{
  "research_question": "Diabetes risk factors",
  "domain": "chronic_disease",
  "params": {
    "pubmed_retmax": 50,
    "max_queries": 3,
    "use_llm_queries": false
  }
}
```

### 4. 历史文献（大时间跨度）

```json
{
  "research_question": "Smoking and lung cancer",
  "domain": "cancer_epi",
  "params": {
    "pubmed_year_range": "1990:2024",
    "pubmed_retmax": 1000,
    "max_queries": 10
  }
}
```

---

## 参数值建议

### pubmed_retmax（总检索数）

| 值   | 用途       | 预计时间 |
| ---- | ---------- | -------- |
| 50   | 快速测试   | ~20 秒   |
| 200  | 中等测试   | ~45 秒   |
| 500  | 标准研究   | ~90 秒   |
| 1000 | 大规模研究 | ~150 秒  |

### max_queries（查询数量）

| 值  | 用途             |
| --- | ---------------- |
| 3   | 快速测试         |
| 6   | 中等覆盖         |
| 12  | 完整覆盖（默认） |

### use_llm_queries（LLM 查询）

| 值      | 优点         | 缺点       |
| ------- | ------------ | ---------- |
| `true`  | 更智能的查询 | 可能失败   |
| `false` | 稳定快速     | 查询较简单 |

**建议**：测试时用 `false`，正式研究用 `true`

---

## 故障排查

### 问题：检索太慢

**优化**：

```json
{
  "params": {
    "pubmed_retmax": 100,
    "max_queries": 3,
    "use_scoping": false
  }
}
```

### 问题：结果太少

**优化**：

```json
{
  "params": {
    "pubmed_retmax": 800,
    "max_queries": 12,
    "include_single_terms": true
  }
}
```

### 问题：LLM 查询失败

**优化**：

```json
{
  "params": {
    "use_llm_queries": false
  }
}
```

---

## 推荐配置组合

根据你的需求选择：

**快速测试** → [quick_test.json](quick_test.json)
**COVID-19 研究** → [covid_2020_full.json](covid_2020_full.json)  
**环境污染** → [air_pollution_cvd.json](air_pollution_cvd.json)
**慢性病** → [diabetes_asia.json](diabetes_asia.json)
**疫苗效果** → [hpv_vaccine.json](hpv_vaccine.json)
