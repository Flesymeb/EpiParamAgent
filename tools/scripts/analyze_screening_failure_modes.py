#!/usr/bin/env python3
"""Classify screening FP/FN failure modes from per-PMID screened CSVs.

The classifier is intentionally transparent and reproducible. It uses model
scores, the model's own justification text, titles/abstracts, and simple
topic-specific lexical signals to produce primary error categories plus flags.
It is designed for paper-facing error analysis rather than adjudicating whether
the systematic-review ground truth is perfect.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


REPO = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_SLUG = "model_5d_screening_multi_adaptive_highc_llmtier_20260507_boyue_qwen3-6-plus"
DEFAULT_MODEL_DISPLAY = "Qwen3.6 Plus"
PREDICTED_INCLUDE = {"strong_candidate", "possible_candidate"}
GT_MARKERS = {"✓", "1", "true", "yes", "y"}

TOPIC_LABELS = {
    "fatality": "Fatality",
    "reproduction_number": "Reproduction number",
    "serial_interval": "Serial interval",
}

NON_ORIGINAL_PATTERNS = [
    r"\breview\b",
    r"\bsystematic review\b",
    r"\bmeta-analysis\b",
    r"\bmeta analysis\b",
    r"\beditorial\b",
    r"\bcommentary\b",
    r"\bcomment\b",
    r"\bletter\b",
    r"\bperspective\b",
    r"\bprotocol\b",
    r"\bguideline\b",
    r"\bconsensus\b",
    r"\bnews\b",
]

ORIGINAL_EVIDENCE_PATTERNS = [
    r"\bcohort\b",
    r"\bcase[- ]series\b",
    r"\bcase report\b",
    r"\bpatients?\b",
    r"\bcases?\b",
    r"\bsurveillance\b",
    r"\bcontact tracing\b",
    r"\boutbreak\b",
    r"\bdata\b",
    r"\bestimat(?:e|ed|ion)\b",
    r"\bmodel(?:led|ing|ling)?\b",
    r"\bobserv(?:e|ed|ational)\b",
]

TOPIC_KEYWORDS = {
    "fatality": [
        "fatality",
        "case fatality",
        "cfr",
        "ifr",
        "mortality",
        "death",
        "deaths",
        "died",
        "survival",
        "outcome",
    ],
    "reproduction_number": [
        "reproduction number",
        "reproductive number",
        "r0",
        "r(t)",
        "rt",
        "r value",
        "transmissibility",
        "transmission rate",
        "growth rate",
        "secondary attack",
    ],
    "serial_interval": [
        "serial interval",
        "generation interval",
        "generation time",
        "incubation period",
        "time from",
        "time interval",
        "onset-to-onset",
        "onset to onset",
    ],
}

OTHER_TOPIC_KEYWORDS = {
    "fatality": TOPIC_KEYWORDS["reproduction_number"] + TOPIC_KEYWORDS["serial_interval"],
    "reproduction_number": TOPIC_KEYWORDS["fatality"] + TOPIC_KEYWORDS["serial_interval"],
    "serial_interval": TOPIC_KEYWORDS["fatality"] + TOPIC_KEYWORDS["reproduction_number"],
}


@dataclass(frozen=True)
class FailureCase:
    model_slug: str
    model_display: str
    disease: str
    topic: str
    profile: str
    project: str
    pmid: str
    error_kind: str
    primary_type: str
    flags: tuple[str, ...]
    prediction: str
    llm_tier: str
    scores: dict[str, int]
    title: str
    year: str
    create_date: str
    journal: str
    abstract_len: int
    overall_justification: str
    parameter_justification: str
    evidence_justification: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(REPO))
    parser.add_argument("--model-slug", default=DEFAULT_MODEL_SLUG)
    parser.add_argument("--model-display", default=DEFAULT_MODEL_DISPLAY)
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--max-examples", type=int, default=5)
    return parser.parse_args()


def safe_int(value: str | None) -> int:
    try:
        return int(float(str(value or "").strip()))
    except ValueError:
        return -1


def norm(text: str | None) -> str:
    return str(text or "").strip()


def low(text: str | None) -> str:
    return norm(text).lower()


def has_any(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def keyword_hit(text: str, keywords: Iterable[str]) -> bool:
    hay = text.lower()
    return any(keyword.lower() in hay for keyword in keywords)


def text_bundle(row: dict[str, str]) -> str:
    return " ".join(
        [
            row.get("Title", ""),
            row.get("Abstract", ""),
            row.get("Keywords", ""),
            row.get("Journal/Book", ""),
            row.get("overall_justification", ""),
            row.get("parameter_justification", ""),
            row.get("evidence_justification", ""),
        ]
    )


def publication_signal_text(row: dict[str, str]) -> str:
    """Text used for publication-type/style signals.

    Avoid scanning generic overall justification text for bare words such as
    "review", because phrases like "the review's target parameter" describe the
    meta-analysis task, not the candidate paper.
    """
    source_text = " ".join(
        [
            row.get("Title", ""),
            row.get("Abstract", ""),
            row.get("Keywords", ""),
            row.get("Journal/Book", ""),
        ]
    )
    justification_text = " ".join(
        [
            row.get("overall_justification", ""),
            row.get("evidence_justification", ""),
        ]
    )
    explicit_justification_signal = " ".join(
        match.group(0)
        for match in re.finditer(
            r"\b(?:is|appears to be|seems to be|likely)\s+(?:a\s+)?(?:systematic\s+review|narrative\s+review|review|commentary|editorial|letter|perspective|protocol)\b",
            justification_text,
            flags=re.IGNORECASE,
        )
    )
    return f"{source_text} {explicit_justification_signal}"


def parse_path(path: Path) -> tuple[str, str, str, str]:
    parts = path.parts
    idx = parts.index("screening")
    disease = parts[idx + 1]
    topic = parts[idx + 2]
    profile = parts[idx + 3].upper()
    match = re.search(r"project_(\d+)_screened\.csv$", path.name)
    project = match.group(1) if match else re.sub(r"\D", "", profile)
    return disease, topic, profile, project


def is_gt(row: dict[str, str]) -> bool:
    return low(row.get("is_ground_truth")) in GT_MARKERS or norm(row.get("is_ground_truth")) == "✓"


def load_gt_pmids(repo: Path, disease: str, topic: str, profile: str, project: str) -> set[str]:
    candidates = [
        repo / "dataset" / disease / "screening" / topic / profile.lower() / "ground_truth.csv",
        repo / "dataset" / disease / "screening" / topic / profile / "ground_truth.csv",
        repo / "dataset" / disease / "screening" / topic / profile.lower() / f"project_{project}_groundtruth.csv",
    ]
    for path in candidates:
        if not path.exists():
            continue
        pmids: set[str] = set()
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                pmid = norm(row.get("PMID")) or norm(row.get("gt_pmid"))
                if pmid:
                    pmids.add(pmid)
        if pmids:
            return pmids
    return set()


def row_is_gt(row: dict[str, str], gt_pmids: set[str]) -> bool:
    if "is_ground_truth" in row and norm(row.get("is_ground_truth")):
        return is_gt(row)
    pmid = norm(row.get("PMID"))
    return pmid in gt_pmids


def is_predicted_include(row: dict[str, str]) -> bool:
    return norm(row.get("llm_suggest")) in PREDICTED_INCLUDE


def score_dict(row: dict[str, str]) -> dict[str, int]:
    return {
        "disease": safe_int(row.get("disease_score")),
        "population": safe_int(row.get("population_score")),
        "location": safe_int(row.get("location_score")),
        "evidence": safe_int(row.get("evidence_score")),
        "parameter": safe_int(row.get("parameter_score")),
        "overall": safe_int(row.get("overall_score")),
    }


def classify_fp(row: dict[str, str], topic: str, scores: dict[str, int]) -> tuple[str, tuple[str, ...]]:
    text = low(text_bundle(row))
    pub_text = low(publication_signal_text(row))
    abstract = norm(row.get("Abstract"))
    prediction = norm(row.get("llm_suggest"))
    has_5d_scores = scores["disease"] >= 0 and scores["evidence"] >= 0 and scores["parameter"] >= 0
    flags: list[str] = []

    if prediction == "possible_candidate":
        flags.append("possible_bucket")
    if has_5d_scores and scores["parameter"] <= 2:
        flags.append("weak_parameter_score")
    if has_5d_scores and scores["evidence"] <= 2:
        flags.append("weak_evidence_score")
    if has_5d_scores and scores["disease"] <= 2:
        flags.append("weak_disease_score")
    if len(abstract) < 160:
        flags.append("sparse_or_no_abstract")
    if has_any(pub_text, NON_ORIGINAL_PATTERNS):
        flags.append("review_or_commentary_signal")
    if keyword_hit(text, OTHER_TOPIC_KEYWORDS.get(topic, [])):
        flags.append("other_parameter_signal")
    if keyword_hit(text, TOPIC_KEYWORDS.get(topic, [])):
        flags.append("target_parameter_signal")
    if has_any(text, ORIGINAL_EVIDENCE_PATTERNS):
        flags.append("original_or_data_signal")
    if has_5d_scores and scores["disease"] >= 4 and scores["evidence"] >= 4 and scores["parameter"] >= 4:
        flags.append("high_5d_scores")

    if "review_or_commentary_signal" in flags and "original_or_data_signal" not in flags:
        primary = "non_original_or_secondary_literature"
    elif "sparse_or_no_abstract" in flags:
        primary = "sparse_metadata_over_inclusion"
    elif "other_parameter_signal" in flags and "target_parameter_signal" not in flags:
        primary = "wrong_epidemiological_parameter"
    elif has_5d_scores and scores["parameter"] <= 2:
        primary = "weak_or_indirect_target_parameter"
    elif has_5d_scores and scores["evidence"] <= 2:
        primary = "weak_original_evidence"
    elif prediction == "possible_candidate":
        primary = "borderline_possible_over_inclusion"
    elif "review_or_commentary_signal" in flags:
        primary = "review_signal_overridden_by_model"
    elif has_5d_scores and scores["disease"] >= 4 and scores["evidence"] >= 4 and scores["parameter"] >= 4:
        primary = "plausibly_relevant_not_in_sr_gt"
    elif not has_5d_scores and "target_parameter_signal" not in flags:
        primary = "weak_or_indirect_target_parameter"
    elif not has_5d_scores and "target_parameter_signal" in flags and "original_or_data_signal" in flags:
        primary = "plausibly_relevant_not_in_sr_gt"
    else:
        primary = "broad_topic_over_inclusion"

    return primary, tuple(sorted(set(flags)))


def classify_fn(row: dict[str, str], topic: str, scores: dict[str, int]) -> tuple[str, tuple[str, ...]]:
    text = low(text_bundle(row))
    pub_text = low(publication_signal_text(row))
    abstract = norm(row.get("Abstract"))
    has_5d_scores = scores["disease"] >= 0 and scores["evidence"] >= 0 and scores["parameter"] >= 0
    flags: list[str] = []

    if len(abstract) < 160:
        flags.append("sparse_or_no_abstract")
    if has_any(pub_text, NON_ORIGINAL_PATTERNS):
        flags.append("review_or_commentary_signal")
    if keyword_hit(text, TOPIC_KEYWORDS.get(topic, [])):
        flags.append("target_parameter_signal")
    if keyword_hit(text, OTHER_TOPIC_KEYWORDS.get(topic, [])):
        flags.append("other_parameter_signal")
    if has_5d_scores and scores["parameter"] <= 2:
        flags.append("weak_parameter_score")
    if has_5d_scores and scores["evidence"] <= 2:
        flags.append("weak_evidence_score")
    if has_5d_scores and scores["disease"] <= 2:
        flags.append("weak_disease_score")
    if has_5d_scores and scores["population"] <= 2:
        flags.append("weak_population_score")
    if has_5d_scores and scores["location"] <= 2:
        flags.append("weak_location_score")
    if has_5d_scores and scores["disease"] >= 3 and scores["evidence"] >= 3 and scores["parameter"] >= 3:
        flags.append("scores_support_inclusion")

    if "review_or_commentary_signal" in flags:
        primary = "possible_gt_non_original_or_review"
    elif "sparse_or_no_abstract" in flags:
        primary = "insufficient_title_abstract_evidence"
    elif has_5d_scores and scores["disease"] <= 2:
        primary = "disease_scope_underestimated"
    elif has_5d_scores and scores["parameter"] <= 2:
        primary = "target_parameter_not_detected"
    elif has_5d_scores and scores["evidence"] <= 2:
        primary = "original_evidence_underestimated"
    elif has_5d_scores and (scores["population"] <= 2 or scores["location"] <= 2):
        primary = "population_or_setting_scope_underestimated"
    elif "scores_support_inclusion" in flags:
        primary = "llm_tier_too_conservative"
    elif not has_5d_scores and "target_parameter_signal" not in flags:
        primary = "target_parameter_not_detected"
    elif not has_5d_scores:
        primary = "llm_tier_too_conservative"
    else:
        primary = "mixed_borderline_under_inclusion"

    return primary, tuple(sorted(set(flags)))


def collect_cases(repo: Path, model_slug: str, model_display: str) -> tuple[list[FailureCase], Counter]:
    root = repo / "evaluation" / "screening"
    files = sorted(root.glob(f"**/experiments/{model_slug}/project_*_screened.csv"))
    if not files:
        raise FileNotFoundError(f"No screened CSVs found for model slug: {model_slug}")

    cases: list[FailureCase] = []
    confusion: Counter = Counter()
    for path in files:
        disease, topic, profile, project = parse_path(path)
        gt_pmids = load_gt_pmids(repo, disease, topic, profile, project)
        with path.open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                if norm(row.get("llm_suggest")) == "error":
                    confusion[(disease, topic, profile, "ERROR")] += 1
                    continue
                pred = is_predicted_include(row)
                gt = row_is_gt(row, gt_pmids)
                if pred and gt:
                    confusion[(disease, topic, profile, "TP")] += 1
                    continue
                if pred and not gt:
                    error_kind = "FP"
                elif not pred and gt:
                    error_kind = "FN"
                else:
                    confusion[(disease, topic, profile, "TN")] += 1
                    continue
                confusion[(disease, topic, profile, error_kind)] += 1

                scores = score_dict(row)
                if error_kind == "FP":
                    primary, flags = classify_fp(row, topic, scores)
                else:
                    primary, flags = classify_fn(row, topic, scores)

                cases.append(
                    FailureCase(
                        model_slug=model_slug,
                        model_display=model_display,
                        disease=disease,
                        topic=topic,
                        profile=profile,
                        project=project,
                        pmid=norm(row.get("PMID")),
                        error_kind=error_kind,
                        primary_type=primary,
                        flags=flags,
                        prediction=norm(row.get("llm_suggest")),
                        llm_tier=norm(row.get("llm_tier")),
                        scores=scores,
                        title=norm(row.get("Title")),
                        year=norm(row.get("Publication Year")),
                        create_date=norm(row.get("Create Date")),
                        journal=norm(row.get("Journal/Book")),
                        abstract_len=len(norm(row.get("Abstract"))),
                        overall_justification=norm(row.get("overall_justification")),
                        parameter_justification=norm(row.get("parameter_justification")),
                        evidence_justification=norm(row.get("evidence_justification")),
                    )
                )
    return cases, confusion


def write_cases(cases: list[FailureCase], out: Path) -> None:
    fields = [
        "model_display",
        "disease",
        "topic",
        "profile",
        "project",
        "pmid",
        "error_kind",
        "primary_type",
        "flags",
        "prediction",
        "llm_tier",
        "disease_score",
        "population_score",
        "location_score",
        "evidence_score",
        "parameter_score",
        "overall_score",
        "title",
        "year",
        "create_date",
        "journal",
        "abstract_len",
        "overall_justification",
        "parameter_justification",
        "evidence_justification",
    ]
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for case in cases:
            writer.writerow(
                {
                    "model_display": case.model_display,
                    "disease": case.disease,
                    "topic": case.topic,
                    "profile": case.profile,
                    "project": case.project,
                    "pmid": case.pmid,
                    "error_kind": case.error_kind,
                    "primary_type": case.primary_type,
                    "flags": ";".join(case.flags),
                    "prediction": case.prediction,
                    "llm_tier": case.llm_tier,
                    "disease_score": case.scores["disease"],
                    "population_score": case.scores["population"],
                    "location_score": case.scores["location"],
                    "evidence_score": case.scores["evidence"],
                    "parameter_score": case.scores["parameter"],
                    "overall_score": case.scores["overall"],
                    "title": case.title,
                    "year": case.year,
                    "create_date": case.create_date,
                    "journal": case.journal,
                    "abstract_len": case.abstract_len,
                    "overall_justification": case.overall_justification,
                    "parameter_justification": case.parameter_justification,
                    "evidence_justification": case.evidence_justification,
                }
            )


def pct(count: int, total: int) -> float:
    return count / total if total else 0.0


def aggregate_cases(cases: list[FailureCase]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    scopes = []
    for disease in sorted({case.disease for case in cases}):
        scopes.append((disease, "all", [case for case in cases if case.disease == disease]))
        for topic in sorted({case.topic for case in cases if case.disease == disease}):
            subset = [case for case in cases if case.disease == disease and case.topic == topic]
            scopes.append((disease, topic, subset))
    scopes.append(("overall", "all", cases))

    for disease, topic, subset in scopes:
        for kind in ("FP", "FN"):
            kind_cases = [case for case in subset if case.error_kind == kind]
            denom = len(kind_cases)
            counts = Counter(case.primary_type for case in kind_cases)
            for primary_type, count in counts.most_common():
                rows.append(
                    {
                        "disease": disease,
                        "topic": topic,
                        "error_kind": kind,
                        "primary_type": primary_type,
                        "count": str(count),
                        "denominator": str(denom),
                        "percent": f"{pct(count, denom):.6f}",
                    }
                )
    return rows


def write_aggregate(rows: list[dict[str, str]], out: Path) -> None:
    fields = ["disease", "topic", "error_kind", "primary_type", "count", "denominator", "percent"]
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def confusion_by_scope(confusion: Counter) -> dict[tuple[str, str], Counter]:
    agg: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for (disease, topic, _profile, label), count in confusion.items():
        agg[(disease, topic)][label] += count
        agg[(disease, "all")][label] += count
        agg[("overall", "all")][label] += count
    return agg


def metric_line(counter: Counter) -> str:
    tp, fp, fn, tn = (counter["TP"], counter["FP"], counter["FN"], counter["TN"])
    recall = pct(tp, tp + fn)
    precision = pct(tp, tp + fp)
    f1 = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
    fdr = pct(fp, tp + fp)
    nns = (tp + fp) / tp if tp else float("inf")
    return (
        f"{tp}/{fp}/{fn}/{tn}",
        f"{recall:.1%}",
        f"{precision:.1%}",
        f"{f1:.1%}",
        f"{fdr:.1%}",
        f"{nns:.2f}" if nns != float("inf") else "inf",
    )


def examples_for(cases: list[FailureCase], disease: str, topic: str, kind: str, primary_type: str, limit: int) -> list[FailureCase]:
    return [
        case
        for case in cases
        if case.disease == disease and case.topic == topic and case.error_kind == kind and case.primary_type == primary_type
    ][:limit]


def write_markdown(
    *,
    cases: list[FailureCase],
    aggregate_rows: list[dict[str, str]],
    confusion: Counter,
    out: Path,
    model_display: str,
    model_slug: str,
    max_examples: int,
) -> None:
    agg = confusion_by_scope(confusion)
    lines: list[str] = []
    lines.append(f"# Screening Failure Mode Analysis — {model_display}")
    lines.append("")
    lines.append(f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append(f"Model slug: `{model_slug}`")
    lines.append("")
    lines.append("## Metric Context")
    lines.append("")
    lines.append("| Scope | TP/FP/FN/TN | Recall | Precision | F1 | FDR | NNS |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for key in sorted(agg):
        disease, topic = key
        if disease == "overall":
            label = "Overall"
        elif topic == "all":
            label = disease
        else:
            label = f"{disease} / {TOPIC_LABELS.get(topic, topic)}"
        counts, recall, precision, f1, fdr, nns = metric_line(agg[key])
        lines.append(f"| {label} | {counts} | {recall} | {precision} | {f1} | {fdr} | {nns} |")

    lines.append("")
    lines.append("## Error-Type Summary")
    lines.append("")
    lines.append("Percentages are within the FP or FN denominator for that disease/topic scope.")
    lines.append("")
    grouped: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in aggregate_rows:
        grouped[(row["disease"], row["topic"], row["error_kind"])].append(row)

    for disease in ["covid19", "mpox"]:
        for topic in ["fatality", "reproduction_number", "serial_interval"]:
            for kind in ["FP", "FN"]:
                rows = grouped.get((disease, topic, kind), [])
                if not rows:
                    continue
                lines.append(f"### {disease} / {TOPIC_LABELS.get(topic, topic)} — {kind}")
                lines.append("")
                lines.append("| Type | Count | Share |")
                lines.append("| --- | ---: | ---: |")
                for row in rows:
                    lines.append(
                        f"| `{row['primary_type']}` | {row['count']}/{row['denominator']} | {float(row['percent']):.1%} |"
                    )
                top = rows[0]
                exs = examples_for(cases, disease, topic, kind, top["primary_type"], max_examples)
                if exs:
                    lines.append("")
                    lines.append(f"Examples for top type `{top['primary_type']}`:")
                    for ex in exs:
                        score_text = (
                            f"D={ex.scores['disease']}, E={ex.scores['evidence']}, "
                            f"Par={ex.scores['parameter']}, tier={ex.llm_tier}"
                        )
                        lines.append(f"- PMID {ex.pmid}: {ex.title} ({score_text})")
                lines.append("")

    lines.append("## Category Definitions")
    lines.append("")
    definitions = {
        "non_original_or_secondary_literature": "FP: review/commentary/editorial-like paper admitted as candidate.",
        "sparse_metadata_over_inclusion": "FP: little or no abstract, yet model still kept it.",
        "wrong_epidemiological_parameter": "FP: evidence points to another parameter family rather than the target one.",
        "weak_or_indirect_target_parameter": "FP: target parameter score was weak or indirect but still admitted.",
        "weak_original_evidence": "FP: original evidence score was weak but still admitted.",
        "borderline_possible_over_inclusion": "FP: possible-candidate bucket admitted a broad or ambiguous paper.",
        "review_signal_overridden_by_model": "FP: review/commentary signal existed but was outweighed by model.",
        "plausibly_relevant_not_in_sr_gt": "FP: high disease/evidence/parameter scores; likely broad relevant paper absent from SR GT or out of SR scope.",
        "broad_topic_over_inclusion": "FP: broad disease/topic relevance without enough extractable target evidence.",
        "possible_gt_non_original_or_review": "FN: GT paper itself looks review-like or secondary from metadata; needs manual GT audit.",
        "insufficient_title_abstract_evidence": "FN: title/abstract too sparse for the model to confirm relevance.",
        "disease_scope_underestimated": "FN: disease dimension was scored too low.",
        "target_parameter_not_detected": "FN: target parameter signal was missed or scored weakly.",
        "original_evidence_underestimated": "FN: paper appears relevant but evidence dimension was scored too low.",
        "population_or_setting_scope_underestimated": "FN: population/location setting lowered the tier.",
        "llm_tier_too_conservative": "FN: scores support inclusion but LLM tier excluded it.",
        "mixed_borderline_under_inclusion": "FN: multiple moderate weaknesses led to exclusion.",
    }
    for key, value in definitions.items():
        lines.append(f"- `{key}`: {value}")
    lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    repo = Path(args.project_root).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else (
        repo / "evaluation" / "results" / f"failure_modes_{args.model_slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    cases, confusion = collect_cases(repo, args.model_slug, args.model_display)
    aggregate_rows = aggregate_cases(cases)
    write_cases(cases, out_dir / "failure_cases_labeled.csv")
    write_aggregate(aggregate_rows, out_dir / "failure_type_summary.csv")
    write_markdown(
        cases=cases,
        aggregate_rows=aggregate_rows,
        confusion=confusion,
        out=out_dir / "FAILURE_MODE_SUMMARY.md",
        model_display=args.model_display,
        model_slug=args.model_slug,
        max_examples=args.max_examples,
    )
    print(f"Cases: {len(cases)}")
    print(f"Output: {out_dir}")


if __name__ == "__main__":
    main()
