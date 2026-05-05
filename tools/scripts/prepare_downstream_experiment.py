from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _normalize_pmid(value: str | None) -> str:
    return (value or "").strip()


def _is_ground_truth_flag(value: str | None) -> bool:
    raw = (value or "").strip()
    return raw == "✓" or raw.lower() in {"gt", "true", "1", "yes", "y"}


def _is_predicted_relevant(value: str | None) -> bool:
    return (value or "").strip() in {"strong_candidate", "possible_candidate"}


def _write_pmid_list(path: Path, pmids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(pmids) + ("\n" if pmids else ""), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _pdf_availability(pmids: list[str], pdf_dir: Path) -> dict[str, int]:
    have = 0
    missing = 0
    for pmid in pmids:
        if (pdf_dir / f"PMID_{pmid}.pdf").exists():
            have += 1
        else:
            missing += 1
    return {"available": have, "missing": missing}


def _subset_rows(screened_rows: list[dict[str, str]], pmids: set[str]) -> list[dict[str, str]]:
    return [row for row in screened_rows if _normalize_pmid(row.get("PMID")) in pmids]


def _screened_projection(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    projected: list[dict[str, str]] = []
    for row in rows:
        projected.append(
            {
                "PMID": row.get("PMID", ""),
                "DOI": row.get("DOI", ""),
                "Title": row.get("Title", ""),
                "Publication Year": row.get("Publication Year", ""),
                "llm_suggest": row.get("llm_suggest", ""),
                "overall_score": row.get("overall_score", ""),
                "is_ground_truth": row.get("is_ground_truth", ""),
                "screening_stage": row.get("screening_stage", ""),
                "fulltext_status": row.get("fulltext_status", ""),
            }
        )
    return projected


def _gt_projection(gt_rows: list[dict[str, str]], matched_pmids: set[str]) -> list[dict[str, str]]:
    projected: list[dict[str, str]] = []
    for row in gt_rows:
        pmid = _normalize_pmid(row.get("gt_pmid"))
        projected.append(
            {
                "gt_pmid": pmid,
                "gt_doi": row.get("gt_doi", ""),
                "gt_title": row.get("gt_title", ""),
                "gt_year": row.get("gt_year", ""),
                "gt_journal": row.get("gt_journal", ""),
                "review_status": row.get("review_status", ""),
                "predicted_relevant": "yes" if pmid in matched_pmids else "no",
            }
        )
    return projected


def _build_readme(
    *,
    out_dir: Path,
    screened_csv: Path,
    gt_csv: Path,
    project_name: str,
    counts: dict[str, int],
    pdf_counts: dict[str, dict[str, int]],
) -> str:
    return f"""# Downstream Robustness Pilot

Project: `{project_name}`

Source files:
- screened: `{screened_csv}`
- ground truth: `{gt_csv}`

Current screening split:
- Pool: {counts['pool']}
- GT: {counts['gt']}
- Predicted relevant: {counts['predicted_relevant']}
- TP: {counts['tp']}
- FP: {counts['fp']}
- FN: {counts['fn']}
- TN: {counts['tn']}

PDF availability in `paper_pool/pdfs`:
- GT: {pdf_counts['gt']['available']} available / {pdf_counts['gt']['missing']} missing
- Predicted relevant: {pdf_counts['predicted_relevant']['available']} available / {pdf_counts['predicted_relevant']['missing']} missing
- TP: {pdf_counts['tp']['available']} available / {pdf_counts['tp']['missing']} missing
- FN: {pdf_counts['fn']['available']} available / {pdf_counts['fn']['missing']} missing

Note:
- `coding_sheet` accepts PMID `.txt` inputs.
- When a PMID is missing from `paper_pool/pdfs`, the extraction pipeline will try to fetch the PDF automatically before MinerU/LLM processing.

Recommended experiment:
1. Run extraction on `inputs/predicted_relevant_pmids.txt`
2. Run extraction on `inputs/gt_pmids.txt`
3. Compare extracted, usable serial-interval studies and final pooled SI against the source SR/meta-analysis

Suggested commands:

```powershell
cd D:\\AILab\\MAS\\Meta-Analysis\\MetaAgent-Epi\\dev\\coding_sheet
.venv\\Scripts\\activate

python cli/extract_epi.py `
  --input "{out_dir / 'inputs' / 'predicted_relevant_pmids.txt'}" `
  --out "{out_dir / 'coding_sheet_predicted_relevant'}" `
  --stage both

python cli/extract_epi.py `
  --input "{out_dir / 'inputs' / 'gt_pmids.txt'}" `
  --out "{out_dir / 'coding_sheet_gt'}" `
  --stage both
```

Useful subsets:
- `inputs/tp_pmids.txt`: retained GT studies
- `inputs/fn_pmids.txt`: missed GT studies
- `inputs/fp_pmids.txt`: non-GT studies sent downstream by screening

Downstream comparison target:
- Final serial interval estimate from extracted usable studies
- Compare predicted-relevant vs GT-only vs original SR/meta-analysis
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare downstream robustness experiment assets from screening outputs.")
    parser.add_argument("--screened-csv", required=True, help="Path to project_*_screened.csv")
    parser.add_argument("--gt-csv", required=True, help="Path to project_*_groundtruth.csv")
    parser.add_argument("--out-dir", required=True, help="Directory to write experiment assets")
    parser.add_argument("--project-name", default="", help="Human-readable project label")
    parser.add_argument(
        "--paper-pool-pdf-dir",
        default="",
        help="Override PDF cache directory (default: repo/paper_pool/pdfs)",
    )
    args = parser.parse_args()

    screened_csv = Path(args.screened_csv).resolve()
    gt_csv = Path(args.gt_csv).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    repo_root = Path(__file__).resolve().parents[2]
    pdf_dir = (
        Path(args.paper_pool_pdf_dir).resolve()
        if args.paper_pool_pdf_dir
        else repo_root / "paper_pool" / "pdfs"
    )

    screened_rows = _read_csv(screened_csv)
    gt_rows = _read_csv(gt_csv)

    gt_pmids = sorted({_normalize_pmid(row.get("gt_pmid")) for row in gt_rows if _normalize_pmid(row.get("gt_pmid"))})
    predicted_relevant_pmids = sorted(
        {
            _normalize_pmid(row.get("PMID"))
            for row in screened_rows
            if _is_predicted_relevant(row.get("llm_suggest")) and _normalize_pmid(row.get("PMID"))
        }
    )

    tp_pmids: list[str] = []
    fp_pmids: list[str] = []
    fn_pmids: list[str] = []
    tn_pmids: list[str] = []

    for row in screened_rows:
        pmid = _normalize_pmid(row.get("PMID"))
        if not pmid:
            continue
        truth = _is_ground_truth_flag(row.get("is_ground_truth"))
        pred = _is_predicted_relevant(row.get("llm_suggest"))
        if pred and truth:
            tp_pmids.append(pmid)
        elif pred and not truth:
            fp_pmids.append(pmid)
        elif (not pred) and truth:
            fn_pmids.append(pmid)
        else:
            tn_pmids.append(pmid)

    tp_set = set(tp_pmids)
    fp_set = set(fp_pmids)
    fn_set = set(fn_pmids)
    predicted_set = set(predicted_relevant_pmids)

    inputs_dir = out_dir / "inputs"
    tables_dir = out_dir / "tables"

    _write_pmid_list(inputs_dir / "gt_pmids.txt", gt_pmids)
    _write_pmid_list(inputs_dir / "predicted_relevant_pmids.txt", predicted_relevant_pmids)
    _write_pmid_list(inputs_dir / "tp_pmids.txt", sorted(tp_set))
    _write_pmid_list(inputs_dir / "fp_pmids.txt", sorted(fp_set))
    _write_pmid_list(inputs_dir / "fn_pmids.txt", sorted(fn_set))

    _write_csv(tables_dir / "gt_records.csv", _gt_projection(gt_rows, tp_set))
    _write_csv(tables_dir / "predicted_relevant_records.csv", _screened_projection(_subset_rows(screened_rows, predicted_set)))
    _write_csv(tables_dir / "tp_records.csv", _screened_projection(_subset_rows(screened_rows, tp_set)))
    _write_csv(tables_dir / "fp_records.csv", _screened_projection(_subset_rows(screened_rows, fp_set)))
    _write_csv(tables_dir / "fn_records.csv", _screened_projection(_subset_rows(screened_rows, fn_set)))

    counts = {
        "pool": len(screened_rows),
        "gt": len(gt_pmids),
        "predicted_relevant": len(predicted_relevant_pmids),
        "tp": len(tp_set),
        "fp": len(fp_set),
        "fn": len(fn_set),
        "tn": len(tn_pmids),
    }
    decision_mix = Counter((row.get("llm_suggest") or "").strip() for row in screened_rows)
    pdf_counts = {
        "gt": _pdf_availability(gt_pmids, pdf_dir),
        "predicted_relevant": _pdf_availability(predicted_relevant_pmids, pdf_dir),
        "tp": _pdf_availability(sorted(tp_set), pdf_dir),
        "fn": _pdf_availability(sorted(fn_set), pdf_dir),
    }
    summary = {
        "project_name": args.project_name or screened_csv.parent.name,
        "screened_csv": str(screened_csv),
        "gt_csv": str(gt_csv),
        "paper_pool_pdf_dir": str(pdf_dir),
        "counts": counts,
        "decision_mix": dict(decision_mix),
        "pdf_availability": pdf_counts,
    }

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "README.md").write_text(
        _build_readme(
            out_dir=out_dir,
            screened_csv=screened_csv,
            gt_csv=gt_csv,
            project_name=args.project_name or screened_csv.parent.name,
            counts=counts,
            pdf_counts=pdf_counts,
        ),
        encoding="utf-8",
    )

    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
