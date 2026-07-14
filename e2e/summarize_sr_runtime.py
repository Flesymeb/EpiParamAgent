#!/usr/bin/env python3
"""Summarize per-source-review screening and coding runtime estimates."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCREENING_EXP = "model_5d_screening_multi_adaptive_highc_llmtier_20260507_boyue_qwen3-6-plus"
OUT_MD = ROOT / "tmp" / "e2e_sr_runtime_summary.md"
OUT_CSV = ROOT / "tmp" / "e2e_sr_runtime_summary.csv"
OUT_COMPACT_MD = ROOT / "tmp" / "e2e_sr_runtime_summary_compact.md"
OUT_DIAGNOSTICS_MD = ROOT / "tmp" / "e2e_sr_runtime_diagnostics.md"
TZ_LOCAL = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class Profile:
    disease: str
    topic: str
    project: str
    parameter: str
    source_review: str


PROFILES = [
    Profile("covid19", "serial_interval", "p10", "Serial interval", "Madewell et al., 2023"),
    Profile("covid19", "serial_interval", "p11", "Serial interval", "Xu et al., 2023"),
    Profile("covid19", "serial_interval", "p12", "Serial interval", "Alene et al., 2021"),
    Profile("covid19", "serial_interval", "p13", "Serial interval", "Ali et al., 2022"),
    Profile("covid19", "serial_interval", "p14", "Serial interval", "Rai et al., 2021"),
    Profile("covid19", "reproduction_number", "p7", "Reproduction number", "Dhungel et al., 2022"),
    Profile("covid19", "reproduction_number", "p8", "Reproduction number", "Ahammed et al., 2021"),
    Profile("covid19", "reproduction_number", "p15", "Reproduction number", "Billah et al., 2020"),
    Profile("covid19", "reproduction_number", "p16", "Reproduction number", "Yu et al., 2021"),
    Profile("covid19", "reproduction_number", "p17", "Reproduction number", "Alimohamadi et al., 2020"),
    Profile("covid19", "fatality", "p4", "Fatality", "Lim et al., 2021"),
    Profile("covid19", "fatality", "p5", "Fatality", "Ioannidis et al., 2021"),
    Profile("covid19", "fatality", "p6", "Fatality", "Alimohamadi et al., 2021"),
    Profile("mpox", "serial_interval", "p5", "Serial interval / incubation period", "Wang et al., 2022"),
    Profile("mpox", "serial_interval", "p6", "Serial interval / incubation period", "Ponce et al., 2024"),
    Profile("mpox", "serial_interval", "p10", "Serial interval / incubation period", "Wu et al., 2025"),
    Profile("mpox", "serial_interval", "p11", "Serial interval / incubation period", "Diaz Brochero et al., 2025"),
    Profile("mpox", "reproduction_number", "p9", "Reproduction number", "Okoli et al., 2024"),
    Profile("mpox", "fatality", "p4", "Fatality", "Cadmus et al., 2024"),
    Profile("mpox", "fatality", "p7", "Fatality", "Vasudevan et al., 2025"),
    Profile("mpox", "fatality", "p8", "Fatality", "Sharif et al., 2023"),
    Profile("mpox", "fatality", "p12", "Fatality", "Sanchez Clemente et al., 2024"),
]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(newline="") as f:
        return max(sum(1 for _ in csv.reader(f)) - 1, 0)


def count_text_rows(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text().splitlines() if line.strip())


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def parse_run_start(run_name: str) -> datetime | None:
    match = re.search(r"(20\d{6}_\d{6})", run_name)
    if not match:
        return None
    # Run directory names are local wall-clock timestamps in Asia/Shanghai.
    local = datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")
    return local.replace(tzinfo=TZ_LOCAL).astimezone(timezone.utc)


def fmt_hours(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"


def fmt_total(screen_h: float | None, coding_h: float | None, status: str) -> str:
    if screen_h is None:
        return "-"
    if coding_h is None:
        return f"running >= {screen_h:.2f}" if status == "running" else "-"
    return f"{screen_h + coding_h:.2f}"


def parse_hours(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    return float(text) if re.fullmatch(r"\d+\.\d+", text) else None


def fmt_delta_hours(total: str, screen: str) -> str:
    total_h = parse_hours(total)
    screen_h = parse_hours(screen)
    if total_h is None or screen_h is None:
        return "running" if total == "running" else "-"
    return f"{max(total_h - screen_h, 0):.2f}"


def standalone_coding_estimate(coding_h: float | None, coded_input: int | None, selected_rows: int | None) -> float | None:
    if coding_h is None or not coded_input or not selected_rows:
        return None
    return coding_h * selected_rows / coded_input


def official_screening_manifests() -> dict[tuple[str, str, str], dict]:
    out: dict[tuple[str, str, str], dict] = {}
    for profile in PROFILES:
        base = (
            ROOT
            / "evaluation"
            / "screening"
            / profile.disease
            / profile.topic
            / profile.project
            / "experiments"
            / SCREENING_EXP
            / "screening_runs"
        )
        manifests = sorted(base.glob("*/run_manifest_screening_*.json"))
        if not manifests:
            continue
        manifest = read_json(manifests[-1])
        out[(profile.disease, profile.topic, profile.project)] = manifest
    return out


def e2e_dirs(profile: Profile) -> list[Path]:
    root = ROOT / "e2e" / "runs" / "screen_to_coding"
    if profile.disease == "covid19" and profile.topic == "fatality" and profile.project == "p6":
        dirs = [p for p in root.glob("covid19_fatality_p6*glm51*") if p.is_dir()]
        return sorted(
            [
                p
                for p in dirs
                if not any(token in p.name for token in ["dryrun", "debug", "ka0", "limit", "preflight", "reverse"])
            ]
        )
    prefix = f"{profile.disease}_{profile.topic}_{profile.project}_glm51"
    dirs = [p for p in root.glob(prefix + "*") if p.is_dir()]
    dirs = [
        p
        for p in dirs
        if not any(token in p.name for token in ["dryrun", "debug", "ka0", "limit", "preflight", "reverse"])
    ]
    preferred = [p for p in dirs if p.name.endswith("_dedup_noproxy") or p.name.endswith("_full_noproxy")]
    return sorted(preferred or dirs)


def e2e_summary(profile: Profile) -> dict:
    dirs = e2e_dirs(profile)
    summaries = []
    for d in dirs:
        sp = d / "screen_to_coding_summary.json"
        if sp.exists():
            try:
                summaries.append((d, read_json(sp)))
            except json.JSONDecodeError:
                pass
    if summaries:
        # Non-sharded completed profiles should have one canonical summary.
        d, js = sorted(
            summaries,
            key=lambda item: (
                bool(item[1].get("coding_ran")),
                item[1].get("coding_input_count") or 0,
                item[0].stat().st_mtime,
            ),
        )[-1]
        manifest_inputs = []
        for mp in d.glob("run_manifest_coding_sheet_extraction_*.json"):
            try:
                manifest_inputs.append(int(read_json(mp).get("extra", {}).get("input_count") or 0))
            except (json.JSONDecodeError, ValueError):
                pass
        coding_input = (
            js.get("coding_input_count")
            or js.get("requested_coding_input_count")
            or count_text_rows(d / "coding_input_pmids.txt")
            or (max(manifest_inputs) if manifest_inputs else None)
        )
        index_count = len(list((d / "index").glob("PMID_*.index.json"))) if (d / "index").exists() else None
        record_count = js.get("coding_record_count")
        return {
            "status": "done" if js.get("coding_ran") else "prepared",
            "coding_h": (js.get("coding_elapsed_s") or 0) / 3600 if js.get("coding_elapsed_s") else None,
            "coding_input": coding_input,
            "coding_records": record_count if record_count is not None else index_count,
            "indexed": index_count,
            "selected_rows": js.get("selected_rows"),
            "dir": d.name,
        }
    # Running or partially generated sharded profile.
    input_count = 0
    selected_rows = 0
    index_pmids: set[str] = set()
    error_pmids: set[str] = set()
    first_index_time: float | None = None
    for d in dirs:
        input_count = max(input_count, count_text_rows(d / "coding_input_pmids.txt"))
        if (d / "screened_sp_pmids.txt").exists():
            selected_rows = max(selected_rows, count_text_rows(d / "screened_sp_pmids.txt"))
        for idx in (d / "index").glob("PMID_*.index.json"):
            pmid = idx.name.removeprefix("PMID_").removesuffix(".index.json")
            index_pmids.add(pmid)
            first_index_time = idx.stat().st_mtime if first_index_time is None else min(first_index_time, idx.stat().st_mtime)
        for err in (d / "errors").glob("PMID_*.json"):
            pmid = err.name.removeprefix("PMID_").split(".")[0]
            error_pmids.add(pmid)
    coding_h = None
    if first_index_time is not None:
        coding_h = (datetime.now().timestamp() - first_index_time) / 3600
    return {
        "status": "running" if dirs else "missing",
        "coding_h": None,
        "coding_elapsed_so_far_h": coding_h,
        "coding_input": input_count or None,
        "coding_records": len(index_pmids),
        "indexed": len(index_pmids),
        "selected_rows": selected_rows or None,
        "errors": len(error_pmids),
        "dir": "+".join(d.name for d in dirs[:3]) + ("+..." if len(dirs) > 3 else ""),
    }


def modular_gt_coding(profile: Profile) -> dict:
    base = ROOT / "evaluation" / "coding" / profile.disease / profile.topic / profile.project / "coding_runs"
    manifests = sorted(base.glob("*/run_manifest_coding_sheet_extraction_*.json"))
    groups: dict[str, dict] = {}
    for manifest_path in manifests:
        js = read_json(manifest_path)
        start = parse_run_start(manifest_path.parent.name)
        if start is None:
            continue
        end = parse_utc(js.get("timestamp_utc", ""))
        key = re.search(r"(20\d{6}_\d{6})", manifest_path.parent.name).group(1)
        group = groups.setdefault(
            key,
            {"start": start, "end": end, "input": 0, "records": 0, "runs": 0, "names": []},
        )
        group["end"] = max(group["end"], end)
        extra = js.get("extra", {})
        group["input"] += int(extra.get("input_count") or 0)
        group["records"] += int(extra.get("record_count") or 0)
        group["runs"] += 1
        group["names"].append(manifest_path.parent.name)
    if not groups:
        return {"coding_h": None, "input": None, "records": None, "runs": 0, "note": "missing"}
    best = sorted(groups.values(), key=lambda g: (g["input"], g["records"], g["end"]))[-1]
    return {
        "coding_h": (best["end"] - best["start"]).total_seconds() / 3600,
        "input": best["input"],
        "records": best["records"],
        "runs": best["runs"],
        "note": "multi-run group" if best["runs"] > 1 else "single run",
    }


def main() -> None:
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    manifests = official_screening_manifests()
    ends = [parse_utc(m["timestamp_utc"]) for m in manifests.values()]
    total_raw = sum(
        count_csv_rows(ROOT / "dataset" / p.disease / "screening" / p.topic / p.project / "raw.csv")
        for p in PROFILES
    )
    screening_span_h = (max(ends) - min(ends)).total_seconds() / 3600 if len(ends) > 1 else None
    screening_throughput = total_raw / screening_span_h if screening_span_h else None

    rows = []
    for profile in PROFILES:
        raw_n = count_csv_rows(ROOT / "dataset" / profile.disease / "screening" / profile.topic / profile.project / "raw.csv")
        gt_n = count_csv_rows(
            ROOT / "dataset" / profile.disease / "screening" / profile.topic / profile.project / "ground_truth.csv"
        )
        screen_h = raw_n / screening_throughput if screening_throughput else None
        e2e = e2e_summary(profile)
        modular = modular_gt_coding(profile)
        coding_h = e2e.get("coding_h")
        status = e2e.get("status", "")
        record_count = e2e.get("coding_records")
        index_count = e2e.get("indexed")
        if record_count is None:
            record_display = "-"
        elif index_count is not None and index_count != record_count:
            record_display = f"{record_count}/{index_count}"
        else:
            record_display = str(record_count)
        if status == "running":
            coding_display = f"running >= {e2e.get('coding_elapsed_so_far_h', 0):.2f}"
            total_display = f"running >= {(screen_h or 0) + (e2e.get('coding_elapsed_so_far_h') or 0):.2f}"
            standalone_display = "running"
        else:
            coding_display = fmt_hours(coding_h)
            total_display = fmt_total(screen_h, coding_h, status)
            standalone_coding_h = standalone_coding_estimate(
                coding_h,
                e2e.get("coding_input") if isinstance(e2e.get("coding_input"), int) else None,
                e2e.get("selected_rows") if isinstance(e2e.get("selected_rows"), int) else None,
            )
            standalone_display = fmt_total(screen_h, standalone_coding_h, status)
        rows.append(
            {
                "Disease": "COVID-19" if profile.disease == "covid19" else "Mpox",
                "Parameter": profile.parameter,
                "Project": profile.project.upper(),
                "Source review": profile.source_review,
                "Raw N": raw_n,
                "GT N": gt_n,
                "S+P selected N": e2e.get("selected_rows") or "-",
                "New coded input N": e2e.get("coding_input") or "-",
                "Screening est. h": fmt_hours(screen_h),
                "Observed E2E coding h": coding_display,
                "Observed E2E total h": total_display,
                "Standalone E2E total est. h": standalone_display,
                "E2E records/indexed": record_display,
                "GT-only input N": modular.get("input") or "-",
                "GT-only coding h": fmt_hours(modular.get("coding_h")),
                "Status": status,
                "Notes": modular.get("note", ""),
            }
        )

    fieldnames = list(rows[0].keys())
    with OUT_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    compact_fields = [
        "Disease",
        "Parameter",
        "Source review",
        "Raw N",
        "GT N",
        "S/P N",
        "Screening runtime (h)",
        "S/P coding runtime (h)",
        "GT-only coding runtime (h)",
        "Automated E2E runtime (h)",
        "Human-confirmed runtime (h)",
        "Status",
    ]
    diagnostic_fields = [
        "Disease",
        "Parameter",
        "Project",
        "Source review",
        "S/P selected N",
        "New coded input N",
        "Observed E2E coding h",
        "Observed E2E total h",
        "Standalone E2E total est. h",
        "E2E records/indexed",
        "Status",
    ]
    compact_rows = []
    diagnostic_rows = []
    for row in rows:
        compact_rows.append(
            {
                "Disease": row["Disease"],
                "Parameter": row["Parameter"],
                "Source review": row["Source review"],
                "Raw N": row["Raw N"],
                "GT N": row["GT N"],
                "S/P N": row["S+P selected N"],
                "Screening runtime (h)": row["Screening est. h"],
                "S/P coding runtime (h)": fmt_delta_hours(
                    str(row["Standalone E2E total est. h"]), str(row["Screening est. h"])
                ),
                "Automated E2E runtime (h)": row["Standalone E2E total est. h"],
                "GT-only coding runtime (h)": row["GT-only coding h"],
                "Human-confirmed runtime (h)": (
                    fmt_total(parse_hours(row["Screening est. h"]), parse_hours(row["GT-only coding h"]), row["Status"])
                    if parse_hours(row["Screening est. h"]) is not None
                    and parse_hours(row["GT-only coding h"]) is not None
                    else "-"
                ),
                "Status": row["Status"],
            }
        )
        diagnostic_rows.append(
            {
                "Disease": row["Disease"],
                "Parameter": row["Parameter"],
                "Project": row["Project"],
                "Source review": row["Source review"],
                "S/P selected N": row["S+P selected N"],
                "New coded input N": row["New coded input N"],
                "Observed E2E coding h": row["Observed E2E coding h"],
                "Observed E2E total h": row["Observed E2E total h"],
                "Standalone E2E total est. h": row["Standalone E2E total est. h"],
                "E2E records/indexed": row["E2E records/indexed"],
                "Status": row["Status"],
            }
        )

    completed = [r for r in rows if r["Status"] == "done"]
    completed_totals = [
        float(r["Observed E2E total h"]) for r in completed if re.fullmatch(r"\d+\.\d+", r["Observed E2E total h"])
    ]
    completed_coding = [
        float(r["Observed E2E coding h"])
        for r in completed
        if re.fullmatch(r"\d+\.\d+", r["Observed E2E coding h"])
    ]

    def median(vals: list[float]) -> float | None:
        if not vals:
            return None
        vals = sorted(vals)
        mid = len(vals) // 2
        return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2

    md = []
    md.append("# Per-source-review runtime summary\n")
    md.append(
        "This table summarizes the estimated runtime for each source-review profile. "
        "Screening time is allocated from the official qwen3.6-plus screening batch throughput "
        f"({total_raw:,} raw records over {screening_span_h:.2f} h, approximately {screening_throughput:.0f} records/h). "
        "Observed E2E coding time is taken directly from `screen_to_coding_summary.json` when completed. "
        "`Standalone E2E total est. h` scales the observed coding time from newly coded records to all S+P selected records, "
        "because the queue reused already coded PMIDs across source reviews. "
        "GT-only modular coding time is reconstructed from historical coding run manifests and should be treated as an approximate wall-clock estimate.\n"
    )
    md.append(
        f"Completed E2E profiles: {len(completed)}/{len(rows)}. "
        f"Median completed E2E coding time: {fmt_hours(median(completed_coding))} h. "
        f"Median completed screening+coding time: {fmt_hours(median(completed_totals))} h.\n"
    )
    md.append("| " + " | ".join(fieldnames) + " |")
    md.append("| " + " | ".join(["---"] * len(fieldnames)) + " |")
    for row in rows:
        md.append("| " + " | ".join(str(row[name]).replace("|", "/") for name in fieldnames) + " |")
    md.append("\n## Notes\n")
    md.append("- `Screening est. h` is an estimated per-profile allocation because the screening manifests store completion timestamps but not per-run elapsed seconds.")
    md.append("- `Observed E2E total h` is `Screening est. h + Observed E2E coding h`; screening itself was not rerun in the E2E coding jobs.")
    md.append("- `Standalone E2E total est. h` is the better estimate for one source review run independently from raw screening to full-text coding.")
    md.append("- `GT-only coding h` uses the historical modular coding runs where the coding input was the source-review included/GT studies rather than screening-retained S+P records.")
    md.append("- Running rows are lower bounds based on files already generated in the active output directories.")
    OUT_MD.write_text("\n".join(md) + "\n")
    compact_md = []
    compact_md.append("# Per-source-review workflow runtime estimates\n")
    compact_md.append(
        "All columns use a per-source-review standalone workflow interpretation. "
        "`Screening runtime (h)` is the shared title/abstract screening stage. "
        "`S/P coding runtime (h)` estimates full-text coding of all Strong/Possible records for that source review. "
        "`Automated E2E runtime (h)` is screening plus S/P coding. "
        "`GT-only coding runtime (h)` is the historical modular coding time using only source-review included studies as input. "
        "`Human-confirmed runtime (h)` is screening plus GT-only coding, representing a reviewer-confirmed inclusion workflow. "
        "Full-text coding time includes PDF retrieval, PMC download when available, MinerU parsing, and Stage A/B extraction.\n"
    )
    compact_md.append("| " + " | ".join(compact_fields) + " |")
    compact_md.append("| " + " | ".join(["---"] * len(compact_fields)) + " |")
    for row in compact_rows:
        compact_md.append("| " + " | ".join(str(row[name]).replace("|", "/") for name in compact_fields) + " |")
    OUT_COMPACT_MD.write_text("\n".join(compact_md) + "\n")
    diag_md = []
    diag_md.append("# E2E batch runtime diagnostics\n")
    diag_md.append(
        "These columns describe the actual queue execution. `New coded input N` can be smaller than `S/P selected N` because already coded PMIDs were reused across source reviews; therefore observed runtime should not be used as the standalone per-SR runtime without scaling.\n"
    )
    diag_md.append("| " + " | ".join(diagnostic_fields) + " |")
    diag_md.append("| " + " | ".join(["---"] * len(diagnostic_fields)) + " |")
    for row in diagnostic_rows:
        diag_md.append("| " + " | ".join(str(row[name]).replace("|", "/") for name in diagnostic_fields) + " |")
    OUT_DIAGNOSTICS_MD.write_text("\n".join(diag_md) + "\n")
    print(OUT_MD)
    print(OUT_COMPACT_MD)
    print(OUT_DIAGNOSTICS_MD)
    print(OUT_CSV)


if __name__ == "__main__":
    main()
