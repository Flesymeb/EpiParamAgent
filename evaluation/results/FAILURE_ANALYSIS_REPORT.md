# 5D Screening Failure Analysis — COVID-19 DeepSeek v4 Flash

## Overall Results (13 projects, 561 GT papers, ~9,012 pool)

| Metric | Value | 95% CI |
|--------|-------|--------|
| **Recall** | 85.7% (481/561) | 82.5%–88.4% |
| **Precision** | 16.6% (481/2895) | 15.3%–18.0% |
| **Work Saved** | 67.5% | — |
| **Strong Precision** | 21.8% (447/2053) | — |
| **Possible Precision** | **4.0%** (34/842) | — |
| **FN** | 80 papers | — |

### By Topic

| Topic | GT | Recall | Precision | Strong Prec | Poss Prec | Key Issue |
|-------|-----|--------|-----------|-------------|-----------|-----------|
| Fatality | 136 | 97.1% | 9.7% | 14.8% | 1.4% | Huge FP: 1227 |
| Reproduction Number | 242 | 74.0% | 16.4% | 19.0% | 5.2% | High FN: 63 |
| Serial Interval | 183 | 92.9% | 38.5% | 47.7% | 13.4% | Best performing |

## Key Findings

### 1. False Positive Analysis (2414 FPs)

**By suggest type**: 1606 Strong (66.5%), 808 Possible (33.5%)

**Dominant failure mode**: The model gives high scores (E=4, P=4) to non-original research:
- 1372 FPs (56.8%) have E=4 AND P=4
- 2409 FPs (99.8%) have D=4 — model almost always says disease matches

**FP by publication type** (actual pub_types in CSV):
- Journal Article: 2186 — many of these are NOT original research despite the label
- Letter: 176 — should ALWAYS be excluded
- Comment: 61 — should ALWAYS be excluded  
- Editorial: 38 — should ALWAYS be excluded
- Review: 11 — should ALWAYS be excluded
- News: 13 — should ALWAYS be excluded

**Root cause**: The evidence score (0-4) is supposed to filter non-original research, but:
1. Letters/Comments/Editorials get E=1-4 instead of E=0
2. The prompt doesn't emphasize strongly enough that pub_types={Editorial, Letter, Comment, News} → evidence=0
3. Structured abstract Methods labels (or lack thereof) are not being used

### 2. False Negative Analysis (80 FNs)

**All 80 are classified as "unlikely_candidate"** — model never misses as strong/possible

**By evidence score**:
- E=0 (3): Systematic reviews correctly excluded, GT error
- E=1 (48): Low evidence — possibly modeling papers or reviews
- E=3-4 (27): Should have been caught, these are real misses

**By parameter score**:
- P=0-1 (13): Model says paper doesn't report target parameter
- P=2 (18): Uncertain parameter relevance
- P=4 (47): Model says parameter IS relevant but paper still excluded

**Key insight**: The 47 FNs with P=4 but excluded likely failed on E=1 or D<4 — these are modeling/aggregate data papers that the strict evidence threshold filters out.

**3 GT errors**: 3 systematic reviews in serial_interval GT should be flagged or removed.

### 3. Strong vs Possible Accuracy

| Bucket | Count | TP | FP | Precision |
|--------|-------|----|----|-----------| 
| Strong | 2053 | 447 | 1606 | **21.8%** |
| Possible | 842 | 34 | 808 | **4.0%** |

**Possible is essentially noise** — 1 in 25 papers is GT. This bucket adds 808 FPs while only recovering 34 GT papers (from 561 total GT).

**Score profile for Possible FPs**: Avg D=4.0, E=2.9, Par=3.0
- 46.2% have E ≤ 2 (could be filtered with full-text evidence check)
- 22.9% have P ≤ 2 (weak parameter signal already)

### 4. Full-Text Enrichment Potential

Tested enrichment agent on key FP cases:
- PMID 32031234 (Editorial): Enrichment adds pub_types=["Editorial"], MeSH=[mortality, humans] → clear signal to exclude
- PMID 32224313 (Letter): pub_types=["Letter"] → should be excluded
- PMID 32198088: Structured abstract has [METHODS] and [RESULTS] labels → shows R0 data but it was included for serial_interval (parameter mismatch!)

**What full-text can fix**:
1. Flag papers with pub_types={Editorial, Letter, Comment, News} → auto-exclude
2. Use structured abstract Labels (METHODS/RESULTS) → better evidence scoring
3. Parameter mismatch detection (R0 vs SI vs CFR)
4. PMC full-text Methods section → verify original data collection

## Recommended Actions

### Short-term (code + prompt fixes)
1. **Pre-filter pub_types**: Exclude Editorial, Letter, Comment, News, Video-Audio Media before LLM screening
2. **Tighten possible thresholds**: Raise evidence_min and parameter_min for possible bucket
3. **Enhance prompt**: Add explicit handling of pub_types and structured abstract labels
4. **Add topic-aware parameter filtering**: R0 papers shouldn't go to serial_interval bucket

### Medium-term (full-text cascade)
5. **Run cascade screening on Possible candidates only**: Only ~842 papers need full-text, not all 9000
6. **Use enrichment agent** to fetch PMC Methods for Possible FPs
7. **Re-screen with enriched content** to filter out non-original research

### For PNAS Paper
8. **Regenerate MPOX results** (files missing from repo)
9. **Use frozen-dataset LEADS-Minimal** as the paper-facing LEADS baseline; do not use pre-freeze LEADS-2 snapshots in main tables
10. **Multi-model comparison** (Qwen 35B, deepseek flash) already have results
11. **Dimension-level contribution analysis** — which dimensions drive decisions?
