# Downstream Robustness Pilot

Project: `P13 Serial Interval Robustness Pilot`

Source files:
- screened: `D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi\evaluation\screening\GT_1\GT_export\serial_interval\p13\project_13_screened.csv`
- ground truth: `D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi\evaluation\screening\GT_1\GT_export\serial_interval\p13\project_13_groundtruth.csv`

Current screening split:
- Pool: 111
- GT: 51
- Predicted relevant: 90
- TP: 44
- FP: 46
- FN: 7
- TN: 14

PDF availability in `dev/paper_pool/pdfs`:
- GT: 2 available / 49 missing
- Predicted relevant: 3 available / 87 missing
- TP: 2 available / 42 missing
- FN: 0 available / 7 missing

Note:
- `coding_sheet` accepts PMID `.txt` inputs.
- When a PMID is missing from `dev/paper_pool/pdfs`, the extraction pipeline will try to fetch the PDF automatically before MinerU/LLM processing.

Recommended experiment:
1. Run extraction on `inputs/predicted_relevant_pmids.txt`
2. Run extraction on `inputs/gt_pmids.txt`
3. Compare extracted, usable serial-interval studies and final pooled SI against the source SR/meta-analysis

Suggested commands:

```powershell
cd D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi\dev\coding_sheet
.venv\Scripts\activate

python cli/extract_epi.py `
  --input "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi\evaluation\screening\GT_1\GT_export\serial_interval\p13\downstream_experiment\inputs\predicted_relevant_pmids.txt" `
  --out "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi\evaluation\screening\GT_1\GT_export\serial_interval\p13\downstream_experiment\coding_sheet_predicted_relevant" `
  --stage both

python cli/extract_epi.py `
  --input "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi\evaluation\screening\GT_1\GT_export\serial_interval\p13\downstream_experiment\inputs\gt_pmids.txt" `
  --out "D:\AILab\MAS\Meta-Analysis\MetaAgent-Epi\evaluation\screening\GT_1\GT_export\serial_interval\p13\downstream_experiment\coding_sheet_gt" `
  --stage both
```

Useful subsets:
- `inputs/tp_pmids.txt`: retained GT studies
- `inputs/fn_pmids.txt`: missed GT studies
- `inputs/fp_pmids.txt`: non-GT studies sent downstream by screening

Downstream comparison target:
- Final serial interval estimate from extracted usable studies
- Compare predicted-relevant vs GT-only vs original SR/meta-analysis
