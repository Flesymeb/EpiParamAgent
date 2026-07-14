#!/usr/bin/env python3
"""Run no-training dense neural retrieval baselines on frozen profiles.

The baselines embed short disease-parameter queries and title/abstract records
with pretrained biomedical/scientific encoders, rank records by cosine
similarity, and use the same matched-workload top-K cutoff as the BM25 baseline.
No source-review ground-truth labels are used for model fitting or cutoff tuning.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROFILE_REGISTRY_PATH = ROOT / "metaagent" / "screening" / "profile_registry.py"
PROFILE_REGISTRY_MODULE = "_metaagent_screening_profile_registry"
profile_spec = importlib.util.spec_from_file_location(
    PROFILE_REGISTRY_MODULE,
    PROFILE_REGISTRY_PATH,
)
if profile_spec is None or profile_spec.loader is None:
    raise ImportError(f"Could not load profile registry from {PROFILE_REGISTRY_PATH}")
profile_registry = importlib.util.module_from_spec(profile_spec)
sys.modules[PROFILE_REGISTRY_MODULE] = profile_registry
profile_spec.loader.exec_module(profile_registry)

ScreeningProfile = profile_registry.ScreeningProfile
load_profile_registry = profile_registry.load_profile_registry


OUT_DIR = Path(__file__).resolve().parent / "results"
CACHE_DIR = Path(__file__).resolve().parent / "cache"
DEFAULT_OUTPUT = OUT_DIR / "neural_retrieval_baselines.csv"
DEFAULT_SUMMARY = OUT_DIR / "neural_retrieval_baselines.md"
DEFAULT_WORKLOAD_SOURCE = ROOT / "docs" / "paper" / "source_data" / "recall_nns_model_sources.csv"
DEFAULT_WORKLOAD_MODEL_SOURCE = "calibrated_qwen3_6_plus_v1_recall"

FIELD_SETS: dict[str, tuple[str, ...]] = {
    "title_abstract": ("Title", "Abstract"),
}

MODEL_SPECS = {
    "pubmedbert": {
        "display": "PubMedBERT retrieval",
        "hf_model": "microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract-fulltext",
        "tokenizer_model": "microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract-fulltext",
        "pooling": "mean",
    },
    "biobert": {
        "display": "BioBERT retrieval",
        "hf_model": "monologg/biobert_v1.1_pubmed",
        "tokenizer_model": "monologg/biobert_v1.1_pubmed",
        "pooling": "mean",
    },
    "specter": {
        "display": "SPECTER retrieval",
        "hf_model": "allenai/specter",
        "tokenizer_model": "allenai/specter",
        "pooling": "cls",
    },
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


@dataclass(frozen=True)
class MetricRow:
    policy: str
    model_key: str
    hf_model: str
    pooling: str
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
    title = (row.get("Title") or "").strip()
    abstract = (row.get("Abstract") or "").strip()
    if tuple(fields) == ("Title", "Abstract"):
        return f"{title}\n\n{abstract}".strip()
    return " ".join((row.get(field) or "") for field in fields).strip()


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


def query_for_profile(profile: ScreeningProfile) -> str:
    return (
        f"{SHORT_DISEASE_QUERY_TERMS[profile.disease_key]} "
        f"{SHORT_PARAMETER_QUERY_TERMS[profile.topic_key]}"
    )


def stable_doc_key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


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


def l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def mean_pool(last_hidden_state, attention_mask):
    import torch

    mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
    summed = torch.sum(last_hidden_state * mask, dim=1)
    counts = torch.clamp(mask.sum(dim=1), min=1e-9)
    return summed / counts


def encode_texts(
    texts: list[str],
    *,
    hf_model: str,
    tokenizer_model: str,
    pooling: str,
    batch_size: int,
    max_length: int,
    device: str,
    progress_label: str = "",
) -> np.ndarray:
    import torch
    from transformers import AutoModel, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(tokenizer_model, use_fast=False)
    model = AutoModel.from_pretrained(hf_model)
    model.to(device)
    model.eval()

    encoded_batches: list[np.ndarray] = []
    with torch.no_grad():
        total_batches = math.ceil(len(texts) / batch_size) if batch_size else 0
        for start in range(0, len(texts), batch_size):
            batch_index = start // batch_size + 1
            if total_batches >= 10 and (
                batch_index == 1 or batch_index % 20 == 0 or batch_index == total_batches
            ):
                label = f" {progress_label}" if progress_label else ""
                print(
                    f"Encoding{label}: batch {batch_index}/{total_batches}",
                    flush=True,
                )
            batch = texts[start : start + batch_size]
            inputs = tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            )
            inputs = {key: value.to(device) for key, value in inputs.items()}
            outputs = model(**inputs)
            if pooling == "cls":
                embeddings = outputs.last_hidden_state[:, 0, :]
            elif pooling == "mean":
                embeddings = mean_pool(outputs.last_hidden_state, inputs["attention_mask"])
            else:
                raise ValueError(f"Unknown pooling mode: {pooling}")
            encoded_batches.append(embeddings.cpu().numpy().astype("float32"))
    return l2_normalize(np.vstack(encoded_batches))


def cache_paths(model_key: str, field_set: str, max_length: int) -> tuple[Path, Path]:
    stem = f"{model_key}_{field_set}_max{max_length}"
    return CACHE_DIR / f"{stem}.npz", CACHE_DIR / f"{stem}.json"


def load_or_encode_documents(
    *,
    model_key: str,
    hf_model: str,
    tokenizer_model: str,
    pooling: str,
    field_set: str,
    doc_text_by_key: dict[str, str],
    batch_size: int,
    max_length: int,
    device: str,
    refresh_cache: bool,
) -> dict[str, np.ndarray]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    matrix_path, meta_path = cache_paths(model_key, field_set, max_length)
    ordered_keys = sorted(doc_text_by_key)
    if not refresh_cache and matrix_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if (
            meta.get("keys") == ordered_keys
            and meta.get("hf_model") == hf_model
            and meta.get("tokenizer_model") == tokenizer_model
        ):
            matrix = np.load(matrix_path)["embeddings"]
            return {key: matrix[i] for i, key in enumerate(ordered_keys)}

    texts = [doc_text_by_key[key] for key in ordered_keys]
    matrix = encode_texts(
        texts,
        hf_model=hf_model,
        tokenizer_model=tokenizer_model,
        pooling=pooling,
        batch_size=batch_size,
        max_length=max_length,
        device=device,
        progress_label=f"{model_key} documents",
    )
    np.savez(matrix_path, embeddings=matrix)
    meta_path.write_text(
        json.dumps(
            {
                "model_key": model_key,
                "hf_model": hf_model,
                "tokenizer_model": tokenizer_model,
                "pooling": pooling,
                "field_set": field_set,
                "max_length": max_length,
                "keys": ordered_keys,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {key: matrix[i] for i, key in enumerate(ordered_keys)}


def evaluate_profile(
    profile: ScreeningProfile,
    *,
    spec: dict[str, str],
    model_key: str,
    field_set: str,
    workload_targets: dict[tuple[str, str, int], int],
    workload_source: str,
    doc_embedding_by_key: dict[str, np.ndarray],
    query_embedding: np.ndarray,
) -> MetricRow:
    raw_path, gt_path = profile_paths(profile)
    rows = deduplicate_rows(read_csv(raw_path))
    gt = load_ground_truth(gt_path)
    target_key = (profile.disease_key, profile.topic_key, profile.project_number)
    if target_key not in workload_targets:
        raise KeyError(f"Missing matched-workload target for {target_key}")

    fields = FIELD_SETS[field_set]
    scored: list[tuple[str, float]] = []
    for row in rows:
        text = text_for_fields(row, fields)
        key = stable_doc_key(text)
        score = float(np.dot(query_embedding, doc_embedding_by_key[key]))
        scored.append((pmid_from_row(row), score))
    ranked = sorted(scored, key=lambda item: (-item[1], item[0]))

    selected_k = min(workload_targets[target_key], len(ranked))
    included_pmids = {pmid for pmid, _ in ranked[:selected_k]}
    raw_pmids = {pmid_from_row(row) for row in rows}
    tp = len(included_pmids & gt)
    fp = len(included_pmids - gt)
    fn = len(gt - included_pmids)
    tn = len(raw_pmids - included_pmids - gt)
    return MetricRow(
        policy=f"{spec['display']}: title+abstract, matched MetaAgent workload",
        model_key=model_key,
        hf_model=spec["hf_model"],
        pooling=spec["pooling"],
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
        query_mode="short_disease_parameter",
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
        model_key=first.model_key,
        hf_model=first.hf_model,
        pooling=first.pooling,
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


def collect_doc_texts(profiles: list[ScreeningProfile], field_set: str) -> dict[str, str]:
    fields = FIELD_SETS[field_set]
    texts: dict[str, str] = {}
    for profile in profiles:
        raw_path, _ = profile_paths(profile)
        for row in deduplicate_rows(read_csv(raw_path)):
            text = text_for_fields(row, fields)
            texts.setdefault(stable_doc_key(text), text)
    return texts


def evaluate_model(
    *,
    model_key: str,
    profiles: list[ScreeningProfile],
    field_set: str,
    workload_targets: dict[tuple[str, str, int], int],
    workload_source: str,
    batch_size: int,
    max_length: int,
    device: str,
    refresh_cache: bool,
) -> list[MetricRow]:
    spec = MODEL_SPECS[model_key]
    doc_texts = collect_doc_texts(profiles, field_set)
    doc_embedding_by_key = load_or_encode_documents(
        model_key=model_key,
        hf_model=spec["hf_model"],
        tokenizer_model=spec.get("tokenizer_model", spec["hf_model"]),
        pooling=spec["pooling"],
        field_set=field_set,
        doc_text_by_key=doc_texts,
        batch_size=batch_size,
        max_length=max_length,
        device=device,
        refresh_cache=refresh_cache,
    )

    query_texts = [query_for_profile(profile) for profile in profiles]
    query_matrix = encode_texts(
        query_texts,
        hf_model=spec["hf_model"],
        tokenizer_model=spec.get("tokenizer_model", spec["hf_model"]),
        pooling=spec["pooling"],
        batch_size=batch_size,
        max_length=max_length,
        device=device,
        progress_label=f"{model_key} queries",
    )
    profile_rows = [
        evaluate_profile(
            profile,
            spec=spec,
            model_key=model_key,
            field_set=field_set,
            workload_targets=workload_targets,
            workload_source=workload_source,
            doc_embedding_by_key=doc_embedding_by_key,
            query_embedding=query_matrix[i],
        )
        for i, profile in enumerate(profiles)
    ]
    rows = [
        aggregate_rows(
            [row for row in profile_rows if row.disease == disease],
            scope=disease,
            disease=disease,
        )
        for disease in ("covid19", "mpox")
        if any(row.disease == disease for row in profile_rows)
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
        "model_key",
        "hf_model",
        "pooling",
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
                    "model_key": row.model_key,
                    "hf_model": row.hf_model,
                    "pooling": row.pooling,
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
    lines = [
        "# Neural Retrieval Screening Baselines",
        "",
        "Generated from frozen `dataset/*/screening/*/p*/raw.csv` and `ground_truth.csv`.",
        "These are no-training dense retrieval baselines: each encoder embeds short disease-parameter queries and title/abstract records, ranks by cosine similarity, and uses the same per-source-review matched-workload top-K cutoff as BM25.",
        "",
        "## Overall",
        "",
        "| Method | Encoder | Pooling | GT | Pool | Selected | Recall | Precision | F1 | WR | NNS | TP/FP/FN/TN |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        if row.scope != "overall":
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    row.policy,
                    row.hf_model,
                    row.pooling,
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
            "## Disease-Level",
            "",
            "| Method | Disease | Recall | Precision | F1 | WR | NNS | TP/FP/FN/TN |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in rows:
        if row.scope not in {"covid19", "mpox"}:
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    row.policy,
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
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        nargs="+",
        choices=tuple(MODEL_SPECS),
        default=("pubmedbert", "biobert", "specter"),
    )
    parser.add_argument("--field-set", choices=FIELD_SETS, default="title_abstract")
    parser.add_argument("--workload-source", type=Path, default=DEFAULT_WORKLOAD_SOURCE)
    parser.add_argument("--workload-model-source", default=DEFAULT_WORKLOAD_MODEL_SOURCE)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--device", default="auto", help="auto, cpu, cuda, cuda:0, ...")
    parser.add_argument("--threads", type=int, default=0)
    parser.add_argument("--limit-profiles", type=int, default=0)
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_SUMMARY)
    return parser


def resolve_device(device: str) -> str:
    if device != "auto":
        return device
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def main() -> None:
    args = build_arg_parser().parse_args()
    if args.threads > 0:
        os.environ["OMP_NUM_THREADS"] = str(args.threads)
        os.environ["MKL_NUM_THREADS"] = str(args.threads)
        try:
            import torch

            torch.set_num_threads(args.threads)
        except Exception:
            pass

    device = resolve_device(args.device)
    profiles = sort_profiles(load_profile_registry().values())
    if args.limit_profiles:
        profiles = profiles[: args.limit_profiles]
    workload_targets = load_workload_targets(args.workload_source, args.workload_model_source)
    workload_source = f"{args.workload_source.relative_to(ROOT)}:{args.workload_model_source}"

    all_rows: list[MetricRow] = []
    for model_key in args.models:
        print(f"Running {model_key} on {len(profiles)} profiles with device={device}", flush=True)
        all_rows.extend(
            evaluate_model(
                model_key=model_key,
                profiles=profiles,
                field_set=args.field_set,
                workload_targets=workload_targets,
                workload_source=workload_source,
                batch_size=args.batch_size,
                max_length=args.max_length,
                device=device,
                refresh_cache=args.refresh_cache,
            )
        )
    write_csv(args.output, all_rows)
    write_summary(args.markdown, all_rows)
    print(f"Wrote {args.output}", flush=True)
    print(f"Wrote {args.markdown}", flush=True)
    # Some torch/huggingface CPU worker threads can keep this short-lived CLI
    # alive after outputs are written. Force exit by default for batch runs.
    if os.environ.get("METAAGENT_NEURAL_RETRIEVAL_FORCE_EXIT", "1") != "0":
        os._exit(0)


if __name__ == "__main__":
    main()
