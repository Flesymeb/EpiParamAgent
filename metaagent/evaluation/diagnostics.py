"""Observed workflow attrition without reference data or causal error claims."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def _identity(row):
    return str(row.get("record_id") or row.get("pmid") or row.get("PMID") or "")


def _tier(row):
    return row.get("llm_tier") or {"strong_candidate": "S", "possible_candidate": "P", "unlikely_candidate": "U"}.get(row.get("llm_suggest"))


def _reasons(row):
    decision = row.get("protocol_decision") or {}
    reasons = decision.get("reasons") or decision.get("failed_criteria") or row.get("exclusion_reasons") or row.get("reason") or row.get("failure_reason")
    if not reasons:
        assessments = decision.get("assessments") or row.get("criterion_assessments") or []
        if isinstance(assessments, list):
            reasons = [str(item.get("criterion_id")) + ":" + str(item.get("reason") or "not_met") for item in assessments if isinstance(item, dict) and item.get("effective_status", item.get("status")) == "not_met"]
    return reasons if isinstance(reasons, list) else [str(reasons)] if reasons else ["reason_not_recorded"]


def diagnose_workflow(manifest, *, run_root=None):
    """Summarize existing artifacts; unknown stages remain unknown, not zero."""
    if isinstance(manifest, (str, Path)):
        manifest_path = Path(manifest).resolve()
        run_root = manifest_path.parent
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Workflow manifest must contain an object")
    root = Path(run_root or manifest.get("output_dir") or ".").resolve()
    artifact_map = dict(manifest.get("artifacts", {}))
    for stage in manifest.get("diagnostic_artifacts", {}).values():
        for key, value in stage.items():
            artifact_map.setdefault(key, value)
    warnings = []
    def read(name, *, table=False):
        value = artifact_map.get(name)
        value = value.get("path") if isinstance(value, dict) else value
        if not value:
            return None
        path = Path(value)
        if not path.is_absolute():
            path = root / path
        if not path.resolve().is_relative_to(root):
            warnings.append("artifact_outside_run:" + name)
            return None
        try:
            if table:
                return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            warnings.append("artifact_unreadable:" + name)
            return None
    pool = read("records_source", table=True)
    screened = read("screening_predictions", table=True)
    fetched = read("fulltext_records", table=True)
    fulltext = read("fulltext_predictions", table=True)
    coding_status = read("coding_record_status", table=True)
    coded = read("coding_estimates", table=True)
    synthesis = read("synthesis_result") or {}
    completeness = read("coding_completeness")
    flow = {"identification_or_import_observed": len(pool) if pool is not None else None,
            "duplicates_removed": None, "deduplication_measurement": "not_inferred_from_similar_titles",
            "screened": len(screened) if screened is not None else None,
            "screening_excluded": sum(_tier(row) == "U" for row in screened) if screened is not None else None,
            "screening_pending_or_error": sum(row.get("record_status") in {"error", "awaiting_fulltext", "eligibility_pending"} or bool(row.get("screening_requires_review")) for row in screened) if screened is not None else None,
            "fulltext_requested": len(fetched) if fetched is not None else None,
            "fulltext_unavailable": sum(row.get("record_status") == "fulltext_unavailable" for row in fetched) if fetched is not None else None,
            "fulltext_eligibility_pending": sum(row.get("record_status") == "eligibility_pending" for row in fulltext) if fulltext is not None else None,
            "fulltext_excluded": sum(_tier(row) == "U" for row in fulltext) if fulltext is not None else None,
            "coded_estimates": len(coded) if coded is not None else None,
            "coded_reports": len({_identity(row) for row in coded if _identity(row)}) if coded is not None else None,
            "synthesis_selected_estimates": synthesis.get("counts", {}).get("selected"),
            "synthesis_independent_units": synthesis.get("counts", {}).get("independent_units", synthesis.get("counts", {}).get("independent_studies")),
            "synthesis_status": synthesis.get("status", "not_observed")}
    retrieval = read("retrieval_stats")
    if retrieval is not None:
        flow["duplicates_removed"] = retrieval.get("duplicates_removed", retrieval.get("dedup", {}).get("removed"))
    audit = read("screening_audit")
    if audit is not None and flow["duplicates_removed"] is None and audit.get("duplicate_records_deleted") == 0:
        flow["duplicates_removed"] = 0
        flow["deduplication_measurement"] = "screening_preserved_records; retrieval_dedup_unmeasured"
    impacts = []
    for stage, rows in (("screening", screened), ("fulltext_screening", fulltext)):
        if rows is None:
            continue
        excluded = [row for row in rows if _tier(row) == "U"]
        fraction = len(excluded) / len(rows) if rows else 0
        impacts.append({"stage": stage, "input_records": len(rows), "excluded": len(excluded),
                        "exclusion_fraction": fraction, "warning": "large_exclusion_fraction_review_protocol" if fraction > .2 else None,
                        "reasons": dict(Counter(str(reason) for row in excluded for reason in _reasons(row))),
                        "removed_record_ids": [_identity(row) for row in excluded],
                        "scope": "observed_decisions_not_new_date_or_subgroup_filters"})
    declared_selection = synthesis.get("selection")
    observed_selection = declared_selection if isinstance(declared_selection, list) else read("analysis_selection", table=True)
    selection = []
    for row in observed_selection or []:
        reasons = row.get("reasons")
        if reasons is None:
            reasons = [str(row["reason"])] if row.get("reason") else []
        selection.append({**row, "estimate_id": row.get("estimate_id") or row.get("input_id"),
            "decision": {"selected": "include", "excluded": "exclude"}.get(row.get("decision"), row.get("decision", "unknown")),
            "reasons": reasons})
    if flow["synthesis_selected_estimates"] is None and observed_selection is not None:
        flow["synthesis_selected_estimates"] = sum(row["decision"] == "include" for row in selection)
    filter_reasons = Counter(reason for row in selection if row.get("decision") == "exclude" for reason in row.get("reasons", []))
    if selection:
        impacts.append({"stage": "synthesis", "input_estimates": len(selection), "excluded": sum(row.get("decision") == "exclude" for row in selection), "reasons": dict(filter_reasons), "scope": "executed_analysis_selection"})
    traces = {}
    for stage, rows in (("input", pool), ("screening", screened), ("fulltext_fetch", fetched), ("fulltext_screening", fulltext), ("coding", coding_status)):
        for row in rows or []:
            identity = _identity(row)
            if identity:
                traces.setdefault(identity, {"record_id": identity, "observed_stages": {}})["observed_stages"][stage] = {
                    "status": row.get("record_status", row.get("status", "unknown")), "tier": _tier(row),
                    "review_flags": row.get("screening_review_flags", row.get("review_flags", [])), "reasons": _reasons(row)}
    for row in coded or []:
        identity = _identity(row)
        if identity:
            trace = traces.setdefault(identity, {"record_id": identity, "observed_stages": {}})
            trace.setdefault("coded_estimate_ids", []).append(row.get("estimate_id"))
            trace.setdefault("coding_review_flags", []).extend(row.get("review_flags", []))
    coded_by_estimate = {row.get("estimate_id"): row for row in coded or [] if row.get("estimate_id")}
    for decision in selection:
        source = coded_by_estimate.get(decision.get("estimate_id"), {})
        identity = _identity(decision) or _identity(source)
        if identity:
            trace = traces.setdefault(identity, {"record_id": identity, "observed_stages": {}})
            trace["observed_stages"].setdefault("synthesis", []).append({"estimate_id": decision.get("estimate_id"), "decision": decision.get("decision", "unknown"), "reasons": decision.get("reasons", [])})
    for contribution in synthesis.get("contributions", []):
        source = contribution.get("source_raw") or coded_by_estimate.get(contribution.get("input_id"), {})
        identity = _identity(source)
        if identity:
            trace = traces.setdefault(identity, {"record_id": identity, "observed_stages": {}})
            trace["observed_stages"].setdefault("synthesis", []).append({"estimate_id": contribution.get("input_id"), "decision": "contributed", "reasons": [], "scope": "contribution_not_proof_of_independent_cohort"})
    return {"schema_version": "1", "scope": "observed_operational_attrition_not_causal_error_attribution",
            "workflow_status": manifest.get("status", "unknown"), "flow_counts": flow, "filter_impacts": impacts,
            "pool_boundary": {"input_sha256": manifest.get("input_sha256"), "pool_kind": manifest.get("pool_kind"),
                "limited_subset": bool(manifest.get("config", {}).get("limit")), "query_in_evaluation": manifest.get("pool_kind") == "natural_search"},
            "stage_statuses": {name: stage.get("status", "unknown") for name, stage in manifest.get("stage_results", {}).items()},
            "operational_error": manifest.get("error"), "scientific_error_measured": False,
            "records": list(traces.values()), "coding_completeness": completeness,
            "resources": manifest.get("metrics"), "warnings": sorted(set(warnings))}
