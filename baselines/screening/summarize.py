#!/usr/bin/env python3
"""Summarize screening baselines and paper-facing model results."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = ROOT / "baselines" / "screening" / "results"
DEFAULT_MODEL_TABLE = ROOT / "docs" / "paper" / "latex" / "tables" / "model_summary.tex"
DEFAULT_LEADS_SUMMARY = ROOT / "evaluation" / "leads_mistral_freeze_leads_minimal_summary.csv"
DEFAULT_KEYWORD_SUMMARY = (
    ROOT / "baselines" / "screening" / "keyword_rules" / "results" / "rule_based_baselines.csv"
)
DEFAULT_BM25_SUMMARY = ROOT / "baselines" / "screening" / "bm25" / "results" / "bm25_baselines.csv"
DEFAULT_NEURAL_RETRIEVAL_SUMMARY = (
    ROOT
    / "baselines"
    / "screening"
    / "neural_retrieval"
    / "results"
    / "neural_retrieval_baselines.csv"
)
DEFAULT_PROFILE_COUNTS_BY_DISEASE = {"covid19": 13, "mpox": 9}


@dataclass(frozen=True)
class SummaryRow:
    method: str
    source: str
    scope: str
    gt: int
    pool: int
    tp: int
    fp: int
    fn: int
    tn: int
    notes: str = ""

    @property
    def predicted_include(self) -> int:
        return self.tp + self.fp

    @property
    def recall(self) -> float:
        return self.tp / self.gt if self.gt else 0.0

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 0.0

    @property
    def specificity(self) -> float:
        denom = self.tn + self.fp
        return self.tn / denom if denom else 0.0

    @property
    def f1(self) -> float:
        denom = self.precision + self.recall
        return 2 * self.precision * self.recall / denom if denom else 0.0

    @property
    def workload_reduction(self) -> float:
        return (self.tn + self.fn) / self.pool if self.pool else 0.0

    @property
    def nns(self) -> float:
        return (self.tp + self.fp) / self.tp if self.tp else math.inf


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def to_int(value: object, default: int = 0) -> int:
    text = str(value if value is not None else "").strip()
    if not text:
        return default
    return int(float(text.replace(",", "")))


def clean_latex_cell(cell: str) -> str:
    text = cell.strip()
    text = re.sub(r"\\textbf\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\makecell(?:\[[^\]]*\])?\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\multirow(?:\[[^\]]*\])?\{[^{}]*\}\{[^{}]*\}\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\centering\s*", "", text)
    text = text.replace("\\\\", " ")
    return text.strip()


def first_number(cell: str) -> int | None:
    match = re.search(r"\d[\d,]*", clean_latex_cell(cell))
    return int(match.group(0).replace(",", "")) if match else None


def parse_paper_model_table(path: Path) -> list[SummaryRow]:
    if not path.exists():
        return []

    rows: list[SummaryRow] = []
    current_pool = 12758
    current_gt = 668
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if "&" not in line or not line.endswith(r"\\"):
            continue
        if line.startswith("Model or method"):
            continue
        cells = [clean_latex_cell(cell) for cell in line.rstrip("\\").split("&")]
        if len(cells) < 12:
            continue

        pool = first_number(cells[1])
        gt = first_number(cells[2])
        if pool is not None:
            current_pool = pool
        if gt is not None:
            current_gt = gt

        method = cells[0]
        try:
            tp = to_int(cells[3])
            fp = to_int(cells[4])
            fn = to_int(cells[5])
            tn = to_int(cells[6])
        except ValueError:
            continue
        rows.append(
            SummaryRow(
                method=method,
                source="paper_model_summary_tex",
                scope="overall",
                gt=current_gt,
                pool=current_pool,
                tp=tp,
                fp=fp,
                fn=fn,
                tn=tn,
                notes="Paper-facing main screening table.",
            )
        )
    return rows


def aggregate(
    rows: Iterable[dict[str, str]],
    *,
    method: str,
    source: str,
    scope: str,
    notes: str = "",
) -> SummaryRow:
    filtered = [row for row in rows if row.get("status", "ok") == "ok"]
    return SummaryRow(
        method=method,
        source=source,
        scope=scope,
        gt=sum(to_int(row.get("ground_truth_count")) for row in filtered),
        pool=sum(to_int(row.get("screened_count")) for row in filtered),
        tp=sum(to_int(row.get("tp")) for row in filtered),
        fp=sum(to_int(row.get("fp")) for row in filtered),
        fn=sum(to_int(row.get("fn")) for row in filtered),
        tn=sum(to_int(row.get("tn")) for row in filtered),
        notes=notes,
    )


def leads_rows(path: Path) -> list[SummaryRow]:
    raw = [row for row in read_csv(path) if row.get("status") == "ok"]
    rows: list[SummaryRow] = []
    for scope in ("covid19", "mpox"):
        rows.append(
            aggregate(
                [row for row in raw if row.get("disease") == scope],
                method="LEADS-Minimal",
                source=str(path.relative_to(ROOT)),
                scope=scope,
                notes="Frozen LEADS-Mistral rerun on dataset/ profiles.",
            )
        )
    rows.append(
        aggregate(
            raw,
            method="LEADS-Minimal",
            source=str(path.relative_to(ROOT)),
            scope="overall",
            notes="Frozen LEADS-Mistral rerun on dataset/ profiles.",
        )
    )
    return rows


def keyword_rows(path: Path) -> list[SummaryRow]:
    rows: list[SummaryRow] = []
    for row in read_csv(path):
        scope = (row.get("scope") or "").strip()
        if scope not in {"covid19", "mpox", "overall"}:
            continue
        rows.append(
            SummaryRow(
                method=row.get("policy", "Keyword rule"),
                source=str(path.relative_to(ROOT)),
                scope=scope,
                gt=to_int(row.get("GT")),
                pool=to_int(row.get("Pool")),
                tp=to_int(row.get("TP")),
                fp=to_int(row.get("FP")),
                fn=to_int(row.get("FN")),
                tn=to_int(row.get("TN")),
                notes="Deterministic keyword-rule rerun from baseline folder.",
            )
        )
    return rows


def bm25_rows(path: Path) -> list[SummaryRow]:
    rows: list[SummaryRow] = []
    for row in read_csv(path):
        scope = (row.get("scope") or "").strip()
        if scope not in {"covid19", "mpox", "overall"}:
            continue
        rows.append(
            SummaryRow(
                method=row.get("policy", "BM25"),
                source=str(path.relative_to(ROOT)),
                scope=scope,
                gt=to_int(row.get("GT")),
                pool=to_int(row.get("Pool")),
                tp=to_int(row.get("TP")),
                fp=to_int(row.get("FP")),
                fn=to_int(row.get("FN")),
                tn=to_int(row.get("TN")),
                notes="BM25 title/abstract rerun with per-profile matched MetaAgent workload.",
            )
        )
    return rows


def neural_retrieval_rows(path: Path) -> list[SummaryRow]:
    rows: list[SummaryRow] = []
    for row in read_csv(path):
        scope = (row.get("scope") or "").strip()
        if scope not in {"covid19", "mpox", "overall"}:
            continue
        rows.append(
            SummaryRow(
                method=row.get("policy", "Neural retrieval"),
                source=str(path.relative_to(ROOT)),
                scope=scope,
                gt=to_int(row.get("GT")),
                pool=to_int(row.get("Pool")),
                tp=to_int(row.get("TP")),
                fp=to_int(row.get("FP")),
                fn=to_int(row.get("FN")),
                tn=to_int(row.get("TN")),
                notes=(
                    "No-training dense retrieval baseline with per-profile "
                    "matched MetaAgent workload."
                ),
            )
        )
    return rows


def llm_prompt_rows(paths: Iterable[Path], *, method: str, notes: str) -> list[SummaryRow]:
    rows: list[SummaryRow] = []
    combined_raw: list[dict[str, str]] = []
    sources: list[str] = []
    for path in paths:
        raw = [row for row in read_csv(path) if row.get("status") == "ok"]
        if not raw:
            continue
        source = str(path.relative_to(ROOT))
        sources.append(source)
        combined_raw.extend(raw)
        path_scope = path.parent.name.strip()
        scope_values = sorted({row.get("disease", "") for row in raw if row.get("disease")})
        if not scope_values and path_scope in DEFAULT_PROFILE_COUNTS_BY_DISEASE:
            scope_values = [path_scope]
        for scope in scope_values:
            rows.append(
                aggregate(
                    [row for row in raw if not row.get("disease") or row.get("disease") == scope],
                    method=method,
                    source=source,
                    scope=scope,
                    notes=notes,
                )
            )
    if combined_raw:
        rows.append(
            aggregate(
                combined_raw,
                method=method,
                source="; ".join(sources),
                scope="overall",
                notes=notes,
            )
        )
    return rows


def screenprompt_rows(paths: Iterable[Path]) -> list[SummaryRow]:
    return llm_prompt_rows(
        paths,
        method="AgentSLR-style ScreenPrompt Lite",
        notes="Optional LLM baseline; not an official AgentSLR reproduction.",
    )


def reviewcopilot_rows(paths: Iterable[Path]) -> list[SummaryRow]:
    return llm_prompt_rows(
        paths,
        method="ReviewCopilot-style GPT screening",
        notes=(
            "Optional open-source workflow baseline inspired by ReviewCopilot; "
            "manual keyword exclusions disabled."
        ),
    )


def reviewcopilot_minimal_rows(paths: Iterable[Path]) -> list[SummaryRow]:
    return llm_prompt_rows(
        paths,
        method="ReviewCopilot-minimal binary screening",
        notes=(
            "Optional prompt-only LLM baseline using only the review question, "
            "title, and abstract; no profile-specific criteria or unclear class."
        ),
    )


def is_complete_llm_summary(path: Path, *, prompt_style: str) -> bool:
    """Return True for full, non-smoke LLM prompt-baseline runs.

    The LLM runner writes `summary.csv` even for `--dry-run`, `--limit`, and
    single-profile smoke tests. Auto-discovery should include only complete
    disease-level runs so the official rollup cannot accidentally mix in partial
    diagnostics.
    """
    run_config_path = path.with_name("run_config.json")
    if not run_config_path.exists():
        return False
    try:
        run_config = json.loads(run_config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if int(run_config.get("limit") or 0) != 0:
        return False
    if str(run_config.get("prompt_style") or "") != prompt_style:
        return False

    rows = read_csv(path)
    ok_rows = [row for row in rows if row.get("status") == "ok"]
    if not ok_rows or len(ok_rows) != len(rows):
        return False
    diseases = {row.get("disease", "").strip() for row in ok_rows if row.get("disease")}
    if not diseases and path.parent.name.strip() in DEFAULT_PROFILE_COUNTS_BY_DISEASE:
        diseases = {path.parent.name.strip()}
    if len(diseases) != 1:
        return False
    disease = next(iter(diseases))
    expected_profiles = DEFAULT_PROFILE_COUNTS_BY_DISEASE.get(disease)
    return expected_profiles is not None and len(ok_rows) == expected_profiles


def is_complete_screenprompt_summary(path: Path) -> bool:
    return is_complete_llm_summary(path, prompt_style="screenprompt_lite")


def is_complete_reviewcopilot_summary(path: Path) -> bool:
    return is_complete_llm_summary(path, prompt_style="reviewcopilot_style")


def is_complete_reviewcopilot_minimal_summary(path: Path) -> bool:
    return is_complete_llm_summary(path, prompt_style="reviewcopilot_minimal")


def fmt_float(value: float) -> str:
    if math.isinf(value):
        return ""
    return f"{value:.6f}"


def write_csv(path: Path, rows: list[SummaryRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "method",
        "source",
        "scope",
        "gt",
        "pool",
        "tp",
        "fp",
        "fn",
        "tn",
        "predicted_include",
        "recall",
        "precision",
        "specificity",
        "f1",
        "workload_reduction",
        "nns",
        "notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "method": row.method,
                    "source": row.source,
                    "scope": row.scope,
                    "gt": row.gt,
                    "pool": row.pool,
                    "tp": row.tp,
                    "fp": row.fp,
                    "fn": row.fn,
                    "tn": row.tn,
                    "predicted_include": row.predicted_include,
                    "recall": fmt_float(row.recall),
                    "precision": fmt_float(row.precision),
                    "specificity": fmt_float(row.specificity),
                    "f1": fmt_float(row.f1),
                    "workload_reduction": fmt_float(row.workload_reduction),
                    "nns": fmt_float(row.nns),
                    "notes": row.notes,
                }
            )


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def write_markdown(path: Path, rows: list[SummaryRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    overall = [row for row in rows if row.scope == "overall"]
    lines = [
        "# Screening Baseline Summary",
        "",
        "This table combines the paper-facing model summary with reproducible baseline reruns under `baselines/screening/`.",
        "",
        "## Overall",
        "",
        "| Method | Source | GT | Pool | Recall | Precision | F1 | WR | NNS | TP/FP/FN/TN |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in overall:
        lines.append(
            "| "
            + " | ".join(
                [
                    row.method,
                    row.source,
                    str(row.gt),
                    str(row.pool),
                    pct(row.recall),
                    pct(row.precision),
                    pct(row.f1),
                    pct(row.workload_reduction),
                    f"{row.nns:.2f}" if not math.isinf(row.nns) else "",
                    f"{row.tp}/{row.fp}/{row.fn}/{row.tn}",
                ]
            )
            + " |"
        )

    by_scope = [row for row in rows if row.scope in {"covid19", "mpox"}]
    if by_scope:
        lines.extend(
            [
                "",
                "## Disease-Level Baselines",
                "",
                "| Method | Scope | Recall | Precision | F1 | WR | NNS | TP/FP/FN/TN |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for row in by_scope:
            lines.append(
                "| "
                + " | ".join(
                    [
                        row.method,
                        row.scope,
                        pct(row.recall),
                        pct(row.precision),
                        pct(row.f1),
                        pct(row.workload_reduction),
                        f"{row.nns:.2f}" if not math.isinf(row.nns) else "",
                        f"{row.tp}/{row.fp}/{row.fn}/{row.tn}",
                    ]
                )
                + " |"
            )

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `paper_model_summary_tex` is the current paper-facing main model table.",
            "- Keyword-rule rerun rows come from `baselines/screening/keyword_rules/run.py` and may differ from the historical paper-row keyword rule because the old generator was not preserved.",
            "- BM25 rows come from `baselines/screening/bm25/run.py`; the default setting ranks title/abstract text and selects the same number of records per source review as the paper-facing MetaAgent/Qwen result.",
            "- Neural retrieval rows come from `baselines/screening/neural_retrieval/run.py` when that optional no-training embedding baseline has been run.",
            "- AgentSLR-style ScreenPrompt Lite rows appear only after a complete disease-level LLM run creates a non-dry-run `summary.csv`; dry-run, limited, and single-profile smoke outputs are ignored by auto-discovery.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def find_screenprompt_summaries() -> list[Path]:
    experiments = ROOT / "evaluation" / "experiments"
    if not experiments.exists():
        return []
    return sorted(
        path
        for path in experiments.glob("*screenprompt_lite*/screening/*/summary.csv")
        if "dryrun" not in str(path) and is_complete_screenprompt_summary(path)
    )


def find_reviewcopilot_summaries() -> list[Path]:
    experiments = ROOT / "evaluation" / "experiments"
    if not experiments.exists():
        return []
    return sorted(
        path
        for path in experiments.glob("*reviewcopilot_style*/screening/*/summary.csv")
        if "dryrun" not in str(path) and is_complete_reviewcopilot_summary(path)
    )


def find_reviewcopilot_minimal_summaries() -> list[Path]:
    experiments = ROOT / "evaluation" / "experiments"
    if not experiments.exists():
        return []
    return sorted(
        path
        for path in experiments.glob("*reviewcopilot_minimal*/screening/*/summary.csv")
        if "dryrun" not in str(path) and is_complete_reviewcopilot_minimal_summary(path)
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-table", type=Path, default=DEFAULT_MODEL_TABLE)
    parser.add_argument("--leads-summary", type=Path, default=DEFAULT_LEADS_SUMMARY)
    parser.add_argument("--keyword-summary", type=Path, default=DEFAULT_KEYWORD_SUMMARY)
    parser.add_argument("--bm25-summary", type=Path, default=DEFAULT_BM25_SUMMARY)
    parser.add_argument("--neural-retrieval-summary", type=Path, default=DEFAULT_NEURAL_RETRIEVAL_SUMMARY)
    parser.add_argument("--screenprompt-summary", type=Path, action="append", default=[])
    parser.add_argument("--reviewcopilot-summary", type=Path, action="append", default=[])
    parser.add_argument("--reviewcopilot-minimal-summary", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT_DIR / "screening_baseline_summary.csv")
    parser.add_argument("--markdown", type=Path, default=DEFAULT_OUT_DIR / "screening_baseline_summary.md")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    screenprompt_paths = args.screenprompt_summary or find_screenprompt_summaries()
    reviewcopilot_paths = args.reviewcopilot_summary or find_reviewcopilot_summaries()
    reviewcopilot_minimal_paths = (
        args.reviewcopilot_minimal_summary or find_reviewcopilot_minimal_summaries()
    )
    rows = (
        parse_paper_model_table(args.model_table)
        + leads_rows(args.leads_summary)
        + keyword_rows(args.keyword_summary)
        + bm25_rows(args.bm25_summary)
        + neural_retrieval_rows(args.neural_retrieval_summary)
        + screenprompt_rows(screenprompt_paths)
        + reviewcopilot_rows(reviewcopilot_paths)
        + reviewcopilot_minimal_rows(reviewcopilot_minimal_paths)
    )
    write_csv(args.output, rows)
    write_markdown(args.markdown, rows)
    print(f"Wrote {args.output}")
    print(f"Wrote {args.markdown}")


if __name__ == "__main__":
    main()
