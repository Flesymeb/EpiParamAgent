"""Update the screening-to-coding E2E pooled-mean tracking table.

The table is project-level: one row per source-review profile in
docs/paper/source_data/coding_estimate_intervals.csv. Completed runs are pooled
with the same defaults as tools/scripts/evaluate_coding.py.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shlex
import subprocess
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "e2e" / "runs" / "screen_to_coding"
SOURCE_DATA = ROOT / "docs" / "paper" / "source_data" / "coding_estimate_intervals.csv"
OFFICIAL_SELECTED_ROOT = RUN_ROOT / "official_qwen36_recall_selected"

sys.path.insert(0, str(ROOT))
from tools.analysis.pooling import enrich_ci, summarize  # noqa: E402


TOPIC_PARAM = {
    "serial_interval": "serial_interval",
    "reproduction_number": "R0",
    "fatality": "CFR",
}
LARGE_DEVIATION_THRESHOLDS = {
    # Absolute thresholds are in each parameter's native unit. Relative
    # threshold is shared, with a minimum absolute delta for fatality to avoid
    # overstating tiny percentage-point changes around very small IFR values.
    "serial_interval": {"abs": 1.0, "rel": 0.20, "label": ">=1 day or >=20%"},
    "reproduction_number": {"abs": 0.5, "rel": 0.20, "label": ">=0.5 R or >=20%"},
    "fatality": {"abs": 2.0, "rel": 0.20, "rel_min_abs": 0.5, "label": ">=2 pp or >=20% with >=0.5 pp"},
}
PARAM_GROUP_TOPIC = {
    "serial interval": "serial_interval",
    "reproduction number": "reproduction_number",
    "fatality": "fatality",
}
IGNORE_RUN_NAME_PARTS = ("dryrun", "debug", "preflight", "limit")
CI_OVERLAP_TOLERANCE = 0.01
CLADE_I_PATTERN = r"(?:^|[^a-z0-9])clade[_\s-]?i(?:[^a-z0-9]|$)|congo[_\s-]?basin|congo basin"
VOC_PATTERN = r"alpha|beta|delta|omicron|variant|voc|ba\."
R0_SPECIAL_CONTEXT_PATTERN = (
    r"cruise|diamond princess|\bship\b|\bprison\b|nursing home|\bhospital\b|healthcare|closed|"
    r"\bairport\b|\bimported\b|\btravel\b|\btraveller\b|\btraveler\b|evacuat|wedding|\bbus\b|"
    r"hypothetical|simulation|developed country|community of 1000"
)
P6_SPECIAL_POPULATION_PATTERN = (
    r"cancer|myeloma|tumou?r|malignan|hemodialysis|dialysis|kidney|renal|ckd|aki|krt|"
    r"cardiogenic|acute limb|stroke|smokers?|obes|diabet|hypertension|copd|"
    r"moderate to severe|severe|critical|icu|intensive|ventilat|pneumonia|comorbid|"
    r"pregnan|elderly|aged|nursing home|long-term care"
)


def _project_num(project: object) -> str:
    value = str(project).strip().lower()
    value = value.removeprefix("mp").removeprefix("p")
    return value


def _norm_pmid(value: object) -> str | None:
    match = re.search(r"\d+", str(value))
    return match.group(0) if match else None


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _run_context(run_dir: Path) -> dict | None:
    summary_path = run_dir / "screen_to_coding_summary.json"
    if summary_path.exists():
        summary = _read_json(summary_path)
        disease = summary.get("disease")
        topic = summary.get("topic")
        project = summary.get("project")
        if disease and topic and project:
            return {
                "disease": str(disease),
                "topic": str(topic),
                "project_num": _project_num(project),
                "summary": summary,
            }

    match = re.search(
        r"(?P<disease>covid19|mpox)_(?P<topic>serial_interval|reproduction_number|fatality)_p(?P<project>\d+)",
        run_dir.name,
    )
    if match:
        return {
            "disease": match.group("disease"),
            "topic": match.group("topic"),
            "project_num": match.group("project"),
            "summary": {},
        }

    match = re.search(r"rescued_(?P<disease>covid19|mpox)_(?P<topic>serial_interval|reproduction_number|fatality)", run_dir.name)
    if match:
        return {
            "disease": match.group("disease"),
            "topic": match.group("topic"),
            "project_num": None,
            "summary": {},
        }
    return None


def _latest_xlsx(run_dir: Path) -> Path | None:
    files = sorted(run_dir.glob("coding_sheet_*.xlsx"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def _running_keys() -> set[tuple[str, str, str]]:
    try:
        proc = subprocess.run(["ps", "-eww", "-o", "cmd"], text=True, capture_output=True, check=False)
    except FileNotFoundError:
        return set()
    keys: set[tuple[str, str, str]] = set()
    for line in proc.stdout.splitlines():
        if "run_screen_to_coding.py" not in line or "python" not in line:
            continue
        try:
            parts = shlex.split(line)
        except ValueError:
            parts = line.split()
        disease = topic = project = None
        for idx, part in enumerate(parts):
            if idx + 1 >= len(parts):
                continue
            if part == "--disease":
                disease = parts[idx + 1]
            elif part == "--topic":
                topic = parts[idx + 1]
            elif part == "--project":
                project = _project_num(parts[idx + 1])
        if disease and topic and project:
            keys.add((disease, topic, project))
    return keys


def _is_running(disease: str, topic: str, project_num: str, running_keys: set[tuple[str, str, str]]) -> bool:
    return (disease, topic, project_num) in running_keys


def _candidate_run_dirs(disease: str, topic: str, project_num: str) -> list[Path]:
    dirs: list[Path] = []
    for run_dir in sorted(RUN_ROOT.iterdir() if RUN_ROOT.exists() else []):
        if not run_dir.is_dir():
            continue
        if any(part in run_dir.name for part in IGNORE_RUN_NAME_PARTS):
            continue
        ctx = _run_context(run_dir)
        if not ctx:
            continue
        if ctx["disease"] == disease and ctx["topic"] == topic and ctx["project_num"] == project_num:
            dirs.append(run_dir)
    def sort_key(path: Path) -> tuple[int, float]:
        # Prefer the full profile run over shard/reverse helper runs when both
        # exist. Shards are still used as record libraries below.
        helper = any(part in path.name for part in ("_shard", "_r2shard", "_reverse"))
        return (1 if helper else 0, -path.stat().st_mtime)

    return sorted(dirs, key=sort_key)


def _library_xlsx_sources(disease: str, topic: str, own_run_dir: Path | None) -> list[Path]:
    own: list[Path] = []
    rest: list[Path] = []
    rescue: list[Path] = []
    for run_dir in sorted(RUN_ROOT.iterdir() if RUN_ROOT.exists() else []):
        if not run_dir.is_dir():
            continue
        if any(part in run_dir.name for part in IGNORE_RUN_NAME_PARTS):
            continue
        ctx = _run_context(run_dir)
        if not ctx or ctx["disease"] != disease or ctx["topic"] != topic:
            continue
        xlsx = _latest_xlsx(run_dir)
        if not xlsx:
            continue
        if own_run_dir and run_dir == own_run_dir:
            own.append(xlsx)
        elif run_dir.name.startswith("rescued_"):
            rescue.append(xlsx)
        else:
            rest.append(xlsx)
    rest = sorted(rest, key=lambda p: p.stat().st_mtime, reverse=True)
    rescue = sorted(rescue, key=lambda p: p.stat().st_mtime, reverse=True)
    return own + rest + rescue


def _read_pmids(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read_gt_pmids(disease: str, topic: str, project_num: str) -> set[str]:
    path = ROOT / "dataset" / disease / "screening" / topic / f"p{project_num}" / "ground_truth.csv"
    if not path.exists():
        return set()
    try:
        df = pd.read_csv(path, dtype=str)
    except Exception:
        return set()
    column = "gt_pmid" if "gt_pmid" in df.columns else "PMID" if "PMID" in df.columns else None
    if not column:
        return set()
    return {pmid for pmid in df[column].map(_norm_pmid).dropna().astype(str)}


def _selected_records(run_dir: Path) -> pd.DataFrame:
    path = run_dir / "screening_selected_records.csv"
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path)
    except Exception:
        return pd.DataFrame()
    if "PMID" not in df.columns:
        return pd.DataFrame()
    df = df.copy()
    df["_pmid"] = df["PMID"].map(_norm_pmid)
    return df[df["_pmid"].notna()]


def _selected_records_from_root(selected_root: Path | None, profile: str) -> tuple[pd.DataFrame, str]:
    if not selected_root:
        return pd.DataFrame(), ""
    path = selected_root / profile / "screening_selected_records.csv"
    if not path.exists():
        return pd.DataFrame(), ""
    try:
        df = pd.read_csv(path, dtype=str, low_memory=False)
    except Exception:
        return pd.DataFrame(), ""
    if "PMID" not in df.columns:
        return pd.DataFrame(), ""
    df = df.copy()
    df["_pmid"] = df["PMID"].map(_norm_pmid)
    df = df[df["_pmid"].notna()].drop_duplicates(subset=["_pmid"], keep="first")
    return df, str(path)


def _profile_selected_pmids(
    profile: str,
    selected_pmids: list[str],
    run_dir: Path | None,
    selected_records: pd.DataFrame | None = None,
) -> tuple[list[str], str]:
    if profile != "MP8":
        return selected_pmids, ""

    selected = selected_records if selected_records is not None else pd.DataFrame()
    if selected.empty and run_dir:
        selected = _selected_records(run_dir)
    if selected.empty or "Create Date" not in selected.columns:
        return selected_pmids, "MP8 date-cutoff filter unavailable; missing screening metadata"

    created = pd.to_datetime(selected["Create Date"], errors="coerce")
    keep = set(selected.loc[created.le(pd.Timestamp("2023-03-20")), "_pmid"].astype(str))
    filtered = [pmid for pmid in selected_pmids if pmid in keep]
    removed = len(selected_pmids) - len(filtered)
    note = f"MP8 Create Date <=2023-03-20 filter removed {removed} selected PMIDs"
    return filtered, note


def _merged_records_for_selected(selected_pmids: list[str], xlsx_sources: list[Path]) -> tuple[pd.DataFrame, list[str]]:
    selected_set = set(selected_pmids)
    selected_order = {pmid: idx for idx, pmid in enumerate(selected_pmids)}
    covered: set[str] = set()
    frames: list[pd.DataFrame] = []
    used_sources: list[str] = []

    for xlsx in xlsx_sources:
        try:
            df = pd.read_excel(xlsx)
        except Exception:
            continue
        if "pmid" not in df.columns:
            continue
        df = df.copy()
        df["pmid"] = df["pmid"].map(_norm_pmid)
        df = df[df["pmid"].isin(selected_set - covered)].copy()
        if df.empty:
            continue
        df["_source_xlsx"] = str(xlsx)
        frames.append(df)
        covered.update(df["pmid"].dropna().astype(str).unique().tolist())
        used_sources.append(str(xlsx))

    if not frames:
        return pd.DataFrame(), used_sources
    merged = pd.concat(frames, ignore_index=True)
    merged["_selected_order"] = merged["pmid"].map(selected_order)
    merged = merged.sort_values(["_selected_order", "pmid"], kind="stable")
    merged = merged.drop(columns=["_selected_order"])
    return merged, used_sources


def _series_to_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.replace(",", "", regex=False), errors="coerce")


def _contains(df: pd.DataFrame, column: str, pattern: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(False, index=df.index)
    return df[column].astype(str).str.contains(pattern, case=False, na=False, regex=True)


def _eq_any(df: pd.DataFrame, column: str, values: set[str]) -> pd.Series:
    if column not in df.columns:
        return pd.Series(False, index=df.index)
    norm_values = {value.lower() for value in values}
    return df[column].astype(str).str.strip().str.lower().isin(norm_values)


def _allowed_values(df: pd.DataFrame, column: str, values: set[str]) -> pd.Series:
    if column not in df.columns:
        return pd.Series(True, index=df.index)
    norm_values = {value.lower() for value in values}
    return df[column].astype(str).str.strip().str.lower().isin(norm_values)


def _contains_any_text(df: pd.DataFrame, columns: tuple[str, ...], pattern: str) -> pd.Series:
    text = pd.Series("", index=df.index)
    for column in columns:
        if column in df.columns:
            text = text + " " + df[column].astype(str)
    return text.str.contains(pattern, case=False, na=False, regex=True)


def _clade_i_mask(df: pd.DataFrame) -> pd.Series:
    return _contains(df, "clade", CLADE_I_PATTERN)


def _p6_general_hfr_mask(df: pd.DataFrame) -> pd.Series:
    hfr = _eq_any(df, "fatality_type", {"HFR"}) | _eq_any(df, "denominator_type", {"hospitalizations"})
    age_overall = _allowed_values(df, "age_group", {"all", "nr", "nan", ""})
    severity_overall = _allowed_values(df, "severity_group", {"all", "nr", "nan", "", "hospitalized"})
    special_population = _contains_any_text(df, ("population", "notes"), P6_SPECIAL_POPULATION_PATTERN)
    return hfr & age_overall & severity_overall & ~special_population


def _secondary_source_mask(df: pd.DataFrame) -> pd.Series:
    return _contains_any_text(
        df,
        ("notes",),
        r"cited|reference statement|not primary|literature statement|who-cited|separate review",
    )


def _sample_size_to_number(value: object) -> float:
    match = re.search(r"\d[\d,]*", str(value))
    if not match:
        return float("nan")
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return float("nan")


def _wilson_ci_percent(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        return float("nan"), float("nan")
    p = successes / total
    denom = 1 + z**2 / total
    centre = (p + z**2 / (2 * total)) / denom
    margin = z * math.sqrt((p * (1 - p) + z**2 / (4 * total)) / total) / denom
    return (centre - margin) * 100.0, (centre + margin) * 100.0


def _fatality_profile_mask(df: pd.DataFrame, disease: str, project_num: str) -> tuple[pd.Series, str]:
    mask = pd.Series(True, index=df.index)
    profile = f"{'MP' if disease == 'mpox' else 'P'}{project_num}"

    if profile == "P4":
        mask &= (
            _contains(df, "fatality_type", r"\bIMV\b|mechanical")
            | _contains(df, "denominator_type", r"\bIMV\b|mechanical")
            | _contains(df, "severity_group", r"\bIMV\b|mechanical")
        )
        return mask, "IMV fatality profile filter"
    if profile == "P5":
        mask &= (
            _eq_any(df, "fatality_type", {"IFR"})
            | _contains(df, "denominator_type", r"estimated_infections|infection")
        )
        return mask, "IFR profile filter"
    if profile == "P6":
        mask &= _p6_general_hfr_mask(df)
        return mask, "general hospitalized fatality profile filter"
    if profile == "MP7":
        mask &= _eq_any(df, "fatality_type", {"CFR"})
        mask &= ~_contains(df, "clade", r"IIb|2022")
        return mask, "pre-2016 CFR profile filter"
    if profile == "MP8":
        mask &= _clade_i_mask(df)
        return mask, "clade I CFR profile filter"
    if profile == "MP12":
        mask &= _contains_any_text(df, ("age_group", "population"), r"child|children|pediatric|paediatric|<18|<16")
        return mask, "pediatric CFR profile filter"

    mask &= _eq_any(df, "fatality_type", {"CFR", "IFR", "HFR", "IMV_fatality_rate", "ICU_fatality_rate"})
    return mask, "generic fatality filter"


def _pool_fatality(df: pd.DataFrame, disease: str, project_num: str) -> dict:
    if df.empty or "point_estimate" not in df.columns:
        return {}

    work = df.copy()
    profile = f"{'MP' if disease == 'mpox' else 'P'}{project_num}"
    work["_point_pct"] = _series_to_number(work["point_estimate"])
    if "unit" in work.columns:
        unit = work["unit"].astype(str).str.strip()
    else:
        unit = pd.Series("", index=work.index)
    if "estimate_measure" in work.columns:
        measure = work["estimate_measure"].astype(str).str.strip().str.lower()
    else:
        measure = pd.Series("", index=work.index)

    # Most fatality codebooks store values as percentages. Convert only when a
    # row is explicitly proportion-like and no percent unit is present.
    proportion_like = measure.isin({"proportion", "rate"}) & ~unit.eq("%") & work["_point_pct"].between(0, 1)
    work.loc[proportion_like, "_point_pct"] = work.loc[proportion_like, "_point_pct"] * 100.0

    measure_mask = measure.isin({"percentage", "proportion", "rate", ""})
    profile_mask, filter_note = _fatality_profile_mask(work, disease, project_num)
    mask = measure_mask & profile_mask & work["_point_pct"].notna()
    if not mask.any():
        mask = measure_mask & work["_point_pct"].notna()
        filter_note = f"{filter_note}; fell back to all fatality percentage/proportion rows"

    if profile == "MP4":
        cfr_mask = _eq_any(work, "fatality_type", {"CFR"})
        denominator_mask = _eq_any(work, "denominator_type", {"confirmed_cases", "PCR_positive"})
        primary_mask = ~_secondary_source_mask(work)
        work["_sample_n"] = work["sample_size"].map(_sample_size_to_number) if "sample_size" in work.columns else np.nan
        aggregate_mask = mask & cfr_mask & denominator_mask & primary_mask & work["_sample_n"].notna()
        if aggregate_mask.any():
            values = work.loc[aggregate_mask, "_point_pct"].astype(float)
            sample_n = work.loc[aggregate_mask, "_sample_n"].astype(float)
            total = int(round(float(sample_n.sum())))
            successes = int(round(float((values / 100.0 * sample_n).sum())))
            mean = successes / total * 100.0 if total else float("nan")
            ci_lower, ci_upper = _wilson_ci_percent(successes, total)
            return {
                "parameter_type": "fatality",
                "estimate_measure": "fatality_rate_percent",
                "pool_method": "profile-filtered aggregate Wilson proportion",
                "pooled_mean": mean,
                "se_pooled": float("nan"),
                "ci_lower": ci_lower,
                "ci_upper": ci_upper,
                "i2": np.nan,
                "tau2": np.nan,
                "p_het": np.nan,
                "n_studies": int(aggregate_mask.sum()),
                "n_excluded": int((~aggregate_mask & measure_mask).sum()),
                "n_imputed": 0,
                "pooled_input_rows": int(aggregate_mask.sum()),
                "pooled_input_pmids": int(work.loc[aggregate_mask, "pmid"].nunique()) if "pmid" in work.columns else np.nan,
                "pooling_warnings": (
                    f"{filter_note}; SR aggregate CFR alignment; "
                    f"Wilson CI from {successes}/{total}; secondary/cited estimates excluded"
                ),
            }

    values = work.loc[mask, "_point_pct"].astype(float)
    if values.empty:
        return {"pooling_warnings": "fatality pooling returned empty"}

    n = int(values.shape[0])
    if profile == "P5":
        mean = float(values.median())
        se = float("nan")
        ci_lower = float("nan")
        ci_upper = float("nan")
        pool_method = "profile-filtered median"
        filter_note = f"{filter_note}; SR median IFR alignment"
    else:
        mean = float(values.mean())
        pool_method = "profile-filtered arithmetic mean"

    if n > 1 and profile != "P5":
        se = float(values.std(ddof=1) / math.sqrt(n))
        ci_lower = mean - 1.96 * se
        ci_upper = mean + 1.96 * se
    elif profile != "P5":
        se = float("nan")
        ci_lower = float("nan")
        ci_upper = float("nan")

    return {
        "parameter_type": "fatality",
        "estimate_measure": "fatality_rate_percent",
        "pool_method": pool_method,
        "pooled_mean": mean,
        "se_pooled": se,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "i2": np.nan,
        "tau2": np.nan,
        "p_het": np.nan,
        "n_studies": n,
        "n_excluded": int((~mask & measure_mask).sum()),
        "n_imputed": 0,
        "pooled_input_rows": n,
        "pooled_input_pmids": int(work.loc[mask, "pmid"].nunique()) if "pmid" in work.columns else np.nan,
        "pooling_warnings": filter_note,
    }


def _pool(df: pd.DataFrame, topic: str, disease: str, project_num: str) -> dict:
    if df.empty:
        return {}
    if topic == "fatality":
        return _pool_fatality(df, disease, project_num)

    work = df.copy()
    filter_notes: list[str] = []
    parameter_type = TOPIC_PARAM.get(topic)
    output_parameter_type = parameter_type
    estimate_measure = "mean"

    profile = f"{'MP' if disease == 'mpox' else 'P'}{project_num}"
    if profile == "P11" and topic == "serial_interval":
        voc_mask = _contains_any_text(
            work,
            ("region", "estimation_period", "population", "method", "notes"),
            VOC_PATTERN,
        )
        if voc_mask.any():
            work = work[voc_mask].copy()
            filter_notes.append("VOC/variant serial-interval filter")

    if disease == "covid19" and topic == "reproduction_number":
        r0_mask = pd.Series(True, index=work.index)
        if "parameter_type" in work.columns:
            r0_mask &= work["parameter_type"].astype(str).str.strip().str.lower().eq("r0")
        if "estimate_measure" in work.columns:
            measure = work["estimate_measure"].astype(str).str.strip().str.lower()
            r0_mask &= measure.isin({"mean", "point_estimate"})
        r0_work = work[r0_mask].copy()
        if not r0_work.empty:
            point_mask = r0_work["estimate_measure"].astype(str).str.strip().str.lower().eq("point_estimate")
            r0_work.loc[point_mask, "estimate_measure"] = "mean"
            general_context = ~_contains_any_text(
                r0_work,
                ("region", "estimation_period", "population", "method", "method_notes"),
                R0_SPECIAL_CONTEXT_PATTERN,
            )
            if general_context.any():
                removed = int((~general_context).sum())
                r0_work = r0_work[general_context].copy()
                if removed:
                    filter_notes.append(f"general-population R0 context filter removed {removed} closed/special-context rows")
            work = r0_work
            parameter_type = None
            output_parameter_type = "R0"
            filter_notes.append("COVID-19 R0 mean/point_estimate filter")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        summary = summarize(
            enrich_ci(work),
            parameter_type=parameter_type,
            estimate_measure=estimate_measure,
            include_median=False,
            impute_missing_se=True,
            method="random",
        )
    if summary.empty:
        if topic == "reproduction_number":
            with warnings.catch_warnings(record=True) as caught_fallback:
                warnings.simplefilter("always")
                summary = summarize(
                    enrich_ci(df),
                    parameter_type=None,
                    estimate_measure=None,
                    include_median=False,
                    impute_missing_se=True,
                    method="random",
                )
            if not summary.empty:
                row = summary.iloc[0].to_dict()
                return {
                    "parameter_type": "reproduction_number",
                    "estimate_measure": "all_available",
                    "pool_method": "random",
                    "pooled_mean": row.get("pooled_mean"),
                    "se_pooled": row.get("se_pooled"),
                    "ci_lower": row.get("ci_lower"),
                    "ci_upper": row.get("ci_upper"),
                    "i2": row.get("i2"),
                    "tau2": row.get("tau2"),
                    "p_het": row.get("p_het"),
                    "n_studies": row.get("n_studies"),
                    "n_excluded": row.get("n_excluded"),
                    "n_imputed": row.get("n_imputed"),
                    "pooled_input_rows": int(len(work)),
                    "pooled_input_pmids": int(work["pmid"].nunique()) if "pmid" in work.columns else np.nan,
                    "pooling_warnings": "R0 mean filter empty; fell back to all reproduction-number records | "
                    + " | ".join(filter_notes + [str(w.message) for w in caught + caught_fallback]),
                }
        return {"pooling_warnings": "summarize returned empty"}
    row = summary.iloc[0].to_dict()
    mask = pd.Series(True, index=work.index)
    if "parameter_type" in work.columns and parameter_type:
        mask &= work["parameter_type"].astype(str).str.strip().str.lower().eq(parameter_type.lower())
    if "estimate_measure" in work.columns:
        mask &= work["estimate_measure"].astype(str).str.strip().str.lower().eq(estimate_measure)
    return {
        "parameter_type": output_parameter_type,
        "estimate_measure": estimate_measure,
        "pool_method": "random",
        "pooled_mean": row.get("pooled_mean"),
        "se_pooled": row.get("se_pooled"),
        "ci_lower": row.get("ci_lower"),
        "ci_upper": row.get("ci_upper"),
        "i2": row.get("i2"),
        "tau2": row.get("tau2"),
        "p_het": row.get("p_het"),
        "n_studies": row.get("n_studies"),
        "n_excluded": row.get("n_excluded"),
        "n_imputed": row.get("n_imputed"),
        "pooled_input_rows": int(mask.sum()),
        "pooled_input_pmids": int(work.loc[mask, "pmid"].nunique()) if "pmid" in work.columns else np.nan,
        "pooling_warnings": " | ".join(filter_notes + [str(w.message) for w in caught]),
    }


def _fmt_num(value: object, digits: int = 4) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return round(v, digits)


def _sr_deviation_flag(
    topic: str,
    pooled_mean: float | None,
    ci_lower: float | None,
    ci_upper: float | None,
    delta: float | None,
    sr: float | None,
    sr_lo: float | None,
    sr_hi: float | None,
) -> tuple[str, float | None, str]:
    if pooled_mean is None or delta is None or sr is None:
        return "", None, ""
    threshold = LARGE_DEVIATION_THRESHOLDS.get(topic)
    if not threshold:
        return "", None, ""
    abs_delta = abs(delta)
    rel_delta = abs_delta / abs(sr) if sr else None
    if sr_lo is not None and sr_hi is not None and sr_lo <= pooled_mean <= sr_hi:
        return "", _fmt_num(rel_delta, 4) if rel_delta is not None else None, str(threshold["label"])
    if None not in (ci_lower, ci_upper, sr_lo, sr_hi):
        if max(float(ci_lower), float(sr_lo)) <= min(float(ci_upper), float(sr_hi)) + CI_OVERLAP_TOLERANCE:
            return "", _fmt_num(rel_delta, 4) if rel_delta is not None else None, str(threshold["label"])
    abs_hit = abs_delta >= float(threshold["abs"])
    rel_min_abs = float(threshold.get("rel_min_abs", 0.0))
    rel_hit = rel_delta is not None and rel_delta >= float(threshold["rel"]) and abs_delta >= rel_min_abs
    flag = "large" if abs_hit or rel_hit else ""
    return flag, _fmt_num(rel_delta, 4) if rel_delta is not None else None, str(threshold["label"])


def build_tracking(selected_root: Path | None = OFFICIAL_SELECTED_ROOT) -> pd.DataFrame:
    source = pd.read_csv(SOURCE_DATA)
    running_keys = _running_keys()
    rows: list[dict] = []

    for _, src in source.iterrows():
        disease = str(src["disease"]).strip()
        topic = PARAM_GROUP_TOPIC[str(src["parameter_group"]).strip().lower()]
        project_num = _project_num(src["project"])
        profile = f"{'MP' if disease == 'mpox' else 'P'}{project_num}"
        run_dirs = _candidate_run_dirs(disease, topic, project_num)
        run_dir = run_dirs[0] if run_dirs else None
        summary = _run_context(run_dir)["summary"] if run_dir else {}
        xlsx = _latest_xlsx(run_dir) if run_dir else None
        running = _is_running(disease, topic, project_num, running_keys)
        selected_records, selected_source = _selected_records_from_root(selected_root, profile)
        if not selected_records.empty:
            selected_pmids = selected_records["_pmid"].astype(str).tolist()
            gt_pmids = _read_gt_pmids(disease, topic, project_num)
            selected_set = set(selected_pmids)
            selected_rows_value = len(selected_pmids)
            gt_total_value = len(gt_pmids)
            screening_tp_value = len(selected_set & gt_pmids)
            screening_fp_value = len(selected_set - gt_pmids)
            screening_fn_value = len(gt_pmids - selected_set)
            coding_input_count_value = selected_rows_value
        else:
            selected_pmids = _read_pmids(run_dir / "screened_sp_pmids.txt") if run_dir else []
            selected_rows_value = summary.get("selected_rows")
            gt_total_value = summary.get("gt_total")
            screening_tp_value = summary.get("screening_tp_in_selected")
            screening_fp_value = summary.get("screening_fp_in_selected")
            screening_fn_value = summary.get("screening_fn_not_selected")
            coding_input_count_value = summary.get("coding_input_count", summary.get("selected_rows"))
        pooling_selected_pmids, selected_filter_note = _profile_selected_pmids(
            profile,
            selected_pmids,
            run_dir,
            selected_records=selected_records,
        )

        if running:
            status = "running"
        elif xlsx:
            status = "completed"
        elif summary.get("coding_ran"):
            status = "completed_no_records"
        elif run_dir:
            status = "prepared"
        else:
            status = "pending"

        # Avoid reporting misleading pooled means from partial reused records while
        # the profile's own coding job is still running or not yet completed.
        if status in {"completed", "completed_no_records"} and pooling_selected_pmids:
            xlsx_sources = _library_xlsx_sources(disease, topic, run_dir)
            merged, used_sources = _merged_records_for_selected(pooling_selected_pmids, xlsx_sources)
            pool = _pool(
                merged.drop(columns=["_source_xlsx"], errors="ignore"),
                topic,
                disease,
                project_num,
            ) if not merged.empty else {}
            if selected_filter_note:
                existing_warning = str(pool.get("pooling_warnings", "") or "")
                pool["pooling_warnings"] = " | ".join(part for part in (selected_filter_note, existing_warning) if part)
        else:
            merged = pd.DataFrame()
            used_sources = []
            pool = {}

        # Profile-level completion should reflect the final merged E2E result,
        # not only whether this run directory produced its own coding sheet.
        # Some rescue/fix runs intentionally process only the PMIDs not already
        # covered by shard runs; if those new PMIDs yield no records but reused
        # records still pool successfully, the profile is complete.
        if status == "completed_no_records" and _fmt_num(pool.get("pooled_mean")) is not None:
            status = "completed"

        covered_pmids = set(merged["pmid"].dropna().astype(str)) if "pmid" in merged.columns else set()
        summary_record_count = summary.get("coding_record_count")
        if _fmt_num(summary_record_count, 0):
            coding_record_count = summary_record_count
        elif not merged.empty:
            coding_record_count = len(merged)
        else:
            coding_record_count = summary_record_count if summary_record_count is not None else None
        pooled_mean = _fmt_num(pool.get("pooled_mean"))
        sr = _fmt_num(src.get("sr"))
        sr_lo = _fmt_num(src.get("sr_lo"))
        sr_hi = _fmt_num(src.get("sr_hi"))
        previous = _fmt_num(src.get("llm"))
        delta_vs_sr = _fmt_num((pooled_mean - sr) if pooled_mean is not None and sr is not None else None)
        e2e_ci_lower = _fmt_num(pool.get("ci_lower"))
        e2e_ci_upper = _fmt_num(pool.get("ci_upper"))
        rel_flag, rel_delta, deviation_threshold = _sr_deviation_flag(
            topic,
            pooled_mean,
            e2e_ci_lower,
            e2e_ci_upper,
            delta_vs_sr,
            sr,
            sr_lo,
            sr_hi,
        )
        rows.append(
            {
                "status": status,
                "disease": disease,
                "topic": topic,
                "profile": profile,
                "article": src.get("article"),
                "selected_rows": selected_rows_value,
                "coding_input_count": coding_input_count_value,
                "own_coding_input_count": summary.get("coding_input_count", summary.get("selected_rows")),
                "skipped_reuse_or_inflight_count": summary.get("skipped_reuse_or_inflight_count", 0),
                "gt_total": gt_total_value,
                "screening_tp": screening_tp_value,
                "screening_fp": screening_fp_value,
                "screening_fn": screening_fn_value,
                "coding_record_count": coding_record_count,
                "selected_pmid_count": len(pooling_selected_pmids) if pooling_selected_pmids else None,
                "covered_pmid_count": len(covered_pmids) if pooling_selected_pmids else None,
                "missing_selected_pmid_count": (len(set(pooling_selected_pmids) - covered_pmids) if pooling_selected_pmids else None),
                "parameter_type": pool.get("parameter_type"),
                "estimate_measure": pool.get("estimate_measure"),
                "pool_method": pool.get("pool_method"),
                "n_studies": _fmt_num(pool.get("n_studies"), 0),
                "n_excluded": _fmt_num(pool.get("n_excluded"), 0),
                "n_imputed": _fmt_num(pool.get("n_imputed"), 0),
                "pooled_input_rows": pool.get("pooled_input_rows"),
                "pooled_input_pmids": pool.get("pooled_input_pmids"),
                "e2e_pooled_mean": pooled_mean,
                "e2e_ci_lower": e2e_ci_lower,
                "e2e_ci_upper": e2e_ci_upper,
                "e2e_i2": _fmt_num(pool.get("i2"), 1),
                "sr_point": sr,
                "sr_ci_lower": sr_lo,
                "sr_ci_upper": sr_hi,
                "previous_module_point": previous,
                "previous_module_ci_lower": _fmt_num(src.get("llm_lo")),
                "previous_module_ci_upper": _fmt_num(src.get("llm_hi")),
                "delta_e2e_vs_sr": delta_vs_sr,
                "abs_delta_e2e_vs_sr": _fmt_num(abs(delta_vs_sr) if delta_vs_sr is not None else None),
                "relative_delta_e2e_vs_sr": rel_delta,
                "sr_deviation_flag": rel_flag,
                "sr_deviation_threshold": deviation_threshold,
                "delta_e2e_vs_previous_module": _fmt_num((pooled_mean - previous) if pooled_mean is not None and previous is not None else None),
                "unit": src.get("unit"),
                "run_dir": str(run_dir) if run_dir else "",
                "selected_source": selected_source or (str(run_dir / "screening_selected_records.csv") if run_dir else ""),
                "own_xlsx": str(xlsx) if xlsx else "",
                "used_record_sources": ";".join(used_sources),
                "profile_filter_note": selected_filter_note,
                "pooling_warnings": pool.get("pooling_warnings", ""),
            }
        )
    return pd.DataFrame(rows)


def build_summary_table(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "Project": df["profile"],
            "SR pooled mean": df.apply(
                lambda r: _format_estimate(r["sr_point"], r["sr_ci_lower"], r["sr_ci_upper"], r["unit"]),
                axis=1,
            ),
            "Module pooled mean": df.apply(
                lambda r: _format_estimate(r["previous_module_point"], r["previous_module_ci_lower"], r["previous_module_ci_upper"], r["unit"]),
                axis=1,
            ),
            "E2E pooled mean": df.apply(
                lambda r: _format_estimate(r["e2e_pooled_mean"], r["e2e_ci_lower"], r["e2e_ci_upper"], r["unit"]),
                axis=1,
            ),
            "Δ vs SR": df.apply(
                lambda r: _format_delta(r["delta_e2e_vs_sr"], r["unit"]),
                axis=1,
            ),
            "Deviation note": df.apply(_deviation_note, axis=1),
        }
    )
    return out


def _deviation_note(row: pd.Series) -> str:
    profile = str(row.get("profile", "")).strip()
    notes = {
        "P7": "COVID-19 R0 context mix; E2E CI overlaps SR CI after closed/special-context filtering.",
        "P8": "COVID-19 R0 context mix; E2E CI overlaps SR CI after closed/special-context filtering.",
        "P16": "COVID-19 R0 is heterogeneous; E2E is lower after closed/special-context filtering but remains inside SR CI.",
        "MP4": "SR-aligned aggregate CFR pooling; E2E CI overlaps SR CI.",
        "MP8": "Clade-I/date filter leaves few CFR inputs; CI overlaps SR despite higher point estimate.",
        "MP10": (
            "SR Fig.5 uses high estimates (Besombes 27.02; Marziano 17.5/11.4; Guzzetta 12.5; "
            "Zhang 11.56); E2E pools serial-mean rows with usable SE, so several SR high estimates "
            "are missing or excluded."
        ),
        "MP12": "Pediatric CFR uses sparse E2E inputs and very wide SR/E2E CIs; point difference remains inside SR CI.",
    }
    return notes.get(profile, "")


def _format_estimate(point: object, lo: object, hi: object, unit: object) -> str:
    point_v = _fmt_num(point, 4)
    if point_v is None:
        return ""
    lo_v = _fmt_num(lo, 4)
    hi_v = _fmt_num(hi, 4)
    unit_s = "" if pd.isna(unit) else str(unit).strip()
    if lo_v is None or hi_v is None:
        return f"{point_v:g}{(' ' + unit_s) if unit_s else ''}"
    return f"{point_v:g} ({lo_v:g}-{hi_v:g}){(' ' + unit_s) if unit_s else ''}"


def _format_delta(delta: object, unit: object) -> str:
    delta_v = _fmt_num(delta, 4)
    if delta_v is None:
        return ""
    unit_s = "" if pd.isna(unit) else str(unit).strip()
    return f"{delta_v:+g}{(' ' + unit_s) if unit_s else ''}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=RUN_ROOT / "e2e_pooled_mean_tracking.csv",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=RUN_ROOT / "e2e_pooled_mean_tracking.json",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=RUN_ROOT / "e2e_pooled_mean_summary.csv",
    )
    parser.add_argument(
        "--selected-root",
        type=Path,
        default=OFFICIAL_SELECTED_ROOT,
        help=(
            "Optional root containing per-profile screening_selected_records.csv "
            "files. Defaults to the official Qwen3.6 high-recall screening queue."
        ),
    )
    args = parser.parse_args()

    selected_root = args.selected_root if args.selected_root.exists() else None
    df = build_tracking(selected_root=selected_root)
    summary = build_summary_table(df)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False)
    summary.to_csv(args.summary_output, index=False, encoding="utf-8-sig")
    args.json.write_text(df.replace({np.nan: None}).to_json(orient="records", force_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")
    print(f"Wrote {args.summary_output}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
