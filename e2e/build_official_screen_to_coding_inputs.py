#!/usr/bin/env python3
"""Build official screening-selected inputs for E2E coding alignment.

The paper-level screening result is the calibrated high-recall Qwen3.6 Plus
operating point. This script reconstructs its per-profile selected PMID set
from local screened CSVs, writes selected-only CSVs that can be consumed by
``run_screen_to_coding.py``, and reports the delta against the previous
screen-to-coding queue.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "e2e" / "runs" / "screen_to_coding"
OUT_ROOT = RUN_ROOT / "official_qwen36_recall_selected"
OFFICIAL_METRICS = (
    ROOT
    / "evaluation"
    / "results"
    / "model_5d_screening_calibrated_boyue_qwen3-6-plus_v1_recall_20260509_profile_metrics.csv"
)
TRACKING_CSV = RUN_ROOT / "e2e_pooled_mean_tracking.csv"

MODE_ORDER = {"tier": 0, "suggest": 1, "score4": 2}
SOURCE_ORDER = {
    "model_5d_screening_multi_adaptive_highc_llmtier_20260507_boyue_qwen3-6-plus": 0,
    "prompt_tuned_sparse_r0recall_boyue_qwen36plus_20260509": 1,
    "prompt_tuned_sparse_boyue_qwen36plus_20260509": 2,
    "qwen36_plus_openrouter_direct_single_b1c8_j2_repeat2_20260510_openrouter_qwen-qwen3-6-plus": 3,
    "qwen36_plus_openrouter_direct_single_b1c8_j2_repeat1_20260510_openrouter_qwen-qwen3-6-plus": 4,
}


def _norm_pmid(value: object) -> str | None:
    match = re.search(r"\d+", str(value))
    return match.group(0) if match else None


def _profile(disease: str, project: object) -> str:
    return f"{'MP' if disease == 'mpox' else 'P'}{int(project)}"


def _gt_pmids(disease: str, topic: str, project: object) -> set[str]:
    path = ROOT / "dataset" / disease / "screening" / topic / f"p{int(project)}" / "ground_truth.csv"
    df = pd.read_csv(path, dtype=str)
    column = "gt_pmid" if "gt_pmid" in df.columns else "PMID"
    return {pmid for pmid in df[column].map(_norm_pmid).dropna().astype(str)}


def _screened_paths() -> list[Path]:
    return sorted((ROOT / "evaluation" / "screening").glob("*/*/p*/experiments/*/project_*_screened.csv"))


def _candidate_key(path: Path) -> tuple[str, str, str, str]:
    rel = path.relative_to(ROOT)
    # evaluation/screening/{disease}/{topic}/p{project}/experiments/{experiment}/project_*.csv
    return rel.parts[2], rel.parts[3], rel.parts[4], rel.parts[6]


def _selected_mask(df: pd.DataFrame, mode: str) -> pd.Series:
    if mode == "tier":
        if "llm_tier" not in df.columns:
            raise KeyError("llm_tier")
        return df["llm_tier"].fillna("").astype(str).str.strip().str.upper().isin({"S", "P"})
    if mode == "suggest":
        if "llm_suggest" not in df.columns:
            raise KeyError("llm_suggest")
        suggest = df["llm_suggest"].fillna("").astype(str).str.strip().str.lower()
        return suggest.str.contains("strong|possible", regex=True) | suggest.isin(
            {"include", "included", "true", "yes"}
        )
    if mode == "score4":
        if "overall_score" not in df.columns:
            raise KeyError("overall_score")
        return pd.to_numeric(df["overall_score"], errors="coerce").fillna(-999) >= 4
    raise ValueError(mode)


def _evaluate(path: Path, mode: str, gt: set[str]) -> tuple[tuple[int, int, int, int, int, int], pd.DataFrame]:
    df = pd.read_csv(path, dtype=str, low_memory=False)
    if "PMID" not in df.columns:
        raise ValueError(f"{path} lacks PMID column")
    df = df.copy()
    df["PMID"] = df["PMID"].map(_norm_pmid)
    df = df[df["PMID"].notna()].drop_duplicates(subset=["PMID"], keep="first")
    selected = df[_selected_mask(df, mode)].copy()
    selected_pmids = set(selected["PMID"].astype(str))
    all_pmids = set(df["PMID"].astype(str))
    metrics = (
        len(selected_pmids & gt),
        len(selected_pmids - gt),
        len(gt - selected_pmids),
        len(all_pmids - selected_pmids - gt),
        len(gt),
        len(all_pmids),
    )
    return metrics, selected


def _current_selected_by_profile() -> dict[str, set[str]]:
    if not TRACKING_CSV.exists():
        return {}
    tracking = pd.read_csv(TRACKING_CSV)
    out: dict[str, set[str]] = {}
    for _, row in tracking.iterrows():
        profile = str(row.get("profile", "")).strip().upper()
        run_dir = Path(str(row.get("run_dir", "")))
        selected_path = run_dir / "screening_selected_records.csv"
        if not profile or not selected_path.exists():
            continue
        selected = pd.read_csv(selected_path, dtype=str, low_memory=False)
        out[profile] = {pmid for pmid in selected["PMID"].map(_norm_pmid).dropna().astype(str)}
    return out


def _write_pmids(path: Path, pmids: list[str]) -> None:
    path.write_text("\n".join(pmids) + ("\n" if pmids else ""), encoding="utf-8")


def main() -> None:
    metrics = pd.read_csv(OFFICIAL_METRICS)
    metrics["profile"] = metrics.apply(lambda r: _profile(str(r["disease"]), r["project"]), axis=1)
    metrics["key"] = metrics.apply(
        lambda r: f"{r['disease']}/{r['topic']}/p{int(r['project'])}",
        axis=1,
    )
    targets = {
        row.key: (
            int(row.tp),
            int(row.fp),
            int(row.fn),
            int(row.tn),
            int(row.gt),
            int(row.total),
        )
        for row in metrics.itertuples()
    }
    gt_by_key = {
        row.key: _gt_pmids(str(row.disease), str(row.topic), row.project)
        for row in metrics.itertuples()
    }

    choices: dict[str, dict[str, object]] = {}
    for path in _screened_paths():
        disease, topic, project_dir, experiment = _candidate_key(path)
        key = f"{disease}/{topic}/{project_dir}"
        if key not in targets:
            continue
        for mode in ("tier", "suggest", "score4"):
            try:
                got, selected = _evaluate(path, mode, gt_by_key[key])
            except Exception:
                continue
            if got != targets[key]:
                continue
            preference = (
                MODE_ORDER[mode],
                SOURCE_ORDER.get(experiment, 999),
                experiment,
            )
            previous = choices.get(key)
            if previous is None or preference < previous["preference"]:
                choices[key] = {
                    "path": path,
                    "experiment": experiment,
                    "mode": mode,
                    "selected": selected,
                    "preference": preference,
                }

    missing = sorted(set(targets) - set(choices))
    if missing:
        raise RuntimeError(f"No exact screened CSV source for: {missing}")

    current = _current_selected_by_profile()
    rows: list[dict[str, object]] = []
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    for row in metrics.itertuples():
        key = row.key
        profile = row.profile
        choice = choices[key]
        selected = choice["selected"].copy()  # type: ignore[assignment]
        selected["PMID"] = selected["PMID"].astype(str)
        selected = selected.drop_duplicates(subset=["PMID"], keep="first")
        selected_pmids = selected["PMID"].tolist()
        selected_set = set(selected_pmids)
        gt = gt_by_key[key]
        cur = current.get(profile, set())
        official_only = sorted(selected_set - cur, key=lambda x: int(x) if x.isdigit() else x)
        current_only = sorted(cur - selected_set, key=lambda x: int(x) if x.isdigit() else x)

        # The generated selected-only CSV is an input artifact. Preserve the
        # original labels, but ensure run_screen_to_coding.py selects every row.
        if "llm_tier" in selected.columns:
            selected["original_llm_tier"] = selected["llm_tier"]
        if "llm_suggest" in selected.columns:
            selected["original_llm_suggest"] = selected["llm_suggest"]
        selected["llm_tier"] = selected.get("llm_tier", "P")
        selected["llm_tier"] = selected["llm_tier"].fillna("").astype(str).str.upper()
        selected.loc[~selected["llm_tier"].isin({"S", "P"}), "llm_tier"] = "P"
        selected["official_selection_source"] = str(choice["experiment"])
        selected["official_selection_mode"] = str(choice["mode"])

        profile_dir = OUT_ROOT / profile
        profile_dir.mkdir(parents=True, exist_ok=True)
        selected.to_csv(profile_dir / "screening_selected_records.csv", index=False)
        _write_pmids(profile_dir / "screened_sp_pmids.txt", selected_pmids)
        _write_pmids(profile_dir / "official_only_pmids.txt", official_only)
        _write_pmids(profile_dir / "current_only_pmids.txt", current_only)

        rows.append(
            {
                "profile": profile,
                "disease": row.disease,
                "topic": row.topic,
                "project": f"p{int(row.project)}",
                "official_selected": len(selected_set),
                "official_tp": len(selected_set & gt),
                "official_fp": len(selected_set - gt),
                "official_fn": len(gt - selected_set),
                "current_selected": len(cur),
                "official_only": len(official_only),
                "official_only_tp": len(set(official_only) & gt),
                "official_only_fp": len(set(official_only) - gt),
                "current_only": len(current_only),
                "current_only_tp": len(set(current_only) & gt),
                "current_only_fp": len(set(current_only) - gt),
                "source_csv": str(choice["path"]),
                "source_experiment": str(choice["experiment"]),
                "selection_mode": str(choice["mode"]),
                "selected_csv": str(profile_dir / "screening_selected_records.csv"),
                "official_only_pmids": str(profile_dir / "official_only_pmids.txt"),
            }
        )

    summary = pd.DataFrame(rows)
    summary.to_csv(OUT_ROOT / "official_screen_to_coding_alignment.csv", index=False)
    manifest = {
        "official_metrics": str(OFFICIAL_METRICS),
        "tracking_csv_compared": str(TRACKING_CSV),
        "output_root": str(OUT_ROOT),
        "profiles": len(summary),
        "official_selected_total": int(summary["official_selected"].sum()),
        "official_tp_total": int(summary["official_tp"].sum()),
        "official_fp_total": int(summary["official_fp"].sum()),
        "official_fn_total": int(summary["official_fn"].sum()),
        "official_only_total": int(summary["official_only"].sum()),
        "official_only_tp_total": int(summary["official_only_tp"].sum()),
        "official_only_fp_total": int(summary["official_only_fp"].sum()),
        "current_only_total": int(summary["current_only"].sum()),
        "current_only_tp_total": int(summary["current_only_tp"].sum()),
        "current_only_fp_total": int(summary["current_only_fp"].sum()),
    }
    (OUT_ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(summary[["profile", "official_selected", "official_only", "official_only_tp", "current_only"]].to_string(index=False))
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
