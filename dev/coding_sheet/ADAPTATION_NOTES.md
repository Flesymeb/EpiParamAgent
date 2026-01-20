# Coding Sheet 流行病学适配说明

## 📋 核心修改

### 1. **配置文件 (YAML Templates)**

#### 原心理学模板 (`early_numeracy.yaml`)

```yaml
- 研究类型: 纵向相关研究 (T1 → T2)
- 核心指标: 相关系数 (r)
- 关键字段: age_at_t1, age_at_t2, sample_size_t1, sample_size_t2
- 领域特定: 数感测验、家庭环境、数学成绩
```

#### 新流行病学模板 (`covid_variants.yaml` / `v2.yaml`)

```yaml
- 研究类型: 变异株传播力比较
- 核心指标: 再生数 (R0/Rt/Re)
- 关键字段: variant_name, r_estimate, r_lower_ci, r_upper_ci
- 领域特定: Pango谱系、突变位点、疫苗接种状态
```

### 2. **字段设计差异**

| 维度         | 心理学                                       | 流行病学                            |
| ------------ | -------------------------------------------- | ----------------------------------- |
| **识别**     | study, year, country                         | study_id, year, doi, country_region |
| **核心变量** | T1变量, T2变量, 相关系数r                    | variant_name, r_estimate, r_ci      |
| **样本**     | sample_size_t1, sample_size_t2, n (pairwise) | sample_size (病例数)                |
| **时间**     | age_at_t1, age_at_t2, time_lag               | data_period_start, data_period_end  |
| **方法**     | correlation_type, control_variables          | study_design, estimation_method     |
| **特定**     | 测验名称, 家庭SES                            | 变异株谱系, 疫苗状态, 序列间隔      |

### 3. **Prompt修改**

#### 原Prompt (prompting.py)

```python
"""You are an expert meta-analyst extracting coding-sheet data from
educational psychology papers."""
```

#### 新Prompt

```python
"""You are an expert epidemiologist and meta-analyst extracting
structured data from infectious disease research papers.

Your task is to extract reproduction number (R0/Rt/Re) estimates
and related epidemiological parameters from papers studying
SARS-CoV-2 variants."""
```

---

## 🎯 关键适配点

### A. 变异株特异性字段

**新增字段** (心理学模板没有的):

```yaml
- variant_name: "Alpha", "Delta", "Omicron"
- pango_lineage: "B.1.1.7", "B.1.617.2"
- key_mutations: "N501Y; E484K; D614G"
- comparator_variant: 对照组变异株
- relative_transmissibility: 相对传播力
```

**对应心理学字段** (已删除):

```yaml
- t1_variable: T1时的测量变量 ❌
- t2_variable: T2时的测量变量 ❌
- time_lag: T1到T2的时间间隔 ❌
```

### B. 效应量类型差异

#### 心理学: 相关系数

```yaml
- r_value: 0.45
- r_lower_ci: 0.32
- r_upper_ci: 0.58
- n: 150  # pairwise样本量
```

#### 流行病学: 再生数

```yaml
- r_estimate: 1.74  # 注意：R表示Reproduction Number，不是correlation!
- r_lower_ci: 1.42
- r_upper_ci: 2.06
- reproduction_number_type: "Rt" / "R0" / "Re"
- sample_size: 5000  # 病例数
```

### C. 研究设计分类

#### 心理学

```yaml
study_design:
  - Longitudinal (纵向)
  - Cross-sectional (横断)
  - Experimental (实验)
```

#### 流行病学

```yaml
study_design:
  - Observational (观察性)
    - Case surveillance
    - Household study
    - Contact tracing
  - Modeling (建模)
    - Mathematical model
    - Statistical model
    - Phylodynamic
  - Mixed (混合)
```

### D. 人群/场景分类

#### 心理学

```yaml
population:
  - Preschool (学前)
  - Elementary school (小学)
  - Age range: 3-8 years
```

#### 流行病学

```yaml
population_setting:
  - General population (普通人群)
  - Healthcare workers (医护)
  - School/University (学校)
  - Household (家庭传播)
  - Long-term care facilities (养老院)

vaccination_status:
  - Pre-vaccination
  - Partial vaccination
  - High vaccination
```

---

## 🔧 使用方式

### 1. 准备DOI列表

```bash
# 从search_v2_gt.csv提取DOI
cd MetaAgent-Epi/dev/coding_sheet
mkdir -p papers
# 手动创建papers/doi.txt，每行一个DOI
```

### 2. 下载PDFs

```bash
python scripts/pdf_fecher.py --download
# → papers/pdfs/*.pdf
```

### 3. 提取数据 (使用v2配置)

```bash
python scripts/run_extraction.py \
  --input papers/pdfs/ \
  --out output/extraction \
  --method mineru \
  --template v2  # 使用流行病学模板!

# 或使用完整名称
python scripts/run_extraction.py \
  --template covid_variants
```

### 4. 输出格式

```
output/extraction/run_YYYYMMDD_HHMMSS/
├── coding_sheet_v2.xlsx  ← 主输出
├── debug/
│   ├── paper_001_response.json
│   └── paper_002_response.json
└── logs/
    └── extraction.log
```

---

## 📊 Excel输出列顺序

**流行病学模板 (v2.yaml)**:

1. Study Identification: study_id, year, doi, country_region
2. Variant Info: variant_name, pango_lineage, key_mutations
3. Study Design: study_design, data_period_start/end, population_setting
4. Sample: sample_size, vaccination_status
5. **核心结果**:
   - reproduction_number_type
   - r_estimate, r_lower_ci, r_upper_ci
   - estimation_method
6. Comparison: comparator_variant, relative_transmissibility
7. Parameters: serial_interval_mean, generation_time_mean
8. Quality: adjustment_factors, sensitivity_analysis, quality_rating
9. Evidence: evidence_chunk_ids, evidence_quotes, extraction_notes

---

## ⚠️ 注意事项

### 1. 字段命名冲突

**问题**: `r_estimate` 在心理学中是相关系数，在流行病学中是再生数

**解决**:

- 字段名保持 `r_estimate`（复用）
- 通过 `reproduction_number_type` 字段明确语义
- 在prompt中强调: "R here means Reproduction Number, NOT correlation"

### 2. 多记录提取规则

心理学:

```
一篇论文 → 多个时间点 → 多条记录
如 T1-T2, T1-T3, T2-T3 各算一条
```

流行病学:

```
一篇论文 → 多个变异株 → 多条记录
如 Alpha vs WT, Delta vs WT 各算一条
同一变异株多时期 → 多条记录
```

### 3. 置信区间处理

心理学:

- 如果仅报告SE或p值，需要计算CI
- Fisher's z transformation for correlation CI

流行病学:

- 通常直接报告95% CI
- 如果是90% CI或其他，需在notes中标注
- 如果仅报告SE，使用 `CI = estimate ± 1.96*SE`

---

## 🚀 后续扩展

### 其他流行病学研究类型

1. **Serial Interval研究** (search_v1)

```yaml
template: covid_serial_interval.yaml
核心字段:
  - serial_interval_mean
  - serial_interval_sd
  - estimation_method
  - data_source (household/hospital/community)
```

2. **Superspreading研究** (search_v3)

```yaml
template: covid_superspreading.yaml
核心字段:
  - dispersion_parameter_k
  - k_lower_ci, k_upper_ci
  - proportion_causing_80pct
  - offspring_distribution
```

3. **疫苗效果研究**

```yaml
template: vaccine_effectiveness.yaml
核心字段:
  - vaccine_type (Pfizer/Moderna/AZ)
  - ve_infection (对感染的VE%)
  - ve_transmission (对传播的VE%)
  - variant_name
```

---

## 📚 参考资源

### 流行病学术语

- **R0**: Basic reproduction number (基本再生数)
- **Rt/Re**: Time-varying/Effective reproduction number (有效再生数)
- **Serial interval**: 连续病例发病间隔
- **Generation time**: 连续传播者感染间隔
- **VOC**: Variant of Concern (关切变异株)
- **Pango**: 病毒谱系命名系统

### Meta分析参考

- [Cochrane Handbook](https://training.cochrane.org/handbook)
- [PRISMA-P for protocols](http://www.prisma-statement.org/)
- [COVID-19 variant transmissibility: Nature 2021](https://doi.org/10.1038/s41586-021-03470-x)

---

## ✅ 检查清单

在运行提取前确认:

- [ ] 使用 `--template v2` 或 `--template covid_variants`
- [ ] PDFs已下载到 `papers/pdfs/`
- [ ] 检查 `.env` 中的API keys (OPENAI_API_KEY 或 ANTHROPIC_API_KEY)
- [ ] 确认MinerU服务运行 (如使用 `--method mineru`)
- [ ] 准备好ground truth文件用于验证 (optional)

测试单篇提取:

```bash
python scripts/run_extraction.py \
  --input papers/pdfs/volz_2021.pdf \
  --out output/test \
  --template v2 \
  --debug
```
