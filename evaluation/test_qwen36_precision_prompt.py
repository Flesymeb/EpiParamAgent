#!/usr/bin/env python3
"""Smoke-test a precision-tuned 5D screening prompt with Qwen3.6 Plus.

This does not overwrite the formal full-run outputs. It builds an enriched
sample from selected hard profiles: all GT records, previous Qwen false
positives, and a small set of previous true negatives. The goal is to check
whether prompt changes reduce FP while preserving recall before a full rerun.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from metaagent.screening.engine import init_llm_model, screen_papers_batch_async


EXP = "model_5d_screening_multi_adaptive_highc_llmtier_20260507_boyue_qwen3-6-plus"
MODEL = "qwen3.6-plus"
PROVIDER = "boyue"
OUT = REPO / "evaluation" / "screening_prompt_eval" / "qwen36_precision_20260509"

BATCH_SIZE = int(os.getenv("QWEN36_TEST_BATCH_SIZE", "8"))
CONCURRENCY = int(os.getenv("QWEN36_TEST_CONCURRENCY", "4"))
BATCH_MODE = os.getenv("QWEN36_TEST_BATCH_MODE", "multi")
FP_PER_PROJECT = int(os.getenv("QWEN36_TEST_FP_PER_PROJECT", "20"))
TN_PER_PROJECT = int(os.getenv("QWEN36_TEST_TN_PER_PROJECT", "8"))
PROJECT_LIMIT = int(os.getenv("QWEN36_TEST_PROJECT_LIMIT", "0") or "0")
PROJECT_FILTER = {
    item.strip()
    for item in os.getenv("QWEN36_TEST_PROJECTS", "").split(",")
    if item.strip()
}
RANDOM_SEED = 20260509


@dataclass(frozen=True)
class Project:
    disease: str
    topic: str
    project: int
    research_question: str
    disease_focus: str
    parameter_focus: str
    parameter_note: str


MPOX_DISEASE = "(mpox OR monkeypox OR monkeypox virus OR MPXV)"
COVID_DISEASE = "(COVID-19 OR COVID19 OR SARS-CoV-2 OR SARS-COV-2 OR 2019-nCoV OR coronavirus)"

PROJECTS = [
    Project(
        "mpox",
        "fatality",
        4,
        "What are the fatality, mortality, or severity outcomes of mpox?",
        MPOX_DISEASE,
        "(mortality OR fatality OR case fatality rate OR case fatality ratio OR CFR OR death OR deaths OR hospitalization OR severe disease OR ICU)",
        "For fatality/severity, original human case reports, case series, outbreak reports, hospital cohorts, or surveillance reports can be Possible candidates even if the abstract does not explicitly state death/CFR, because clinical outcomes may be in full text. Do not exclude human case/outbreak reports solely because the abstract emphasizes diagnosis, imported-case response, contact tracing, or transmission. Exclude environmental-only, laboratory-only without human clinical cases, animal-only, vaccine-only, policy/commentary, or non-original papers.",
    ),
    Project(
        "mpox",
        "fatality",
        8,
        "What are the fatality, mortality, or severity outcomes of mpox?",
        MPOX_DISEASE,
        "(mortality OR fatality OR case fatality rate OR case fatality ratio OR CFR OR death OR deaths OR hospitalization OR severe disease OR ICU)",
        "For fatality/severity, original human case reports, case series, outbreak reports, hospital cohorts, or surveillance reports can be Possible candidates even if the abstract does not explicitly state death/CFR, because clinical outcomes may be in full text. Do not exclude human case/outbreak reports solely because the abstract emphasizes diagnosis, imported-case response, contact tracing, or transmission. Exclude environmental-only, laboratory-only without human clinical cases, animal-only, vaccine-only, policy/commentary, or non-original papers.",
    ),
    Project(
        "mpox",
        "fatality",
        12,
        "What are the fatality, mortality, or severity outcomes of mpox?",
        MPOX_DISEASE,
        "(mortality OR fatality OR case fatality rate OR case fatality ratio OR CFR OR death OR deaths OR hospitalization OR severe disease OR ICU)",
        "For fatality/severity, original human case reports, case series, outbreak reports, hospital cohorts, or surveillance reports can be Possible candidates even if the abstract does not explicitly state death/CFR, because clinical outcomes may be in full text. Do not exclude human case/outbreak reports solely because the abstract emphasizes diagnosis, imported-case response, contact tracing, or transmission. Exclude environmental-only, laboratory-only without human clinical cases, animal-only, vaccine-only, policy/commentary, or non-original papers.",
    ),
    Project(
        "mpox",
        "serial_interval",
        5,
        "What is the serial interval or generation time of mpox?",
        MPOX_DISEASE,
        "(serial interval OR generation time OR incubation period OR latent period)",
        "For serial interval/generation/incubation, keep original human transmission-chain, household/family cluster, linked-case, outbreak-investigation, and disease-specific Rt/R0/growth modeling papers as Possible candidates when they may use or report interval assumptions/values in methods or full text. Disease-specific Rt/R0 or growth-rate models usually require serial/generation interval assumptions, so prefer P unless the paper is purely generic methods or has no disease-specific human outbreak data.",
    ),
    Project(
        "mpox",
        "serial_interval",
        6,
        "What is the serial interval, incubation period, or latent period of mpox?",
        MPOX_DISEASE,
        "(serial interval OR generation time OR incubation period OR latent period)",
        "For serial interval/generation/incubation, keep original human transmission-chain, household/family cluster, linked-case, outbreak-investigation, and disease-specific Rt/R0/growth modeling papers as Possible candidates when they may use or report interval assumptions/values in methods or full text. Disease-specific Rt/R0 or growth-rate models usually require serial/generation interval assumptions, so prefer P unless the paper is purely generic methods or has no disease-specific human outbreak data.",
    ),
    Project(
        "mpox",
        "serial_interval",
        10,
        "What is the serial interval or generation time of mpox?",
        MPOX_DISEASE,
        "(serial interval OR generation time OR incubation period OR latent period)",
        "For serial interval/generation/incubation, keep original human transmission-chain, household/family cluster, linked-case, outbreak-investigation, and disease-specific Rt/R0/growth modeling papers as Possible candidates when they may use or report interval assumptions/values in methods or full text. Disease-specific Rt/R0 or growth-rate models usually require serial/generation interval assumptions, so prefer P unless the paper is purely generic methods or has no disease-specific human outbreak data.",
    ),
    Project(
        "mpox",
        "serial_interval",
        11,
        "What is the serial interval or incubation period of mpox?",
        MPOX_DISEASE,
        "(serial interval OR generation time OR incubation period OR latent period)",
        "For serial interval/generation/incubation, keep original human transmission-chain, household/family cluster, linked-case, outbreak-investigation, and disease-specific Rt/R0/growth modeling papers as Possible candidates when they may use or report interval assumptions/values in methods or full text. Disease-specific Rt/R0 or growth-rate models usually require serial/generation interval assumptions, so prefer P unless the paper is purely generic methods or has no disease-specific human outbreak data.",
    ),
    Project(
        "mpox",
        "reproduction_number",
        9,
        "What is the reproduction number of mpox?",
        MPOX_DISEASE,
        "(reproduction number OR R0 OR Rt OR effective reproduction number OR basic reproduction number)",
        "For reproduction number, include fitted estimates of R0/Rt/Re but exclude generic outbreak, transmission, or forecasting papers without a reproduction-number cue.",
    ),
    Project(
        "covid19",
        "fatality",
        4,
        "What are the fatality and severity outcomes of SARS-CoV-2 infection?",
        COVID_DISEASE,
        "(mortality OR fatality OR case fatality rate OR case fatality ratio OR CFR OR infection fatality rate OR infection fatality ratio OR IFR OR death rate OR died OR ICU admission OR intensive care OR invasive mechanical ventilation)",
        "For fatality/severity, original human case reports, case series, outbreak reports, hospital cohorts, or surveillance reports can be Possible candidates when they plausibly contain deaths, ICU admission, ventilation, severity, or outcomes in full text. Do not exclude human clinical/outbreak reports solely because the abstract emphasizes diagnosis, contact tracing, or public-health response. Exclude clearly non-original or unrelated papers.",
    ),
    Project(
        "covid19",
        "reproduction_number",
        16,
        "What is the reproduction number of COVID-19?",
        COVID_DISEASE,
        "(reproduction number OR R0 OR Rt OR effective reproduction number OR basic reproduction number OR transmission rate OR epidemic growth rate OR doubling time)",
        "For reproduction number, include empirical or model-fitted transmission estimates, but exclude generic epidemic descriptions without a target-parameter cue.",
    ),
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_gt_pmids(project: Project) -> set[str]:
    path = REPO / "dataset" / project.disease / "screening" / project.topic / f"p{project.project}" / "ground_truth.csv"
    pmids: set[str] = set()
    for row in read_csv(path):
        for col in ("PMID", "pmid", "gt_pmid"):
            value = (row.get(col) or "").strip()
            if value.isdigit():
                exclude = (row.get("exclude_flag") or "").strip().lower()
                if exclude not in {"review_low_evidence", "review", "low_evidence"}:
                    pmids.add(value)
                break
    return pmids


def baseline_path(project: Project) -> Path:
    return (
        REPO
        / "evaluation"
        / "screening"
        / project.disease
        / project.topic
        / f"p{project.project}"
        / "experiments"
        / EXP
        / f"project_{project.project}_screened.csv"
    )


def raw_path(project: Project) -> Path:
    return REPO / "dataset" / project.disease / "screening" / project.topic / f"p{project.project}" / "raw.csv"


def project_meta_path(project: Project) -> Path:
    return REPO / "dataset" / project.disease / "screening" / project.topic / f"p{project.project}" / "project.json"


def scope_note(project: Project) -> str:
    path = project_meta_path(project)
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    start = str(data.get("query_date_from") or "").strip()
    end = str(data.get("query_date_to") or "").strip()
    if start and end:
        return f"In-scope records must have Create Date between {start} and {end}, inclusive."
    if end:
        return f"In-scope records must have Create Date on or before {end}."
    if start:
        return f"In-scope records must have Create Date on or after {start}."
    return ""


def is_include(row: dict[str, str], prefix: str = "") -> bool:
    return row.get(f"{prefix}llm_suggest", row.get("llm_suggest", "")) in {
        "strong_candidate",
        "possible_candidate",
    }


def compute_metrics(rows: list[dict[str, str]], gt_pmids: set[str], prefix: str = "") -> dict[str, float | int]:
    valid = [row for row in rows if row.get(f"{prefix}llm_suggest", row.get("llm_suggest", "")) != "error"]
    included = [row for row in valid if is_include(row, prefix=prefix)]
    tp = sum(1 for row in included if (row.get("PMID") or "").strip() in gt_pmids)
    fp = len(included) - tp
    gt_in_sample = sum(1 for row in valid if (row.get("PMID") or "").strip() in gt_pmids)
    fn = gt_in_sample - tp
    precision = tp / len(included) if included else 0.0
    recall = tp / gt_in_sample if gt_in_sample else 0.0
    f1 = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
    return {
        "n": len(valid),
        "gt": gt_in_sample,
        "included": len(included),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "recall": recall,
        "precision": precision,
        "f1": f1,
        "nns": 1 / precision if precision else 0.0,
    }


def build_sample(project: Project, rng: random.Random) -> tuple[list[dict[str, str]], set[str]]:
    raw_rows = {(row.get("PMID") or "").strip(): row for row in read_csv(raw_path(project))}
    baseline_rows = read_csv(baseline_path(project))
    gt_pmids = load_gt_pmids(project)

    baseline_by_pmid = {(row.get("PMID") or "").strip(): row for row in baseline_rows}
    previous_fp = [
        row for row in baseline_rows
        if is_include(row) and (row.get("PMID") or "").strip() not in gt_pmids
    ]
    previous_tn = [
        row for row in baseline_rows
        if not is_include(row) and (row.get("PMID") or "").strip() not in gt_pmids
    ]
    previous_fp.sort(key=lambda row: (
        row.get("llm_tier") != "P",
        -(int(float(row.get("parameter_score") or 0)) if (row.get("parameter_score") or "0").replace(".", "", 1).isdigit() else 0),
        row.get("PMID") or "",
    ))
    rng.shuffle(previous_tn)

    selected_pmids: list[str] = []
    selected_pmids.extend(sorted(pmid for pmid in gt_pmids if pmid in raw_rows))
    selected_pmids.extend((row.get("PMID") or "").strip() for row in previous_fp[:FP_PER_PROJECT])
    selected_pmids.extend((row.get("PMID") or "").strip() for row in previous_tn[:TN_PER_PROJECT])

    seen: set[str] = set()
    sample: list[dict[str, str]] = []
    for pmid in selected_pmids:
        if not pmid or pmid in seen or pmid not in raw_rows:
            continue
        seen.add(pmid)
        row = dict(raw_rows[pmid])
        old = baseline_by_pmid.get(pmid, {})
        for key in (
            "llm_suggest",
            "llm_tier",
            "disease_score",
            "evidence_score",
            "parameter_score",
            "overall_justification",
        ):
            row[f"baseline_{key}"] = old.get(key, "")
        row["ground_truth_include"] = "1" if pmid in gt_pmids else "0"
        row["sample_source"] = (
            "gt" if pmid in gt_pmids else
            "previous_fp" if is_include(old) else
            "previous_tn"
        )
        sample.append(row)
    return sample, gt_pmids


async def run_project(llm, project: Project, rng: random.Random) -> dict[str, object]:
    rows, gt_pmids = build_sample(project, rng)
    print(
        f"\n[{project.disease}/{project.topic}/p{project.project}] "
        f"sample={len(rows)} gt={sum(r['ground_truth_include'] == '1' for r in rows)}"
    )

    scoped_question = project.research_question
    note = scope_note(project)
    if note:
        scoped_question = f"{scoped_question} Scope note: {note}"

    config = {
        "research_question": scoped_question,
        "disease_focus": project.disease_focus,
        "disease_exclude": "other diseases or pathogens not matching the target disease",
        "parameter_focus": project.parameter_focus,
        "parameter_exclude": "studies that do not report, estimate, or directly measure the target parameter",
        "parameter_scoring_note": project.parameter_note,
    }

    await screen_papers_batch_async(
        rows,
        research_question=scoped_question,
        llm_model=llm,
        batch_size=BATCH_SIZE,
        batch_concurrency=CONCURRENCY,
        batch_mode=BATCH_MODE,
        screening_stage="title_abstract",
        content_label="Abstract",
        content_key="Abstract",
        content_fallback="(NO ABSTRACT AVAILABLE - cannot assess evidence or parameter from title alone. Score conservatively.)",
        strategy="5d",
        screening_config=config,
        prefer_llm_tier=True,
    )

    base = compute_metrics(rows, gt_pmids, prefix="baseline_")
    tuned = compute_metrics(rows, gt_pmids)
    previous_fp_rows = [row for row in rows if row["sample_source"] == "previous_fp"]
    demoted_fp = sum(1 for row in previous_fp_rows if not is_include(row))
    baseline_fn_rows = [
        row for row in rows
        if row["ground_truth_include"] == "1" and not is_include(row, prefix="baseline_")
    ]
    rescued_fn = sum(1 for row in baseline_fn_rows if is_include(row))

    out_file = OUT / f"{project.disease}_{project.topic}_p{project.project}_screened.csv"
    write_csv(out_file, rows)

    summary = {
        "label": f"{project.disease}/{project.topic}/p{project.project}",
        "sample_n": len(rows),
        "baseline": base,
        "tuned": tuned,
        "previous_fp_sampled": len(previous_fp_rows),
        "previous_fp_demoted": demoted_fp,
        "baseline_fn_sampled": len(baseline_fn_rows),
        "baseline_fn_rescued": rescued_fn,
        "output": str(out_file.relative_to(REPO)),
    }
    print(
        "  baseline "
        f"R={base['recall']:.3f} P={base['precision']:.3f} F1={base['f1']:.3f} "
        f"incl={base['included']} FP={base['fp']}"
    )
    print(
        "  tuned   "
        f"R={tuned['recall']:.3f} P={tuned['precision']:.3f} F1={tuned['f1']:.3f} "
        f"incl={tuned['included']} FP={tuned['fp']} "
        f"demoted_prev_fp={demoted_fp}/{len(previous_fp_rows)} rescued_fn={rescued_fn}/{len(baseline_fn_rows)}"
    )
    return summary


def pooled_summary(project_summaries: list[dict[str, object]]) -> dict[str, object]:
    def add_counts(section: str) -> dict[str, float | int]:
        tp = sum(int(item[section]["tp"]) for item in project_summaries)  # type: ignore[index]
        fp = sum(int(item[section]["fp"]) for item in project_summaries)  # type: ignore[index]
        fn = sum(int(item[section]["fn"]) for item in project_summaries)  # type: ignore[index]
        gt = sum(int(item[section]["gt"]) for item in project_summaries)  # type: ignore[index]
        included = sum(int(item[section]["included"]) for item in project_summaries)  # type: ignore[index]
        recall = tp / gt if gt else 0.0
        precision = tp / included if included else 0.0
        f1 = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
        return {
            "gt": gt,
            "included": included,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "recall": recall,
            "precision": precision,
            "f1": f1,
            "nns": 1 / precision if precision else 0.0,
        }

    return {
        "baseline": add_counts("baseline"),
        "tuned": add_counts("tuned"),
        "previous_fp_sampled": sum(int(item["previous_fp_sampled"]) for item in project_summaries),
        "previous_fp_demoted": sum(int(item["previous_fp_demoted"]) for item in project_summaries),
        "baseline_fn_sampled": sum(int(item["baseline_fn_sampled"]) for item in project_summaries),
        "baseline_fn_rescued": sum(int(item["baseline_fn_rescued"]) for item in project_summaries),
    }


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(RANDOM_SEED)
    llm = init_llm_model(model_override=MODEL, provider_override=PROVIDER)
    projects = PROJECTS
    if PROJECT_FILTER:
        projects = [
            project for project in projects
            if (
                f"{project.disease}/{project.topic}/p{project.project}" in PROJECT_FILTER
                or f"{project.disease}_{project.topic}_p{project.project}" in PROJECT_FILTER
            )
        ]
    if PROJECT_LIMIT:
        projects = projects[:PROJECT_LIMIT]
    if not projects:
        raise SystemExit(
            "No projects matched QWEN36_TEST_PROJECTS; refusing to overwrite summary."
        )
    print(
        f"Running {len(projects)} project(s); batch={BATCH_SIZE}, "
        f"concurrency={CONCURRENCY}, mode={BATCH_MODE}, "
        f"fp/project={FP_PER_PROJECT}, tn/project={TN_PER_PROJECT}",
        flush=True,
    )
    summaries = []
    for project in projects:
        summaries.append(await run_project(llm, project, rng))

    pooled = pooled_summary(summaries)
    report = {
        "model": MODEL,
        "provider": PROVIDER,
        "baseline_experiment": EXP,
        "sample_design": {
            "all_gt": True,
            "fp_per_project": FP_PER_PROJECT,
            "tn_per_project": TN_PER_PROJECT,
            "random_seed": RANDOM_SEED,
            "note": "Enriched smoke-test sample; precision/F1 are not full-pool estimates.",
        },
        "projects": summaries,
        "pooled": pooled,
    }
    (OUT / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n=== POOLED ENRICHED SAMPLE ===")
    for name in ("baseline", "tuned"):
        metrics = pooled[name]
        print(
            f"{name:<8} R={metrics['recall']:.3f} P={metrics['precision']:.3f} "
            f"F1={metrics['f1']:.3f} NNS={metrics['nns']:.2f} "
            f"TP/FP/FN={metrics['tp']}/{metrics['fp']}/{metrics['fn']} "
            f"included={metrics['included']}"
        )
    print(
        "demoted previous FP: "
        f"{pooled['previous_fp_demoted']}/{pooled['previous_fp_sampled']}; "
        "rescued baseline FN: "
        f"{pooled['baseline_fn_rescued']}/{pooled['baseline_fn_sampled']}"
    )
    print(f"wrote {OUT.relative_to(REPO)}/summary.json")


if __name__ == "__main__":
    asyncio.run(main())
