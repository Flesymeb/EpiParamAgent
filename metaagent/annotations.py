"""Blinded human annotation, explicit adjudication and report-group dataset splits.

Reviewer identities and independence are self-attestations supplied by operators.
The tool records them; it cannot authenticate humans or manufacture review work.
"""
from __future__ import annotations

import hashlib
import json
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import click
from pydantic import BaseModel, ConfigDict, Field


class FieldAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["reported", "verified_not_reported", "not_applicable", "pending"]
    value: Any = None
    quote: str = ""
    review_note: str = ""
    source_ref: dict[str, str] = Field(default_factory=dict)


class AnnotationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: str = Field(min_length=1)
    record_id: str = Field(min_length=1)
    estimate_id: str = Field(min_length=1)
    report_version: str = "unknown"
    document_sha256: str | None = None
    fields: dict[str, FieldAnnotation]
    version_conflict: bool = False
    disposition: Literal["keep", "reject", "pending"] = "keep"
    decision_reason: str = ""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def read_objects(path: Path) -> list[dict]:
    if path.suffix.lower() == ".csv":
        import csv
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    else:
        text = path.read_text(encoding="utf-8-sig")
        value = [json.loads(line) for line in text.splitlines() if line.strip()] if path.suffix.lower() == ".jsonl" else json.loads(text)
        rows = value if isinstance(value, list) else value.get("records")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Input must contain record objects")
    return rows


def write_revision(root: Path, kind: str, payload: dict, rows: list[dict] | None = None) -> Path:
    """Publish one immutable, content-addressed revision; never overwrite history."""
    revision = digest(payload)
    target = root / "revisions" / revision
    if target.exists():
        existing = json.loads((target / "artifact.json").read_text())
        if existing != payload:
            raise ValueError("Existing revision content conflicts with its digest")
        manifest = json.loads((target / "manifest.json").read_text())
        for name, expected in manifest["files"].items():
            if hashlib.sha256((target / name).read_bytes()).hexdigest() != expected:
                raise ValueError("Existing immutable revision was modified: " + name)
        return target
    target.mkdir(parents=True, exist_ok=False)
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    (target / "artifact.json").write_text(text, encoding="utf-8")
    files = {"artifact.json": hashlib.sha256(text.encode()).hexdigest()}
    if rows is not None:
        text = "".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in rows)
        name = "reference_adjudication.jsonl" if kind == "adjudication" else "records.jsonl"
        (target / name).write_text(text, encoding="utf-8")
        files[name] = hashlib.sha256(text.encode()).hexdigest()
    manifest = {"schema_version": "1", "kind": kind, "revision": revision,
                "created_at": datetime.now(UTC).isoformat(), "files": files,
                "identity_verification": "operator_supplied_self_attestation"}
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def blinded_template(records: list[dict], fields: list[str], *, base_dir: Path | None = None) -> dict:
    """Whitelist bibliography and source identity; never copy any numeric answers."""
    if not fields or len(fields) != len(set(fields)) or any(not f.strip() for f in fields):
        raise ValueError("Declare unique nonempty annotation fields")
    output, seen = [], set()
    for row in records:
        identity = str(row.get("record_id") or row.get("execution_record_id") or ("pmid:" + str(row["pmid"]) if row.get("pmid") else ""))
        if not identity or identity in seen:
            raise ValueError("Bibliographic input needs unique report record_id values")
        seen.add(identity)
        metadata = {k: row[k] for k in ("title", "pmid", "doi", "pmcid", "study_family_id", "report_version", "source_url") if k in row}
        source = row.get("fulltext_path") or row.get("document_path")
        source_hash = row.get("document_sha256") or row.get("source_sha256")
        if source:
            path = Path(str(source)).expanduser()
            if not path.is_absolute() and base_dir:
                path = base_dir / path
            if not path.is_file():
                raise FileNotFoundError(f"Missing primary document for {identity}: {path}")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if source_hash and source_hash != actual:
                raise ValueError("Declared primary document hash mismatch")
            source_hash = actual
            metadata["document_path"] = str(path.resolve())
        if source_hash and (len(str(source_hash)) != 64 or any(c not in "0123456789abcdef" for c in str(source_hash))):
            raise ValueError("Document hash must be lowercase SHA256")
        output.append({"item_id": identity, "record_id": identity,
                       "document_sha256": source_hash, "report_version": row.get("report_version", "unknown"),
                       "bibliography": metadata,
                       "fields": {name: {"status": "pending", "value": None, "quote": "", "review_note": "", "source_ref": {}} for name in fields}})
    return {"schema_version": "1", "kind": "blinded_template", "blinding": "bibliographic_and_document_identity_only",
            "fields": fields, "records": output,
            "instructions": "Each human independently adds estimate_id records and source-grounded field annotations. Do not consult model predictions or another reviewer submission."}


def _records_for_template(template: dict, rows: list[dict]) -> list[dict]:
    allowed = {row["item_id"]: row for row in template["records"]}
    normalized, identities = [], set()
    for raw in rows:
        row = AnnotationRecord.model_validate(raw).model_dump()
        if row["item_id"] not in allowed or row["record_id"] != allowed[row["item_id"]]["record_id"]:
            raise ValueError("Annotation record is outside template identities")
        key = (row["item_id"], row["estimate_id"])
        if key in identities:
            raise ValueError("Duplicate report/estimate annotation")
        identities.add(key)
        if set(row["fields"]) != set(template["fields"]):
            raise ValueError("Every annotation record must assess exactly the template fields")
        for field in row["fields"].values():
            if field["status"] == "reported" and field["value"] is None:
                raise ValueError("reported fields require a supplied value, including explicit zero")
            if field["status"] in {"verified_not_reported", "not_applicable"} and field["value"] is not None:
                raise ValueError("Absent/inapplicable fields must not contain values")
        normalized.append(row)
    return normalized


def human_submission(template: dict, payload: dict, reviewer: str) -> dict:
    """Accept only explicit independent-human attestation, without authenticating it."""
    if not reviewer.strip():
        raise ValueError("A real reviewer name must be supplied")
    if payload.get("reviewer_type") != "human" or payload.get("independent_primary_source_review") is not True:
        raise ValueError("Submission requires explicit human independent-primary-source attestation")
    if payload.get("reviewer") and payload["reviewer"].strip().casefold() != reviewer.strip().casefold():
        raise ValueError("Submission reviewer conflicts with supplied reviewer name")
    if payload.get("template_sha256") != digest(template):
        raise ValueError("Submission template revision does not match")
    rows = _records_for_template(template, payload.get("records", []))
    if not rows:
        raise ValueError("An empty submission cannot establish human review")
    return {"schema_version": "1", "kind": "human_submission", "template_sha256": digest(template),
            "reviewer": reviewer.strip(), "reviewer_type": "human",
            "independent_primary_source_review": True,
            "identity_verification": "operator_supplied_self_attestation", "records": rows,
            "raw_submission": payload}


def adjudicate(template: dict, submissions: list[dict], decisions: list[dict], adjudicator: str) -> dict:
    """Publish only actual supplied arbitration decisions; unresolved source versions stay pending."""
    if len(submissions) < 2:
        raise ValueError("At least two independent human submissions are required")
    names = [str(s.get("reviewer", "")).strip().casefold() for s in submissions]
    if not all(names) or len(set(names)) != len(names):
        raise ValueError("Reviewers must be distinct named humans")
    if not adjudicator.strip():
        raise ValueError("An explicit adjudicator name is required")
    for sub in submissions:
        if sub.get("kind") != "human_submission" or sub.get("reviewer_type") != "human" or sub.get("independent_primary_source_review") is not True or sub.get("template_sha256") != digest(template):
            raise ValueError("Invalid human submission or mismatched template")
        _records_for_template(template, sub["records"])
    rows = _records_for_template(template, decisions)
    supplied_items = {(row["item_id"], row["estimate_id"]) for sub in submissions for row in sub["records"]}
    if {(row["item_id"], row["estimate_id"]) for row in rows} != supplied_items:
        raise ValueError("Adjudication must explicitly account for every submitted report/estimate")
    sources = {row["item_id"]: row for row in template["records"]}
    final = []
    for row in rows:
        issues = []
        if row["disposition"] == "pending":
            issues.append("adjudicator_decision_pending")
        if row["disposition"] == "reject" and not row["decision_reason"].strip():
            issues.append("rejection_reason_missing")
        relevant = [[r for r in s["records"] if r["item_id"] == row["item_id"]] for s in submissions]
        if any(not records for records in relevant):
            issues.append("report_not_independently_reviewed_by_all_submitters")
        source = sources[row["item_id"]]
        expected_hash = source.get("document_sha256")
        if not expected_hash or row.get("document_sha256") != expected_hash:
            issues.append("primary_source_hash_unverified_or_mismatched")
        if row["report_version"] == "unknown" or row["report_version"] != source.get("report_version"):
            issues.append("report_version_unverified_or_mismatched")
        if row["version_conflict"] or any(r.get("version_conflict") or r.get("document_sha256") != expected_hash or r.get("report_version") != row["report_version"] for records in relevant for r in records):
            issues.append("independent_review_source_version_conflict")
        fields, states = {}, {}
        for name, annotation in row["fields"].items():
            field_issues = []
            if annotation["status"] != "pending":
                evidence = annotation["source_ref"]
                if evidence.get("document_sha256") != expected_hash or not evidence.get("location"):
                    field_issues.append("missing_primary_source_reference")
                if annotation["status"] == "reported" and not annotation["quote"].strip():
                    field_issues.append("missing_primary_source_quote")
                if annotation["status"] in {"verified_not_reported", "not_applicable"} and not annotation["review_note"].strip():
                    field_issues.append("missing_absence_or_applicability_review_note")
            for records in relevant:
                reviewed = [r["fields"][name] for r in records if r["estimate_id"] == row["estimate_id"]]
                def substantive(a):
                    ref = a["source_ref"]
                    return (a["status"] != "pending" and ref.get("document_sha256") == expected_hash
                            and bool(ref.get("location")) and bool(a["quote"].strip() if a["status"] == "reported" else a["review_note"].strip()))
                if not any(substantive(a) for a in reviewed):
                    field_issues.append("field_not_independently_reviewed_by_all_submitters")
                    break
            status = "pending" if issues or field_issues else annotation["status"]
            fields[name] = annotation["value"]
            states[name] = {**annotation, "status": status, "issues": field_issues}
        final.append({"record_id": row["record_id"], "estimate_id": row["estimate_id"],
                      "document_sha256": row.get("document_sha256"), "report_version": row["report_version"],
                      "fields": fields, "field_states": states, "disposition": row["disposition"],
                      "decision_reason": row["decision_reason"], "eligible_for_target": False if row["disposition"] == "reject" else None if row["disposition"] == "pending" else True,
                      "annotation_status": "adjudicated" if not issues and all(v["status"] != "pending" for v in states.values()) else "pending_review",
                      "validation_status": "adjudicated" if not issues and all(v["status"] != "pending" for v in states.values()) else "pending_review",
                      "reviewers": [s["reviewer"] for s in submissions], "adjudicator": adjudicator.strip(),
                      "adjudication_issues": issues, "identity_verification": "operator_supplied_self_attestation"})
    return {"schema_version": "1", "kind": "adjudication", "template_sha256": digest(template),
            "submission_sha256": [digest(s) for s in submissions], "adjudicator": adjudicator.strip(),
            "records": final, "raw_decisions": decisions}


def connected_split(records: list[dict], *, test_fraction: float, seed: int) -> dict:
    """Assign connected report/family groups together, preserving task instances."""
    if not 0 < test_fraction < 1:
        raise ValueError("test_fraction must lie strictly between zero and one")
    parent = list(range(len(records)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    seen = {}
    for i, row in enumerate(records):
        tokens = []
        for key in ("record_id", "report_id", "execution_record_id", "study_family_id"):
            if row.get(key):
                tokens.append(("family" if key == "study_family_id" else "report", str(row[key])))
        if not tokens:
            raise ValueError("Every split input needs an explicit report or family identity")
        for token in tokens:
            if token in seen:
                parent[find(i)] = find(seen[token])
            seen[token] = i
    groups = {}
    for i in range(len(records)):
        groups.setdefault(find(i), []).append(i)
    def identity_key(row):
        return tuple((key, str(row.get(key, ""))) for key in ("record_id", "report_id", "execution_record_id", "study_family_id", "profile"))
    components = sorted(groups.values(), key=lambda g: tuple(sorted(identity_key(records[i]) for i in g)))
    random.Random(seed).shuffle(components)
    target = round(len(records) * test_fraction)
    test, development = [], []
    for group in components:
        (test if len(test) < target else development).extend(group)
    return {"schema_version": "1", "kind": "connected_group_split", "seed": seed,
            "requested_test_fraction": test_fraction, "input_sha256": digest(records),
            "components": components, "development_indices": sorted(development), "test_indices": sorted(test),
            "actual_test_fraction": len(test) / len(records) if records else 0,
            "limitations": "Groups are indivisible; target fraction may be unattainable. Supplied report/family identities define connectivity; no numerical or title similarity is inferred."}


@click.group()
def annotations():
    """Blinded primary-source human labels and explicit adjudication revisions."""


def _emit(root, kind, payload, rows=None):
    target = write_revision(root, kind, payload, rows)
    click.echo(str(target))


@annotations.command("template")
@click.option("--input", "input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--field", "fields", multiple=True, required=True)
@click.option("--out", type=click.Path(file_okay=False, path_type=Path), required=True)
def template_command(input_path, fields, out):
    try:
        _emit(out, "blinded_template", blinded_template(read_objects(input_path), list(fields), base_dir=input_path.parent))
    except (ValueError, OSError, TypeError) as exc:
        raise click.ClickException(str(exc)) from exc


@annotations.command("submit")
@click.option("--template", "template_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--input", "input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--reviewer", required=True)
@click.option("--out", type=click.Path(file_okay=False, path_type=Path), required=True)
def submit_command(template_path, input_path, reviewer, out):
    try:
        template = json.loads(template_path.read_text())
        payload = human_submission(template, json.loads(input_path.read_text()), reviewer)
        _emit(out, "human_submission", payload)
    except (ValueError, OSError, TypeError) as exc:
        raise click.ClickException(str(exc)) from exc


@annotations.command("finalize")
@click.option("--template", "template_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--submission", "submission_paths", multiple=True, type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--decisions", "decisions_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--adjudicator", required=True)
@click.option("--out", type=click.Path(file_okay=False, path_type=Path), required=True)
def finalize_command(template_path, submission_paths, decisions_path, adjudicator, out):
    try:
        payload = adjudicate(json.loads(template_path.read_text()), [json.loads(p.read_text()) for p in submission_paths], read_objects(decisions_path), adjudicator)
        _emit(out, "adjudication", payload, payload["records"])
    except (ValueError, OSError, TypeError) as exc:
        raise click.ClickException(str(exc)) from exc


@annotations.command("split")
@click.option("--input", "input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--out", type=click.Path(file_okay=False, path_type=Path), required=True)
@click.option("--test-fraction", type=click.FloatRange(min=0, max=1, min_open=True, max_open=True), default=.2)
@click.option("--seed", type=int, default=42)
def split_command(input_path, out, test_fraction, seed):
    try:
        _emit(out, "connected_group_split", connected_split(read_objects(input_path), test_fraction=test_fraction, seed=seed))
    except (ValueError, OSError, TypeError) as exc:
        raise click.ClickException(str(exc)) from exc
