"""Paired stage ablations with an immutable shared screening/fulltext prefix."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from metaagent.workflow_runner import WorkflowRunError, _jsonl, _load_jsonl, _retained, _write_json, file_hash, run_workflow


def run_variants(options, variants=("full", "without_a", "without_b")) -> dict:
    if not variants or len(set(variants)) != len(variants) or set(variants) - {"full", "without_a", "without_b"}:
        raise ValueError("Supply distinct supported stage variants")
    if options.start_at != "retrieval" or options.stop_after != "pooling":
        raise ValueError("Paired variants require the full workflow range; module runs use workflow run")
    root = Path(options.output_dir).resolve()
    try:
        prefix = run_workflow(replace(options, output_dir=root / "shared_prefix", stop_after="fulltext_screening"))
    except WorkflowRunError as exc:
        prefix = exc.manifest
    artifact = prefix.get("artifacts", {}).get("fulltext_predictions")
    result = {"status": "partial", "design": "shared frozen upstream, paired coding-stage ablations",
              "prefix_status": prefix["status"], "prefix_manifest": str(root / "shared_prefix/workflow_manifest.json"),
              "variants": [], "cost_policy": "Upstream executed once; full cold-run cost includes the shared prefix."}
    if not artifact:
        result["reason"] = "No fulltext-screening artifact available"
        _write_json(root / "variants.json", result)
        return result
    rows = _load_jsonl(artifact)
    docs = [{"record_id": r["record_id"], "pmid": r.get("pmid"), "title": r.get("title") or r.get("Title"),
             "path": r["fulltext_path"], "supplements": r.get("supplements", []), "fulltext_coverage": r.get("fulltext_coverage", {})}
            for r in rows if r.get("record_status") == "screened" and _retained(r)]
    manifest = root / "paired_documents.jsonl"
    _jsonl(manifest, docs)
    result.update(planned_upstream_records=len(rows), scheduled_coding_reports=len(docs),
                  document_manifest=str(manifest), document_manifest_sha256=file_hash(manifest))
    for variant in variants:
        try:
            run = run_workflow(replace(options, output_dir=root / variant, start_at="coding", raw_input=None,
                                       input_mode="search", document_manifest=manifest, ablation=variant))
        except WorkflowRunError as exc:
            run = exc.manifest
        result["variants"].append({"variant": variant, "status": run["status"], "artifacts": run.get("artifacts", {}),
                                   "manifest": str(root / variant / "workflow_manifest.json")})
        _write_json(root / "variants.json", result)
    result["status"] = "complete" if prefix["status"] == "complete" and all(r["status"] == "complete" for r in result["variants"]) else "partial"
    _write_json(root / "variants.json", result)
    return result
