"""Dynamic review criteria, grounded assessments and deterministic three-valued logic."""
from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ProtocolAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criterion_id: str
    status: Literal["met", "not_met", "unknown", "not_applicable"]
    evidence: str = Field(default="", description="A short exact contiguous quotation copied from this record source. Never copy a criterion description, task instruction, or reasoning into evidence. Empty if no supporting source quote exists.")
    evidence_basis: Literal["explicit", "absence", "insufficient"] = "explicit"
    reason: str = ""


class ProtocolDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_id: str
    assessments: list[ProtocolAssessment]
    proposed_route: Literal["retain", "exclude", "review"] = "review"
    missing_materials: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


def _references(expr: Any, known: set[str], depth: int = 0) -> set[str]:
    if depth > 30:
        raise ValueError("Protocol logic exceeds maximum depth")
    if isinstance(expr, str):
        if expr not in known:
            raise ValueError(f"Unknown criterion in protocol logic: {expr}")
        return {expr}
    if not isinstance(expr, dict):
        raise ValueError("Protocol logic must be a criterion ID or expression")
    keys = set(expr)
    if keys in ({"all"}, {"any"}):
        children = expr[next(iter(keys))]
        if not isinstance(children, list) or not children:
            raise ValueError("all/any requires a nonempty expression list")
    elif keys in ({"if", "then"}, {"if", "then", "else"}):
        children = list(expr.values())
    else:
        raise ValueError("Supported protocol logic operators are all, any and if/then/else")
    return set().union(*(_references(c, known, depth + 1) for c in children))


def validate_protocol(protocol: dict) -> dict:
    """Validate configuration before any model call, including applicability cycles."""
    if not isinstance(protocol, dict) or not str(protocol.get("version", "")).strip():
        raise ValueError("review_protocol requires an explicit version")
    criteria = protocol.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise ValueError("review_protocol requires nonempty criteria")
    for criterion in criteria:
        if not isinstance(criterion, dict) or not isinstance(criterion.get("id"), str) or not criterion["id"].strip() or not isinstance(criterion.get("description"), str) or not criterion["description"].strip():
            raise ValueError("Each criterion requires nonempty id and description")
        if set(criterion) - {"id", "description", "when"}:
            raise ValueError("Unknown criterion fields; use id, description and optional when")
    ids = [c["id"] for c in criteria]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate criterion IDs in review_protocol")
    known = set(ids)
    if "logic" not in protocol:
        raise ValueError("review_protocol requires explicit logic")
    used = _references(protocol["logic"], known)
    dependencies = {c["id"]: _references(c["when"], known) if "when" in c else set() for c in criteria}
    active: set[str] = set()
    done: set[str] = set()

    def visit(identity):
        if identity in active:
            raise ValueError("Cyclic criterion applicability")
        if identity in done:
            return
        active.add(identity)
        for dependency in dependencies[identity]:
            visit(dependency)
        active.remove(identity)
        done.add(identity)

    for identity in ids:
        visit(identity)
    # Criteria used only as applicability inputs are legitimate. Unused entries
    # otherwise risk silently omitting a required restriction.
    used |= set().union(*dependencies.values())
    if known - used:
        raise ValueError(f"Criteria unused by logic or applicability: {sorted(known - used)}")
    return protocol


def _evaluate(expr: Any, status) -> bool | None:
    if isinstance(expr, str):
        return status(expr)
    if "all" in expr:
        values = [_evaluate(c, status) for c in expr["all"]]
        return False if False in values else None if None in values else True
    if "any" in expr:
        values = [_evaluate(c, status) for c in expr["any"]]
        return True if True in values else None if None in values else False
    condition = _evaluate(expr["if"], status)
    yes = _evaluate(expr["then"], status)
    no = _evaluate(expr["else"], status) if "else" in expr else True
    return yes if condition is True else no if condition is False else yes if yes == no else None


def reduce_assessments(protocol: dict, decision: ProtocolDecision | dict, source: str, *, stage: str = "title_abstract", coverage: dict | None = None) -> dict:
    """Ground each judgment and reduce protocol logic; unknown never means negative."""
    validate_protocol(protocol)
    decision = decision if isinstance(decision, ProtocolDecision) else ProtocolDecision.model_validate(decision)
    expected = {c["id"] for c in protocol["criteria"]}
    supplied = [a.criterion_id for a in decision.assessments]
    if len(supplied) != len(set(supplied)) or set(supplied) != expected:
        raise ValueError("Model must assess each protocol criterion exactly once")
    criteria = {c["id"]: c for c in protocol["criteria"]}
    raw = {a.criterion_id: a.model_dump() for a in decision.assessments}
    resolved = {}
    coverage = coverage if isinstance(coverage, dict) else {}
    complete = (stage == "full_text" and coverage.get("complete") is True
                and coverage.get("truncated") is False and not coverage.get("missing_materials"))
    required = set(coverage.get("required_materials") or [])
    provided = set(coverage.get("provided_materials") or [])
    complete = complete and required <= provided

    def status(identity):
        if identity in resolved:
            return resolved[identity]["value"]
        item = dict(raw[identity])
        flags = []
        applicability = _evaluate(criteria[identity]["when"], status) if "when" in criteria[identity] else True
        quote = item["evidence"].strip()
        grounded = bool(quote and quote in source)
        absence_supported = item["evidence_basis"] == "absence" and complete and bool(item["reason"].strip())
        if applicability is False:
            effective, value = "not_applicable", True
        elif applicability is None:
            effective, value = "unknown", None
            flags.append("applicability_unknown")
        elif item["evidence_basis"] == "absence" and not absence_supported:
            effective, value = "unknown", None
            flags.append("absence_requires_complete_fulltext_bundle")
        elif item["evidence_basis"] == "insufficient":
            effective, value = "unknown", None
        elif item["status"] in {"met", "not_met"} and (grounded or (item["status"] == "not_met" and absence_supported)):
            effective, value = item["status"], item["status"] == "met"
        else:
            effective, value = "unknown", None
            if item["status"] == "not_applicable":
                flags.append("unsupported_not_applicable")
            elif item["status"] in {"met", "not_met"}:
                flags.append("missing_or_unmatched_evidence")
        item.update(effective_status=effective, evidence_verified=grounded,
                    applicability=applicability, validation_flags=flags)
        resolved[identity] = {"value": value, "assessment": item}
        return value

    value = _evaluate(protocol["logic"], status)
    for identity in expected:
        status(identity)
    route = "retain" if value is True else "exclude" if value is False else "review"
    return {
        "record_id": decision.record_id,
        "protocol_version": str(protocol["version"]),
        "source_coverage": coverage,
        "complete_fulltext_bundle": complete,
        "route": route,
        "proposed_route": decision.proposed_route,
        "proposal_agrees": route == decision.proposed_route,
        "assessments": [resolved[c["id"]]["assessment"] for c in protocol["criteria"]],
        "missing_materials": decision.missing_materials,
        "conflicts": decision.conflicts,
    }


def evidence_source_context(source: str, invalid_quote: str, *, radius: int = 240) -> dict | None:
    """Locate an unmodified source window by longest shared contiguous characters.

    This is a navigation hint, never evidence acceptance or text normalization.
    Offsets address the exact record.source string sent to the model, in Python
    Unicode code points. Quote length is bounded to keep invalid outputs cheap.
    """
    from difflib import SequenceMatcher
    if not source or not invalid_quote:
        return None
    match = SequenceMatcher(None, invalid_quote[:1000], source, autojunk=False).find_longest_match()
    if match.size < 8:
        return None
    start = max(0, match.b - radius)
    end = min(len(source), match.b + match.size + radius)
    return {"offset_reference": "record.source; Python Unicode code points",
            "match_start": match.b, "match_end": match.b + match.size,
            "matching_text": source[match.b:match.b + match.size],
            "context_start": start, "context_end": end, "source_context": source[start:end],
            "usage": "Navigation only; choose a short exact source quotation and rerun ordinary evidence validation. This window does not establish criterion eligibility."}


def protocol_system_prompt() -> str:
    """Load the versionable stage instruction independently of engine code."""
    from pathlib import Path
    from .guards import guide_text
    return (Path(__file__).resolve().parents[1] / "prompts" / "screening" / "protocol_system.md").read_text(encoding="utf-8") + "\n\n" + guide_text()


def render_protocol_messages(protocol: dict, records: list[dict], stage: str, *, multi: bool = False, research_question: str = "") -> list[dict]:
    """Render validated protocol plus source-only evidence and a unique schema."""
    validate_protocol(protocol)
    schema = ProtocolDecision.model_json_schema()
    if multi:
        definitions = schema.pop("$defs", {})
        schema = {"type": "object", "required": ["records"], "additionalProperties": False,
                  "$defs": definitions,
                  "properties": {"records": {"type": "array", "items": schema}}}
    content = {"research_question": research_question,
               "question_role": "Background for interpretation only. Apply the complete review_protocol eligibility logic; do not narrow it to a downstream pooled-analysis target.",
               "review_protocol": {key: protocol[key] for key in ("version", "criteria", "logic")}, "screening_stage": stage,
               "records": records, "output_schema": schema}
    return [{"role": "system", "content": protocol_system_prompt()},
            {"role": "user", "content": json.dumps(content, ensure_ascii=False)}]
