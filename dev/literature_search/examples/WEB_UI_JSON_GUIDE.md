# Web UI JSON 输入指南

## 快速开始（最简格式）

```json
{
  "research_question": "你的研究问题",
  "domain": "流行病学子领域"
}
```

---

## 完整测试格式（推荐用于测试）

```json
{
  "research_question": "COVID-19 serial interval distribution meta-analysis in early 2020 pandemic",
  "domain": "infectious_disease",
  "workdir": "langgraph_runs/covid_serial_interval_test",
  "providers": ["pubmed"],
  "params": {
    "use_scoping": true,
    "scoping_providers": ["tavily"],
    "scoping_max_results": 5,
    "scoping_max_items": 8,
    "scoping_max_chars": 1600,
    "pubmed_year_range": "2020:2020",
    "pubmed_retmax": 200,
    "pubmed_per_query_limit": 200,
    "max_queries": 6,
    "use_llm_queries": false,
    "include_single_terms": false,
    "apply_wildcards": true
  }
}
```

---

## 字段说明

### 必填字段

| 字段                | 类型   | 说明           | 示例                                       |
| ------------------- | ------ | -------------- | ------------------------------------------ |
| `research_question` | string | 研究问题       | `"COVID-19 serial interval meta-analysis"` |
| `domain`            | string | 流行病学子领域 | `"infectious_disease"`                     |

### 可选字段

| 字段        | 类型   | 默认值       | 说明               |
| ----------- | ------ | ------------ | ------------------ |
| `workdir`   | string | 自动生成     | 结果输出目录       |
| `providers` | array  | `["pubmed"]` | 数据源列表         |
| `params`    | object | `{}`         | 详细参数（见下方） |

### params 参数详解

#### Scoping Search（背景调查）

| 参数                  | 类型    | 默认值       | 说明                        |
| --------------------- | ------- | ------------ | --------------------------- |
| `use_scoping`         | boolean | `false`      | 是否启用背景调查            |
| `scoping_providers`   | array   | `["tavily"]` | 调查数据源（tavily/serper） |
| `scoping_max_results` | int     | `5`          | 每个查询最大结果数          |
| `scoping_max_items`   | int     | `8`          | 最大提取条目数              |
| `scoping_max_chars`   | int     | `1600`       | 最大字符数                  |

#### PubMed 检索参数

| 参数                     | 类型   | 默认值   | 说明                                            |
| ------------------------ | ------ | -------- | ----------------------------------------------- |
| `pubmed_date_range`      | string | `null`   | **精确日期范围**，格式：`"2020/1/1-2020/10/22"` |
| `pubmed_year_range`      | string | `null`   | 年份范围，格式：`"2020-2024"` 或 `"2020:2024"`  |
| `pubmed_retmax`          | int    | `500`    | 总检索上限                                      |
| `pubmed_per_query_limit` | int    | 自动分配 | 每个查询的限制                                  |
| `pubmed_min_year`        | int    | `null`   | 最小年份（可单独设置）                          |
| `pubmed_max_year`        | int    | `null`   | 最大年份（可单独设置）                          |

**日期参数优先级**：`pubmed_date_range` > `pubmed_year_range` > `pubmed_min_year/max_year`

#### 查询生成参数

| 参数                   | 类型    | 默认值  | 说明                   |
| ---------------------- | ------- | ------- | ---------------------- |
| `max_queries`          | int     | `12`    | 每个数据源的最大查询数 |
| `use_llm_queries`      | boolean | `true`  | 是否使用 LLM 生成查询  |
| `include_single_terms` | boolean | `false` | 是否包含单术语查询     |
| `apply_wildcards`      | boolean | `true`  | 是否应用通配符         |
| `use_seed_queries`     | boolean | `false` | 是否使用种子查询       |

#### 其他参数

| 参数                      | 类型    | 默认值  | 说明                  |
| ------------------------- | ------- | ------- | --------------------- |
| `no_limits`               | boolean | `false` | 取消所有限制（慎用）  |
| `eric_force_rule_queries` | boolean | `false` | ERIC 强制使用规则生成 |

---

## 常见场景配置

### 1. 快速测试（最少结果）

```json
{
  "research_question": "COVID-19 transmission dynamics",
  "domain": "infectious_disease",
  "params": {
    "pubmed_retmax": 50,
    "max_queries": 3,
    "use_llm_queries": false
  }
}
```

### 2. 限定特定日期范围（精确到日）

```json
{
  "research_question": "COVID-19 serial interval distribution",
  "domain": "infectious_disease",
  "params": {
    "pubmed_date_range": "2020/1/1-2020/10/22",
    "pubmed_retmax": 200
  }
}
```

**生成的 PubMed 查询**：`(query) AND (2020/1/1:2020/10/22[pdat])`

### 3. 限定年份范围

```json
{
  "research_question": "COVID-19 incubation period",
  "domain": "infectious_disease",
  "params": {
    "pubmed_year_range": "2020-2021",
    "pubmed_retmax": 300
  }
}
```

或使用独立的最小/最大年份：

```json
{
  "params": {
    "pubmed_min_year": 2020,
    "pubmed_max_year": 2021
  }
}
```

### 4. 完整研究（大量检索）

```json
{
  "research_question": "Air pollution and cardiovascular disease",
  "domain": "environmental_epi",
  "params": {
    "use_scoping": true,
    "scoping_providers": ["tavily"],
    "pubmed_retmax": 1000,
    "max_queries": 12,
    "use_llm_queries": true
  }
}
```

### 5. 禁用 LLM（避免失败，更快）

```json
{
  "research_question": "Diabetes risk factors",
  "domain": "chronic_disease",
  "params": {
    "use_llm_queries": false,
    "max_queries": 8,
    "pubmed_retmax": 400
  }
}
```

---

## 实际示例

### 1. COVID-19 Serial Interval（你的案例）

```json
{
  "research_question": "COVID-19 serial interval distribution meta-analysis in early 2020 pandemic",
  "domain": "infectious_disease"
}
```

### 2. 空气污染与心血管疾病

```json
{
  "research_question": "Association between PM2.5 exposure and cardiovascular disease incidence",
  "domain": "environmental_epi"
}
```

### 3. 糖尿病危险因素

```json
{
  "research_question": "Risk factors for type 2 diabetes in Asian populations",
  "domain": "chronic_disease"
}
```

### 4. 疫苗效果

```json
{
  "research_question": "Effectiveness of influenza vaccines in preventing hospitalization",
  "domain": "infectious_disease"
}
```

### 5. 癌症筛查

```json
{
  "research_question": "Effectiveness of colorectal cancer screening programs",
  "domain": "cancer_epi"
}
```

---

---

## 年份/日期过滤详解

### 方式 1：精确日期范围（推荐用于特定时期研究）

```json
{
  "params": {
    "pubmed_date_range": "2020/1/1-2020/10/22"
  }
}
```

- 格式：`"起始日期-结束日期"` 或 `"起始日期:结束日期"`
- 示例：`"2020/1/1-2020/10/22"` 或 `"2020/01/01:2020/10/22"`
- **适用场景**：COVID-19 疫情早期、特定事件时期

### 方式 2：年份范围

```json
{
  "params": {
    "pubmed_year_range": "2020-2024"
  }
}
```

- 格式：`"起始年-结束年"` 或 `"起始年:结束年"`
- 单年：`"2020-2020"` 或 `"2020:2020"`

### 方式 3：分别指定最小/最大年份

```json
{
  "params": {
    "pubmed_min_year": 2020,
    "pubmed_max_year": 2024
  }
}
```

### 方式 4：只限制最小年份

```json
{
  "params": {
    "pubmed_min_year": 2020
  }
}
```

只检索 2020 年及以后的文献

### 方式 5：只限制最大年份

```json
{
  "params": {
    "pubmed_max_year": 2021
  }
}
```

只检索 2021 年及以前的文献

**重要提示**：

- 日期格式中的分隔符可以用**短横线 `-`** 或**冒号 `:`**（系统会自动转换）
- 对于 PubMed，最终会转为 `[pdat]` 搜索字段
- 例如：`"2020/1/1-2020/10/22"` → `(query) AND (2020/1/1:2020/10/22[pdat])`

---

## domain 字段选项

| 值                   | 中文说明       | 适用研究                     |
| -------------------- | -------------- | ---------------------------- |
| `infectious_disease` | 传染病流行病学 | COVID-19, 流感, 疟疾, 结核等 |
| `chronic_disease`    | 慢性病流行病学 | 糖尿病, 高血压, COPD 等      |
| `environmental_epi`  | 环境流行病学   | 空气污染, 水污染, 气候变化   |
| `cancer_epi`         | 癌症流行病学   | 各类癌症危险因素和筛查       |
| `nutritional_epi`    | 营养流行病学   | 膳食因素与疾病关系           |
| `genetic_epi`        | 遗传流行病学   | 基因-环境交互作用            |
| `social_epi`         | 社会流行病学   | 社会经济地位与健康           |
| `epidemiology`       | 通用流行病学   | 不确定时使用                 |

---

## research_question 撰写技巧

### ✅ 好的研究问题（清晰具体）

- "COVID-19 serial interval distribution meta-analysis"
- "Association between air pollution and cardiovascular mortality"
- "Risk factors for type 2 diabetes in adults"
- "Effectiveness of HPV vaccine in preventing cervical cancer"

### ❌ 不好的研究问题（太宽泛）

- "COVID-19 research" → 改为 "COVID-19 transmission dynamics"
- "cancer" → 改为 "risk factors for lung cancer"
- "diabetes" → 改为 "dietary factors associated with type 2 diabetes"

### 推荐格式

- **关联研究**: "Association/Relationship between [暴露] and [结局]"
- **Meta 分析**: "[疾病/暴露] [参数] meta-analysis"
- **危险因素**: "Risk factors for [疾病] in [人群]"
- **干预效果**: "Effectiveness of [干预] in [结局]"

---

## 高级配置（可选）

如果需要自定义更多参数，编辑 `configs/pipeline_config.yaml`：

```yaml
# 数据源
default_providers:
  - pubmed  # 默认只用 PubMed

# 查询数量
query_generation:
  max_queries_per_provider: 12  # 默认 12 个查询

# 结果限制
pubmed:
  max_results: 500  # 每个查询最多 500 篇
  year_filter: null  # 不限年份，或设为 "2020:2024"

# 日志级别
logging:
  level: WARNING  # 只显示警告（避免UI卡顿）
```

修改后重启 `langgraph dev` 即可生效。

---

## 故障排查

### 问题：Web UI 右侧日志太多，页面卡顿

**原因**：默认显示所有检索细节（每篇文章信息）

**解决**：已优化为 WARNING 级别，只显示警告和错误

**验证**：重启后右侧不再显示每篇文章的详细信息

### 问题：检索结果太少

**建议**：

1. 扩大研究问题范围（加同义词）
2. 检查 `year_filter` 是否限制太严
3. 增加 `max_queries_per_provider`

### 问题：检索时间太长

**建议**：

1. 减少 `max_queries_per_provider: 6`
2. 限制 `max_results: 200`
3. 禁用 Scoping search: `scoping.enabled: false`

---

## 下一步

1. 复制上面的 JSON 示例
2. 修改 `research_question` 和 `domain`
3. 在 Web UI 中粘贴并点击 Run
4. 等待 60-90 秒完成检索和筛选
5. 查看结果导出到 `langgraph_runs/` 目录
