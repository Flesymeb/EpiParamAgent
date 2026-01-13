# 配置系统使用指南

## Web UI 快速开始（推荐）

### 启动 LangGraph Studio

```bash
cd MetaAgent-Epi/dev/literature_search
langgraph dev --allow-blocking
```

### 在 Web UI 中输入 JSON

**最简格式**（推荐）：

```json
{
  "research_question": "COVID-19 serial interval distribution meta-analysis in early 2020 pandemic",
  "domain": "infectious_disease"
}
```

**其他示例**：

1. **慢性病研究**：

```json
{
  "research_question": "Association between air pollution and cardiovascular disease incidence",
  "domain": "chronic_disease"
}
```

2. **环境流行病学**：

```json
{
  "research_question": "Effects of climate change on vector-borne disease transmission",
  "domain": "environmental_epi"
}
```

3. **癌症流行病学**：

```json
{
  "research_question": "Risk factors for colorectal cancer in Asian populations",
  "domain": "cancer_epi"
}
```

### 可用的 domain 值

- `infectious_disease` - 传染病流行病学
- `chronic_disease` - 慢性病流行病学
- `environmental_epi` - 环境流行病学
- `cancer_epi` - 癌症流行病学
- `nutritional_epi` - 营养流行病学
- `genetic_epi` - 遗传流行病学
- `social_epi` - 社会流行病学
- `epidemiology` - 通用流行病学（默认）

---

## 配置文件位置

主配置文件：`configs/pipeline_config.yaml`

## 快速开始

### 1. 使用默认配置（推荐）

系统会自动加载默认配置，无需任何设置：

```python
from langgraph_pipeline.graph import build_graph, run_once

graph = build_graph()
result = run_once(
    graph,
    research_question="What is the incubation period of COVID-19?",
    domain="infectious_disease"
)
```

**默认行为**：

- 仅使用 PubMed 数据库
- LLM 布尔查询生成（失败时回退到规则）
- 自动筛选启用
- 导出 CSV 和 JSON 格式

### 2. 修改默认配置

编辑 `configs/pipeline_config.yaml`：

```yaml
# 示例：禁用 LLM 查询生成，仅使用规则
query_generation:
  use_llm_queries: false
  fallback_to_rules: true
```

修改后重启 `langgraph dev` 即可生效。

### 3. 编程方式自定义配置

```python
from src.config import PipelineConfig, set_config

# 加载并修改配置
config = PipelineConfig.load_default()
config.query_generation.max_queries_per_provider = 8
config.pubmed.max_results = 300
set_config(config)

# 之后的运行将使用修改后的配置
graph = build_graph()
result = run_once(graph, ...)
```

## 关键配置项说明

### 数据源配置

```yaml
default_providers:
  - pubmed  # 仅使用 PubMed

# 如果需要添加 ERIC（不推荐在流行病学研究中）
# default_providers:
#   - pubmed
#   - eric
```

### 查询生成

```yaml
query_generation:
  use_llm_queries: true  # 使用 LLM 生成查询
  fallback_to_rules: true  # LLM 失败时回退
  llm_max_retries: 2  # LLM 重试次数
  max_queries_per_provider: 12  # 每个数据源的查询数
```

**建议**：

- 如果 LLM 频繁失败，设置 `use_llm_queries: false`
- 如果查询过多导致速度慢，减少 `max_queries_per_provider`

### PubMed 限制

```yaml
pubmed:
  max_results: 500  # 每个查询最多检索 500 篇
  include_medline_only: true  # 仅 MEDLINE 索引文章
  year_filter: "2020-2024"  # 限制年份（可选）
```

### 筛选标准

```yaml
screening:
  enable_autoscreen: true  # 启用 LLM 自动筛选
  study_design_priority:  # 研究设计优先级
    - meta_analysis
    - systematic_review
    - cohort
    - case_control
  exclude_types:  # 排除类型
    - editorial
    - commentary
    - letter
```

### 性能优化

```yaml
performance:
  api_rate_limit_delay: 0.34  # API 调用延迟（秒）
  warn_if_results_exceed: 10000  # 结果数警告阈值
```

## 常见场景

### 场景 1: 快速测试（减少检索量）

```yaml
pubmed:
  max_results: 100  # 限制为 100 篇

query_generation:
  max_queries_per_provider: 5  # 只生成 5 个查询
```

### 场景 2: 高精度研究（最大检索）

```yaml
pubmed:
  max_results: 10000  # 最大限制

query_generation:
  max_queries_per_provider: 20  # 生成更多查询
  min_terms_per_query: 3  # 更严格的查询
```

### 场景 3: 禁用 LLM（纯规则）

```yaml
keyword_generation:
  enable_domain_analysis: false  # 禁用领域分析

query_generation:
  use_llm_queries: false  # 不使用 LLM

screening:
  enable_autoscreen: false  # 不使用 LLM 筛选
```

### 场景 4: 特定年份范围

```yaml
pubmed:
  year_filter: "2020-2024"  # 仅 2020-2024 年文献
```

## 配置验证

运行后检查日志：

```
INFO - Loaded config: default_providers=['pubmed']
INFO - Query generation: use_llm=True, fallback=True
INFO - PubMed config: max_results=500, medline_only=True
```

## 故障排查

### 问题：ERIC 返回大量无关结果

**解决**：在 `pipeline_config.yaml` 中移除 ERIC：

```yaml
default_providers:
  - pubmed  # 仅保留 PubMed
```

### 问题：LLM 生成查询频繁失败

**解决**：禁用 LLM 或调整重试：

```yaml
query_generation:
  use_llm_queries: false  # 选项 1：禁用 LLM
  # 或
  llm_max_retries: 5  # 选项 2：增加重试次数
```

### 问题：PubMed 查询超过 10,000 限制

**解决**：增加查询精度：

```yaml
query_generation:
  min_terms_per_query: 3  # 要求更多术语
  max_terms_per_query: 12  # 限制最大术语数
```

### 问题：检索速度太慢

**解决**：减少查询数量或结果数：

```yaml
pubmed:
  max_results: 200  # 减少每个查询的结果

query_generation:
  max_queries_per_provider: 8  # 减少查询数量
```

## 高级用法

### 动态加载不同配置

```python
from src.config import PipelineConfig, set_config

# 快速测试配置
test_config = PipelineConfig.from_yaml("configs/test_config.yaml")
set_config(test_config)

# 生产配置
prod_config = PipelineConfig.from_yaml("configs/production_config.yaml")
set_config(prod_config)
```

### 查看当前配置

```python
from src.config import get_config

config = get_config()
print(f"Providers: {config.default_providers}")
print(f"Max results: {config.pubmed.max_results}")
```

## 参考

- 完整配置项说明：见 `configs/pipeline_config.yaml` 内注释
- 配置类定义：见 `src/config.py`
- LangGraph Studio：配置自动应用到 Studio UI
