# Coding Sheet Extraction - Features & Roadmap

## ✅ Core Features (Implemented)

### Multi-Timepoint Extraction

- **Extract ALL longitudinal timepoints** reported in papers
- Each timepoint → separate records (e.g., Pre-K, K, 1st grade)
- No filtering during extraction (筛选留给后续分析)

### Dependency Tracking

- `sample_id`: Links records from same participant group
- `is_dependent`: Flags non-independent effect sizes
- `timepoint_label`: Original timepoint (e.g., "4½ years")
- `developmental_stage`: Standardized stage (Preschool/Elementary/etc.)

### Smart Sample Size Calculation

```
Priority 1: n = (Sample_T1 + Sample_T2) / 2  [default, float]
Priority 2: n from r(df) in text (e.g., r(97) → n=99)
Priority 3: Explicit statement in text
```

### Full-Context Mode

- Max 500K chars input (tables preserved)
- MinerU VLM extraction: PDF → Markdown
- No pre-truncation when template provided

---

## 🎯 Template: `early_numeracy`

**Research Question**: Early Numeracy (T1) → Math Achievement (T2)

**Key Fields**:

- `sample_size_t1`, `sample_size_t2`: From Table 1 missing rates
- `n`: Pairwise complete cases (float, from T1+T2 average)
- `timepoint_label`, `developmental_stage`: For stage-specific meta-analysis
- `sample_id`, `is_dependent`: For multilevel models / RVE correction

**Extraction Output** (Casey et al., 2018):

- 8 records: 4 EN measures × 2 timepoints (4½yr, 1st grade)
- All flagged `is_dependent=True`, `sample_id="casey_2018"`

---

## 📋 TODO

### High Priority

- [ ] Create `scripts/filter_timepoints.py` - 后处理筛选脚本
  - Filter by longest follow-up
  - Filter by specific developmental stage
  - Export for three-level meta-analysis
- [ ] Add validation warning when `r(df)` differs from `(T1+T2)/2` by >10%

### Medium Priority

- [ ] Support multi-group studies (intervention vs control)

  - Add `group` field
  - Add `comparison_type` (between/within)

- [ ] Batch processing improvements
  - Resume from checkpoint
  - Parallel paper processing

### Low Priority

- [ ] Auto-detect if study has multiple samples (by country/cohort)
- [ ] Generate dependency graph visualization
- [ ] Add field: `outcome_domain` for subgroup meta-analysis

---

## 🔧 Configuration

**Max Tokens**: 32000 (supports 8+ records per paper)

**Template Location**: `src/coding_sheet/configs/templates/`

---

## 📖 Usage Examples

### Single Paper Test

```bash
python test_early_numeracy.py
```

### Batch Extraction

```bash
python scripts/run_extraction.py \
  --input papers/scihub_urls.txt \
  --out output/extraction \
  --method mineru \
  --template early_numeracy \
  --continue-on-error
```
