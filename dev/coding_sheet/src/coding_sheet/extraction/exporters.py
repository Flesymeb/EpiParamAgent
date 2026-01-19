from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Type, Union

import pandas as pd
from pydantic import BaseModel
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from ..schema import CodingSheetRecord
from ..template import DEFAULT_TEMPLATE, TemplateSpec
from ..config_schema import ProjectConfig, get_column_mapping


def export_coding_sheet(
    records: Iterable[BaseModel],
    *,
    out_dir: str | Path,
    basename: str = "coding_sheet",
    template: TemplateSpec | None = None,
    config: Optional[ProjectConfig] = None,
) -> tuple[Path, Path]:
    """Export records to Excel and CSV.

    Args:
        records: Iterable of record objects (CodingSheetRecord or dynamic model)
        out_dir: Output directory
        basename: Base filename
        template: Legacy template spec (ignored if config provided)
        config: ProjectConfig for dynamic column mapping

    Returns:
        Tuple of (xlsx_path, csv_path)
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    xlsx_path = out_dir / f"{basename}_{ts}.xlsx"
    csv_path = out_dir / f"{basename}_{ts}.csv"

    records_list = list(records)
    if not records_list:
        # Empty export
        df = pd.DataFrame()
        df.to_excel(xlsx_path, index=False)
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        return xlsx_path, csv_path

    # Determine if using config-driven mode
    first_record = records_list[0]
    record_config: Optional[ProjectConfig] = getattr(
        type(first_record), "_project_config", None
    )

    if config is not None:
        record_config = config

    if record_config is not None:
        # Config-driven export
        return _export_config_driven(records_list, record_config, xlsx_path, csv_path)
    else:
        # Legacy export
        return _export_legacy(records_list, template, xlsx_path, csv_path)


def _export_config_driven(
    records: list[BaseModel],
    config: ProjectConfig,
    xlsx_path: Path,
    csv_path: Path,
) -> tuple[Path, Path]:
    """Export using config-driven column mapping."""

    # Build field → column mapping from config
    field_to_column = {f.name: f.label for f in config.fields}

    # Add metadata columns
    metadata_mapping = {
        "extraction_confidence": "Extraction_Confidence",
        "needs_review": "Needs_Review",
        "review_notes": "Review_Notes",
        "evidence_chunk_ids": "Evidence_Chunk_IDs",
        "source_id": "Source_ID",
        "source_doi": "Source_DOI",
        "source_database": "Source_Database",
        "extractor_model": "Extractor_Model",
        "extraction_timestamp": "Extraction_Timestamp",
    }
    field_to_column.update(metadata_mapping)

    # Build column order: user fields first, then metadata
    column_order = [f.label for f in config.fields]
    column_order.extend(metadata_mapping.values())

    rows = []
    for r in records:
        row = {}
        for field_name, col_name in field_to_column.items():
            value = getattr(r, field_name, None)
            # Handle list fields
            if isinstance(value, list):
                value = json.dumps(value, ensure_ascii=False)
            row[col_name] = value
        rows.append(row)

    df = pd.DataFrame(rows)
    df = df.reindex(columns=[c for c in column_order if c in df.columns])

    # Sort by Study column (case-insensitive) if it exists
    study_col = None
    for col in df.columns:
        if col.lower() == "study":
            study_col = col
            break
    if study_col:
        df = df.sort_values(by=study_col, ascending=True, na_position="last")
        df = df.reset_index(drop=True)

    # Write Excel with formatting
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="All Records")

        # Apply formatting
        _format_excel_sheet(w.book["All Records"], df)

        if "Needs_Review" in df.columns:
            df_review = df[df["Needs_Review"] == True]
            if not df_review.empty:
                df_review.to_excel(w, index=False, sheet_name="Needs Review")
                _format_excel_sheet(w.book["Needs Review"], df_review)

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    return xlsx_path, csv_path


def _format_excel_sheet(ws, df):
    """Apply formatting to Excel worksheet.

    - Header row: bold, colored background
    - Study column: merge cells for same study (for superspreading analysis)
    - Data_Source column: color-coded by type
    - Alternating row colors for readability
    """
    # Color schemes
    HEADER_FILL = PatternFill(
        start_color="4472C4", end_color="4472C4", fill_type="solid"
    )
    HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)

    DATA_SOURCE_COLORS = {
        "ten_retest": PatternFill(
            start_color="E7E6F7", end_color="E7E6F7", fill_type="solid"
        ),  # Light purple
        "predictive_validity": PatternFill(
            start_color="FFF2CC", end_color="FFF2CC", fill_type="solid"
        ),  # Light yellow
        "teacher_rating": PatternFill(
            start_color="FCE4D6", end_color="FCE4D6", fill_type="solid"
        ),  # Light orange
    }

    ALT_ROW_FILL = PatternFill(
        start_color="F2F2F2", end_color="F2F2F2", fill_type="solid"
    )  # Light gray
    BORDER = Border(
        left=Side(style="thin", color="D3D3D3"),
        right=Side(style="thin", color="D3D3D3"),
        top=Side(style="thin", color="D3D3D3"),
        bottom=Side(style="thin", color="D3D3D3"),
    )

    # Format header row
    for cell in ws[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(
            horizontal="center", vertical="center", wrap_text=True
        )
        cell.border = BORDER

    # Find column indices
    study_col_idx = None
    data_source_col_idx = None
    for idx, col_name in enumerate(df.columns, start=1):
        if col_name == "Study" or col_name == "study":
            study_col_idx = idx
        elif col_name == "Data_Source":
            data_source_col_idx = idx

    # Merge cells for Study column only (same study = same value)
    if study_col_idx:
        _merge_consecutive_cells(ws, study_col_idx, df, "Study")

    # Apply alternating row colors and data_source colors
    for row_idx in range(2, len(df) + 2):
        # Alternating background for entire row
        if row_idx % 2 == 0:
            for col_idx in range(1, len(df.columns) + 1):
                ws.cell(row_idx, col_idx).fill = ALT_ROW_FILL
                ws.cell(row_idx, col_idx).border = BORDER
        else:
            for col_idx in range(1, len(df.columns) + 1):
                ws.cell(row_idx, col_idx).border = BORDER

        # Color-code Data_Source column
        if data_source_col_idx:
            cell = ws.cell(row_idx, data_source_col_idx)
            data_source_value = cell.value
            if data_source_value in DATA_SOURCE_COLORS:
                cell.fill = DATA_SOURCE_COLORS[data_source_value]

    # Merge Study column cells for same study
    if study_col_idx and "Study" in df.columns:
        current_study = None
        start_row = 2

        for row_idx in range(2, len(df) + 2):
            study_value = ws.cell(row_idx, study_col_idx).value

            if study_value != current_study:
                # Merge previous group if more than 1 row
                if current_study is not None and row_idx - 1 > start_row:
                    ws.merge_cells(
                        start_row=start_row,
                        start_column=study_col_idx,
                        end_row=row_idx - 1,
                        end_column=study_col_idx,
                    )
                    # Center align merged cell
                    ws.cell(start_row, study_col_idx).alignment = Alignment(
                        horizontal="center", vertical="center", wrap_text=True
                    )

                current_study = study_value
                start_row = row_idx

        # Merge last group
        if current_study is not None and len(df) + 1 > start_row:
            ws.merge_cells(
                start_row=start_row,
                start_column=study_col_idx,
                end_row=len(df) + 1,
                end_column=study_col_idx,
            )
            ws.cell(start_row, study_col_idx).alignment = Alignment(
                horizontal="center", vertical="center", wrap_text=True
            )

    # Auto-adjust column widths
    for col_idx in range(1, len(df.columns) + 1):
        col_letter = get_column_letter(col_idx)
        max_length = 0

        # Check header length
        header_cell = ws.cell(1, col_idx)
        if header_cell.value:
            max_length = len(str(header_cell.value))

        # Check data lengths (sample first 100 rows for performance)
        for row_idx in range(2, min(102, len(df) + 2)):
            cell = ws.cell(row_idx, col_idx)
            if cell.value:
                cell_length = len(str(cell.value))
                if cell_length > max_length:
                    max_length = cell_length

        # Set width (with max limit)
        adjusted_width = min(max_length + 2, 50)
        ws.column_dimensions[col_letter].width = adjusted_width

    # Freeze first row (header)
    ws.freeze_panes = "A2"


def _merge_consecutive_cells(ws, col_idx, df, col_name):
    """Merge consecutive cells with same value in specified column.

    Args:
        ws: openpyxl worksheet
        col_idx: Column index (1-based)
        df: DataFrame for value lookup
        col_name: Column name to search for in df
    """
    from openpyxl.utils import get_column_letter

    # Find actual column name in df (case-insensitive)
    actual_col = None
    for c in df.columns:
        if c.lower() == col_name.lower():
            actual_col = c
            break

    if actual_col is None:
        return

    col_letter = get_column_letter(col_idx)
    values = df[actual_col].tolist()

    if not values:
        return

    # Track consecutive ranges
    start_row = 2  # Data starts at row 2 (row 1 is header)
    current_value = values[0]
    merge_start = start_row

    for i in range(1, len(values)):
        row_num = start_row + i
        if values[i] != current_value:
            # Different value - merge previous group if needed
            merge_end = row_num - 1
            if merge_end > merge_start:
                ws.merge_cells(f"{col_letter}{merge_start}:{col_letter}{merge_end}")
                ws[f"{col_letter}{merge_start}"].alignment = Alignment(
                    horizontal="center", vertical="center"
                )
            # Start new group
            current_value = values[i]
            merge_start = row_num

    # Handle final group
    final_row = start_row + len(values) - 1
    if final_row > merge_start:
        ws.merge_cells(f"{col_letter}{merge_start}:{col_letter}{final_row}")
        ws[f"{col_letter}{merge_start}"].alignment = Alignment(
            horizontal="center", vertical="center"
        )


def _export_legacy(
    records: list[BaseModel],
    template: Optional[TemplateSpec],
    xlsx_path: Path,
    csv_path: Path,
) -> tuple[Path, Path]:
    """Export using legacy hardcoded mapping - for CodingSheetRecord."""

    rows = []
    for r in records:
        # Type hint for IDE - these are CodingSheetRecord
        rows.append(
            {
                "Study": getattr(r, "study", None),
                "Country": getattr(r, "country", None),
                "Student_Type": getattr(r, "student_type", None),
                "Gender (Boy%)": getattr(r, "gender_boy_percent", None),
                "Age (T1)": getattr(r, "age_t1", None),
                "Age (T2)": getattr(r, "age_t2", None),
                "Interval": getattr(r, "interval", None),
                "n": getattr(r, "n", None),
                "Early Numeracy Measurements": getattr(
                    r, "early_numeracy_measurements", None
                ),
                "Early Numeracy Skills": getattr(r, "early_numeracy_skills", None),
                "Later Mathematics Measures": getattr(
                    r, "later_mathematics_measures", None
                ),
                "Mathematics Domains": getattr(r, "mathematics_domains", None),
                "Correlations": getattr(r, "correlations", None),
                "Evidence_Chunk_IDs": (
                    json.dumps(
                        getattr(r, "evidence_chunk_ids", None), ensure_ascii=False
                    )
                    if getattr(r, "evidence_chunk_ids", None) is not None
                    else None
                ),
                "Evidence_Quotes": (
                    "\n---\n".join(getattr(r, "evidence_quotes", []) or [])
                    if getattr(r, "evidence_quotes", None)
                    else None
                ),
                "Extraction_Confidence": getattr(r, "extraction_confidence", None),
                "Needs_Review": getattr(r, "needs_review", None),
                "Review_Notes": getattr(r, "review_notes", None),
                "Source_ID": getattr(r, "source_id", None),
                "Source_DOI": getattr(r, "source_doi", None),
                "Source_Database": getattr(r, "source_database", None),
                "Extractor_Model": getattr(r, "extractor_model", None),
                "Extraction_Timestamp": getattr(r, "extraction_timestamp", None),
            }
        )

    df = pd.DataFrame(rows)

    # Keep template core columns at front
    spec = template or DEFAULT_TEMPLATE
    core_cols = list(spec.core_columns)
    ordered = core_cols + [c for c in df.columns if c not in core_cols]
    df = df.reindex(columns=ordered)

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="All Records")

        # Apply formatting
        _format_excel_sheet(w.book["All Records"], df)

        if "Needs_Review" in df.columns:
            df_review = df[df["Needs_Review"] == True]
            if not df_review.empty:
                df_review.to_excel(w, index=False, sheet_name="Needs Review")
                _format_excel_sheet(w.book["Needs Review"], df_review)

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    return xlsx_path, csv_path
