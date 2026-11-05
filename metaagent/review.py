"""Revision-bound prediction review; machine artifacts are immutable."""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

import click

REVIEWABLE = {"screening_predictions": "screening", "fulltext_predictions": "fulltext_screening", "coding_estimates": "coding"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temp.replace(path)


def export_review(run_dir: Path, artifact: str) -> dict:
    if artifact not in REVIEWABLE:
        raise ValueError("Only prediction JSONL artifacts can be reviewed")
    manifest = json.loads((run_dir / "workflow_manifest.json").read_text())
    path = Path(manifest["artifacts"][artifact])
    return {"artifact": artifact, "revision": digest(path), "records": [json.loads(line) for line in path.read_text().splitlines() if line.strip()],
            "reviewer": "", "reason": "", "changes": []}


def apply_review(run_dir: Path, patch: dict) -> dict:
    import fcntl
    with (run_dir / ".review.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            return _apply_review(run_dir, patch)
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _apply_review(run_dir: Path, patch: dict) -> dict:
    """Publish a new reviewed revision and an append-only audit receipt.

    Screening edits are criterion assessments, recomputed through the protocol
    reducer. Coding edits are explicit field updates; no model reviews are counted
    as gold adjudication. Applying the same revision twice is a conflict.
    """
    artifact = patch.get("artifact")
    if artifact not in REVIEWABLE:
        raise ValueError("Unsupported prediction artifact")
    if not patch.get("reviewer", "").strip() or not patch.get("reason", "").strip():
        raise ValueError("Reviewer and reason are required")
    manifest_path = run_dir / "workflow_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    current = Path(manifest["artifacts"][artifact])
    if digest(current) != patch.get("revision"):
        raise ValueError("Review revision conflict; export the current artifact again")
    changes = patch.get("changes")
    if not isinstance(changes, list) or not changes:
        raise ValueError("Nonempty changes list required")
    records = [json.loads(line) for line in current.read_text().splitlines() if line.strip()]
    id_key = "estimate_id" if artifact == "coding_estimates" else "record_id"
    identities = [str(r.get(id_key) or "") for r in records]
    if any(not i for i in identities) or len(set(identities)) != len(identities):
        raise ValueError(f"Artifact requires unique {id_key}")
    by_id = dict(zip(identities, records))
    audit = []
    for change in changes:
        identity = str(change.get(id_key) or "")
        if identity not in by_id or not isinstance(change.get("fields"), dict):
            raise ValueError("Unknown record identity or missing fields object")
        fields = change["fields"]
        if not fields or set(fields) & {"record_id", "estimate_id", "pmid", "doi", "producer", "ablation"}:
            raise ValueError("Identity and machine provenance cannot be edited")
        before = json.loads(json.dumps(by_id[identity]))
        row = by_id[identity]
        if artifact != "coding_estimates":
            if set(fields) != {"assessments"}:
                raise ValueError("Screening review edits require assessments, not an ungrounded route override")
            from metaagent.screening.protocol import reduce_assessments
            config = manifest["config"]["screening_config"]
            from metaagent.screening.engine import _protocol_source
            stage = "full_text" if artifact == "fulltext_predictions" else "title_abstract"
            evidence_row = dict(row)
            if artifact == "fulltext_predictions":
                from metaagent.documents import document_bundle
                evidence_row["fulltext"], evidence_row["fulltext_coverage"] = document_bundle(row)
            source = _protocol_source(evidence_row, "fulltext" if stage == "full_text" else "Abstract")
            decision = reduce_assessments(config["review_protocol"], {"record_id": identity, "assessments": fields["assessments"]}, source,
                                          stage=stage, coverage=evidence_row.get("fulltext_coverage"))
            route = decision["route"]
            row.update(protocol_decision=decision, criterion_assessments=decision["assessments"],
                       llm_tier={"retain": "S", "review": "P", "exclude": "U"}[route],
                       llm_suggest={"retain": "strong_candidate", "review": "possible_candidate", "exclude": "unlikely_candidate"}[route],
                       record_status="eligibility_pending" if route == "review" and artifact == "fulltext_predictions" else "screened")
        else:
            from metaagent.coding.schema.config_loader import load_config, create_model_from_config
            codebook = load_config(Path(manifest["config"]["codebook"]))
            allowed = {f.name for f in codebook.fields} | {"needs_review", "review_flags", "field_evidence", "field_status", "cohort_id", "stratum", "time_window", "method", "statistic", "analysis_role", "notes", "eligible_for_target"}
            if set(fields) - allowed:
                raise ValueError("Only canonical coding fields can be corrected; source snapshots/provenance are immutable")
            if any(isinstance(v, float) and not math.isfinite(v) for v in fields.values()):
                raise ValueError("Reviewed numeric fields must be finite")
            candidate = {**row, **fields}
            checked = create_model_from_config(codebook).model_validate({f.name: candidate.get(f.name) for f in codebook.fields}).model_dump()
            row.update(fields)
            row.update(checked)
        row["human_review"] = {"reviewer": patch["reviewer"], "reason": patch["reason"]}
        audit.append({id_key: identity, "before": before, "after": row.copy()})
    folder = run_dir / "reviews" / uuid.uuid4().hex
    folder.mkdir(parents=True)
    path = folder / (artifact + ".jsonl")
    path.write_text("".join(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n" for r in records))
    receipt = {"artifact": artifact, "base_revision": patch["revision"], "revision": digest(path),
               "reviewer": patch["reviewer"], "reason": patch["reason"], "at": datetime.now(timezone.utc).isoformat(), "changes": audit}
    _write(folder / "prediction_review.json", receipt)
    overrides = manifest.setdefault("artifact_overrides", {})
    prior = overrides.get(artifact)
    base = prior["machine_sha256"] if prior else patch["revision"]
    overrides[artifact] = {"path": str(path.resolve()), "sha256": digest(path), "machine_sha256": base,
                           "receipt": str((folder / "prediction_review.json").resolve())}
    manifest["artifacts"][artifact] = str(path.resolve())
    order = ["retrieval", "screening", "fulltext_fetch", "fulltext_screening", "coding", "pooling"]
    for stage in order[order.index(REVIEWABLE[artifact]) + 1:]:
        if stage in manifest.get("stage_results", {}):
            manifest["stage_results"][stage]["stale"] = True
    manifest["status"] = "reviewed_requires_resume"
    _write(manifest_path, manifest)
    return receipt


@click.group()
def review():
    """Export predictions and apply auditable, revision-bound human corrections."""


@review.command("export")
@click.option("--run-dir", type=click.Path(path_type=Path, exists=True), required=True)
@click.option("--artifact", type=click.Choice(list(REVIEWABLE)), required=True)
@click.option("--out", type=click.Path(path_type=Path), required=True)
def export_command(run_dir, artifact, out):
    try:
        _write(out, export_review(run_dir, artifact))
    except (ValueError, OSError, KeyError) as exc:
        raise click.ClickException(str(exc)) from exc


@review.command("apply")
@click.option("--run-dir", type=click.Path(path_type=Path, exists=True), required=True)
@click.option("--patch", type=click.Path(path_type=Path, exists=True), required=True)
def apply_command(run_dir, patch):
    try:
        receipt = apply_review(run_dir, json.loads(patch.read_text()))
    except (ValueError, OSError, KeyError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps({"revision": receipt["revision"], "status": "reviewed_requires_resume"}))
