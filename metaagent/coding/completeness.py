"""Source-bound completeness diagnostics, separate from extraction and eligibility.

A lexical signal is a review candidate, never proof of a missed eligible estimate.
No signal becomes an extracted record or supplies a missing numerical value.
"""
from __future__ import annotations

import hashlib
import math
import re

from metaagent.coding.prompt_context import parameter_key

AUDIT_VERSION = "coding_coverage_v1"
_TERMS = {
    "reproduction_number": ["R0", "R_0", "R₀", "Rt", "R_t", "Re", "R_e", "basic reproduction number", "effective reproduction number", "reproduction number"],
    "incubation_period": ["incubation period", "incubation time"],
    "serial_interval": ["serial interval", "generation interval", "generation time"],
    "fatality": ["CFR", "IFR", "HFR", "case fatality rate", "case fatality ratio", "case fatality proportion", "infection fatality rate", "infection fatality ratio"],
    "positivity": ["positivity rate", "positivity proportion", "test positivity", "seroprevalence"],
    "dispersion_k": ["dispersion parameter", "dispersion parameter k", "k"],
}
_NUMBER = r"[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?"
_REPORT = r"(?:(?:was|were|is|are|of|=|:|had\s+a|estimated(?:\s+at|\s+as|\s+to\s+be)?|mean|median|averaged|\|)\s*){1,4}"


def coverage_policy(config):
    """Return a validated literal-term policy; unknown books get no invented scope."""
    field_names = {field.name for field in config.fields}
    field = "point_estimate" if "point_estimate" in field_names else "k_value" if "k_value" in field_names else None
    key = "dispersion_k" if config.effect_type == "dispersion_k" else parameter_key(config)
    terms = config.parameters.get("coverage_terms", _TERMS.get(key, []))
    if not isinstance(terms, list) or len(terms) > 64 or any(
        not isinstance(term, str) or not term.strip() or len(term) > 256 for term in terms
    ):
        raise ValueError("coverage_terms must be a list of at most 64 nonempty literal terms")
    return field, list(dict.fromkeys(term.strip() for term in terms))


def _source_signals(source, field, terms):
    text = source["text"]
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    found = {}
    for term in terms:
        expression = re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)\s*(?:\([^\n)]{0,30}\)\s*)?" + _REPORT + r"(?P<token>" + _NUMBER + r")(?!\w|[.,]\d)", re.I)
        for match in expression.finditer(text):
            token_start, token_end = match.span("token")
            # One location can match both a long parameter name and its suffix.
            key = (token_start, token_end)
            left = max(text.rfind("\n", 0, match.start()) + 1, match.start() - 80)
            right = text.find("\n", match.end())
            right = min(len(text) if right < 0 else right, match.end() + 160)
            found[key] = {"source_id": source["source_id"], "source_sha256": digest,
                          "field": field, "matched_term": term, "literal_value": match.group("token"),
                          "signal_start": match.start(), "signal_end": match.end(),
                          "value_start": token_start, "value_end": token_end,
                          "source_start": left, "source_end": right,
                          "quote": text[left:right], "signal_kind": "explicit_numeric_parameter_phrase"}
    # Column headers identify where a numeric table cell belongs. The cell is a
    # source clue only; no cohort/statistic/eligible-record interpretation follows.
    lines = list(re.finditer(r"[^\n]+", text))
    for index, line in enumerate(lines[:-1]):
        if "|" not in line.group() or not re.match(r"\s*\|?\s*:?-{3,}", lines[index + 1].group()):
            continue
        def cells_of(value):
            cells = list(re.finditer(r"(?:^|(?<=\|))[^|]*", value))
            if value.startswith("|"):
                cells = cells[1:]
            if value.endswith("|"):
                cells = cells[:-1]
            return cells
        headers = cells_of(line.group())
        target_columns = [i for i, cell in enumerate(headers) if any(
            re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", cell.group(), re.I) for term in terms)]
        for row in lines[index + 2:]:
            if "|" not in row.group():
                break
            cells = cells_of(row.group())
            for column in target_columns:
                if column >= len(cells):
                    continue
                cell = cells[column]
                number = re.match(r"\s*(?P<token>" + _NUMBER + r")(?!\w|[.,]\d)", cell.group())
                if not number:
                    continue
                start = row.start() + cell.start() + number.start("token")
                end = row.start() + cell.start() + number.end("token")
                found[(start, end)] = {"source_id": source["source_id"], "source_sha256": digest,
                    "field": field, "matched_term": headers[column].group().strip(),
                    "literal_value": number.group("token"), "signal_start": start, "signal_end": end,
                    "value_start": start, "value_end": end, "source_start": row.start(), "source_end": row.end(),
                    "quote": row.group(), "signal_kind": "numeric_parameter_column",
                    "table_header": {"source_start": line.start(), "source_end": line.end(), "quote": line.group()}}
    return [found[key] for key in sorted(found)]


def _matches(signal, row):
    value = row.get(signal["field"])
    if isinstance(value, bool):
        return False
    try:
        equal = math.isclose(float(value), float(signal["literal_value"].replace(",", "")), rel_tol=1e-10, abs_tol=1e-12)
    except (TypeError, ValueError, OverflowError):
        return False
    return equal and any(entry.get("source_id", "main") == signal["source_id"]
                         and entry.get("source_start", entry.get("start", -1)) <= signal["value_start"]
                         and entry.get("source_end", entry.get("end", -1)) >= signal["value_end"]
                         for entry in row.get("field_evidence", {}).get(signal["field"], []))


def _external_report_cue(signal, sources):
    source = next(item["text"] for item in sources if item["source_id"] == signal["source_id"])
    prefix = source[max(0, signal["signal_start"] - 180):signal["signal_start"]]
    cue = re.search(r"\b(?:previous|prior|earlier|published|other)\s+(?:studies|reports|research|work)\b[^.!?\n]{0,120}$", prefix, re.I)
    return bool(cue and not re.search(r"\b(?:our|we)\b", cue.group(), re.I))


def audit_completeness(sources, records, candidates, dispositions, config, blocks, completed_blocks):
    """Audit every source against grounded outputs, without mutating any input."""
    field, terms = coverage_policy(config)
    signals = [signal for source in sources for signal in _source_signals(source, field, terms)] if field and terms else []
    rejected = {item["candidate_id"]: item for item in dispositions if item.get("action") == "reject"}
    for signal in signals:
        output = [row.get("estimate_id") for row in records if _matches(signal, row)]
        rejected_matches = [row["candidate_id"] for row in candidates if row.get("candidate_id") in rejected and _matches(signal, row)]
        context_cue = _external_report_cue(signal, sources)
        signal["status"] = "grounded_output" if output else "explicit_candidate_rejection" if rejected_matches else "external_report_navigation_cue" if context_cue else "unresolved_source_signal"
        signal["external_report_cue"] = context_cue
        signal["estimate_ids"] = output
        signal["rejected_candidate_ids"] = rejected_matches
        if rejected_matches:
            signal["rejection_reasons"] = [rejected[cid].get("reason", "") for cid in rejected_matches]
    pending = [signal for signal in signals if signal["status"] == "unresolved_source_signal"]
    complete = set(completed_blocks) == {block["block_id"] for block in blocks}
    fields = {item.name: {"grounded_records": sum(bool(row.get("field_evidence", {}).get(item.name)) for row in records),
                          "unresolved_records": sum(row.get("field_status", {}).get(item.name) == "unresolved" for row in records),
                          "not_found_in_supplied_material_records": sum(row.get("field_status", {}).get(item.name) == "not_found_in_supplied_material" for row in records)}
              for item in config.fields}
    return {"schema_version": "1", "audit_version": AUDIT_VERSION,
            "status": "incomplete_source_processing" if not complete else "needs_review" if pending else "processed_no_unresolved_detected_signals",
            "source_processing_complete": complete, "blocks_total": len(blocks), "blocks_completed": len(set(completed_blocks)),
            "numeric_target_field": field, "literal_terms": terms, "field_coverage": fields,
            "candidate_count": len(candidates), "record_count": len(records), "disposition_count": len(dispositions),
            "signal_count": len(signals), "unresolved_signal_count": len(pending), "signals": signals,
            "missing_estimate_proven": False, "no_signal_does_not_prove_absence": True,
            "scope": "literal_reported_parameter_clues_only_not_eligibility_or_semantic_completeness"}


def attributable_pending_signal(signal, row, config):
    """Conservatively bind an unresolved source clue to an existing output.

    Free-text extraction scope cannot be adjudicated by a lexical audit. An
    unrepresented subgroup similarly remains a document-level review candidate
    instead of declaring a retained overall record invalid.
    """
    if config.parameters.get("extraction_scope"):
        return False
    if signal.get("external_report_cue") or signal.get("status") == "external_report_navigation_cue":
        return False
    entries = row.get("field_evidence", {}).get(signal["field"], [])
    if not any(entry.get("source_id", "main") == signal["source_id"] for entry in entries):
        return False
    groups = re.findall(r"\b(?:children|pediatric|paediatric|adults|women|men|pregnant|subgroup|stratum)\b", signal["quote"], re.I)
    evidence = " ".join(entry.get("quote", "") for entry in entries)
    return not groups or all(re.search(r"\b" + re.escape(group) + r"\b", evidence, re.I) for group in groups)
