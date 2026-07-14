#!/usr/bin/env python3
"""Run a BM25 title/abstract screening baseline on frozen profiles.

The default cutoff is a matched-workload top-K setting: for each source review,
BM25 selects the same number of records selected by the current paper-facing
MetaAgent/Qwen profile-level result. This avoids tuning BM25 on ground truth
while making the manual-review workload directly comparable.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metaagent.screening.profile_registry import ScreeningProfile, load_profile_registry


OUT_DIR = Path(__file__).resolve().parent / "results"
DEFAULT_OUTPUT = OUT_DIR / "bm25_baselines.csv"
DEFAULT_SUMMARY = OUT_DIR / "bm25_baselines.md"
DEFAULT_WORKLOAD_SOURCE = ROOT / "docs" / "paper" / "source_data" / "recall_nns_model_sources.csv"
DEFAULT_WORKLOAD_MODEL_SOURCE = "calibrated_qwen3_6_plus_v1_recall"

FIELD_SETS: dict[str, tuple[str, ...]] = {
    "title_abstract": ("Title", "Abstract"),
    "title_abstract_keywords": ("Title", "Abstract", "Keywords"),
}

SHORT_DISEASE_QUERY_TERMS = {
    "covid19": "COVID-19 SARS-CoV-2",
    "mpox": "mpox monkeypox",
}

SHORT_PARAMETER_QUERY_TERMS = {
    "serial_interval": "serial interval",
    "reproduction_number": "basic reproduction number",
    "fatality": "fatality",
}

TOPIC_LABELS = {
    "serial interval": "serial_interval",
    "reproduction number": "reproduction_number",
    "fatality": "fatality",
}

STOPWORDS = {
    "a",
    "about",
    "above",
    "after",
    "again",
    "against",
    "all",
    "am",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "because",
    "been",
    "before",
    "being",
    "below",
    "between",
    "both",
    "but",
    "by",
    "can",
    "did",
    "do",
    "does",
    "doing",
    "down",
    "during",
    "each",
    "few",
    "for",
    "from",
    "further",
    "had",
    "has",
    "have",
    "having",
    "he",
    "her",
    "here",
    "hers",
    "herself",
    "him",
    "himself",
    "his",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "itself",
    "me",
    "more",
    "most",
    "my",
    "myself",
    "no",
    "nor",
    "not",
    "of",
    "off",
    "on",
    "once",
    "only",
    "or",
    "other",
    "our",
    "ours",
    "ourselves",
    "out",
    "over",
    "own",
    "same",
    "she",
    "should",
    "so",
    "some",
    "such",
    "than",
    "that",
    "the",
    "their",
    "theirs",
    "them",
    "themselves",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "to",
    "too",
    "under",
    "until",
    "up",
    "very",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "whom",
    "why",
    "with",
    "you",
    "your",
    "yours",
    "yourself",
    "yourselves",
}

TOKEN_RE = re.compile(r"[a-z0-9]+")


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
    selected_k: int
    query_mode: str
    field_set: str
    workload_source: str

    @property
    def recall(self) -> float:
        return self.tp / self.gt if self.gt else 0.0

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 0.0

    @property
    def f1(self) -> float:
        denom = self.recall + self.precision
        return 2 * self.recall * self.precision / denom if denom else 0.0

    @property
    def workload_reduction(self) -> float:
        return (self.fn + self.tn) / self.pool if self.pool else 0.0

    @property
    def nns(self) -> float:
        return (self.tp + self.fp) / self.tp if self.tp else math.inf


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


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


def normalize_text(text: str) -> str:
    text = text.casefold()
    for char in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"):
        text = text.replace(char, "-")
    return text


def tokenize(text: str) -> list[str]:
    tokens = TOKEN_RE.findall(normalize_text(text.replace("-", " ")))
    return [token for token in tokens if token not in STOPWORDS and len(token) > 1]


def profile_paths(profile: ScreeningProfile) -> tuple[Path, Path]:
    project_dir = (
        ROOT
        / "dataset"
        / profile.disease_key
        / "screening"
        / profile.topic_key
        / profile.project_dir_name
    )
    return project_dir / "raw.csv", project_dir / "ground_truth.csv"


def text_for_fields(row: dict[str, str], fields: Iterable[str]) -> str:
    return " ".join((row.get(field) or "") for field in fields)


def query_for_profile(profile: ScreeningProfile, mode: str) -> str:
    if mode == "short_disease_parameter":
        return (
            f"{SHORT_DISEASE_QUERY_TERMS[profile.disease_key]} "
            f"{SHORT_PARAMETER_QUERY_TERMS[profile.topic_key]}"
        )
    if mode == "disease_parameter":
        return f"{profile.disease_focus} {profile.parameter_focus}"
    if mode == "research_question":
        return profile.research_question
    if mode == "all_profile_text":
        return (
            f"{profile.research_question} {profile.disease_focus} "
            f"{profile.parameter_focus}"
        )
    raise ValueError(f"Unknown query mode: {mode}")


def deduplicate_rows(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    by_pmid: dict[str, dict[str, str]] = {}
    for row in rows:
        pmid = pmid_from_row(row)
        if not pmid:
            continue
        if pmid not in by_pmid:
            by_pmid[pmid] = dict(row)
            continue
        existing = by_pmid[pmid]
        for field in ("Title", "Abstract", "Keywords", "Citation", "Journal/Book"):
            if not existing.get(field) and row.get(field):
                existing[field] = row[field]
    return list(by_pmid.values())


def bm25_rank(
    rows: list[dict[str, str]],
    *,
    fields: tuple[str, ...],
    query: str,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[tuple[str, float]]:
    docs = [tokenize(text_for_fields(row, fields)) for row in rows]
    query_terms = list(dict.fromkeys(tokenize(query)))
    doc_count = len(docs)
    avg_len = sum(len(doc) for doc in docs) / doc_count if doc_count else 0.0

    df: Counter[str] = Counter()
    for doc in docs:
        df.update(set(doc))

    idf = {
        term: math.log(1.0 + (doc_count - freq + 0.5) / (freq + 0.5))
        for term, freq in df.items()
    }

    ranked: list[tuple[str, float]] = []
    for row, doc in zip(rows, docs):
        tf = Counter(doc)
        doc_len = len(doc)
        score = 0.0
        for term in query_terms:
            freq = tf.get(term, 0)
            if not freq:
                continue
            denominator = freq + k1 * (1.0 - b + b * (doc_len / avg_len if avg_len else 0.0))
            score += idf.get(term, 0.0) * (freq * (k1 + 1.0)) / denominator
        ranked.append((pmid_from_row(row), score))
    return sorted(ranked, key=lambda item: (-item[1], item[0]))


def topic_key_from_label(label: str) -> str:
    key = label.strip().casefold()
    if key not in TOPIC_LABELS:
        raise ValueError(f"Unknown topic label in workload source: {label!r}")
    return TOPIC_LABELS[key]


def load_workload_targets(path: Path, model_source: str) -> dict[tuple[str, str, int], int]:
    targets: dict[tuple[str, str, int], int] = {}
    for row in read_csv(path):
        if row.get("model_source") != model_source or row.get("row_type") != "project":
            continue
        disease = (row.get("disease") or "").strip()
        topic = topic_key_from_label(row.get("topic") or "")
        project = int(row.get("project") or 0)
        selected = int(float(row.get("tp") or 0)) + int(float(row.get("fp") or 0))
        targets[(disease, topic, project)] = selected
    return targets


def sort_profiles(profiles: Iterable[ScreeningProfile]) -> list[ScreeningProfile]:
    topic_order = {"serial_interval": 0, "reproduction_number": 1, "fatality": 2}
    return sorted(
        profiles,
        key=lambda profile: (
            profile.disease_key,
            topic_order.get(profile.topic_key, 99),
            profile.project_number,
        ),
    )


def evaluate_profile(
    profile: ScreeningProfile,
    *,
    field_set: str,
    query_mode: str,
    workload_targets: dict[tuple[str, str, int], int],
    workload_source: str,
) -> MetricRow:
    raw_path, gt_path = profile_paths(profile)
    rows = deduplicate_rows(read_csv(raw_path))
    gt = load_ground_truth(gt_path)
    target_key = (profile.disease_key, profile.topic_key, profile.project_number)
    if target_key not in workload_targets:
        raise KeyError(f"Missing matched-workload target for {target_key}")

    fields = FIELD_SETS[field_set]
    ranked = bm25_rank(
        rows,
        fields=fields,
        query=query_for_profile(profile, query_mode),
    )
    selected_k = min(workload_targets[target_key], len(ranked))
    included_pmids = {pmid for pmid, _ in ranked[:selected_k]}
    raw_pmids = {pmid_from_row(row) for row in rows}

    tp = len(included_pmids & gt)
    fp = len(included_pmids - gt)
    fn = len(gt - included_pmids)
    tn = len(raw_pmids - included_pmids - gt)
    policy = "BM25: short disease+parameter, matched MetaAgent workload"
    if field_set != "title_abstract" or query_mode != "short_disease_parameter":
        policy = f"BM25: {field_set}, {query_mode}, matched MetaAgent workload"
    return MetricRow(
        policy=policy,
        scope="profile",
        disease=profile.disease_key,
        topic=profile.topic_key,
        profile=profile.profile_key,
        gt=len(gt),
        pool=len(raw_pmids),
        tp=tp,
        fp=fp,
        fn=fn,
        tn=tn,
        selected_k=selected_k,
        query_mode=query_mode,
        field_set=field_set,
        workload_source=workload_source,
    )


def aggregate_rows(
    rows: list[MetricRow],
    *,
    scope: str,
    disease: str,
    topic: str = "",
    profile: str = "",
) -> MetricRow:
    first = rows[0]
    return MetricRow(
        policy=first.policy,
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
        selected_k=sum(row.selected_k for row in rows),
        query_mode=first.query_mode,
        field_set=first.field_set,
        workload_source=first.workload_source,
    )


def evaluate_all(
    *,
    field_set: str,
    query_mode: str,
    workload_source_path: Path,
    workload_model_source: str,
) -> list[MetricRow]:
    workload_targets = load_workload_targets(workload_source_path, workload_model_source)
    profiles = sort_profiles(load_profile_registry().values())
    profile_rows = [
        evaluate_profile(
            profile,
            field_set=field_set,
            query_mode=query_mode,
            workload_targets=workload_targets,
            workload_source=f"{workload_source_path.relative_to(ROOT)}:{workload_model_source}",
        )
        for profile in profiles
    ]
    rows = [
        aggregate_rows(
            [row for row in profile_rows if row.disease == disease],
            scope=disease,
            disease=disease,
        )
        for disease in ("covid19", "mpox")
    ]
    rows.append(aggregate_rows(profile_rows, scope="overall", disease="overall"))
    rows.extend(profile_rows)
    return rows


def fmt_float(value: float) -> str:
    if math.isinf(value):
        return ""
    return f"{value:.6f}"


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
        "selected_k",
        "Recall",
        "Precision",
        "F1",
        "WR",
        "NNS",
        "query_mode",
        "field_set",
        "workload_source",
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
                    "selected_k": row.selected_k,
                    "Recall": fmt_float(row.recall),
                    "Precision": fmt_float(row.precision),
                    "F1": fmt_float(row.f1),
                    "WR": fmt_float(row.workload_reduction),
                    "NNS": fmt_float(row.nns),
                    "query_mode": row.query_mode,
                    "field_set": row.field_set,
                    "workload_source": row.workload_source,
                }
            )


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def write_summary(path: Path, rows: list[MetricRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary_rows = [row for row in rows if row.scope in {"overall", "covid19", "mpox"}]
    profile_rows = [row for row in rows if row.scope == "profile"]
    lines = [
        "# BM25 Screening Baseline",
        "",
        "Generated from frozen `dataset/*/screening/*/p*/raw.csv` and `ground_truth.csv`.",
        "The default policy ranks records with BM25 over title and abstract text, then selects the top-K records per source review where K equals the current paper-facing MetaAgent/Qwen selected count for that review. No ground-truth labels are used to choose K.",
        "",
        "## Summary",
        "",
        "| Scope | GT | Pool | Selected | Recall | Precision | F1 | WR | NNS | TP/FP/FN/TN |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in summary_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    row.scope,
                    str(row.gt),
                    str(row.pool),
                    str(row.selected_k),
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
            "## Profile Rows",
            "",
            "| Profile | Disease | Topic | GT | Pool | Selected | Recall | Precision | NNS | TP/FP/FN/TN |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in profile_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    row.profile,
                    row.disease,
                    row.topic,
                    str(row.gt),
                    str(row.pool),
                    str(row.selected_k),
                    pct(row.recall),
                    pct(row.precision),
                    f"{row.nns:.2f}" if not math.isinf(row.nns) else "",
                    f"{row.tp}/{row.fp}/{row.fn}/{row.tn}",
                ]
            )
            + " |"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--field-set", choices=FIELD_SETS, default="title_abstract")
    parser.add_argument(
        "--query-mode",
        choices=(
            "short_disease_parameter",
            "disease_parameter",
            "research_question",
            "all_profile_text",
        ),
        default="short_disease_parameter",
    )
    parser.add_argument("--workload-source", type=Path, default=DEFAULT_WORKLOAD_SOURCE)
    parser.add_argument("--workload-model-source", default=DEFAULT_WORKLOAD_MODEL_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_SUMMARY)
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    rows = evaluate_all(
        field_set=args.field_set,
        query_mode=args.query_mode,
        workload_source_path=args.workload_source,
        workload_model_source=args.workload_model_source,
    )
    write_csv(args.output, rows)
    write_summary(args.markdown, rows)
    print(f"Wrote {args.output}")
    print(f"Wrote {args.markdown}")


if __name__ == "__main__":
    main()
