"""Stage-specific wire envelopes; scientific/candidate guards remain in stages."""

from __future__ import annotations
import copy
from pathlib import Path


def stage_b_response_format(*, evidence_only=False):
    identity = {"type": ["string", "null"]}
    if evidence_only:
        item = {
            "type": "object",
            "properties": {
                "record_index": {"type": "integer", "minimum": 0},
                "candidate_id": identity,
                "field": {"type": "string"},
                "quotes": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
            },
            "required": ["record_index", "candidate_id", "field", "quotes"],
            "additionalProperties": False,
        }
        properties = {"evidence_patches": {"type": "array", "items": item}}
        required = ["evidence_patches"]
        name = "coding_stage_b_evidence"
    else:
        record = {
            "type": "object",
            "properties": {"candidate_id": identity},
            "required": ["candidate_id"],
            "additionalProperties": True,
        }
        disposition = {
            "type": "object",
            "properties": {
                "candidate_id": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": ["keep", "correct", "reject", "pending"],
                },
                "reason": {"type": "string"},
            },
            "required": ["candidate_id", "action", "reason"],
            "additionalProperties": False,
        }
        properties = {
            "records": {"type": "array", "items": record},
            "dispositions": {"type": "array", "items": disposition},
            "request_block_ids": {
                "type": "array",
                "maxItems": 2,
                "items": {"type": "string"},
            },
        }
        required = ["records", "dispositions"]
        name = "coding_stage_b"
    # strict=False keeps provider compatibility with open scientific record
    # properties; JSON Schema still declares both mandatory envelope arrays.
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": False,
            "schema": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


def response_format_for_call(stage_name, messages):
    if stage_name != "stage_b":
        return None
    evidence_prompt = (
        Path(__file__).resolve().parents[1] / "prompts/coding/stage_b_evidence.md"
    ).read_text()
    evidence_only = bool(
        messages
        and messages[0].get("role") == "system"
        and messages[0].get("content") == evidence_prompt
    )
    return stage_b_response_format(evidence_only=evidence_only)


def stage_request_overrides(overrides, stage_name, messages):
    value = dict(overrides or {})
    contract = response_format_for_call(stage_name, messages)
    if contract:
        value["_coding_response_format"] = copy.deepcopy(contract)
    return value
