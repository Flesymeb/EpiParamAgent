"""Project-aware planning and manifests for full-text PDF retrieval."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class PdfFetchRecord:
    """One PubMed record selected for full-text retrieval."""

    pmid: str
    doi: str = ""
    pmcid: str = ""
    tier: str = ""


def _slug(value: str) -> str:
    text = re.sub(r"[^\w]+", "_", str(value).strip().casefold(), flags=re.UNICODE)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        raise ValueError("Disease, parameter, and project ID must contain path-safe text")
    return text


def project_fetch_dir(
    *,
    paper_pool: Path,
    disease: str,
    parameter: str,
    project_id: str,
) -> Path:
    """Return the project manifest directory inside the shared paper pool."""
    return (
        Path(paper_pool)
        / "projects"
        / _slug(disease)
        / _slug(parameter)
        / _slug(project_id)
    )


def default_fetch_input(
    *,
    project_root: Path,
    disease: str,
    parameter: str,
    project_id: str,
    source: str,
) -> Path:
    """Resolve the conventional raw or screened project CSV path."""
    disease_key = _slug(disease)
    parameter_key = _slug(parameter)
    project_key = _slug(project_id)
    if source == "raw":
        return (
            Path(project_root)
            / "dataset"
            / disease_key
            / "screening"
            / parameter_key
            / project_key
            / "raw.csv"
        )
    if source != "screened":
        raise ValueError("A custom source requires an explicit input path")

    canonical = (
        Path(project_root)
        / "evaluation"
        / disease_key
        / "screening"
        / parameter_key
        / project_key
        / "screened.csv"
    )
    project_number = re.sub(r"^[a-z]+", "", project_key)
    legacy = (
        Path(project_root)
        / "evaluation"
        / "screening"
        / disease_key
        / parameter_key
        / project_key
        / f"project_{project_number}_screened.csv"
    )
    return legacy if legacy.exists() and not canonical.exists() else canonical


def _column_map(fieldnames: list[str] | None) -> dict[str, str]:
    return {name.strip().casefold(): name for name in (fieldnames or []) if name}


def _normalize_tier(value: str | None) -> str:
    aliases = {
        "s": "S",
        "strong": "S",
        "strong_candidate": "S",
        "p": "P",
        "possible": "P",
        "possible_candidate": "P",
        "u": "U",
        "unlikely": "U",
        "unlikely_candidate": "U",
        "error": "ERROR",
    }
    text = str(value or "").strip().casefold()
    if not text:
        return ""
    return aliases.get(text, "OTHER")


def load_pdf_records(
    input_path: Path,
    *,
    tiers: tuple[str, ...] | None = None,
    pmid_column: str | None = None,
    tier_column: str | None = None,
) -> list[PdfFetchRecord]:
    """Load unique PMIDs from a screened/raw CSV or a text list."""
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    normalized_tiers = {tier.strip().upper() for tier in tiers or () if tier.strip()}
    if input_path.suffix.casefold() != ".csv":
        if normalized_tiers:
            raise ValueError("Tier filtering requires a CSV input")
        values = [
            line.strip().removeprefix("PMID_")
            for line in input_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        return [PdfFetchRecord(pmid=value) for value in dict.fromkeys(values)]

    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = _column_map(reader.fieldnames)
        pmid_key = columns.get((pmid_column or "PMID").casefold())
        if not pmid_key:
            raise ValueError(
                f"PMID column not found in {input_path}; available columns: "
                + ", ".join(reader.fieldnames or [])
            )

        candidates = (
            [tier_column]
            if tier_column
            else ["llm_suggest", "final_tier", "screening_tier", "llm_tier", "tier"]
        )
        selected_tier_keys = [
            columns[candidate.casefold()]
            for candidate in candidates
            if candidate and candidate.casefold() in columns
        ]
        if normalized_tiers and not selected_tier_keys:
            raise ValueError(
                "Tier filtering requested, but no tier column was found. "
                "Use --tiers all for an unfiltered CSV."
            )

        doi_key = columns.get("doi")
        pmcid_key = columns.get("pmcid")
        records: list[PdfFetchRecord] = []
        seen: set[str] = set()
        for row in reader:
            tier = next(
                (
                    normalized
                    for key in selected_tier_keys
                    if (normalized := _normalize_tier(row.get(key)))
                ),
                "",
            )
            if normalized_tiers and tier not in normalized_tiers:
                continue
            pmid = str(row.get(pmid_key, "") or "").strip().removeprefix("PMID_")
            if not pmid or pmid in seen:
                continue
            seen.add(pmid)
            records.append(
                PdfFetchRecord(
                    pmid=pmid,
                    doi=str(row.get(doi_key, "") or "").strip() if doi_key else "",
                    pmcid=str(row.get(pmcid_key, "") or "").strip() if pmcid_key else "",
                    tier=tier,
                )
            )
    return records


def save_fetch_plan(
    *,
    records: list[PdfFetchRecord],
    output_dir: Path,
    input_path: Path,
    source: str,
    tiers: tuple[str, ...] | None,
    strategy: str,
    pdf_cache_dir: Path,
) -> tuple[Path, Path]:
    """Save the PMID list and a reproducible JSON fetch plan."""
    output_dir.mkdir(parents=True, exist_ok=True)
    pmids_path = output_dir / "pmids.txt"
    plan_path = output_dir / "fetch_plan.json"
    pmids_path.write_text(
        "".join(f"{record.pmid}\n" for record in records),
        encoding="utf-8",
    )
    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "input": str(Path(input_path).resolve()),
        "source": source,
        "tiers": list(tiers or []),
        "strategy": strategy,
        "record_count": len(records),
        "pdf_cache_dir": str(Path(pdf_cache_dir).resolve()),
        "records": [asdict(record) for record in records],
    }
    plan_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return pmids_path, plan_path


def save_fetch_results(
    *,
    records: list[PdfFetchRecord],
    statuses: dict[str, dict[str, str]],
    output_dir: Path,
) -> Path:
    """Save one stable status row for every requested PMID."""
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "fetch_results.csv"
    with result_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["PMID", "DOI", "PMCID", "tier", "status", "pdf_path"],
        )
        writer.writeheader()
        for record in records:
            status = statuses.get(record.pmid, {})
            writer.writerow(
                {
                    "PMID": record.pmid,
                    "DOI": record.doi,
                    "PMCID": record.pmcid,
                    "tier": record.tier,
                    "status": status.get("status", "not_attempted"),
                    "pdf_path": status.get("pdf_path", ""),
                }
            )
    return result_path


__all__ = [
    "PdfFetchRecord",
    "default_fetch_input",
    "load_pdf_records",
    "project_fetch_dir",
    "save_fetch_plan",
    "save_fetch_results",
]
