#!/usr/bin/env python3
"""Write LaTeX coding comparison tables with current E2E estimates.

The LEADS figure script is intentionally component-level. These tables extend
that comparison by merging the latest screening-to-coding E2E pooled estimates.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
LEADS_DIR = ROOT / "evaluation" / "leads_coding_official_final_results"
LEADS_ESTIMATES = LEADS_DIR / "sr_5d_leads_official_final_estimates.csv"
TRACKING = ROOT / "e2e" / "runs" / "screen_to_coding" / "e2e_pooled_mean_tracking.csv"
LATEX_TABLES = ROOT / "docs" / "paper" / "latex" / "tables"
OUT_DIR = ROOT / "docs" / "paper" / "coding" / "compare_leads"


PROFILE_ORDER = [
    "P10",
    "P11",
    "P12",
    "P13",
    "P14",
    "P7",
    "P8",
    "P15",
    "P16",
    "P17",
    "P4",
    "P5",
    "P6",
    "MP5",
    "MP6",
    "MP10",
    "MP11",
    "MP9",
    "MP4",
    "MP7",
    "MP8",
    "MP12",
]

SOURCE_LABELS = {
    "P10": "Madewell et al., 2023",
    "P11": "Xu et al., 2023",
    "P12": "Alene et al., 2021",
    "P13": "Ali et al., 2022",
    "P14": "Rai et al., 2021",
    "P7": "Dhungel et al., 2022",
    "P8": "Ahammed et al., 2021",
    "P15": "Billah et al., 2020",
    "P16": "Yu et al., 2021",
    "P17": "Alimohamadi et al., 2020",
    "P4": "Lim et al., 2021",
    "P5": "Ioannidis et al., 2021",
    "P6": "Alimohamadi et al., 2021",
    "MP5": "Wang et al., 2022",
    "MP6": "Ponce et al., 2024",
    "MP10": "Wu et al., 2025",
    "MP11": "Diaz Brochero et al., 2025",
    "MP9": "Okoli et al., 2024",
    "MP4": "Cadmus et al., 2024",
    "MP7": "Vasudevan et al., 2025",
    "MP8": "Sharif et al., 2023",
    "MP12": "Sanchez Clemente et al., 2024",
}


@dataclass(frozen=True)
class Estimate:
    point: float | None
    lo: float | None
    hi: float | None
    unit: str


def _finite(value: object) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _unit(value: object) -> str:
    text = "" if pd.isna(value) else str(value).strip()
    if text == "d":
        return "d"
    if text in {"%", "R"}:
        return text
    return ""


def _parse_estimate(text: object) -> Estimate:
    raw = str(text)
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", re.sub(r"(?<=\d)\s*-\s*(?=\d)", ",", raw))]
    if not nums:
        return Estimate(None, None, None, "")
    unit = "%"
    if "day" in raw:
        unit = "d"
    elif " R" in raw or raw.strip().endswith("R"):
        unit = ""
    lo = nums[1] if len(nums) >= 3 else None
    hi = nums[2] if len(nums) >= 3 else None
    return Estimate(nums[0], lo, hi, unit)


def _estimate_from_row(row: pd.Series, prefix: str) -> Estimate:
    return Estimate(
        _finite(row.get(f"{prefix}_point")),
        _finite(row.get(f"{prefix}_ci_lower")),
        _finite(row.get(f"{prefix}_ci_upper")),
        _unit(row.get("unit")),
    )


def _latex_escape(text: object) -> str:
    out = str(text)
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "_": r"\_",
    }
    for old, new in replacements.items():
        out = out.replace(old, new)
    return out


def _source_label(profile: str) -> str:
    text = SOURCE_LABELS.get(profile, profile)
    if text == "Alimohamadi et al., 2020":
        return r"\makecell[c]{Alimohamadi\\et al., 2020}"
    if text == "Alimohamadi et al., 2021":
        return r"\makecell[c]{Alimohamadi\\et al., 2021}"
    if text == "Diaz Brochero et al., 2025":
        return r"\makecell[c]{Diaz Brochero\\et al., 2025}"
    if text == "Sanchez Clemente et al., 2024":
        return r"\makecell[c]{Sanchez Clemente\\et al., 2024}"
    return _latex_escape(text)


def _parameter_group(profile: str, parameter: str) -> str:
    if profile in {"P10", "P11", "P12", "P13", "P14", "MP5", "MP6", "MP10", "MP11"}:
        return "Serial Interval"
    if profile in {"P7", "P8", "P15", "P16", "P17", "MP9"}:
        return r"\makecell[c]{Reproduction\\Number}"
    return "Fatality"


def _scope(profile: str, parameter: str) -> str:
    if _parameter_group(profile, parameter) == "Serial Interval":
        return "serial_interval"
    if profile in {"P7", "P8", "P15", "P16", "P17", "MP9"}:
        return "r0"
    return "fatality"


def _fmt_number(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}"


def _fmt_estimate(est: Estimate) -> str:
    if est.point is None:
        return ""
    point = est.point
    lo = est.lo
    hi = est.hi
    unit = r"\%" if est.unit == "%" else f" {est.unit}" if est.unit else ""
    if est.unit == "%":
        lo = max(0.0, lo) if lo is not None else None
        hi = min(100.0, hi) if hi is not None else None
    point_text = f"{point:.2f}{unit}"
    if lo is None or hi is None:
        return point_text
    return rf"\shortstack[c]{{{point:.2f}{unit}\\({lo:.2f}--{hi:.2f})}}"


def _fmt_abs_delta(value: object, *, bold_threshold: float | None = None) -> str:
    num = _finite(value)
    if num is None:
        return ""
    text = f"{abs(num):.2f}"
    if bold_threshold is not None and abs(num) >= bold_threshold:
        return rf"\textbf{{{text}}}"
    return text


def _load_rows() -> pd.DataFrame:
    leads = pd.read_csv(LEADS_ESTIMATES)
    tracking = pd.read_csv(TRACKING)
    leads["profile"] = leads["profile"].astype(str).str.upper()
    tracking["profile"] = tracking["profile"].astype(str).str.upper()
    rows = leads.merge(
        tracking[
            [
                "profile",
                "unit",
                "sr_point",
                "sr_ci_lower",
                "sr_ci_upper",
                "previous_module_point",
                "previous_module_ci_lower",
                "previous_module_ci_upper",
                "e2e_pooled_mean",
                "e2e_ci_lower",
                "e2e_ci_upper",
                "delta_e2e_vs_sr",
            ]
        ],
        on="profile",
        how="left",
        validate="one_to_one",
    )
    rows["order"] = rows["profile"].map({profile: idx for idx, profile in enumerate(PROFILE_ORDER)})
    rows = rows.sort_values("order", kind="stable").reset_index(drop=True)
    rows["module_abs"] = rows["delta_5d_vs_sr"].abs()
    rows["leads_abs"] = rows["delta_leads_vs_sr"].abs()
    rows["e2e_abs"] = rows["delta_e2e_vs_sr"].abs()
    rows["scope"] = rows.apply(lambda row: _scope(str(row["profile"]), str(row["parameter"])), axis=1)
    return rows


def _summary(rows: pd.DataFrame) -> pd.DataFrame:
    scopes: list[tuple[str, pd.Series]] = [
        ("Overall", pd.Series(True, index=rows.index)),
        ("COVID-19", rows["disease"].eq("covid19")),
        ("Mpox", rows["disease"].eq("mpox")),
        ("Serial interval", rows["scope"].eq("serial_interval")),
        ("Reproduction number", rows["scope"].eq("r0")),
        ("Fatality", rows["scope"].eq("fatality")),
    ]
    out = []
    for label, mask in scopes:
        chunk = rows.loc[mask].copy()
        out.append(
            {
                "Scope": label,
                "Source reviews": int(len(chunk)),
                "Module MAE": chunk["module_abs"].mean(),
                "E2E MAE": chunk["e2e_abs"].mean(),
                "LEADS MAE": chunk["leads_abs"].mean(),
                "Module closer than LEADS": int((chunk["module_abs"] < chunk["leads_abs"]).sum()),
                "E2E closer than LEADS": int((chunk["e2e_abs"] < chunk["leads_abs"]).sum()),
            }
        )
    return pd.DataFrame(out)


def _write_summary(summary: pd.DataFrame) -> str:
    body_rows: list[str] = []
    for idx, row in summary.iterrows():
        if idx == 1:
            body_rows.append(r"\midrule")
            body_rows.append(r"\multicolumn{7}{l}{\textit{By disease}} \\")
        if idx == 3:
            body_rows.append(r"\midrule")
            body_rows.append(r"\multicolumn{7}{l}{\textit{By parameter domain}} \\")
        if row["Scope"] == "Overall":
            module_mae = e2e_mae = leads_mae = "--"
        else:
            module_mae = f"{row['Module MAE']:.3f}"
            e2e_mae = f"{row['E2E MAE']:.3f}"
            leads_mae = f"{row['LEADS MAE']:.3f}"
        body_rows.append(
            f"{row['Scope']} & {int(row['Source reviews'])} & {module_mae} & "
            f"{e2e_mae} & {leads_mae} & "
            f"{int(row['Module closer than LEADS'])} & {int(row['E2E closer than LEADS'])} \\\\"
        )
    body = "\n".join(body_rows)
    return rf"""% !TEX root = ../main.tex
\begin{{table}}[H]
\centering
\caption{{Coding estimate agreement by disease and parameter domain against source-review references. Module denotes the stage-specific \metagent{{}} full-text coding run with source-review included studies as fixed inputs; E2E denotes the screening-to-coding run.}}
\label{{tab:coding-leads-summary}}
\small
\setlength{{\tabcolsep}}{{4.2pt}}
\renewcommand{{\arraystretch}}{{1.12}}
\begin{{tabular}}{{lrrrrrr}}
\toprule
Scope & Source reviews & Module MAE & E2E MAE & LEADS MAE & \makecell[c]{{Module closer\\than LEADS}} & \makecell[c]{{E2E closer\\than LEADS}} \\
\midrule
{body}
\bottomrule
\end{{tabular}}
\vspace{{0.25em}}
\parbox{{0.95\textwidth}}{{\footnotesize Overall MAE is not shown because serial interval, reproduction number, and fatality are measured on different scales. Parameter-domain rows provide the interpretable MAE summaries.}}
\end{{table}}
"""


def _span(rows: pd.DataFrame, disease: str, group: str) -> int:
    return int((rows["disease"].eq(disease) & rows.apply(lambda row: _parameter_group(str(row["profile"]), str(row["parameter"])) == group, axis=1)).sum())


def _write_detail(rows: pd.DataFrame) -> str:
    body_rows: list[str] = []
    last_disease = ""
    last_group = ""
    disease_counts = rows["disease"].value_counts().to_dict()
    for _, row in rows.iterrows():
        profile = str(row["profile"])
        disease = str(row["disease"])
        disease_label = r"\verticalcell{COVID-19}" if disease == "covid19" else r"\verticalcell{Mpox}"
        group = _parameter_group(profile, str(row["parameter"]))

        if disease != last_disease:
            body_rows.append(r"\midrule" if body_rows else "")
            disease_cell = rf"\multirow[c]{{{int(disease_counts[disease])}}}{{0.048\textwidth}}{{\centering {disease_label}}}"
        else:
            disease_cell = ""

        if disease != last_disease or group != last_group:
            span = _span(rows, disease, group)
            if span > 1:
                group_cell = rf"\multirow[c]{{{span}}}{{0.098\textwidth}}{{\centering {group}}}"
            else:
                group_cell = group
            if body_rows and disease == last_disease:
                body_rows.append(r"\cmidrule(lr){2-10}")
        else:
            group_cell = ""

        sr = _estimate_from_row(row, "sr")
        module = _estimate_from_row(
            row.rename(
                {
                    "previous_module_point": "module_point",
                    "previous_module_ci_lower": "module_ci_lower",
                    "previous_module_ci_upper": "module_ci_upper",
                }
            ),
            "module",
        )
        e2e = Estimate(
            _finite(row.get("e2e_pooled_mean")),
            _finite(row.get("e2e_ci_lower")),
            _finite(row.get("e2e_ci_upper")),
            _unit(row.get("unit")),
        )
        leads = _parse_estimate(row.get("leads_official"))

        body_rows.append(
            " & ".join(
                [
                    disease_cell,
                    group_cell,
                    _source_label(profile),
                    _fmt_estimate(sr),
                    _fmt_estimate(module),
                    _fmt_estimate(e2e),
                    _fmt_estimate(leads),
                    _fmt_abs_delta(row.get("delta_5d_vs_sr")),
                    _fmt_abs_delta(row.get("delta_e2e_vs_sr"), bold_threshold=1.0),
                    _fmt_abs_delta(row.get("delta_leads_vs_sr")),
                ]
            )
            + r" \\"
        )
        last_disease = disease
        last_group = group

    body = "\n".join(row for row in body_rows if row)
    return rf"""% !TEX root = ../main.tex
\begin{{table}}[p]
\centering
\caption{{Per-source-review coding comparison among source-review (SR), stage-specific \metagent{{}} module, end-to-end (E2E), and LEADS estimates. The module condition uses source-review included studies as fixed inputs, whereas E2E uses records selected by the screening-to-coding pipeline. Absolute deviations are measured against SR; E2E deviations of at least 1.00 unit are bolded.}}
\label{{tab:coding-compare-leads-detail}}
\tiny
\setlength{{\tabcolsep}}{{2.2pt}}
\renewcommand{{\arraystretch}}{{1.24}}
\hfuzz=20pt
\noindent\makebox[\textwidth][c]{{%
\resizebox{{\textwidth}}{{!}}{{%
\begin{{tabular}}{{>{{\centering\arraybackslash}}m{{0.048\textwidth}} >{{\centering\arraybackslash}}m{{0.098\textwidth}} >{{\centering\arraybackslash}}m{{0.134\textwidth}} >{{\centering\arraybackslash}}m{{0.086\textwidth}} >{{\centering\arraybackslash}}m{{0.086\textwidth}} >{{\centering\arraybackslash}}m{{0.086\textwidth}} >{{\centering\arraybackslash}}m{{0.086\textwidth}} >{{\centering\arraybackslash}}m{{0.052\textwidth}} >{{\centering\arraybackslash}}m{{0.052\textwidth}} >{{\centering\arraybackslash}}m{{0.052\textwidth}}}}
\toprule
\multirow[c]{{2}}{{*}}{{\makecell[c]{{Disease}}}} & \multirow[c]{{2}}{{*}}{{\makecell[c]{{Parameter}}}} & \multirow[c]{{2}}{{*}}{{\makecell[c]{{Source\\review}}}} & \multicolumn{{4}}{{c}}{{Estimate (95\% CI)}} & \multicolumn{{3}}{{c}}{{$|\Delta|$ vs SR}} \\
\cmidrule(lr){{4-7}}\cmidrule(lr){{8-10}}
 &  &  & SR & Module & E2E & LEADS & Module & E2E & LEADS \\
\midrule
{body}
\bottomrule
\end{{tabular}}}}}}
\end{{table}}
"""


def main() -> None:
    rows = _load_rows()
    summary = _summary(rows)
    summary_tex = _write_summary(summary)
    detail_tex = _write_detail(rows)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LATEX_TABLES.mkdir(parents=True, exist_ok=True)
    for root in (OUT_DIR, LATEX_TABLES):
        (root / "coding_compare_leads_summary.tex").write_text(summary_tex, encoding="utf-8")
        (root / "coding_compare_leads_detail.tex").write_text(detail_tex, encoding="utf-8")
    print(summary.to_string(index=False))
    print(f"Wrote {LATEX_TABLES / 'coding_compare_leads_summary.tex'}")
    print(f"Wrote {LATEX_TABLES / 'coding_compare_leads_detail.tex'}")


if __name__ == "__main__":
    main()
