#!/usr/bin/env python3
"""Evaluate reproducible keyword-rule screening baselines on frozen profiles.

The rules are intentionally simple: a record is selected when at least one
disease term and at least one parameter term occur in the configured text
fields. This script is used for non-LLM screening baselines in the paper.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from metaagent.screening.profile_registry import ScreeningProfile, load_profile_registry


OUT_DIR = PROJECT_ROOT / "docs" / "paper" / "screening" / "tables"
DEFAULT_OUTPUT = OUT_DIR / "rule_based_baselines_20260617_title_abstract.csv"
DEFAULT_SUMMARY = OUT_DIR / "rule_based_baselines_20260617_title_abstract.md"
DEFAULT_ARCHIVED_CSV = OUT_DIR / "rule_based_baselines_20260508_0253.csv"

FIELD_SETS: dict[str, tuple[str, ...]] = {
    "full_metadata": ("Title", "Abstract", "Keywords", "Citation", "Journal/Book"),
    "title_abstract": ("Title", "Abstract"),
    "title_keywords_mesh": ("Title", "Keywords"),
}

REVIEW_LIKE_TERMS = (
    "review",
    "systematic review",
    "scoping review",
    "rapid review",
    "meta-analysis",
    "meta analysis",
    "protocol",
    "editorial",
    "comment",
    "letter",
    "correspondence",
    "perspective",
    "opinion",
    "guideline",
)

COVID19_DISEASE_TERMS = (
    "covid-19",
    "covid 19",
    "covid19",
    "covid-2019",
    "coronavirus disease 2019",
    "sars-cov-2",
    "sars cov 2",
    "sars-cov2",
    "2019-ncov",
    "2019 ncov",
    "2019ncov",
    "n2019-cov",
    "novel coronavirus",
    "severe acute respiratory syndrome coronavirus 2",
    "coronavirus",
    "corona virus",
    "wuhan coronavirus",
)

MPOX_DISEASE_TERMS = (
    "mpox",
    "monkeypox",
    "monkey pox",
    "mpxv",
    "monkeypox virus",
)

TOPIC_PARAMETER_TERMS: dict[str, tuple[str, ...]] = {
    "fatality": (
        "mortality",
        "fatality",
        "case fatality",
        "case fatality rate",
        "case fatality ratio",
        "fatality rate",
        "infection fatality",
        "infection fatality rate",
        "infection fatality ratio",
        "mortality rate",
        "death rate",
        "death",
        "deaths",
        "died",
        "fatal outcome",
        "fatal outcomes",
        "no deaths",
        "cfr",
        "ifr",
    ),
    "reproduction_number": (
        "basic reproduction number",
        "basic reproductive number",
        "reproduction number",
        "reproductive number",
        "effective reproduction number",
        "instantaneous reproduction number",
        "secondary infections per case",
        "r naught",
        "r0",
        "rt",
        "re",
    ),
    "serial_interval": (
        "serial interval",
        "serial intervals",
        "serial distribution",
        "generation interval",
        "generation intervals",
        "generation time",
        "generation times",
        "generation time distribution",
        "incubation period",
        "latent period",
        "reproduction number",
        "r0",
    ),
}

PROFILE_PARAMETER_TERMS: dict[str, tuple[str, ...]] = {
    "P4": (
        "icu admission",
        "intensive care",
        "intensive care unit",
        "invasive mechanical ventilation",
        "mechanical ventilation",
        "ventilation",
        "clinical characteristic",
        "clinical characteristics",
    ),
    "P5": (
        "seroprevalence",
        "sero-prevalence",
        "seropositivity",
        "serological survey",
        "serosurvey",
        "seroepidemiology",
        "seroepidemiological",
        "anti-sars-cov-2 antibody",
        "anti-sars-cov-2 antibodies",
        "antibody prevalence",
        "antibody survey",
    ),
    "MP10": (
        "reproduction number",
        "reproductive number",
        "r0",
    ),
}

# Best-effort recovery of the historical 20260508 keyword rule. The archived
# CSV did not preserve the generator or exact term dictionary. These overrides
# are derived from profile-level deltas against that archive and are deliberately
# kept separate from the cleaner current rules.
LEGACY_PROFILE_PARAMETER_TERMS: dict[str, tuple[str, ...]] = {
    # The old P5 result behaves like a broad antibody screen, not the cleaner
    # seroprevalence/antibody-prevalence rule used in the reproducible rerun.
    "P5": ("antibody",),
    # Old mpox fatality rows are much broader than direct fatality terms; adding
    # "case" approximates MP7/MP8/MP12 without changing MP4.
    "MP7": TOPIC_PARAMETER_TERMS["fatality"] + ("case",),
    "MP8": TOPIC_PARAMETER_TERMS["fatality"] + ("case",),
    "MP12": TOPIC_PARAMETER_TERMS["fatality"] + ("case",),
}

LEGACY_TOPIC_PARAMETER_TERMS: dict[str, tuple[str, ...]] = {
    # Historical serial-interval counts are closer when broad reproduction-number
    # rescue terms are not included.
    "serial_interval": (
        "serial interval",
        "serial intervals",
        "serial distribution",
        "generation interval",
        "generation intervals",
        "generation time",
        "generation times",
        "generation time distribution",
        "incubation period",
        "latent period",
    ),
}

LEGACY_PROFILE_EXCLUDE_TERMS: dict[str, tuple[str, ...]] = {
    # Minimal exclusion that brings P5 full-metadata counts close to the archive.
    "P5": ("diagnostic", "blood donor"),
}


@dataclass(frozen=True)
class RulePolicy:
    name: str
    field_set: str
    exclude_review_like: bool = False
    term_mode: str = "current"


@dataclass(frozen=True)
class MetricRow:
    policy: str
    scope: str
    disease: str
    topic: str
    profile: str
    gt: int
    pool: int
    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def recall(self) -> float:
        return self.tp / self.gt if self.gt else 0.0

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 0.0

    @property
    def f1(self) -> float:
        recall = self.recall
        precision = self.precision
        return (
            2 * recall * precision / (recall + precision)
            if recall + precision
            else 0.0
        )

    @property
    def workload_reduction(self) -> float:
        return (self.fn + self.tn) / self.pool if self.pool else 0.0

    @property
    def nns(self) -> float:
        return 1 / self.precision if self.precision else 0.0


POLICIES = (
    RulePolicy("Rule: disease+parameter keywords", "full_metadata"),
    RulePolicy(
        "Rule: disease+parameter keywords (legacy 20260508 approximation)",
        "full_metadata",
        term_mode="legacy_20260508",
    ),
    RulePolicy(
        "Rule: keywords, exclude review-like records",
        "full_metadata",
        exclude_review_like=True,
    ),
    RulePolicy("Rule: title+abstract disease+parameter keywords", "title_abstract"),
    RulePolicy(
        "Rule: title+abstract keywords, exclude review-like records",
        "title_abstract",
        exclude_review_like=True,
    ),
    RulePolicy("Rule: title/keyword/MeSH only", "title_keywords_mesh"),
    RulePolicy(
        "Rule: title/keyword/MeSH, exclude review-like records",
        "title_keywords_mesh",
        exclude_review_like=True,
    ),
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: Iterable[MetricRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "policy",
        "scope",
        "disease",
        "topic",
        "profile",
        "GT",
        "Pool",
        "TP",
        "FP",
        "FN",
        "TN",
        "Recall",
        "Precision",
        "F1",
        "WR",
        "NNS",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "policy": row.policy,
                    "scope": row.scope,
                    "disease": row.disease,
                    "topic": row.topic,
                    "profile": row.profile,
                    "GT": row.gt,
                    "Pool": row.pool,
                    "TP": row.tp,
                    "FP": row.fp,
                    "FN": row.fn,
                    "TN": row.tn,
                    "Recall": row.recall,
                    "Precision": row.precision,
                    "F1": row.f1,
                    "WR": row.workload_reduction,
                    "NNS": row.nns,
                }
            )


def pmid_from_row(row: dict[str, str]) -> str:
    for key in ("PMID", "pmid", "gt_pmid"):
        value = (row.get(key) or "").strip()
        if value:
            return value
    return ""


def load_ground_truth(path: Path) -> set[str]:
    gt: set[str] = set()
    for row in read_csv(path):
        pmid = pmid_from_row(row)
        if not pmid:
            continue
        exclude = (row.get("exclude_flag") or "").strip().lower()
        if exclude in {"review_low_evidence", "review", "low_evidence"}:
            continue
        gt.add(pmid)
    return gt


def normalize(text: str) -> str:
    text = text.casefold()
    text = text.replace("\u2010", "-").replace("\u2011", "-").replace("\u2012", "-")
    text = text.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
    return text


def text_for_fields(row: dict[str, str], fields: Iterable[str]) -> str:
    return normalize(" ".join((row.get(field) or "") for field in fields))


def compile_term(term: str) -> re.Pattern[str]:
    """Compile a phrase term into a conservative whole-token regex."""
    term = normalize(term).strip()
    if term == "r0":
        return re.compile(r"(?<![a-z0-9])r[\s_-]*0(?![a-z0-9])")
    if term in {"rt", "re"}:
        return re.compile(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])")

    pieces = [re.escape(piece) for piece in re.split(r"[\s_/-]+", term) if piece]
    if not pieces:
        return re.compile(r"a^")
    pattern = r"[\s_/-]+".join(pieces)
    return re.compile(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])")


def compile_terms(terms: Iterable[str]) -> tuple[re.Pattern[str], ...]:
    return tuple(compile_term(term) for term in terms)


def contains_any(text: str, patterns: Iterable[re.Pattern[str]]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def disease_terms(profile: ScreeningProfile) -> tuple[str, ...]:
    if profile.disease_key == "mpox":
        return MPOX_DISEASE_TERMS
    return COVID19_DISEASE_TERMS


def parameter_terms(
    profile: ScreeningProfile,
    *,
    term_mode: str = "current",
) -> tuple[str, ...]:
    if term_mode == "legacy_20260508":
        if profile.profile_key in LEGACY_PROFILE_PARAMETER_TERMS:
            return LEGACY_PROFILE_PARAMETER_TERMS[profile.profile_key]
        terms = list(
            LEGACY_TOPIC_PARAMETER_TERMS.get(
                profile.topic_key,
                TOPIC_PARAMETER_TERMS[profile.topic_key],
            )
        )
    else:
        terms = list(TOPIC_PARAMETER_TERMS[profile.topic_key])

    terms.extend(PROFILE_PARAMETER_TERMS.get(profile.profile_key, ()))

    # Keep COVID-19 fatality profile P5 aligned with its source review, which is
    # a seroprevalence/antibody proxy for IFR rather than a direct mortality query.
    if term_mode != "legacy_20260508" and profile.profile_key == "P5":
        terms = list(PROFILE_PARAMETER_TERMS["P5"])

    return tuple(dict.fromkeys(terms))


def exclude_terms(
    profile: ScreeningProfile,
    *,
    term_mode: str = "current",
) -> tuple[str, ...]:
    if term_mode == "legacy_20260508":
        return LEGACY_PROFILE_EXCLUDE_TERMS.get(profile.profile_key, ())
    return ()


def profile_paths(profile: ScreeningProfile) -> tuple[Path, Path]:
    project_dir = (
        PROJECT_ROOT
        / "dataset"
        / profile.disease_key
        / "screening"
        / profile.topic_key
        / profile.project_dir_name
    )
    return project_dir / "raw.csv", project_dir / "ground_truth.csv"


def include_record(
    row: dict[str, str],
    *,
    fields: tuple[str, ...],
    disease_patterns: tuple[re.Pattern[str], ...],
    parameter_patterns: tuple[re.Pattern[str], ...],
    review_patterns: tuple[re.Pattern[str], ...],
    extra_exclude_patterns: tuple[re.Pattern[str], ...],
    exclude_review_like: bool,
) -> bool:
    text = text_for_fields(row, fields)
    if exclude_review_like and contains_any(text, review_patterns):
        return False
    if extra_exclude_patterns and contains_any(text, extra_exclude_patterns):
        return False
    return contains_any(text, disease_patterns) and contains_any(text, parameter_patterns)


def evaluate_profile(profile: ScreeningProfile, policy: RulePolicy) -> MetricRow:
    raw_path, gt_path = profile_paths(profile)
    rows = [row for row in read_csv(raw_path) if pmid_from_row(row)]
    gt = load_ground_truth(gt_path)
    fields = FIELD_SETS[policy.field_set]
    disease_patterns = compile_terms(disease_terms(profile))
    parameter_patterns = compile_terms(
        parameter_terms(profile, term_mode=policy.term_mode)
    )
    review_patterns = compile_terms(REVIEW_LIKE_TERMS)
    extra_exclude_patterns = compile_terms(
        exclude_terms(profile, term_mode=policy.term_mode)
    )

    included_pmids: set[str] = set()
    for row in rows:
        if include_record(
            row,
            fields=fields,
            disease_patterns=disease_patterns,
            parameter_patterns=parameter_patterns,
            review_patterns=review_patterns,
            extra_exclude_patterns=extra_exclude_patterns,
            exclude_review_like=policy.exclude_review_like,
        ):
            included_pmids.add(pmid_from_row(row))

    raw_pmids = [pmid_from_row(row) for row in rows]
    raw_pmid_set = set(raw_pmids)
    tp = len(included_pmids & gt)
    fp = len(included_pmids - gt)
    fn = len(gt - included_pmids)
    tn = len(raw_pmid_set - included_pmids - gt)
    return MetricRow(
        policy=policy.name,
        scope="profile",
        disease=profile.disease_key,
        topic=profile.topic_key,
        profile=profile.profile_key,
        gt=len(gt),
        pool=len(raw_pmid_set),
        tp=tp,
        fp=fp,
        fn=fn,
        tn=tn,
    )


def aggregate_rows(
    rows: list[MetricRow],
    *,
    policy: str,
    scope: str,
    disease: str,
    topic: str = "",
    profile: str = "",
) -> MetricRow:
    return MetricRow(
        policy=policy,
        scope=scope,
        disease=disease,
        topic=topic,
        profile=profile,
        gt=sum(row.gt for row in rows),
        pool=sum(row.pool for row in rows),
        tp=sum(row.tp for row in rows),
        fp=sum(row.fp for row in rows),
        fn=sum(row.fn for row in rows),
        tn=sum(row.tn for row in rows),
    )


def sort_profiles(profiles: Iterable[ScreeningProfile]) -> list[ScreeningProfile]:
    topic_order = {"fatality": 0, "reproduction_number": 1, "serial_interval": 2}
    return sorted(
        profiles,
        key=lambda profile: (
            profile.disease_key,
            topic_order.get(profile.topic_key, 99),
            profile.project_number,
        ),
    )


def evaluate_all() -> list[MetricRow]:
    profiles = sort_profiles(load_profile_registry().values())
    all_rows: list[MetricRow] = []
    for policy in POLICIES:
        profile_rows = [evaluate_profile(profile, policy) for profile in profiles]
        disease_rows = [
            aggregate_rows(
                [row for row in profile_rows if row.disease == disease],
                policy=policy.name,
                scope=disease,
                disease=disease,
            )
            for disease in ("covid19", "mpox")
        ]
        overall = aggregate_rows(
            profile_rows,
            policy=policy.name,
            scope="overall",
            disease="overall",
        )
        all_rows.extend(disease_rows)
        all_rows.append(overall)
        all_rows.extend(profile_rows)
    return all_rows


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def metric_row_from_csv(row: dict[str, str]) -> MetricRow:
    return MetricRow(
        policy=row["policy"],
        scope=row["scope"],
        disease=row["disease"],
        topic=row.get("topic", ""),
        profile=row.get("profile", ""),
        gt=int(float(row["GT"])),
        pool=int(float(row["Pool"])),
        tp=int(float(row["TP"])),
        fp=int(float(row["FP"])),
        fn=int(float(row["FN"])),
        tn=int(float(row["TN"])),
    )


def archived_keyword_rows(archive_csv: Path) -> list[MetricRow]:
    if not archive_csv.exists():
        return []
    return [
        metric_row_from_csv(row)
        for row in read_csv(archive_csv)
        if row.get("policy") == "Rule: disease+parameter keywords"
    ]


def write_summary(
    path: Path,
    rows: list[MetricRow],
    *,
    archive_csv: Path = DEFAULT_ARCHIVED_CSV,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    overall_rows = [row for row in rows if row.scope == "overall"]
    lines = [
        "# Rule-Based Screening Baselines",
        "",
        "Generated from frozen `dataset/*/screening/*/p*/raw.csv` and `ground_truth.csv`.",
        "This is a reproducible rerun with explicit term lists in `tools/scripts/rule_based_screening_baselines.py`; the historical 20260508 rule CSV did not preserve its generator, so repeated legacy policies are comparable but not byte-identical.",
        "",
        "## Overall",
        "",
        "| Policy | GT | Pool | Recall | Precision | F1 | WR | NNS | TP/FP/FN/TN |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in overall_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    row.policy,
                    str(row.gt),
                    str(row.pool),
                    pct(row.recall),
                    pct(row.precision),
                    pct(row.f1),
                    pct(row.workload_reduction),
                    f"{row.nns:.2f}",
                    f"{row.tp}/{row.fp}/{row.fn}/{row.tn}",
                ]
            )
            + " |"
        )

    title_abstract = [
        row
        for row in rows
        if row.policy == "Rule: title+abstract disease+parameter keywords"
        and row.scope in {"covid19", "mpox", "overall"}
    ]
    lines.extend(
        [
            "",
            "## Title + Abstract Rule",
            "",
            "| Scope | GT | Pool | Recall | Precision | F1 | WR | NNS | TP/FP/FN/TN |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in title_abstract:
        lines.append(
            "| "
            + " | ".join(
                [
                    row.scope,
                    str(row.gt),
                    str(row.pool),
                    pct(row.recall),
                    pct(row.precision),
                    pct(row.f1),
                    pct(row.workload_reduction),
                    f"{row.nns:.2f}",
                    f"{row.tp}/{row.fp}/{row.fn}/{row.tn}",
                ]
            )
            + " |"
        )

    archived_rows = archived_keyword_rows(archive_csv)
    if archived_rows:
        archived_overall = next(
            row for row in archived_rows if row.scope == "overall"
        )
        legacy_overall = next(
            row
            for row in rows
            if row.policy
            == "Rule: disease+parameter keywords (legacy 20260508 approximation)"
            and row.scope == "overall"
        )
        current_overall = next(
            row
            for row in rows
            if row.policy == "Rule: disease+parameter keywords"
            and row.scope == "overall"
        )
        lines.extend(
            [
                "",
                "## Legacy Recovery Check",
                "",
                "The archived 20260508 keyword-rule CSV does not preserve its generator. The legacy approximation is a best-effort reconstruction from profile-level archived counts, not an exact source-script recovery.",
                "",
                "| Version | Recall | Precision | F1 | WR | NNS | TP/FP/FN/TN |",
                "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for label, row in (
            ("Archived 20260508", archived_overall),
            ("Current clean rerun", current_overall),
            ("Legacy approximation", legacy_overall),
        ):
            lines.append(
                "| "
                + " | ".join(
                    [
                        label,
                        pct(row.recall),
                        pct(row.precision),
                        pct(row.f1),
                        pct(row.workload_reduction),
                        f"{row.nns:.2f}",
                        f"{row.tp}/{row.fp}/{row.fn}/{row.tn}",
                    ]
                )
                + " |"
            )

        archived_profiles = {
            row.profile: row
            for row in archived_rows
            if row.scope == "profile"
        }
        legacy_profiles = [
            row
            for row in rows
            if row.policy
            == "Rule: disease+parameter keywords (legacy 20260508 approximation)"
            and row.scope == "profile"
        ]
        diffs: list[tuple[int, MetricRow, MetricRow]] = []
        for legacy_row in legacy_profiles:
            archived_row = archived_profiles.get(legacy_row.profile)
            if archived_row is None:
                continue
            distance = abs(legacy_row.tp - archived_row.tp) + abs(
                legacy_row.fp - archived_row.fp
            )
            diffs.append((distance, archived_row, legacy_row))
        lines.extend(
            [
                "",
                "Largest remaining profile-level differences:",
                "",
                "| Profile | Topic | Archived TP/FP | Approx TP/FP | Delta TP | Delta FP |",
                "| --- | --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for _, archived_row, legacy_row in sorted(
            diffs, key=lambda item: item[0], reverse=True
        )[:8]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        legacy_row.profile,
                        legacy_row.topic,
                        f"{archived_row.tp}/{archived_row.fp}",
                        f"{legacy_row.tp}/{legacy_row.fp}",
                        str(legacy_row.tp - archived_row.tp),
                        str(legacy_row.fp - archived_row.fp),
                    ]
                )
                + " |"
            )

    lines.extend(
        [
            "",
            "## Rule Definitions",
            "",
            "- `full_metadata`: Title, Abstract, Keywords, Citation, Journal/Book.",
            "- `title_abstract`: Title and Abstract only.",
            "- `title_keywords_mesh`: Title and Keywords; PubMed MeSH terms appear in the `Keywords` field when available.",
            "- `exclude review-like records`: remove records where the selected fields contain review-like terms such as review, systematic review, meta-analysis, protocol, editorial, comment, letter, correspondence, perspective, opinion, or guideline.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--archived-csv", type=Path, default=DEFAULT_ARCHIVED_CSV)
    args = parser.parse_args()

    rows = evaluate_all()
    write_csv(args.output, rows)
    write_summary(args.summary, rows, archive_csv=args.archived_csv)

    print(f"Wrote {args.output}")
    print(f"Wrote {args.summary}")
    print()
    for row in rows:
        if row.scope == "overall":
            print(
                f"{row.policy}: recall={pct(row.recall)}, "
                f"precision={pct(row.precision)}, NNS={row.nns:.2f}, "
                f"TP/FP/FN/TN={row.tp}/{row.fp}/{row.fn}/{row.tn}"
            )


if __name__ == "__main__":
    main()
