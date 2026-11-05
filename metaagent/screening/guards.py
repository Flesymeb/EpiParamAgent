"""Deterministic review diagnostics; missing keywords never prove ineligibility."""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from .context import bibliographic_context, metadata_text

VERSION = "screening-tools-v1"
_GUIDE = Path(__file__).with_name("guide.md")
_TERMS = {
    "R0": ([r"\bR[_ ]?0\b", r"basic reproduction (?:number|ratio)"], [r"\bR[_ ]?[te]\b", r"effective reproduction", r"growth rate"]),
    "CFR": ([r"case fatality", r"\bCFR\b", r"fatality (?:risk|rate|ratio)"], [r"death counts?", r"number of deaths", r"risk factors?", r"seroprevalence"]),
    "serial_interval": ([r"serial intervals?"], [r"incubation periods?", r"generation (?:time|interval)"]),
    "incubation_period": ([r"incubation periods?"], [r"serial intervals?", r"generation (?:time|interval)"]),
}
_ORIGINAL = re.compile(r"\b(?:we (?:enrolled|recruited|analysed|analyzed|followed|collected)|cohort|contact.tracing|surveillance data|participants|patients|transmission pairs)\b", re.I)
_NONPRIMARY = re.compile(r"\b(?:review|editorial|comment|news|letter)\b", re.I)


def guide_text():
    return _GUIDE.read_text(encoding="utf-8")


def guide_metadata():
    return {"version": VERSION, "sha256": hashlib.sha256(guide_text().encode()).hexdigest()}


def _identity(row, index):
    return str(row.get("record_id") or row.get("PMID") or row.get("pmid") or f"row:{index}")


def annotate_duplicate_candidates(rows, *, threshold=0.95, max_comparisons_per_bucket=10000):
    """Bound title comparisons by year/author buckets; retain every original row."""
    if not 0 < threshold <= 1 or max_comparisons_per_bucket < 1:
        raise ValueError("Invalid duplicate candidate limits")
    buckets = defaultdict(list)
    metadata = guide_metadata()
    comparisons = defaultdict(int)
    for index, row in enumerate(rows):
        row["screening_tools"] = metadata
        context = bibliographic_context(row)
        title = re.sub(r"[^\w]+", " ", context["title"].casefold()).strip()
        author = metadata_text(row.get("First Author") or row.get("first_author")) or context["authors"].split(";")[0].split(",")[0]
        author = re.sub(r"[^\w]+", "", author.casefold())
        year = context["year"]
        if len(title) < 15 or not author or not year:
            continue
        bucket = buckets[(year, author)]
        if comparisons[(year, author)] + len(bucket) > max_comparisons_per_bucket:
            row["duplicate_scan_incomplete"] = True
            continue
        identity = _identity(row, index)
        for previous, old_title, old_id in bucket:
            comparisons[(year, author)] += 1
            if min(len(title), len(old_title)) / max(len(title), len(old_title)) < threshold:
                continue
            score = SequenceMatcher(None, title, old_title, autojunk=False).ratio()
            if score >= threshold:
                row.setdefault("duplicate_candidates", []).append({"record_id": old_id, "similarity": round(score, 5), "basis": "title_year_first_author"})
                previous.setdefault("duplicate_candidates", []).append({"record_id": identity, "similarity": round(score, 5), "basis": "title_year_first_author"})
        bucket.append((row, title, identity))


def prepare_screening(rows, config, *, content_key, stage):
    """Bound context before model invocation; unprocessed text remains pending."""
    maximum = ((config or {}).get("tool_policy") or {}).get("max_source_chars", 120000)
    if type(maximum) is not int or maximum < 1000:
        raise ValueError("tool_policy.max_source_chars must be an integer >=1000")
    _target(config, bool((config or {}).get("review_protocol")))
    for row in rows:
        if row.get("fulltext_coverage", {}).get("origin") == "screening_budget_only_unknown_materials":
            row.pop("fulltext_coverage", None)
        for key in ("duplicate_candidates", "duplicate_scan_incomplete", "screening_budget", "screening_guard_route", "screening_review_flags", "publication_type_conflict", "screening_requires_review", "screening_processing_coverage"):
            row.pop(key, None)
    annotate_duplicate_candidates(rows)
    active = []
    for row in rows:
        source = metadata_text(row.get(content_key))
        size = len(source) + sum(len(str(b.get("text", ""))) for b in (row.get("source_blocks") or []) if isinstance(b, dict))
        if size > maximum:
            row.update(screening_budget={"status": "pending_source_budget", "source_chars": size, "max_source_chars": maximum, "processed_chars": 0},
                       screening_requires_review=True, screening_review_flags=["source_exceeds_context_budget"], llm_suggest="possible_candidate", llm_tier="P", fulltext_eligible=None,
                       screening_processing_coverage={"complete": False, "supplied_content": content_key, "reason": "pending_source_budget"},
                       overall_justification="Source exceeds declared context budget; no eligibility decision was made.")
            row.setdefault("fulltext_coverage", {"complete": False, "origin": "screening_budget_only_unknown_materials"})
            for key in ("protocol_decision", "criterion_assessments", "protocol_error"):
                row.pop(key, None)
        else:
            active.append(row)
    return active


def _target(config, protocol):
    explicit = (config or {}).get("estimand_guard") or {}
    if explicit.get("enabled") is False:
        return None
    target = explicit.get("target")
    if target:
        if target not in _TERMS:
            raise ValueError("estimand_guard.target must be R0, CFR, serial_interval or incubation_period")
        return target
    if protocol:
        return None
    focus = str((config or {}).get("parameter_focus") or "")
    matches = [name for name, (terms, _) in _TERMS.items() if any(re.search(term, focus, re.I) for term in terms)]
    if len(matches) == 1 and any(re.search(term, focus, re.I) for term in _TERMS[matches[0]][1]):
        return None
    return matches[0] if len(matches) == 1 else None


def apply_screening_guards(rows, config=None, *, protocol=False, content_key="Abstract", stage="title_abstract", preserve_model_tier=False):
    """Downgrade uncertain positives; preserve unrelated grounded exclusions."""
    target = _target(config, protocol)
    for row in rows:
        if row.get("llm_suggest") == "error" or row.get("screening_budget", {}).get("status") == "pending_source_budget":
            continue
        context = bibliographic_context(row)
        text = context["title"] + "\n" + metadata_text(row.get(content_key))
        flags = []
        if target:
            terms, confounders = _TERMS[target]
            hits = [m for term in terms for m in re.finditer(term, text, re.I)]
            confused = any(re.search(term, text, re.I) for term in confounders)
            negated = any(re.search(r"\b(?:not|no|without|did not)\b[^.!?;]{0,45}$", text[max(0, m.start()-60):m.start()], re.I) for m in hits)
            if confused and not hits or negated:
                flags.append("estimand_ambiguity:" + target)
        nonprimary = bool(_NONPRIMARY.search(context["pub_types"]))
        original = bool(_ORIGINAL.search(text))
        if nonprimary and not original:
            flags.append("publication_type_requires_source_review")
        elif nonprimary:
            row["publication_type_conflict"] = "original_data_cues_present"
        if not flags:
            continue
        row["screening_review_flags"] = sorted(set(row.get("screening_review_flags", []) + flags))
        before = row.get("llm_suggest")
        if preserve_model_tier and not protocol:
            if before == "strong_candidate":
                row["screening_requires_review"] = True
                row["fulltext_eligible"] = None
                row["screening_guard_route"] = {"before": before, "after": before,
                                               "review_required": True, "reasons": flags, "stage": stage}
            continue  # No numeric rescue, expanded pending scope or tag override.
        def score(name, default):
            try:
                value = row.get(name)
                return float(default if value in (None, "") else value)
            except (TypeError, ValueError):
                return default
        rescue = (not protocol and nonprimary and not original and before == "unlikely_candidate"
                  and all(score(k, 0) >= 2 for k in ("disease_score", "population_score", "location_score", "parameter_score"))
                  and score("evidence_score", 4) <= 1)
        primary_policy = (config or {}).get("publication_type_guard") or {}
        primary_criterion = any(re.search(r"\b(?:primary|original)\b.{0,35}\b(?:research|stud\w*|data)\b", str(c.get("description", "")), re.I)
                                for c in ((config or {}).get("review_protocol") or {}).get("criteria", []))
        route_flags = [f for f in flags if not (protocol and f == "publication_type_requires_source_review"
                       and not (primary_policy.get("enabled") is True or primary_criterion))]
        if route_flags and (before == "strong_candidate" or rescue):
            row["screening_requires_review"] = True
            row["fulltext_eligible"] = None
            row.update(screening_guard_route={"before": before, "after": "possible_candidate", "reasons": route_flags, "stage": stage}, llm_suggest="possible_candidate", llm_tier="P")
            if protocol and row.get("protocol_decision", {}).get("route") == "retain":
                row["protocol_decision"].update(unguarded_route="retain", route="review", guard_flags=route_flags)
    return rows


def audit_filter_impact(before, after, *, filter_name, warning_fraction=0.2):
    """Report an executed filter's identity-level effect without applying one."""
    if not 0 <= warning_fraction <= 1:
        raise ValueError("warning_fraction must be in [0,1]")
    retained = {_identity(row, i) for i, row in enumerate(after)}
    removed = [_identity(row, i) for i, row in enumerate(before) if _identity(row, i) not in retained]
    fraction = len(removed) / len(before) if before else 0.0
    return {"filter": filter_name, "before": len(before), "after": len(after), "removed": len(removed), "removed_record_ids": removed,
            "removed_fraction": fraction, "warning": "large_filter_impact" if fraction > warning_fraction else None,
            "identity_coverage": "explicit" if all(r.get("record_id") or r.get("PMID") or r.get("pmid") for r in before) else "row_fallback_not_stable_across_reordering"}


def screening_audit(rows):
    return {"schema_version": 1, "tools": guide_metadata(), "records": len(rows),
            "routes": {name: sum(r.get("llm_suggest") == name for r in rows) for name in ("strong_candidate", "possible_candidate", "unlikely_candidate", "error")},
            "guarded": sum(bool(r.get("screening_guard_route")) for r in rows),
            "pending_source_budget": sum(r.get("screening_budget", {}).get("status") == "pending_source_budget" for r in rows),
            "duplicate_candidate_records": sum(bool(r.get("duplicate_candidates")) for r in rows), "duplicate_records_deleted": 0}
