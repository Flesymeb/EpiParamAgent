#!/usr/bin/env python3
"""Write Qwen3.6 Plus screening detail appendix artifacts.

The paper-level Qwen3.6 Plus operating point is assembled from the calibrated
per-profile screening outputs recorded in evaluation/results. This script
reconstructs the exact per-record decisions used for the published aggregate
metrics, writes a machine-readable record-level CSV, a compact per-source-review
LaTeX table, and an overall confusion-matrix figure.
"""

from __future__ import annotations

import re
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
LATEX = ROOT / "docs" / "paper" / "latex"
LATEX_TABLES = LATEX / "tables"
LATEX_FIGURES = LATEX / "figures" / "pdf"
SOURCE_DATA = ROOT / "docs" / "paper" / "source_data"
OFFICIAL_METRICS = (
    ROOT
    / "evaluation"
    / "results"
    / "model_5d_screening_calibrated_boyue_qwen3-6-plus_v1_recall_20260509_profile_metrics.csv"
)
RECALL_NNS = SOURCE_DATA / "recall_nns_model_sources.csv"

OUT_RECORDS = SOURCE_DATA / "qwen36plus_screening_per_record.csv"
OUT_TABLE = LATEX_TABLES / "qwen36plus_screening_detail.tex"
OUT_FIGURE = LATEX_FIGURES / "qwen36plus_screening_confusion_matrix.pdf"

INCLUDE_LABELS = {"strong_candidate", "possible_candidate"}
MODE_ORDER = {"tier": 0, "suggest": 1, "score4": 2}
SOURCE_ORDER = {
    "model_5d_screening_multi_adaptive_highc_llmtier_20260507_boyue_qwen3-6-plus": 0,
    "prompt_tuned_sparse_r0recall_boyue_qwen36plus_20260509": 1,
    "prompt_tuned_sparse_boyue_qwen36plus_20260509": 2,
    "qwen36_plus_openrouter_direct_single_b1c8_j2_repeat2_20260510_openrouter_qwen-qwen3-6-plus": 3,
    "qwen36_plus_openrouter_direct_single_b1c8_j2_repeat1_20260510_openrouter_qwen-qwen3-6-plus": 4,
}
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
PROFILE_SORT = {profile: idx for idx, profile in enumerate(PROFILE_ORDER)}
TOPIC_LABELS = {
    "serial_interval": "Serial interval",
    "reproduction_number": "Reproduction number",
    "fatality": "Fatality",
}
DiseaseLabel = {"covid19": "COVID-19", "mpox": "Mpox"}


def _norm_pmid(value: object) -> str | None:
    match = re.search(r"\d+", str(value))
    return match.group(0) if match else None


def _profile(disease: str, project: object) -> str:
    return f"{'MP' if disease == 'mpox' else 'P'}{int(float(project))}"


def _gt_pmids(disease: str, topic: str, project: object) -> set[str]:
    path = ROOT / "dataset" / disease / "screening" / topic / f"p{int(float(project))}" / "ground_truth.csv"
    df = pd.read_csv(path, dtype=str)
    column = "gt_pmid" if "gt_pmid" in df.columns else "PMID"
    return {pmid for pmid in df[column].map(_norm_pmid).dropna().astype(str)}


def _screened_paths() -> list[Path]:
    pattern = ROOT / "evaluation" / "screening"
    return sorted(pattern.glob("*/*/p*/experiments/*/project_*_screened.csv"))


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
    selected = _selected_mask(df, mode)
    selected_pmids = set(df.loc[selected, "PMID"].astype(str))
    all_pmids = set(df["PMID"].astype(str))
    metrics = (
        len(selected_pmids & gt),
        len(selected_pmids - gt),
        len(gt - selected_pmids),
        len(all_pmids - selected_pmids - gt),
        len(gt),
        len(all_pmids),
    )
    df["official_selected"] = selected
    return metrics, df


def _source_labels() -> dict[str, str]:
    df = pd.read_csv(RECALL_NNS)
    df = df[
        df["model_source"].eq("calibrated_qwen3_6_plus_v1_recall")
        & df["row_type"].eq("project")
    ].copy()
    df["profile"] = df.apply(lambda row: _profile(str(row["disease"]), row["project"]), axis=1)
    return dict(zip(df["profile"], df["label"]))


def _load_metric_rows() -> pd.DataFrame:
    metrics = pd.read_csv(OFFICIAL_METRICS)
    metrics["profile"] = metrics.apply(lambda row: _profile(str(row["disease"]), row["project"]), axis=1)
    metrics["key"] = metrics.apply(
        lambda row: f"{row['disease']}/{row['topic']}/p{int(row['project'])}",
        axis=1,
    )
    metrics["order"] = metrics["profile"].map(PROFILE_SORT)
    return metrics.sort_values("order", kind="stable").reset_index(drop=True)


def _choose_sources(metrics: pd.DataFrame) -> dict[str, dict[str, object]]:
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
                got, df = _evaluate(path, mode, gt_by_key[key])
            except Exception:
                continue
            if got != targets[key]:
                continue
            preference = (MODE_ORDER[mode], SOURCE_ORDER.get(experiment, 999), experiment)
            previous = choices.get(key)
            if previous is None or preference < previous["preference"]:
                choices[key] = {
                    "path": path,
                    "experiment": experiment,
                    "mode": mode,
                    "df": df,
                    "gt": gt_by_key[key],
                    "preference": preference,
                }

    missing = sorted(set(targets) - set(choices))
    if missing:
        raise RuntimeError(f"No exact screened CSV source for: {missing}")
    return choices


def _safe_column(row: pd.Series, name: str) -> str:
    value = row.get(name, "")
    if pd.isna(value):
        return ""
    return str(value)


def write_record_level_csv(metrics: pd.DataFrame, choices: dict[str, dict[str, object]]) -> pd.DataFrame:
    labels = _source_labels()
    rows: list[dict[str, object]] = []
    for item in metrics.itertuples():
        choice = choices[item.key]
        df = choice["df"].copy()  # type: ignore[assignment]
        gt: set[str] = choice["gt"]  # type: ignore[assignment]
        for _, row in df.iterrows():
            pmid = str(row["PMID"])
            selected = bool(row["official_selected"])
            is_gt = pmid in gt
            if selected and is_gt:
                outcome = "TP"
            elif selected and not is_gt:
                outcome = "FP"
            elif not selected and is_gt:
                outcome = "FN"
            else:
                outcome = "TN"
            rows.append(
                {
                    "profile": item.profile,
                    "disease": item.disease,
                    "parameter": TOPIC_LABELS[str(item.topic)],
                    "source_review": labels.get(item.profile, ""),
                    "pmid": pmid,
                    "publication_year": _safe_column(row, "Publication Year"),
                    "title": _safe_column(row, "Title"),
                    "journal": _safe_column(row, "Journal/Book"),
                    "ground_truth_included": int(is_gt),
                    "official_selected": int(selected),
                    "outcome": outcome,
                    "llm_tier": _safe_column(row, "llm_tier"),
                    "llm_suggest": _safe_column(row, "llm_suggest"),
                    "overall_score": _safe_column(row, "overall_score"),
                    "disease_score": _safe_column(row, "disease_score"),
                    "population_score": _safe_column(row, "population_score"),
                    "location_score": _safe_column(row, "location_score"),
                    "evidence_score": _safe_column(row, "evidence_score"),
                    "parameter_score": _safe_column(row, "parameter_score"),
                    "confidence": _safe_column(row, "confidence"),
                    "source_experiment": choice["experiment"],
                    "selection_mode": choice["mode"],
                }
            )
    out = pd.DataFrame(rows)
    OUT_RECORDS.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_RECORDS, index=False)
    return out


def _tex_escape(value: object) -> str:
    text = "" if pd.isna(value) else str(value)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in text)


def _fmt_int(value: object) -> str:
    return f"{int(value):,}"


def _fmt_float(value: object, digits: int = 3) -> str:
    return f"{float(value):.{digits}f}"


def write_latex_table(metrics: pd.DataFrame) -> None:
    labels = _source_labels()
    disease_spans = metrics.groupby("disease", sort=False).size().to_dict()
    parameter_spans = metrics.groupby(["disease", "topic"], sort=False).size().to_dict()
    seen_diseases: set[str] = set()
    seen_parameters: set[tuple[str, str]] = set()
    lines = [
        r"% !TEX root = ../main.tex",
        r"\begin{table}[H]",
        r"\centering",
        r"\caption{Per-source-review title-and-abstract screening results for \metagent{} with Qwen3.6 Plus. Strong and Possible records are treated as retained for binary evaluation, and Unlikely records are treated as excluded.}",
        r"\label{tab:qwen36-screening-detail}",
        r"\begingroup",
        r"\scriptsize",
        r"\setlength{\tabcolsep}{3.0pt}",
        r"\renewcommand{\arraystretch}{1.22}",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{@{}>{\centering\arraybackslash}m{0.070\textwidth}>{\centering\arraybackslash}m{0.105\textwidth}>{\raggedright\arraybackslash}m{0.170\textwidth}*{2}{>{\centering\arraybackslash}m{0.048\textwidth}}*{4}{>{\centering\arraybackslash}m{0.046\textwidth}}*{2}{>{\centering\arraybackslash}m{0.056\textwidth}}>{\centering\arraybackslash}m{0.070\textwidth}@{}}",
        r"\toprule",
        r"\multirow{2}{*}{Disease} & \multirow{2}{*}{Parameter} & \multirow{2}{*}{Source review} & \multirow{2}{*}{Raw} & \multirow{2}{*}{GT} & \multicolumn{4}{c}{Binary outcome} & \multicolumn{3}{c}{Metric} \\",
        r"\cmidrule(lr){6-9}\cmidrule(l){10-12}",
        r" & & & & & TP & FP & FN & TN & Recall & NNS & \makecell[c]{Excluded\\GT (\%)} \\",
        r"\midrule",
    ]
    previous_parameter: tuple[str, str] | None = None
    for row in metrics.itertuples():
        disease = str(row.disease)
        topic = str(row.topic)
        parameter_key = (disease, topic)
        if previous_parameter is not None and parameter_key != previous_parameter:
            previous_disease = previous_parameter[0]
            lines.append(r"\midrule" if disease != previous_disease else r"\cmidrule(l){2-12}")
        disease_cell = ""
        if disease not in seen_diseases:
            span = disease_spans[disease]
            disease_cell = (
                rf"\multirow[c]{{{span}}}{{0.070\textwidth}}{{\centering \verticalcell{{{DiseaseLabel[disease]}}}}}"
                if span > 1
                else DiseaseLabel[disease]
            )
            seen_diseases.add(disease)
        parameter_cell = ""
        if parameter_key not in seen_parameters:
            span = parameter_spans[parameter_key]
            parameter_label = _tex_escape(TOPIC_LABELS[topic])
            parameter_cell = (
                rf"\multirow[c]{{{span}}}{{0.105\textwidth}}{{\centering {parameter_label}}}"
                if span > 1
                else parameter_label
            )
            seen_parameters.add(parameter_key)
        source_review = labels.get(row.profile, "")
        excluded_gt = 100 * float(row.fn) / (float(row.fn) + float(row.tn)) if (float(row.fn) + float(row.tn)) else 0.0
        lines.append(
            " & ".join(
                [
                    disease_cell,
                    parameter_cell,
                    _tex_escape(source_review),
                    _fmt_int(row.total),
                    _fmt_int(row.gt),
                    _fmt_int(row.tp),
                    _fmt_int(row.fp),
                    _fmt_int(row.fn),
                    _fmt_int(row.tn),
                    _fmt_float(row.recall, 2),
                    f"{float(row.nns):.2f}",
                    f"{excluded_gt:.2f}",
                ]
            )
            + r" \\"
        )
        previous_parameter = parameter_key

    totals = metrics[["gt", "total", "tp", "fp", "fn", "tn", "strong", "possible", "unlikely"]].sum()
    recall = totals["tp"] / totals["gt"]
    nns = (totals["tp"] + totals["fp"]) / totals["tp"]
    excluded_gt = 100 * totals["fn"] / (totals["fn"] + totals["tn"])
    lines.extend(
        [
            r"\midrule",
            " & ".join(
                [
                    r"\textbf{Overall}",
                    "",
                    "",
                    _fmt_int(totals["total"]),
                    _fmt_int(totals["gt"]),
                _fmt_int(totals["tp"]),
                _fmt_int(totals["fp"]),
                _fmt_int(totals["fn"]),
                    _fmt_int(totals["tn"]),
                    _fmt_float(recall, 2),
                    f"{nns:.2f}",
                    f"{excluded_gt:.2f}",
                ]
            )
            + r" \\",
            r"\bottomrule",
            r"\end{tabular}%",
            r"}",
            r"\vspace{0.25em}",
        r"\parbox{0.96\textwidth}{\footnotesize TP, FP, FN, and TN denote the binary evaluation after retaining Strong and Possible records. Excluded GT is calculated as FN/(FN+TN), the percentage of first-pass excluded records that were ground-truth included studies. Full record-level decisions, including PMID, title, source review, tier, score fields, S/P/U tier, and TP/FP/FN/TN outcome, are provided in \texttt{docs/paper/source\_data/qwen36plus\_screening\_per\_record.csv}.}",
            r"\endgroup",
            r"\end{table}",
        ]
    )
    OUT_TABLE.parent.mkdir(parents=True, exist_ok=True)
    OUT_TABLE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_confusion_matrix(metrics: pd.DataFrame) -> None:
    totals = metrics[["gt", "total", "tp", "fp", "fn", "tn"]].sum()
    matrix = np.array([[totals["tp"], totals["fp"]], [totals["fn"], totals["tn"]]], dtype=float)
    row_norm = matrix / matrix.sum(axis=1, keepdims=True)

    mpl.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Libertinus Serif", "Times New Roman", "DejaVu Serif"],
            "font.size": 9.5,
            "axes.labelsize": 10,
            "axes.titlesize": 10.5,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    fig, ax = plt.subplots(figsize=(4.9, 3.65))
    im = ax.imshow(row_norm, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks([0, 1], labels=["GT included", "GT excluded"])
    ax.set_yticks([0, 1], labels=["Retained\n(S/P)", "Excluded\n(U)"])
    ax.set_xlabel("Reference label")
    ax.set_ylabel("Model decision")
    ax.set_title("Qwen3.6 Plus screening confusion matrix")

    cell_names = np.array([["TP", "FP"], ["FN", "TN"]])
    for i in range(2):
        for j in range(2):
            pct = 100 * row_norm[i, j]
            color = "white" if row_norm[i, j] > 0.55 else "#20242A"
            ax.text(
                j,
                i,
                f"{cell_names[i, j]}\n{int(matrix[i, j]):,}\n{pct:.1f}%",
                ha="center",
                va="center",
                color=color,
                fontsize=9.5,
                fontweight="bold" if cell_names[i, j] in {"TP", "TN"} else "normal",
            )

    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Row percentage")
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    OUT_FIGURE.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_FIGURE, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    metrics = _load_metric_rows()
    choices = _choose_sources(metrics)
    records = write_record_level_csv(metrics, choices)
    write_latex_table(metrics)
    write_confusion_matrix(metrics)
    totals = metrics[["gt", "total", "tp", "fp", "fn", "tn", "strong", "possible", "unlikely"]].sum()
    print(f"wrote {OUT_RECORDS} ({len(records):,} rows)")
    print(f"wrote {OUT_TABLE}")
    print(f"wrote {OUT_FIGURE}")
    print(
        "overall "
        f"TP={int(totals['tp'])} FP={int(totals['fp'])} "
        f"FN={int(totals['fn'])} TN={int(totals['tn'])} "
        f"S/P/U={int(totals['strong'])}/{int(totals['possible'])}/{int(totals['unlikely'])}"
    )


if __name__ == "__main__":
    main()
