# 查询质量优化指南

## 问题诊断

根据 `run_20260113_023744` 的结果分析：

### terms.json 问题

- **过度发散**: primary_keywords 11 个，synonyms 25 个，related_terms 33 个
- **充斥复合短语**: "case isolation delay", "time to isolation", "onset-to-isolation interval"
- **同义词泛滥**: isolation delay/isolation lag/isolation timing/isolation interval (说同一件事)

### queries.json 问题

- **过于冗长**: Query 1 包含 14 个 OR 条件，3 层嵌套括号
- **盲目组合**: 所有 keywords 全部塞入，导致精确率下降

### 对比 Ground Truth

```
Ground Truth: ("interval" OR "delay" OR "latency") AND ("Isolation" OR "quarantine") AND (病毒词)
            = 3个核心词 × 2个动作词 × 病毒 = 简洁有力

你的Query:  14个病毒相关词 AND 6个outcome词 AND 6个design词 = 过度复杂
```

---

## 优化方案

### 1. 限制 Keywords 生成数量

修改 `src/epidemiology/keyword_generator.py` 的 prompt (约 1110 行):

```python
default_system = (
    "You are an expert in epidemiology literature search. Your task is to generate "
    "FOCUSED and HIGH-QUALITY search keywords for academic databases (e.g., PubMed).\n\n"
    "CRITICAL RULES:\n"
    "1. QUANTITY LIMITS (strictly enforce):\n"
    "   - primary_keywords: 3-5 core concepts ONLY\n"
    "   - synonyms: 5-8 true synonyms (not variations)\n"
    "   - related_terms: 5-10 closely related concepts\n"
    "   - domain_terms: 3-5 epidemiological methods\n"
    "   - outcome_terms: 3-5 key outcomes\n"
    "   - design_terms: 3-5 study types\n"
    "   - population_terms: 3-5 if applicable\n"
    "   - measurement_terms: 3-5 if applicable\n"
    "   - context_terms: 3-5 if applicable\n\n"
    "2. PHRASE COMPOSITION RULES:\n"
    "   - Use SINGLE WORDS or STANDARD MEDICAL TERMS only\n"
    "   - AVOID inventing compound phrases (e.g., 'case isolation delay')\n"
    "   - AVOID 'X to Y', 'X-to-Y', 'time to X' patterns\n"
    "   - Break concepts into separate words: 'isolation', 'delay' (NOT 'isolation delay')\n\n"
    "3. META-ANALYSIS DETECTION:\n"
    "   - If user says 'conduct/perform meta-analysis' → search for PRIMARY STUDIES\n"
    "   - Do NOT include 'meta-analysis' in keywords\n"
    "   - Design terms: use 'cohort study', 'observational study', NOT 'meta-analysis'\n\n"
    "4. SYNONYM QUALITY:\n"
    "   - Only TRUE synonyms (exact same meaning)\n"
    "   - NOT variations or related concepts (those go to related_terms)\n"
    "   - Example: 'serial interval' ↔ 'generation time' ✓\n"
    "   - Example: 'isolation delay' ↔ 'isolation lag' ✗ (invented phrases)\n\n"
    "Format: Return ONLY valid JSON with STRICT number limits."
)
```

### 2. 改进 Query 构建策略

修改 `src/epidemiology/boolean_search_agent.py` 的 `generate_queries()` 方法：

**当前问题**: 使用 combinations 盲目组合所有 terms
**解决方案**: 精选核心 terms，避免全量组合

```python
def generate_queries(self, keyword_set) -> List[str]:
    """Generate queries using selective combination strategy."""
    queries: List[str] = []

    # 精选核心词（不要全部使用）
    prim = keyword_set.primary_keywords[:3]  # 原来可能有11个，只用前3个
    syn = keyword_set.synonyms[:5]           # 原来25个，只用前5个
    dom = keyword_set.domain_terms[:3]
    rel = keyword_set.related_terms[:5]

    # Strategy 1: Simple 2-concept core queries
    for p in prim[:3]:
        for s in syn[:3]:
            q = self._and_join([self._quote(p), self._quote(s)])
            queries.append(self._format(q))
            if len(queries) >= self.max_queries:
                return queries[:self.max_queries]

    # Strategy 2: Add 1 domain constraint
    for p in prim[:2]:
        or_syn = self._or_group([p] + syn[:3])
        for d in dom[:2]:
            q = self._and_join([or_syn, self._quote(d)])
            queries.append(self._format(q))
            if len(queries) >= self.max_queries:
                return queries[:self.max_queries]

    # Strategy 3: Add related term specificity
    for p in prim[:2]:
        or_syn = self._or_group([p] + syn[:3])
        for r in rel[:3]:
            q = self._and_join([or_syn, self._quote(r)])
            queries.append(self._format(q))
            if len(queries) >= self.max_queries:
                return queries[:self.max_queries]

    return queries[:self.max_queries]
```

### 3. 配置参数优化

修改 `configs/pipeline_config.yaml`:

```yaml
query_generation:
  max_queries_per_provider: 5  # 从10减少到5，提高单个query质量
  use_llm_queries: true
  llm_max_retries: 3

# 可选：限制每个category的terms数量
llm_term_limits:
  primary_keywords: 5
  synonyms: 8
  related_terms: 10
  domain_terms: 5
  outcome_terms: 5
  design_terms: 5
  population_terms: 5
  measurement_terms: 5
  context_terms: 5
```

---

## 预期效果

### Before (当前)

```json
{
  "primary_keywords": [11项, 包含"case isolation delay"等复合短语],
  "synonyms": [25项, 大量重复概念],
  "query": "(14个病毒词) AND (6个outcome) AND (6个design)"
}
```

### After (优化后)

```json
{
  "primary_keywords": ["COVID-19", "SARS-CoV-2", "isolation", "delay", "transmission"],
  "synonyms": ["2019-nCoV", "novel coronavirus", "quarantine", "latency", "interval"],
  "query": "((COVID-19 OR SARS-CoV-2) AND (isolation AND delay)) AND (transmission OR outbreak)"
}
```

### 关键改进

1. **Terms 精简 50-70%**: 从 95+个 → 30-40 个核心词
2. **Query 简洁度提升**: 从 3 层嵌套 14 条件 → 2 层嵌套 5-8 条件
3. **精确率提升**: 减少噪音，类似 Ground Truth 的简洁风格
4. **可维护性**: 人类可读，易于调试和修改

---

## 实施步骤

1. **第一步**: 修改 `keyword_generator.py` prompt，添加数量限制
2. **第二步**: 测试 keywords 生成，验证数量符合限制
3. **第三步**: 可选修改 `boolean_search_agent.py` 的组合策略
4. **第四步**: 重新运行 pipeline，对比效果

建议先实施第一步，因为 keywords 质量是根本。Query 构建可以在 LLM prompt 中通过示例引导。
