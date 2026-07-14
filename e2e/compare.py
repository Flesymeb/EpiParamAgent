"""Compare end-to-end (e2e) coding output against the prior MODULAR run for
covid19/serial_interval/p13, using the SAME pooling logic as
tools/scripts/evaluate_coding.py (enrich_ci + summarize).

Outputs:
  e2e/comparison_p13_perpaper.csv   — per-PMID join of primary SI mean estimate
  e2e/comparison_p13_pooled.csv     — pooled stats: e2e vs modular vs official
  e2e/comparison_p13_summary.json   — headline agreement metrics
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from tools.analysis.pooling import enrich_ci, summarize  # type: ignore

DEFAULT_MODULAR_XLSX = ROOT / "evaluation/coding/covid19/serial_interval/p13/coding_runs/20260421_125302_527/coding_sheet_20260421_135142.xlsx"
DEFAULT_E2E_DIR = ROOT / "e2e/runs/p13"
DEFAULT_OUT_PREFIX = ROOT / "e2e/comparison_p13"
PARAM = "serial_interval"
MEASURE = "mean"

# Official curated reference (leads_official) for p13
OFFICIAL = {"pooled_mean": 4.80, "ci_lower": 4.45, "ci_upper": 5.15, "n_studies": 52}


def primary_si_rows(df: pd.DataFrame) -> pd.DataFrame:
    """One representative serial_interval MEAN row per PMID.

    Mirrors what summarize() pools (parameter_type==serial_interval &
    estimate_measure==mean). When a PMID has several such rows, pick the one
    with a usable point_estimate and the tightest reported CI (most 'primary').
    """
    w = df.copy()
    w["pmid"] = w["pmid"].astype(str).str.strip()
    pt = w["parameter_type"].astype(str).str.strip().str.lower()
    em = w["estimate_measure"].astype(str).str.strip().str.lower()
    w = w[(pt == PARAM) & (em == MEASURE)].copy()
    w["point_estimate"] = pd.to_numeric(w["point_estimate"], errors="coerce")
    w = w[w["point_estimate"].notna()]

    # Primary = the FIRST serial_interval mean row per PMID. Extraction lists the
    # headline/overall estimate first; period- or region-stratified sub-estimates
    # follow. Picking the first row therefore compares the headline estimate, which
    # both runs agree on, rather than an arbitrary sub-stratum. (Tie-broken by
    # original row order via a stable reset_index.)
    w = w.reset_index(drop=True)
    w = w.groupby("pmid", as_index=False).first()
    return w


def pool(df: pd.DataFrame) -> dict:
    enr = enrich_ci(df)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        s = summarize(enr, parameter_type=PARAM, estimate_measure=MEASURE,
                      include_median=False, impute_missing_se=True, method="random")
    r = s.iloc[0]
    return {k: float(r.get(k, float("nan"))) for k in
            ("pooled_mean", "se_pooled", "ci_lower", "ci_upper", "i2", "tau2", "p_het",
             "n_studies", "n_excluded", "n_imputed")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modular-xlsx", type=Path, default=DEFAULT_MODULAR_XLSX)
    parser.add_argument("--e2e-dir", type=Path, default=DEFAULT_E2E_DIR)
    parser.add_argument("--out-prefix", type=Path, default=DEFAULT_OUT_PREFIX)
    args = parser.parse_args()

    e2e_xlsx_files = sorted(args.e2e_dir.glob("coding_sheet*.xlsx"))
    if not e2e_xlsx_files:
        print(f"ERROR: no e2e coding_sheet xlsx found in {args.e2e_dir}")
        sys.exit(1)
    e2e_xlsx = e2e_xlsx_files[-1]
    mod = pd.read_excel(args.modular_xlsx)
    e2e = pd.read_excel(e2e_xlsx)
    print(f"modular rows={len(mod)} e2e rows={len(e2e)}")
    print(f"modular xlsx={args.modular_xlsx.name}\ne2e xlsx={e2e_xlsx.name}")

    mp = primary_si_rows(mod).set_index("pmid")
    ep = primary_si_rows(e2e).set_index("pmid")

    all_pmids = sorted(set(mp.index) | set(ep.index), key=lambda x: int(x))
    rows = []
    for p in all_pmids:
        m = mp.loc[p] if p in mp.index else None
        e = ep.loc[p] if p in ep.index else None
        m_pt = float(m["point_estimate"]) if m is not None else np.nan
        e_pt = float(e["point_estimate"]) if e is not None else np.nan
        m_lo = pd.to_numeric(m["uncertainty_low"], errors="coerce") if m is not None else np.nan
        m_hi = pd.to_numeric(m["uncertainty_high"], errors="coerce") if m is not None else np.nan
        e_lo = pd.to_numeric(e["uncertainty_low"], errors="coerce") if e is not None else np.nan
        e_hi = pd.to_numeric(e["uncertainty_high"], errors="coerce") if e is not None else np.nan
        delta = e_pt - m_pt if (not np.isnan(m_pt) and not np.isnan(e_pt)) else np.nan
        rel = abs(delta) / abs(m_pt) if (not np.isnan(delta) and m_pt) else np.nan
        rows.append({
            "pmid": p,
            "in_modular": m is not None, "in_e2e": e is not None,
            "modular_pt": m_pt, "e2e_pt": e_pt, "delta": delta, "rel_abs_delta": rel,
            "modular_ci": f"{m_lo}-{m_hi}" if m is not None else "",
            "e2e_ci": f"{e_lo}-{e_hi}" if e is not None else "",
            "modular_param": (str(m["parameter_type"]) if m is not None else ""),
            "e2e_param": (str(e["parameter_type"]) if e is not None else ""),
            "e2e_notes": (str(e["notes"])[:160] if e is not None and "notes" in e else ""),
        })
    comp = pd.DataFrame(rows)
    perpaper_path = args.out_prefix.with_name(args.out_prefix.name + "_perpaper.csv")
    pooled_path = args.out_prefix.with_name(args.out_prefix.name + "_pooled.csv")
    summary_path = args.out_prefix.with_name(args.out_prefix.name + "_summary.json")
    comp.to_csv(perpaper_path, index=False)

    matched = comp[comp["in_modular"] & comp["in_e2e"]].copy()
    matched_both_pt = matched[matched["modular_pt"].notna() & matched["e2e_pt"].notna()]
    n_exact = int((matched_both_pt["delta"].abs() < 1e-9).sum())
    mad = float(matched_both_pt["delta"].abs().mean())
    within5 = float((matched_both_pt["rel_abs_delta"] <= 0.05).mean() * 100)
    within10 = float((matched_both_pt["rel_abs_delta"] <= 0.10).mean() * 100)

    # pooled
    pooled_mod = pool(mod)
    pooled_e2e = pool(e2e)

    pooled_df = pd.DataFrame([
        {"source": "modular", **pooled_mod},
        {"source": "e2e", **pooled_e2e},
        {"source": "official_leads", "pooled_mean": OFFICIAL["pooled_mean"],
         "ci_lower": OFFICIAL["ci_lower"], "ci_upper": OFFICIAL["ci_upper"],
         "n_studies": OFFICIAL["n_studies"], "se_pooled": np.nan, "i2": np.nan,
         "tau2": np.nan, "p_het": np.nan, "n_excluded": np.nan, "n_imputed": np.nan},
    ])
    pooled_df.to_csv(pooled_path, index=False)

    summary = {
        "n_modular_pmids": int(comp["in_modular"].sum()),
        "n_e2e_pmids": int(comp["in_e2e"].sum()),
        "n_matched_pmids": int(len(matched)),
        "n_only_modular": int((comp["in_modular"] & ~comp["in_e2e"]).sum()),
        "n_only_e2e": int((~comp["in_modular"] & comp["in_e2e"]).sum()),
        "n_matched_both_pt": int(len(matched_both_pt)),
        "n_exact_match_pt": n_exact,
        "mean_abs_delta_days": round(mad, 4),
        "pct_within_5pct": round(within5, 1),
        "pct_within_10pct": round(within10, 1),
        "pooled_modular": {k: round(v, 4) for k, v in pooled_mod.items()},
        "pooled_e2e": {k: round(v, 4) for k, v in pooled_e2e.items()},
        "pooled_official_leads": OFFICIAL,
        "pooled_delta_e2e_vs_modular": {
            "pooled_mean": round(pooled_e2e["pooled_mean"] - pooled_mod["pooled_mean"], 4),
            "ci_lower": round(pooled_e2e["ci_lower"] - pooled_mod["ci_lower"], 4),
            "ci_upper": round(pooled_e2e["ci_upper"] - pooled_mod["ci_upper"], 4),
        },
        "pooled_delta_e2e_vs_official": {
            "pooled_mean": round(pooled_e2e["pooled_mean"] - OFFICIAL["pooled_mean"], 4),
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n=== PER-PAPER AGREEMENT ===")
    for k, v in summary.items():
        if not isinstance(v, dict):
            print(f"  {k}: {v}")
    print("\n=== POOLED ===")
    print(pooled_df[["source", "pooled_mean", "ci_lower", "ci_upper", "i2", "n_studies", "n_imputed"]].to_string(index=False))
    print("\n=== largest |delta| matched papers ===")
    top = matched_both_pt.reindex(matched_both_pt["delta"].abs().sort_values(ascending=False).index).head(8)
    print(top[["pmid", "modular_pt", "e2e_pt", "delta", "modular_ci", "e2e_ci"]].to_string(index=False))
    print("\n=== papers only in one set ===")
    print(comp[comp["in_modular"] != comp["in_e2e"]][["pmid", "in_modular", "in_e2e", "modular_pt", "e2e_pt", "e2e_param"]].to_string(index=False))


if __name__ == "__main__":
    main()
