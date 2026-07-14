#!/usr/bin/env python3
"""Build an E2E coding comparison table aligned with the modular paper source data.

This mirrors the structure of docs/paper/source_data/coding_estimate_intervals.csv,
but substitutes the E2E pooled estimate as the comparison target. The output is
intended for direct MAE/closer-count analysis against source-review references.
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "e2e" / "runs" / "screen_to_coding"
SOURCE_CSV = ROOT / "docs" / "paper" / "source_data" / "coding_estimate_intervals.csv"
E2E_SUMMARY_CSV = RUN_ROOT / "e2e_pooled_mean_tracking.csv"
OUT_CSV = RUN_ROOT / "e2e_coding_estimate_intervals.csv"
OUT_MD = RUN_ROOT / "e2e_coding_compare_summary.md"
EVAL_ROOT = ROOT / "evaluation" / "coding"

import sys

sys.path.insert(0, str(ROOT))
from tools.analysis.pooling import enrich_ci, summarize  # noqa: E402


def _norm_profile(value: object) -> str:
    text = str(value).strip()
    return text.upper()


def _fmt_num(value: object, ndigits: int = 2) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    try:
        return f"{float(value):.{ndigits}f}"
    except Exception:
        return str(value)


def _scope(panel: str) -> str:
    text = str(panel)
    if text in {"Serial interval", "Incubation period", "Transmission interval"}:
        return "serial_interval"
    if text == "Reproduction number":
        return "r0"
    return "fatality"


def _load_rows() -> pd.DataFrame:
    src = pd.read_csv(SOURCE_CSV)
    e2e = pd.read_csv(E2E_SUMMARY_CSV)
    e2e["profile"] = e2e["profile"].map(_norm_profile)
    src["project"] = src["project"].map(_norm_profile)
    rows = src.merge(
        e2e[
            [
                "profile",
                "disease",
                "topic",
                "article",
                "sr_point",
                "sr_ci_lower",
                "sr_ci_upper",
                "previous_module_point",
                "previous_module_ci_lower",
                "previous_module_ci_upper",
                "e2e_pooled_mean",
                "e2e_ci_lower",
                "e2e_ci_upper",
                "unit",
                "status",
            ]
        ],
        left_on=["project", "disease", "article"],
        right_on=["profile", "disease", "article"],
        how="left",
        suffixes=("", "_e2e"),
        validate="one_to_one",
    )
    rows["profile"] = rows["project"]

    rows["abs_delta_e2e_vs_sr"] = (rows["e2e_pooled_mean"] - rows["sr"]).abs()
    rows["abs_delta_module_vs_sr"] = (rows["llm"] - rows["sr"]).abs()
    rows["closer"] = rows.apply(
        lambda r: "e2e"
        if pd.notna(r["abs_delta_e2e_vs_sr"]) and pd.notna(r["abs_delta_module_vs_sr"]) and r["abs_delta_e2e_vs_sr"] < r["abs_delta_module_vs_sr"]
        else ("module" if pd.notna(r["abs_delta_e2e_vs_sr"]) and pd.notna(r["abs_delta_module_vs_sr"]) and r["abs_delta_module_vs_sr"] < r["abs_delta_e2e_vs_sr"] else "tie"),
        axis=1,
    )
    rows["scope"] = rows["parameter_group"].map(_scope)
    return rows


def _latest_module_xlsx(disease: str, topic: str, project: str) -> Path | None:
    project_dir = EVAL_ROOT / disease / topic / project / "coding_runs"
    if not project_dir.exists():
        return None
    runs = sorted([p for p in project_dir.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)
    for run in runs:
        xlsx_files = sorted(run.glob("coding_sheet_*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
        if xlsx_files:
            return xlsx_files[0]
    return None


def _module_pool_for_row(row: pd.Series) -> tuple[float | None, float | None, float | None]:
    xlsx = _latest_module_xlsx(str(row["disease"]), str(row["topic"]), str(row["project"]).lower())
    if xlsx is None:
        return None, None, None
    try:
        df = pd.read_excel(xlsx)
    except Exception:
        return None, None, None

    topic = str(row["topic"])
    if topic == "fatality":
        # Match the current E2E fatality treatment: profile-aware percent pooling.
        # The module baseline in paper source data is retained for display, but
        # the comparison uses the same filter family as the E2E side.
        project = str(row["project"]).upper()
        text_cols = [c for c in ("parameter_type", "fatality_type", "denominator_type", "summary_type", "age_group", "severity_group", "notes") if c in df.columns]
        blob = (
            df[text_cols]
            .apply(lambda row: " | ".join("" if pd.isna(value) else str(value) for value in row.tolist()), axis=1)
            .str.lower()
            if text_cols
            else pd.Series("", index=df.index)
        )
        if project == "P4":
            mask = blob.str.contains("imv|icu|mechanical ventilation", na=False)
        elif project == "P5":
            mask = blob.str.contains("ifr|infection fatality", na=False)
        elif project == "P6":
            mask = blob.str.contains("hfr|hospital fatality|hospitalized fatality", na=False)
        elif project == "MP7":
            mask = blob.str.contains("pre-2016|pre2016|cfr", na=False)
        elif project == "MP8":
            mask = blob.str.contains("clade i|clade1|clade i cfr", na=False)
        elif project == "MP12":
            mask = blob.str.contains("pediatric|child", na=False)
        else:
            mask = pd.Series(True, index=df.index)
        df = df.loc[mask].copy()
        df["parameter_type"] = "fatality"
        df["estimate_measure"] = "fatality_rate_percent"
    else:
        param = "serial_interval" if topic == "serial_interval" else "R0"
        df = df[df["parameter_type"].astype(str).str.strip().str.lower().eq(param.lower())].copy()
        if topic == "reproduction_number":
            # Same fallback as current E2E tracking for R0.
            if "estimate_measure" in df.columns and not (df["estimate_measure"].astype(str).str.strip().str.lower() == "mean").any():
                df["estimate_measure"] = "all_available"
            else:
                df = df[df["estimate_measure"].astype(str).str.strip().str.lower().eq("mean")].copy()
        else:
            df = df[df["estimate_measure"].astype(str).str.strip().str.lower().eq("mean")].copy()

    if df.empty or "point_estimate" not in df.columns:
        return None, None, None

    enriched = enrich_ci(df)
    if topic == "fatality":
        summary = summarize(
            enriched,
            parameter_type=None,
            estimate_measure=None,
            include_median=False,
            impute_missing_se=True,
            method="random",
        )
    else:
        summary = summarize(
            enriched,
            parameter_type=("serial_interval" if topic == "serial_interval" else "R0"),
            estimate_measure="mean",
            include_median=False,
            impute_missing_se=True,
            method="random",
        )
    if summary.empty:
        return None, None, None
    r = summary.iloc[0]
    return float(r["pooled_mean"]), float(r["ci_lower"]), float(r["ci_upper"])


def _summary(rows: pd.DataFrame) -> pd.DataFrame:
    scopes = [
        ("overall", rows.index),
        ("serial_interval", rows["scope"].eq("serial_interval")),
        ("r0", rows["scope"].eq("r0")),
        ("fatality", rows["scope"].eq("fatality")),
        ("covid19", rows["disease"].eq("covid19")),
        ("mpox", rows["disease"].eq("mpox")),
    ]

    out = []
    for scope, mask in scopes:
        g = rows.loc[mask].copy()
        g = g[g["e2e_pooled_mean"].notna() & g["sr"].notna()]
        if g.empty:
            continue
        g = g[g["module_pooled_mean"].notna()]
        if g.empty:
            continue
        e2e_mae = float(g["abs_delta_e2e_vs_sr"].mean())
        module_mae = float(g["abs_delta_module_vs_sr"].mean())
        e2e_closer = int((g["abs_delta_e2e_vs_sr"] < g["abs_delta_module_vs_sr"]).sum())
        module_closer = int((g["abs_delta_module_vs_sr"] < g["abs_delta_e2e_vs_sr"]).sum())
        tie = int((g["abs_delta_module_vs_sr"] == g["abs_delta_e2e_vs_sr"]).sum())
        out.append({
            "scope": scope,
            "profiles": int(len(g)),
            "module_mae": round(module_mae, 4),
            "e2e_mae": round(e2e_mae, 4),
            "module_closer": module_closer,
            "e2e_closer": e2e_closer,
            "tie": tie,
        })
    return pd.DataFrame(out)


def _write_md(summary: pd.DataFrame) -> None:
    lines = [
        "# E2E coding comparison summary",
        "",
        "| Scope | Profiles | Module MAE | E2E MAE | Module closer | E2E closer | Tie |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    scope_label = {
        "overall": "Overall",
        "serial_interval": "Transmission interval",
        "r0": "Reproduction number",
        "fatality": "Fatality",
        "covid19": "COVID-19",
        "mpox": "Mpox",
    }
    for _, row in summary.iterrows():
        lines.append(
            f"| {scope_label.get(row['scope'], row['scope'])} | {int(row['profiles'])} | "
            f"{row['module_mae']:.3f} | {row['e2e_mae']:.3f} | {int(row['module_closer'])} | "
            f"{int(row['e2e_closer'])} | {int(row['tie'])} |"
        )
    lines.append("")
    lines.append("E2E and module are both compared against the same source-review reference rows.")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    rows = _load_rows()
    module_vals = rows.apply(lambda r: pd.Series(_module_pool_for_row(r), index=["module_pooled_mean", "module_ci_lower", "module_ci_upper"]), axis=1)
    rows = pd.concat([rows, module_vals], axis=1)
    rows["abs_delta_module_vs_sr"] = (rows["module_pooled_mean"] - rows["sr"]).abs()
    rows["abs_delta_e2e_vs_module"] = (rows["e2e_pooled_mean"] - rows["module_pooled_mean"]).abs()
    rows.to_csv(OUT_CSV, index=False)
    summary = _summary(rows)
    _write_md(summary)
    print(f"wrote {OUT_CSV}")
    print(f"wrote {OUT_MD}")


if __name__ == "__main__":
    main()
