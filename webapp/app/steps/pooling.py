from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import pandas as pd
from sqlmodel import Session, select

from app.db import engine
from app.events import StreamToEvents
from app.models import PipelineStep

# Topic key (from UI) -> canonical parameter_type label used in coding sheets.
# Mirrors tools/scripts/evaluate_coding.py::TOPIC_PARAM.
TOPIC_PARAM = {
    "serial_interval": "serial_interval",
    "reproduction_number": "R0",
    "fatality": "CFR",
}


def run_pooling_step(run_id: str, params: dict[str, Any]) -> str:
    input_path = _resolve_input_path(run_id, params)
    out_dir = Path("data") / "runs" / run_id / "step-5"
    out_dir.mkdir(parents=True, exist_ok=True)
    pooled_path = out_dir / "pooled.csv"
    forest_path = out_dir / "forest.csv"

    with Session(engine) as session:
        stream = StreamToEvents(session=session, run_id=run_id, step_no=5)
        with redirect_stdout(stream), redirect_stderr(stream):
            from tools.analysis.pooling import enrich_ci, summarize

            print(f"pooling step: input={input_path}")
            df = _load_table(input_path)
            print(f"pooling step: loaded rows={len(df)} columns={len(df.columns)}")

            target = _resolve_parameter_type(df, params)

            # Mirror evaluate_coding.py: enrich CIs before pooling.
            df_enriched = enrich_ci(df)
            pooled = summarize(
                df_enriched,
                parameter_type=target,
                estimate_measure=params.get("estimate_measure", "mean"),
                include_median=_bool_param(params.get("include_median"), False),
                impute_missing_se=_bool_param(params.get("impute_missing_se"), True),
                group_by=params.get("group_by"),
                method=str(params.get("method", "random")),
                log_transform=_bool_param(params.get("log_transform"), False),
            )
            pooled.to_csv(pooled_path, index=False)
            print(f"pooling step: wrote {pooled_path}")

            forest, forest_notes = _build_forest_rows(df_enriched, target, params)
            forest.to_csv(forest_path, index=False)
            print(f"pooling step: wrote {forest_path} with {len(forest)} studies")
            for note in forest_notes:
                print(f"pooling step: forest.csv {note}")

    return str(pooled_path)


def _resolve_parameter_type(df: pd.DataFrame, params: dict[str, Any]) -> str | None:
    """Resolve the parameter_type filter, mirroring tools/scripts/evaluate_coding.py.

    Precedence: explicit params['parameter_type'] > TOPIC_PARAM[params['parameter']]
    > params['parameter'] as-is. Then case-insensitive match against the sheet's
    available values; if absent, warn loudly and fall back to no filter.
    """
    explicit = params.get("parameter_type")
    parameter = params.get("parameter")
    if explicit:
        target: str | None = str(explicit)
    elif parameter:
        target = TOPIC_PARAM.get(str(parameter), str(parameter))
    else:
        target = None

    if target is None:
        print("pooling step: no parameter_type filter requested; pooling all rows")
        return None

    if "parameter_type" not in df.columns:
        print(f"pooling step: no 'parameter_type' column; ignoring filter {target!r}")
        return None

    available = df["parameter_type"].dropna().unique().tolist()
    if target in available:
        print(f"pooling step: parameter_type={target!r} (rows match)")
        return target

    match = next((p for p in available if p.lower().strip() == target.lower()), None)
    if match:
        print(f"pooling step: parameter_type {target!r} matched {match!r}")
        return match

    print(
        f"pooling step: WARNING parameter_type {target!r} NOT found. "
        f"Available: {available}. Pooling WITHOUT filter — "
        "results may mix different parameter types."
    )
    return None


def _resolve_input_path(run_id: str, params: dict[str, Any]) -> Path:
    explicit = params.get("input_path")
    if explicit:
        path = Path(str(explicit))
        if not path.exists():
            raise FileNotFoundError(f"Input artifact not found: {path}")
        return path

    with Session(engine) as session:
        step = session.exec(
            select(PipelineStep).where(
                PipelineStep.run_id == run_id,
                PipelineStep.step_no == 4,
            )
        ).one_or_none()

    if step is None:
        raise FileNotFoundError("No step-4 artifact found for this run")

    artifact = step.edited_artifact_path or step.artifact_path
    if not artifact:
        raise FileNotFoundError("Step 4 has no artifact path")

    path = Path(artifact)
    if not path.exists():
        raise FileNotFoundError(f"Step-4 artifact not found: {path}")
    return path


def _load_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if suffix == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported pooling input format: {path}")


def _build_forest_rows(
    df: pd.DataFrame,
    parameter_type: str | None,
    params: dict[str, Any],
) -> tuple[pd.DataFrame, list[str]]:
    work = _filter_forest_input(df, parameter_type, params)
    notes: list[str] = []

    estimate_col = _find_column(
        work,
        (
            "point_estimate",
            "estimate",
            "effect_estimate",
            "effect_size",
            "mean",
            "value",
        ),
    )
    ci_lower_col = _find_column(
        work,
        (
            "ci_95_derived_lower",
            "ci_lower",
            "lower_ci",
            "ci_low",
            "lower",
        ),
    )
    ci_upper_col = _find_column(
        work,
        (
            "ci_95_derived_upper",
            "ci_upper",
            "upper_ci",
            "ci_high",
            "upper",
        ),
    )

    if estimate_col is None:
        notes.append("could not identify an estimate column; estimate values left blank")
    elif estimate_col != "point_estimate":
        notes.append(f"using fallback estimate column {estimate_col!r}")

    if ci_lower_col is None or ci_upper_col is None:
        notes.append("could not identify complete CI columns; missing CI values left blank")

    forest = pd.DataFrame(
        {
            "study_label": _study_labels(work),
            "estimate": work[estimate_col] if estimate_col else "",
            "ci_lower": _ci_values(work, ci_lower_col, "uncertainty_low"),
            "ci_upper": _ci_values(work, ci_upper_col, "uncertainty_high"),
        }
    )
    return forest, notes


def _filter_forest_input(
    df: pd.DataFrame,
    parameter_type: str | None,
    params: dict[str, Any],
) -> pd.DataFrame:
    work = df.copy()

    if parameter_type and "parameter_type" in work.columns:
        work = work[
            work["parameter_type"].astype(str).str.strip().str.lower()
            == parameter_type.strip().lower()
        ]

    estimate_measure = params.get("estimate_measure", "mean")
    if estimate_measure is None or "estimate_measure" not in work.columns:
        return work.copy()

    measure = str(estimate_measure).strip().lower()
    em = work["estimate_measure"].astype(str).str.strip().str.lower()

    if measure == "mean" and _bool_param(params.get("include_median"), False):
        if "pmid" in work.columns:
            pmids_with_mean = set(work.loc[em == "mean", "pmid"].astype(str))
            median_mask = (em == "median") & ~work["pmid"].astype(str).isin(
                pmids_with_mean
            )
        else:
            median_mask = em == "median"
        return work[(em == "mean") | median_mask].copy()

    return work[em == measure].copy()


def _find_column(df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    normalized = {str(column).strip().lower(): str(column) for column in df.columns}
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    return None


def _study_labels(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return []

    study_col = _find_column(df, ("study", "study_id", "study_label", "label"))
    if study_col:
        return _dedupe_labels(
            [
                str(value).strip() if pd.notna(value) and str(value).strip() else ""
                for value in df[study_col]
            ],
            df.index,
        )

    author_col = _find_column(df, ("first_author", "author", "authors"))
    year_col = _find_column(df, ("year", "publication_year"))
    if author_col and year_col:
        labels = []
        for _, row in df.iterrows():
            author = row.get(author_col)
            year = row.get(year_col)
            parts = [
                str(value).strip()
                for value in (author, year)
                if pd.notna(value) and str(value).strip()
            ]
            labels.append("/".join(parts))
        return _dedupe_labels(labels, df.index)

    for column in (
        author_col,
        _find_column(df, ("pmid", "doi", "title")),
    ):
        if column:
            return _dedupe_labels(
                [
                    str(value).strip()
                    if pd.notna(value) and str(value).strip()
                    else ""
                    for value in df[column]
                ],
                df.index,
            )

    return [f"row {index}" for index in df.index]


def _dedupe_labels(labels: list[str], indexes: pd.Index) -> list[str]:
    counts: dict[str, int] = {}
    deduped: list[str] = []

    for label, index in zip(labels, indexes, strict=False):
        base = label or f"row {index}"
        counts[base] = counts.get(base, 0) + 1
        if counts[base] == 1:
            deduped.append(base)
        else:
            deduped.append(f"{base} #{counts[base]}")

    return deduped


def _ci_values(
    df: pd.DataFrame,
    ci_col: str | None,
    uncertainty_col: str,
) -> pd.Series | str:
    if ci_col:
        return df[ci_col]

    if uncertainty_col not in df.columns or "uncertainty_type" not in df.columns:
        return ""

    uncertainty_type = (
        df["uncertainty_type"]
        .astype(str)
        .str.replace(r"[\s_/\-]", "", regex=True)
        .str.lower()
    )
    ci_mask = uncertainty_type.isin(
        (
            "ci",
            "cri",
            "confidenceinterval",
            "confidenceintervals",
            "credibleinterval",
            "credibleintervals",
        )
    )
    return df[uncertainty_col].where(ci_mask, "")


def _bool_param(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return bool(value)
