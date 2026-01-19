from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd


# EN.xlsx-compatible core columns (Legacy template for early numeracy psychology research)
# For new projects, use config-based dynamic columns via ProjectConfig
EN_XLSX_COLUMNS: list[str] = [
    "Study",
    "Country",
    "Student_Type",
    "Gender (Boy%)",
    "Age (T1)",
    "Age (T2)",
    "Interval",
    "n",
    "Early Numeracy Measurements",
    "Early Numeracy Skills",
    "Later Mathematics Measures",
    "Mathematics Domains",
    "Correlations",
]


QC_COLUMNS: list[str] = [
    "Extraction_Confidence",
    "Needs_Review",
    "Review_Notes",
    "Source_ID",
    "Source_DOI",
    "Source_Database",
    "Extractor_Model",
    "Extraction_Timestamp",
]


@dataclass(frozen=True)
class TemplateSpec:
    """Coding-sheet template specification.

    Legacy template system. New projects should use config-based
    schemas (ProjectConfig + get_model()) for flexible field definitions.

    DEFAULT_TEMPLATE matches EN.xlsx (early numeracy psychology) for backward compatibility.
    """

    name: str
    core_columns: tuple[str, ...]
    qc_columns: tuple[str, ...] = tuple()

    def columns(self, *, include_qc_columns: bool = False) -> list[str]:
        cols = list(self.core_columns)
        if include_qc_columns and self.qc_columns:
            cols.extend(list(self.qc_columns))
        return cols


DEFAULT_TEMPLATE = TemplateSpec(
    name="en_xlsx_v1",
    core_columns=tuple(EN_XLSX_COLUMNS),
    qc_columns=tuple(QC_COLUMNS),
)


def make_empty_template_dataframe(
    *,
    template: TemplateSpec | None = None,
    include_qc_columns: bool = False,
) -> pd.DataFrame:
    """Create an empty coding sheet DataFrame (headers only)."""

    spec = template or DEFAULT_TEMPLATE
    return pd.DataFrame(columns=spec.columns(include_qc_columns=include_qc_columns))


def export_empty_template(
    *,
    out_dir: str | Path,
    basename: str = "coding_sheet_template",
    include_qc_columns: bool = False,
    template: TemplateSpec | None = None,
) -> tuple[Path, Path]:
    """Export an empty coding sheet template (xlsx + csv)."""

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    xlsx_path = out_dir / f"{basename}_{ts}.xlsx"
    csv_path = out_dir / f"{basename}_{ts}.csv"

    df = make_empty_template_dataframe(
        template=template,
        include_qc_columns=include_qc_columns,
    )

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Template")

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    return xlsx_path, csv_path


def load_template_columns_from_xlsx(
    xlsx_path: str | Path,
    *,
    sheet_name: str | int | None = 0,
) -> list[str]:
    """Load header columns from an existing XLSX.

    Intended for future: align to a ground-truth Excel template without changing code.
    """

    df = pd.read_excel(Path(xlsx_path), sheet_name=sheet_name, nrows=0)
    return [str(c) for c in df.columns]


def template_from_xlsx(
    xlsx_path: str | Path,
    *,
    name: str = "from_xlsx",
    sheet_name: str | int | None = 0,
) -> TemplateSpec:
    cols = load_template_columns_from_xlsx(xlsx_path, sheet_name=sheet_name)
    return TemplateSpec(name=name, core_columns=tuple(cols), qc_columns=tuple())


__all__ = [
    "EN_XLSX_COLUMNS",
    "QC_COLUMNS",
    "TemplateSpec",
    "DEFAULT_TEMPLATE",
    "make_empty_template_dataframe",
    "export_empty_template",
    "load_template_columns_from_xlsx",
    "template_from_xlsx",
]
