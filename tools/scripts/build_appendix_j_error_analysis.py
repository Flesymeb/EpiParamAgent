#!/usr/bin/env python3
"""Build Appendix J record-level screening and coding error analysis artifacts.

The key output is a stable set of source-data CSV files under docs/paper/source_data.
False positives are classified at the screening-task record level
(profile + parameter + PMID), not at unique-PMID level.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs" / "paper" / "source_data"
FIGDIR = ROOT / "docs" / "paper" / "latex" / "figures" / "pdf"
SCREENING_CSV = SOURCE / "qwen36plus_screening_per_record.csv"
CODING_CSV = SOURCE / "coding_estimate_intervals.csv"
E2E_CODING_CSV = ROOT / "e2e" / "runs" / "screen_to_coding" / "e2e_coding_estimate_intervals.csv"
E2E_TRACKING_CSV = ROOT / "e2e" / "runs" / "screen_to_coding" / "e2e_pooled_mean_tracking.csv"
E2E_AUDIT_CSV = ROOT / "e2e" / "runs" / "screen_to_coding" / "e2e_sr_deviation_audit.csv"
FP_TAG_JSONL = SOURCE / "error_fp_record_tags.jsonl"
FP_TAXONOMY_CSV = SOURCE / "error_fp_record_taxonomy.csv"
FN_TAXONOMY_CSV = SOURCE / "error_fn_record_taxonomy.csv"
CODING_TAXONOMY_CSV = SOURCE / "error_coding_review_taxonomy.csv"
SUMMARY_JSON = SOURCE / "appendix_j_error_analysis_summary.json"


FP_CATEGORIES = {
    "DIFFERENT_QUANTITY": "Different related quantity",
    "MODELING_ASSUMED_INPUT": "Modeling or assumed input",
    "NON_PRIMARY_STUDY": "Non-primary study type",
    "ELIGIBILITY_SCOPE": "Eligibility or estimand scope",
    "ABSTRACT_LIMITATION": "Not verifiable from abstract",
    "PARAMETER_ABSENT": "Parameter absent / over-inference",
    "OTHER": "Other",
}

FP_SHORT_LABELS = {
    "DIFFERENT_QUANTITY": "Different\nquantity",
    "MODELING_ASSUMED_INPUT": "Modeling /\ninput",
    "NON_PRIMARY_STUDY": "Non-primary\nstudy",
    "ELIGIBILITY_SCOPE": "Scope /\nestimand",
    "ABSTRACT_LIMITATION": "Abstract\nlimited",
    "PARAMETER_ABSENT": "Parameter\nabsent",
    "OTHER": "Other",
}

FP_CATEGORY_ORDER = [
    "DIFFERENT_QUANTITY",
    "MODELING_ASSUMED_INPUT",
    "NON_PRIMARY_STUDY",
    "ELIGIBILITY_SCOPE",
    "ABSTRACT_LIMITATION",
    "PARAMETER_ABSENT",
    "OTHER",
]

FP_COLORS = {
    "DIFFERENT_QUANTITY": "#4C78A8",
    "MODELING_ASSUMED_INPUT": "#F58518",
    "NON_PRIMARY_STUDY": "#7F7F7F",
    "ELIGIBILITY_SCOPE": "#54A24B",
    "ABSTRACT_LIMITATION": "#72B7B2",
    "PARAMETER_ABSENT": "#E45756",
    "OTHER": "#B279A2",
}

FN_CATEGORIES = {
    "FULLTEXT_ONLY": "Parameter absent from abstract; recoverable in full text",
    "SPARSE_OR_BORDERLINE": "Sparse, borderline, or weakly stated evidence",
    "NON_PRIMARY_OR_TANGENTIAL": "Non-primary or tangential source-review inclusion",
}

FN_CATEGORY_ORDER = ["FULLTEXT_ONLY", "SPARSE_OR_BORDERLINE", "NON_PRIMARY_OR_TANGENTIAL"]
FN_COLORS = {
    "FULLTEXT_ONLY": "#4C78A8",
    "SPARSE_OR_BORDERLINE": "#F58518",
    "NON_PRIMARY_OR_TANGENTIAL": "#7F7F7F",
}


def load_env_local() -> None:
    env_path = ROOT / ".env.local"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_abstracts() -> dict[str, str]:
    candidates = [
        SOURCE / "pubmed_abstract_cache.json",
        Path("/tmp/all_abs_full.json"),
    ]
    for path in candidates:
        if path.exists():
            return {str(k): str(v or "") for k, v in json.loads(path.read_text()).items()}
    return {}


def record_id(row: dict[str, str]) -> str:
    return f"{row['profile']}|{row['parameter']}|{row['pmid']}"


def load_jsonl(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = item.get("record_id")
            if rid:
                out[rid] = item
    return out


def classification_failed(item: dict | None) -> bool:
    if not item:
        return True
    return (
        item.get("mismatch_type") == "classification_failed"
        or str(item.get("rationale", "")).startswith("classification failed:")
        or item.get("confidence") in {0, "0", 0.0}
    )


def append_jsonl(path: Path, items: list[dict]) -> None:
    if not items:
        return
    with path.open("a") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")


def extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    match = re.search(r"\{.*\}", text, flags=re.S)
    if match:
        text = match.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        upper = text.upper()
        for category in FP_CATEGORY_ORDER:
            if category in upper:
                return {
                    "category": category,
                    "mismatch_type": "parsed_from_non_json_response",
                    "study_type": "",
                    "confidence": 0.6,
                    "rationale": text[:260],
                }
        lower = text.lower()
        keyword_map = [
            ("MODELING_ASSUMED_INPUT", ["model", "simulation", "assumed", "forecast", "seir", "sir"]),
            ("DIFFERENT_QUANTITY", ["different quantity", "incubation", "generation", "mortality", "death", "risk factor", "rt", "re "]),
            ("NON_PRIMARY_STUDY", ["review", "case report", "case series", "editorial", "commentary", "letter", "laboratory", "genomic"]),
            ("ELIGIBILITY_SCOPE", ["scope", "population", "variant", "period", "denominator", "geograph", "outside"]),
            ("ABSTRACT_LIMITATION", ["no abstract", "not verifiable", "abstract", "sparse"]),
            ("PARAMETER_ABSENT", ["absent", "not present", "does not report", "no target"]),
        ]
        for category, needles in keyword_map:
            if any(needle in lower for needle in needles):
                return {
                    "category": category,
                    "mismatch_type": "inferred_from_non_json_response",
                    "study_type": "",
                    "confidence": 0.45,
                    "rationale": text[:260],
                }
        raise


def fp_prompt(row: dict[str, str], abstract: str) -> list[dict[str, str]]:
    parameter_hint = {
        "Serial interval": "serial interval, defined as time between symptom onset in an infector and infectee; incubation period and generation interval are not the same target unless the source review explicitly accepts them",
        "Reproduction number": "basic reproduction number R0; effective reproduction number Rt/Re, growth rate, or assumed model parameters may be different targets",
        "Fatality": "case fatality rate CFR or infection fatality rate IFR; deaths, mortality risk factors, biomarkers, or severity outcomes are not automatically CFR/IFR estimates",
    }.get(row["parameter"], row["parameter"])
    system = (
        "You are auditing one false-positive record from a systematic-review screening benchmark. "
        "The screening model retained the record, but the source review did not include it. "
        "Classify the single most likely record-level failure cause for this specific profile and target parameter. "
        "Use only the title, journal, target parameter, source-review profile, and abstract. "
        "Return JSON only with keys: category, mismatch_type, study_type, confidence, rationale. "
        "Allowed category values: DIFFERENT_QUANTITY, MODELING_ASSUMED_INPUT, NON_PRIMARY_STUDY, "
        "ELIGIBILITY_SCOPE, ABSTRACT_LIMITATION, PARAMETER_ABSENT, OTHER. "
        "Prefer DIFFERENT_QUANTITY when the paper reports a related but non-target epidemiological quantity. "
        "Prefer MODELING_ASSUMED_INPUT when the parameter is only assumed, simulated, forecast, or fitted as a model input. "
        "Prefer NON_PRIMARY_STUDY for reviews, editorials, commentaries, case reports/series, methods, laboratory, or purely genomic papers. "
        "Prefer ELIGIBILITY_SCOPE when the target parameter appears but the population, disease variant, geography, denominator, date range, or estimand is outside the source-review scope. "
        "Prefer ABSTRACT_LIMITATION when the abstract is missing or too sparse to verify eligibility. "
        "Prefer PARAMETER_ABSENT only when neither the target nor a related parameter is present."
    )
    user = (
        f"Profile: {row['profile']}\n"
        f"Source review: {row['source_review']}\n"
        f"Disease: {row['disease']}\n"
        f"Target parameter: {parameter_hint}\n"
        f"PMID: {row['pmid']}\n"
        f"Title: {row['title']}\n"
        f"Journal: {row['journal']}\n"
        f"Screening scores: disease={row['disease_score']}, population={row['population_score']}, "
        f"location={row['location_score']}, evidence={row['evidence_score']}, parameter={row['parameter_score']}\n"
        f"Abstract: {(abstract or '(no abstract available)')[:1800]}\n"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def call_llm(row: dict[str, str], abstract: str, base_url: str, api_key: str, model: str) -> dict:
    body = {
        "model": model,
        "enable_thinking": False,
        "messages": fp_prompt(row, abstract),
        "temperature": 0,
        "max_tokens": 160,
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(body).encode()
    url = base_url.rstrip("/") + "/chat/completions"
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                content = json.loads(resp.read())["choices"][0]["message"]["content"]
            parsed = extract_json(content)
            category = str(parsed.get("category", "OTHER")).strip().upper()
            if category not in FP_CATEGORIES:
                category = "OTHER"
            return {
                "record_id": record_id(row),
                "profile": row["profile"],
                "parameter": row["parameter"],
                "disease": row["disease"],
                "pmid": row["pmid"],
                "source_review": row["source_review"],
                "title": row["title"],
                "category": category,
                "mismatch_type": str(parsed.get("mismatch_type", ""))[:120],
                "study_type": str(parsed.get("study_type", ""))[:80],
                "confidence": parsed.get("confidence", None),
                "rationale": str(parsed.get("rationale", ""))[:300],
                "classifier": model,
            }
        except Exception as exc:  # noqa: BLE001
            if attempt == 2:
                return {
                    "record_id": record_id(row),
                    "profile": row["profile"],
                    "parameter": row["parameter"],
                    "disease": row["disease"],
                    "pmid": row["pmid"],
                    "source_review": row["source_review"],
                    "title": row["title"],
                    "category": "OTHER",
                    "mismatch_type": "classification_failed",
                    "study_type": "",
                    "confidence": 0,
                    "rationale": f"classification failed: {type(exc).__name__}",
                    "classifier": model,
                }
            time.sleep(0.7 * (attempt + 1))
    raise AssertionError("unreachable")


def classify_fp_records(fps: list[dict[str, str]], abstracts: dict[str, str], workers: int) -> dict[str, dict]:
    load_env_local()
    cache = load_jsonl(FP_TAG_JSONL)
    missing = [row for row in fps if classification_failed(cache.get(record_id(row)))]
    print(f"FP record-level tags: cached={len(cache)} missing={len(missing)} total={len(fps)}")
    if not missing:
        return cache

    base_url = os.environ.get("BAILIAN_BASE_URL")
    api_key = os.environ.get("BAILIAN_API_KEY")
    model = os.environ.get("BAILIAN_MODEL", "qwen3.6-plus")
    if not base_url or not api_key:
        raise RuntimeError("BAILIAN_BASE_URL/BAILIAN_API_KEY missing; cannot classify missing FP records")

    completed: list[dict] = []
    t0 = time.time()
    last_report = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {
            pool.submit(call_llm, row, abstracts.get(row["pmid"], ""), base_url, api_key, model): record_id(row)
            for row in missing
        }
        for i, fut in enumerate(as_completed(futs), start=1):
            item = fut.result()
            cache[item["record_id"]] = item
            completed.append(item)
            if len(completed) >= 50:
                append_jsonl(FP_TAG_JSONL, completed)
                completed.clear()
            if i - last_report >= 100:
                last_report = i
                print(f"  classified {i}/{len(missing)} missing FP records in {time.time() - t0:.0f}s", flush=True)
    append_jsonl(FP_TAG_JSONL, completed)
    return cache


def write_fp_taxonomy(fps: list[dict[str, str]], tags: dict[str, dict]) -> pd.DataFrame:
    rows = []
    for row in fps:
        rid = record_id(row)
        tag = tags.get(rid, {})
        cat = tag.get("category", "OTHER")
        if cat not in FP_CATEGORIES:
            cat = "OTHER"
        rows.append(
            {
                "record_id": rid,
                "profile": row["profile"],
                "disease": row["disease"],
                "parameter": row["parameter"],
                "source_review": row["source_review"],
                "pmid": row["pmid"],
                "publication_year": row["publication_year"],
                "title": row["title"],
                "llm_tier": row["llm_tier"],
                "overall_score": row["overall_score"],
                "disease_score": row["disease_score"],
                "population_score": row["population_score"],
                "location_score": row["location_score"],
                "evidence_score": row["evidence_score"],
                "parameter_score": row["parameter_score"],
                "category": cat,
                "category_label": FP_CATEGORIES[cat],
                "mismatch_type": tag.get("mismatch_type", ""),
                "study_type": tag.get("study_type", ""),
                "confidence": tag.get("confidence", ""),
                "rationale": tag.get("rationale", ""),
                "classifier": tag.get("classifier", ""),
            }
        )
    df = pd.DataFrame(rows)
    df.to_csv(FP_TAXONOMY_CSV, index=False)
    return df


def fn_category(row: dict[str, str]) -> tuple[str, str]:
    title = row["title"].lower()
    parameter = row["parameter"]
    if parameter == "Serial interval":
        if any(term in title for term in ["systematic review", "review and meta-analysis", "status of human monkeypox"]):
            return "NON_PRIMARY_OR_TANGENTIAL", "Source review included a secondary or broad review-like record."
        if any(term in title for term in ["incubation period", "clinical severity"]):
            return "SPARSE_OR_BORDERLINE", "Title/abstract emphasized a related or downstream quantity rather than serial interval."
        return "FULLTEXT_ONLY", "Disease and empirical evidence were visible, but the serial-interval signal was absent or weak in the abstract."
    if parameter == "Reproduction number":
        if "viral kinetics" in title:
            return "NON_PRIMARY_OR_TANGENTIAL", "Source-review inclusion is tangential to review-level R0 extraction from title/abstract evidence."
        if "power-law distribution" in title:
            return "SPARSE_OR_BORDERLINE", "Title/abstract indicated modelling but did not clearly expose an eligible R0 estimate."
        return "FULLTEXT_ONLY", "The R0 signal was not sufficiently explicit in title/abstract metadata."
    if parameter == "Fatality":
        if any(term in title for term in ["contamination", "suicide", "saliva", "seminal fluids"]):
            return "NON_PRIMARY_OR_TANGENTIAL", "Source-review inclusion was tangential or case/lab focused rather than clearly fatality-focused from metadata."
        return "SPARSE_OR_BORDERLINE", "Fatality evidence was sparse, denominator-specific, or not explicit in the abstract."
    return "SPARSE_OR_BORDERLINE", "Weak title/abstract evidence."


def write_fn_taxonomy(fns: list[dict[str, str]]) -> pd.DataFrame:
    rows = []
    for row in fns:
        cat, note = fn_category(row)
        rows.append(
            {
                "record_id": record_id(row),
                "profile": row["profile"],
                "disease": row["disease"],
                "parameter": row["parameter"],
                "source_review": row["source_review"],
                "pmid": row["pmid"],
                "publication_year": row["publication_year"],
                "title": row["title"],
                "llm_tier": row["llm_tier"],
                "disease_score": row["disease_score"],
                "evidence_score": row["evidence_score"],
                "parameter_score": row["parameter_score"],
                "category": cat,
                "category_label": FN_CATEGORIES[cat],
                "audit_note": note,
            }
        )
    df = pd.DataFrame(rows)
    df.to_csv(FN_TAXONOMY_CSV, index=False)
    return df


def coding_category(row: pd.Series) -> tuple[str, str]:
    project = str(row.get("project", row.get("profile", "")))
    topic = str(row.get("topic", ""))
    abs_e2e = float(row["abs_delta_e2e_vs_sr"])
    abs_module = float(row["abs_delta_module_vs_sr"])
    note = ""
    if project == "MP10":
        return "POOLING_INPUT_MISSING", "High serial-interval estimates used by the source review lacked usable E2E SE/sample-size inputs."
    if project == "P16":
        return "POOLING_HETEROGENEITY", "R0 estimates were heterogeneous and E2E pooling remained lower after closed/special-context filtering."
    if project == "MP8":
        return "PROFILE_DATE_FILTER", "Clade/date filtering left a sparse fatality input set; CI still overlapped the source-review interval."
    if project == "MP12":
        return "SPARSE_SUBGROUP_INPUT", "Paediatric fatality target used sparse E2E inputs with very wide uncertainty."
    if project in {"P7", "P8", "P15", "P17"}:
        return "R0_CONTEXT_ALIGNMENT", "General-population R0 context filtering affected the pooled input set."
    if project in {"P5", "P6", "MP4"} or topic == "fatality":
        if abs_e2e > 0.5:
            note = "Fatality denominator or subgroup alignment drove a moderate point shift."
            return "DENOMINATOR_ALIGNMENT", note
    if abs_e2e <= abs_module:
        return "NO_MATERIAL_E2E_ERROR", "E2E estimate was at least as close to the source review as the stage-specific module."
    return "SMALL_EXTRACTION_OR_POOLING_DRIFT", "E2E deviation exceeded the module deviation but remained small or within the source-review interval."


def coding_parameter_group(topic: object) -> str:
    mapping = {
        "serial_interval": "Serial interval",
        "reproduction_number": "Reproduction number",
        "fatality": "Fatality",
    }
    return mapping.get(str(topic), str(topic))


def write_coding_taxonomy() -> pd.DataFrame:
    out = pd.read_csv(E2E_TRACKING_CSV)
    out["profile"] = out["profile"].astype(str).str.upper()
    out["parameter_group"] = out["topic"].map(coding_parameter_group)
    out["abs_delta_module_vs_sr"] = (pd.to_numeric(out["previous_module_point"]) - pd.to_numeric(out["sr_point"])).abs()
    out["abs_delta_e2e_vs_sr"] = pd.to_numeric(out["abs_delta_e2e_vs_sr"])

    if E2E_AUDIT_CSV.exists():
        audit = pd.read_csv(E2E_AUDIT_CSV)
        audit["profile"] = audit["profile"].astype(str).str.upper()
        audit_cols = [
            "profile",
            "point_in_sr_ci",
            "interval_overlaps_sr_ci",
            "audit_status",
            "audit_reason",
            "alignment_note",
        ]
        out = out.merge(audit[audit_cols], on="profile", how="left", validate="one_to_one")
    else:
        for col in ["point_in_sr_ci", "interval_overlaps_sr_ci", "audit_status", "audit_reason", "alignment_note"]:
            out[col] = ""

    rows = []
    for _, row in out.iterrows():
        cat, note = coding_category(row)
        rows.append(
            {
                "project": row["profile"],
                "disease": row["disease"],
                "parameter_group": row["parameter_group"],
                "source_review": row["article"],
                "sr": row["sr_point"],
                "module": row["previous_module_point"],
                "e2e": row["e2e_pooled_mean"],
                "abs_delta_module_vs_sr": row["abs_delta_module_vs_sr"],
                "abs_delta_e2e_vs_sr": row["abs_delta_e2e_vs_sr"],
                "point_in_sr_ci": row.get("point_in_sr_ci", ""),
                "interval_overlaps_sr_ci": row.get("interval_overlaps_sr_ci", ""),
                "audit_status": row.get("audit_status", ""),
                "audit_reason": row.get("audit_reason", ""),
                "alignment_note": row.get("alignment_note", ""),
                "pooled_input_rows": row.get("pooled_input_rows", ""),
                "pooled_input_pmids": row.get("pooled_input_pmids", ""),
                "covered_pmid_count": row.get("covered_pmid_count", ""),
                "missing_selected_pmid_count": row.get("missing_selected_pmid_count", ""),
                "category": cat,
                "audit_note": note,
            }
        )
    result = pd.DataFrame(rows)
    result.to_csv(CODING_TAXONOMY_CSV, index=False)
    return result


def setup_plot_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "DejaVu Sans", "sans-serif"],
            "font.size": 8.2,
            "axes.labelsize": 8.4,
            "xtick.labelsize": 7.5,
            "ytick.labelsize": 7.8,
            "legend.fontsize": 7.6,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.linewidth": 0.75,
        }
    )


def savefig(fig: plt.Figure, name: str) -> None:
    pdf = FIGDIR / f"{name}.pdf"
    png = FIGDIR / f"{name}.png"
    fig.savefig(pdf, bbox_inches="tight", pad_inches=0.04)
    fig.savefig(png, bbox_inches="tight", pad_inches=0.04, dpi=300)
    plt.close(fig)
    print(f"saved {pdf.relative_to(ROOT)}")


def plot_screening_overview(fp_df: pd.DataFrame, fn_df: pd.DataFrame) -> None:
    setup_plot_style()
    fig, axes = plt.subplots(1, 2, figsize=(7.35, 3.05), dpi=180, gridspec_kw={"width_ratios": [2.6, 1.45]})
    ax = axes[0]
    fp_counts = fp_df["category"].value_counts().reindex(FP_CATEGORY_ORDER, fill_value=0)
    ordered = sorted([c for c in FP_CATEGORY_ORDER if fp_counts[c] > 0], key=lambda c: fp_counts[c], reverse=True)
    labels = [FP_CATEGORIES[c] for c in ordered]
    vals = [fp_counts[c] for c in ordered]
    colors = [FP_COLORS[c] for c in ordered]
    y = np.arange(len(vals))
    ax.barh(y, vals, color=colors, edgecolor="white", linewidth=0.7)
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlabel("Records")
    ax.set_xlim(0, max(vals) * 1.20)
    total = int(sum(vals))
    for yi, val in zip(y, vals):
        ax.text(val + max(vals) * 0.025, yi, f"{val:,} ({val / total * 100:.1f}%)", va="center", fontsize=7.7)
    ax.text(0.0, 1.05, f"a  False positives (n={total:,})", transform=ax.transAxes, fontweight="bold", fontsize=9.0)
    ax.grid(axis="x", color="#E8E8E8", lw=0.55)

    ax = axes[1]
    fn_counts = fn_df["category"].value_counts().reindex(FN_CATEGORY_ORDER, fill_value=0)
    fn_order = [c for c in FN_CATEGORY_ORDER if fn_counts[c] > 0]
    fn_vals = [int(fn_counts[c]) for c in fn_order]
    fn_labels = [
        "Full-text-only\nparameter evidence" if c == "FULLTEXT_ONLY"
        else "Sparse or\nborderline evidence" if c == "SPARSE_OR_BORDERLINE"
        else "Non-primary or\ntangential inclusion"
        for c in fn_order
    ]
    y = np.arange(len(fn_vals))
    ax.barh(y, fn_vals, color=[FN_COLORS[c] for c in fn_order], edgecolor="white", linewidth=0.7)
    ax.set_yticks(y)
    ax.set_yticklabels(fn_labels)
    ax.invert_yaxis()
    ax.set_xlabel("Records")
    ax.set_xlim(0, max(fn_vals) * 1.34)
    fn_total = sum(fn_vals)
    for yi, val in zip(y, fn_vals):
        ax.text(val + max(fn_vals) * 0.055, yi, f"{val} ({val / fn_total * 100:.0f}%)", va="center", fontsize=7.5)
    ax.text(0.0, 1.05, f"b  False negatives (n={fn_total})", transform=ax.transAxes, fontweight="bold", fontsize=9.0)
    ax.grid(axis="x", color="#E8E8E8", lw=0.55)
    fig.subplots_adjust(wspace=0.78, bottom=0.20, top=0.87, left=0.24, right=0.96)
    savefig(fig, "error_screening_fp_fn_overview")


def plot_fp_domain_heatmap(fp_df: pd.DataFrame) -> None:
    setup_plot_style()
    domains = ["Serial interval", "Reproduction number", "Fatality"]
    cats = [
        c
        for c in [
            "MODELING_ASSUMED_INPUT",
            "DIFFERENT_QUANTITY",
            "ELIGIBILITY_SCOPE",
            "NON_PRIMARY_STUDY",
            "ABSTRACT_LIMITATION",
            "PARAMETER_ABSENT",
            "OTHER",
        ]
        if (fp_df["category"] == c).any()
    ]
    matrix = np.zeros((len(domains), len(cats)), dtype=int)
    for i, domain in enumerate(domains):
        sub = fp_df[fp_df["parameter"] == domain]
        counts = sub["category"].value_counts()
        for j, cat in enumerate(cats):
            matrix[i, j] = int(counts.get(cat, 0))
    pct = np.divide(matrix, matrix.sum(axis=1, keepdims=True), out=np.zeros_like(matrix, dtype=float), where=matrix.sum(axis=1, keepdims=True) != 0) * 100
    cmap = LinearSegmentedColormap.from_list("soft_blues", ["#F7FAFC", "#D9E5EF", "#8FB6D6", "#3F6F9C"])
    fig, ax = plt.subplots(figsize=(7.55, 2.85), dpi=180)
    im = ax.imshow(pct, cmap=cmap, vmin=0, vmax=max(65, math.ceil(pct.max() / 10) * 10), aspect="auto")
    ax.set_xticks(range(len(cats)))
    ax.set_xticklabels([FP_SHORT_LABELS[c] for c in cats], rotation=0, ha="center")
    ax.set_yticks(range(len(domains)))
    ax.set_yticklabels(domains)
    for i in range(len(domains)):
        for j in range(len(cats)):
            val = matrix[i, j]
            text_color = "white" if pct[i, j] > 42 else "#1f1f1f"
            ax.text(j, i, f"{val:,}\n{pct[i, j]:.0f}%", ha="center", va="center", color=text_color, fontsize=7.0)
        ax.text(len(cats) + 0.03, i, f"n={matrix[i].sum():,}", ha="left", va="center", fontsize=7.8, color="#444")
    ax.set_xlim(-0.5, len(cats) + 0.72)
    cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.015)
    cbar.set_label("% within parameter domain")
    cbar.ax.tick_params(labelsize=7.2)
    fig.subplots_adjust(left=0.18, right=0.92, bottom=0.26, top=0.96)
    savefig(fig, "error_fp_record_domain_heatmap")


def compact_source_review_label(value: object) -> str:
    text = str(value).replace(",", "").strip()
    text = text.replace(" et al. ", " ")
    text = text.replace("Sanchez Clemente", "S. Clemente")
    text = text.replace("Diaz Brochero", "D. Brochero")
    return text


def plot_coding_error(coding_df: pd.DataFrame) -> None:
    setup_plot_style()
    df = coding_df.copy()
    df["abs_delta_e2e_vs_sr"] = pd.to_numeric(df["abs_delta_e2e_vs_sr"])
    df["abs_delta_module_vs_sr"] = pd.to_numeric(df["abs_delta_module_vs_sr"])
    panel_specs = [
        ("Serial interval", "days"),
        ("Reproduction number", "absolute R"),
        ("Fatality", "percentage points"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(7.7, 4.55), dpi=180)
    handles = None
    for ax, (domain, xlabel) in zip(axes, panel_specs):
        sub = df[df["parameter_group"] == domain].sort_values("abs_delta_e2e_vs_sr", ascending=True)
        y = np.arange(len(sub))
        ax.hlines(y, sub["abs_delta_module_vs_sr"], sub["abs_delta_e2e_vs_sr"], color="#C8C8C8", lw=0.85, zorder=0)
        h1 = ax.scatter(sub["abs_delta_module_vs_sr"], y, s=22, color="#4C78A8", label="Module", zorder=2)
        h2 = ax.scatter(sub["abs_delta_e2e_vs_sr"], y, s=22, color="#F58518", label="E2E", zorder=2)
        handles = (h1, h2)
        ax.set_yticks(y)
        ax.set_yticklabels([compact_source_review_label(v) for v in sub["source_review"]], fontsize=7.2)
        ax.set_xlabel(xlabel)
        ax.set_title(domain.replace("Reproduction number", "R number"), fontsize=8.8, fontweight="bold", pad=5)
        xmax = max(float(sub["abs_delta_module_vs_sr"].max()), float(sub["abs_delta_e2e_vs_sr"].max()))
        xpad = max(0.05, xmax * 0.14)
        ax.set_xlim(-0.02 * xmax, xmax + xpad)
        ax.grid(axis="x", color="#E6E6E6", lw=0.6)
        for yi, (_, row) in enumerate(sub.iterrows()):
            if row["category"] in {"POOLING_INPUT_MISSING", "PROFILE_DATE_FILTER", "SPARSE_SUBGROUP_INPUT", "POOLING_HETEROGENEITY"} or row["abs_delta_e2e_vs_sr"] >= 1.0:
                ax.text(max(row["abs_delta_module_vs_sr"], row["abs_delta_e2e_vs_sr"]) + max(0.025, xmax * 0.025), yi, "*", va="center", fontsize=9.5, color="#333")
    if handles:
        fig.legend(handles, ["Module", "E2E"], frameon=False, loc="upper center", ncol=2, bbox_to_anchor=(0.56, 0.985))
    fig.text(0.05, 0.035, "* Audited large-deviation source reviews; full notes are provided in the source-data table.", ha="left", va="bottom", fontsize=7.0, color="#555")
    fig.subplots_adjust(left=0.08, right=0.99, bottom=0.17, top=0.86, wspace=0.58)
    savefig(fig, "error_coding_review_deviation")


def write_summary(fp_df: pd.DataFrame, fn_df: pd.DataFrame, coding_df: pd.DataFrame) -> dict:
    summary = {
        "screening": {
            "fp_records": int(len(fp_df)),
            "fp_unique_pmids": int(fp_df["pmid"].nunique()),
            "fn_records": int(len(fn_df)),
            "fn_unique_pmids": int(fn_df["pmid"].nunique()),
            "fp_by_category": fp_df["category"].value_counts().reindex(FP_CATEGORY_ORDER, fill_value=0).astype(int).to_dict(),
            "fn_by_category": fn_df["category"].value_counts().reindex(FN_CATEGORY_ORDER, fill_value=0).astype(int).to_dict(),
            "fp_by_parameter_category": {
                parameter: group["category"].value_counts().reindex(FP_CATEGORY_ORDER, fill_value=0).astype(int).to_dict()
                for parameter, group in fp_df.groupby("parameter")
            },
            "fn_by_parameter_category": {
                parameter: group["category"].value_counts().reindex(FN_CATEGORY_ORDER, fill_value=0).astype(int).to_dict()
                for parameter, group in fn_df.groupby("parameter")
            },
        },
        "coding": {
            "reviews": int(len(coding_df)),
            "category_counts": coding_df["category"].value_counts().to_dict(),
            "e2e_median_abs_delta": float(pd.to_numeric(coding_df["abs_delta_e2e_vs_sr"]).median()),
            "module_median_abs_delta": float(pd.to_numeric(coding_df["abs_delta_module_vs_sr"]).median()),
        },
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--skip-fp-classification", action="store_true")
    args = parser.parse_args()

    SOURCE.mkdir(parents=True, exist_ok=True)
    FIGDIR.mkdir(parents=True, exist_ok=True)

    with SCREENING_CSV.open(newline="") as f:
        rows = list(csv.DictReader(f))
    fps = [row for row in rows if row["outcome"] == "FP"]
    fns = [row for row in rows if row["outcome"] == "FN"]
    if len(fps) != 2727 or len(fns) != 27:
        raise RuntimeError(f"Unexpected FP/FN counts: FP={len(fps)} FN={len(fns)}")

    abstracts = load_abstracts()
    tags = load_jsonl(FP_TAG_JSONL)
    has_missing_or_failed = any(classification_failed(tags.get(record_id(row))) for row in fps)
    if not args.skip_fp_classification and has_missing_or_failed:
        tags = classify_fp_records(fps, abstracts, args.workers)
    remaining = len([row for row in fps if classification_failed(tags.get(record_id(row)))])
    if remaining:
        raise RuntimeError(f"FP record tags incomplete or failed: remaining={remaining}")

    fp_df = write_fp_taxonomy(fps, tags)
    fn_df = write_fn_taxonomy(fns)
    coding_df = write_coding_taxonomy()
    plot_screening_overview(fp_df, fn_df)
    plot_fp_domain_heatmap(fp_df)
    plot_coding_error(coding_df)
    summary = write_summary(fp_df, fn_df, coding_df)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
