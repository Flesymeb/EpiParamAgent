"""Integration regression cases from independent review; no remote services."""
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from metaagent.review import apply_review, export_review
from metaagent.workflow_runner import WorkflowOptions, execute_stage, plan_workflow


def _review_setup(tmp_path, *, supplement=False):
    main = tmp_path / "main.md"
    main.write_text("Main study text.")
    row = {"record_id": "r1", "title": "Study", "fulltext_path": str(main), "record_status": "screened", "fulltext_coverage": {"complete": True, "truncated": False, "missing_materials": []}}
    if supplement:
        extra = tmp_path / "supplement.md"
        extra.write_text("The supplemental original result was reported.")
        row["supplements"] = [{"path": str(extra), "source_id": "S1"}]
    source = tmp_path / "predictions.jsonl"
    source.write_text(json.dumps(row) + "\n")
    manifest = {"artifacts": {"fulltext_predictions": str(source)}, "config": {"screening_config": {"review_protocol": {
        "version": "1", "criteria": [{"id": "result", "description": "Reports the required result"}], "logic": "result"}}}, "stage_results": {}}
    (tmp_path / "workflow_manifest.json").write_text(json.dumps(manifest))
    return row


@pytest.mark.parametrize("kind", ["supplement", "absence"])
def test_fulltext_review_uses_original_bundle_stage_and_coverage(tmp_path, kind):
    _review_setup(tmp_path, supplement=kind == "supplement")
    patch = export_review(tmp_path, "fulltext_predictions")
    assessment = {"criterion_id": "result", "status": "met" if kind == "supplement" else "not_met",
                  "evidence": "The supplemental original result was reported." if kind == "supplement" else "",
                  "reason": "Full source bundle inspected", "evidence_basis": "explicit" if kind == "supplement" else "absence"}
    patch.update(reviewer="human-test", reason="Independent test of available material", changes=[{"record_id": "r1", "fields": {"assessments": [assessment]}}])
    apply_review(tmp_path, patch)
    manifest = json.loads((tmp_path / "workflow_manifest.json").read_text())
    reviewed = json.loads(Path(manifest["artifacts"]["fulltext_predictions"]).read_text())
    assert reviewed["protocol_decision"]["route"] == ("retain" if kind == "supplement" else "exclude")


def test_pooling_legacy_sheet_uses_real_shared_reader(tmp_path):
    sheet = tmp_path / "estimates.xlsx"
    pd.DataFrame([{"estimate_id": "e1", "cohort_id": "c1", "record_id": "r1", "parameter_type": "SI", "estimate_measure": "mean", "point_estimate": 5, "unit": "days", "uncertainty_type": "SE", "uncertainty_high": 1}]).to_excel(sheet, index=False)
    opts = WorkflowOptions(profile="test", dataset_root=tmp_path, output_dir=tmp_path / "run")
    ctx = {"analysis_protocol": {"analysis_id": "mean", "parameter_type": "SI", "estimate_measure": "mean", "unit": "days", "method": "fixed", "uncertainty_rules": {"allowed_types": ["SE"]}, "independence": {"unit": "cohort_id"}}}
    result = execute_stage("pooling", opts, ctx, tmp_path / "stage", {"coding_predictions": str(sheet)})
    assert result["unresolved"] == 0
    assert json.loads(Path(result["artifacts"]["synthesis_result"]).read_text())["result"]["pooled_mean"] == 5


def test_document_module_plan_fingerprints_declared_primary_content(tmp_path):
    primary = tmp_path / "primary.md"
    primary.write_text("Original input")
    manifest = tmp_path / "documents.jsonl"
    manifest.write_text(json.dumps({"record_id": "r1", "path": str(primary)}) + "\n")
    codebook = tmp_path / "codebook.yaml"
    codebook.write_text("project: {name: Synthetic, effect_type: serial_interval}\nfields: []\n")
    task = tmp_path / "task.yaml"
    task.write_text(yaml.safe_dump({"task_id": "audit", "disease": "X", "topic": "SI", "research_question": "Intervals?", "codebook": str(codebook),
                                    "review_protocol": {"version": "1", "criteria": [{"id": "human", "description": "Human study"}], "logic": "human"}}))
    opts = WorkflowOptions(profile="audit", dataset_root=tmp_path, output_dir=tmp_path / "run", task_config=task,
                           document_manifest=manifest, start_at="coding", stop_after="coding")
    before = plan_workflow(opts)
    primary.write_text("Substantially changed input")
    after = plan_workflow(opts)
    assert before["config_sha256"] != after["config_sha256"]


def test_unbounded_incomplete_source_marks_stage_partial(tmp_path, monkeypatch):
    # Only the external HTTP transport is replaced. The real cursor adapter,
    # source merging and workflow stage status are exercised.
    monkeypatch.setattr('tools.literature.sources._get', lambda *args, **kwargs: {
        'hitCount': 2, 'nextCursorMark': '*',
        'resultList': {'result': [{'id': '1', 'pmid': '1', 'source': 'MED', 'title': 'One returned record'}]},
    })
    opts = WorkflowOptions(profile='audit', dataset_root=tmp_path, output_dir=tmp_path / 'run')
    directory = tmp_path / 'retrieval'
    result = execute_stage('retrieval', opts, {'source_queries': {'europepmc': 'disease X'}}, directory, {})
    stats = json.loads(Path(result['artifacts']['retrieval_stats']).read_text())
    assert stats['retrieval_complete'] is False
    assert result['unresolved'] > 0


def test_optional_report_missing_credential_does_not_discard_numeric_result(tmp_path, monkeypatch):
    monkeypatch.delenv('METAAGENT_AUDIT_MISSING_KEY', raising=False)
    task = tmp_path / 'task.yaml'
    task.write_text(yaml.safe_dump({'task_id': 'audit', 'disease': 'X', 'topic': 'SI', 'research_question': 'Intervals?', 'codebook': 'unused.yaml',
                                    'review_protocol': {'version': '1', 'criteria': [{'id': 'human', 'description': 'Human study'}], 'logic': 'human'},
                                    'llm': {'synthesis': {'api_key_env': 'METAAGENT_AUDIT_MISSING_KEY'}}}))
    estimates = tmp_path / 'estimates.jsonl'
    estimates.write_text(json.dumps({'estimate_id': 'e1', 'cohort_id': 'c1', 'record_id': 'r1', 'parameter_type': 'SI', 'estimate_measure': 'mean',
                                     'point_estimate': 5, 'unit': 'days', 'uncertainty_type': 'SE', 'uncertainty_high': 1}) + '\n')
    opts = WorkflowOptions(profile='audit', dataset_root=tmp_path, output_dir=tmp_path / 'run', task_config=task)
    ctx = {'analysis_protocol': {'analysis_id': 'mean', 'parameter_type': 'SI', 'estimate_measure': 'mean', 'unit': 'days', 'method': 'fixed',
                                'uncertainty_rules': {'allowed_types': ['SE']}, 'independence': {'unit': 'cohort_id'}, 'llm_report': True}}
    directory = tmp_path / 'stage'
    directory.mkdir()
    result = execute_stage('pooling', opts, ctx, directory, {'coding_estimates': str(estimates)})
    numeric = json.loads(Path(result['artifacts']['synthesis_result']).read_text())
    assert numeric['result']['pooled_mean'] == 5
    assert numeric['llm_report']['status'] == 'rejected_or_unavailable'
