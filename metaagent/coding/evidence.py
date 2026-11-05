"""Deterministic presentation metadata from already grounded field evidence."""
from __future__ import annotations


def evidence_locations(field_evidence: dict) -> list[str]:
    """Describe verified source spans; never accept model-authored location labels."""
    locations = set()
    for name, entries in field_evidence.items():
        if name == "evidence_locations":
            continue
        for entry in entries:
            if entry.get("exact_text_match") is False:
                continue
            start, end = entry.get("start"), entry.get("end")
            if isinstance(start, int) and isinstance(end, int) and 0 <= start < end:
                locations.add((entry.get("source_id", "main"), start, end))
    return [f"{source}:{start}-{end}" for source, start, end in sorted(locations)]
