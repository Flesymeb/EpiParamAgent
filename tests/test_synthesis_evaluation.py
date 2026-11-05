"""Synthesis module/e2e evidence reporting without model calls or fabricated scores."""
import hashlib
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from metaagent.evaluation.benchmark import (
    BenchmarkOptions, evaluate_synthesis_artifact, plan_benchmark, run_benchmark,
)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def protocol():
    return {"analysis_id": "a", "parameter_type": "serial_interval", "estimate_measure": "mean",
            "unit": "days", "method": "fixed", "uncertainty_rules": {"allowed_types": ["SE"]},
            "independence": {"unit": "cohort_id"}}


def records():
    return [{"record_id": "report1", "estimate_id": "e1", "cohort_id": "c1", "parameter_type": "serial_interval",
             "estimate_measure": "mean", "point_estimate": 5, "unit": "days", "se": 1, "uncertainty_type": "SE"}]


def bind_synthetic_policy(release, task):
    """Bind a software-only policy; it never certifies a human-verified oracle."""
    policy = {
        "release_id": "synthetic-software-test-not-real-gold",
        "profiles": {"T1": {
            "source_review_pmid": "synthetic-review-no-real-pmid",
            "task_sha256": hashlib.sha256((task / "task.json").read_bytes()).hexdigest(),
            "synthesis": {"main_candidate": True, "status": "test_only_pending_reference", "reason": "Software fixture only"},
            "coding": {"main_candidate": True, "status": "test_only_pending_reference", "reason": "Software fixture only"},
        }},
    }
    write(release / "scoring_policy.json", policy)
    digest = hashlib.sha256((release / "scoring_policy.json").read_bytes()).hexdigest()
    write(release / "manifest.json", {"version": "synthetic-test", "release_id": policy["release_id"],
        "default_scoring_scope": "main", "scoring_policy_sha256": digest})
    diagnostic = release / "diagnostic"
    write(diagnostic / "manifest.json", {"release_id": policy["release_id"],
        "view_kind": "historical_diagnostic_unscored", "release_root": "..",
        "default_scoring_scope": "diagnostic", "scoring_policy_sha256": digest})
    (diagnostic / "profiles.csv").write_text("profile,path,disease,topic\nT1,../profiles/T1,test,serial_interval\n")


def dataset(tmp_path, *, make_input=True):
    release = tmp_path / "data"
    task = release / "profiles" / "T1"
    task.mkdir(parents=True)
    (release / "profiles.csv").write_text("profile,path,disease,topic\nT1,profiles/T1,test,serial_interval\n")
    write(task / "task.json", {"profile": "T1", "source_review_pmid": "synthetic-review-no-real-pmid",
                              "analysis_protocol": protocol()})
    if make_input:
        (task / "synthesis_input.jsonl").write_text(''.join(json.dumps(r) + '\n' for r in records()))
    bind_synthetic_policy(release, task)
    return release / "diagnostic", task


def synthetic_comparison_context():
    """Explicit comparator-unit permission, not a benchmark/release assertion."""
    return {"scope": "synthetic_unit_test", "comparison_allowed": True,
            "status": "test_only_comparator_branch_not_real_gold"}


def options(root, tmp_path, **kwargs):
    return BenchmarkOptions(dataset_root=root, output_dir=tmp_path / "out", run_id="run", modes=("synthesis",), **kwargs)


def test_module_runs_without_model_key_or_workflow(tmp_path, monkeypatch):
    root, _ = dataset(tmp_path)
    monkeypatch.delenv("WORKFLOW_LLM_API_KEY", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("Synthesis-only benchmark must not call workflow/model")

    result = run_benchmark(options(root, tmp_path), workflow_runner=forbidden, workflow_options_factory=forbidden)
    item = result["results"][0]
    assert item["execution_status"] == "completed"
    assert item["synthesis"]["counts"]["selected"] == 1
    assert item["synthesis"]["result"]["pooled_mean"] == 5
    assert item["synthesis"]["comparison_status"] == "diagnostic_unscored"
    assert "comparison" not in item["synthesis"]
    assert Path(item["artifacts"]["synthesis_result"]).is_file()


def test_module_missing_explicit_input_does_not_use_coding_gold(tmp_path):
    root, task = dataset(tmp_path, make_input=False)
    (task / "coding_reference.jsonl").write_text(json.dumps(records()[0]) + '\n')
    result = run_benchmark(options(root, tmp_path))
    assert result["status"] == "partial_or_failed"
    item = result["results"][0]
    assert item["execution_status"] == "excluded_by_scoring_policy"
    assert "structured_synthesis_input_missing" in item["scoring_policy"]["blocked_reasons"]
    assert "artifacts" not in item


def test_module_explicit_protocol_input_and_hash_freeze(tmp_path):
    root, _ = dataset(tmp_path, make_input=False)
    source = write(tmp_path / "structured.json", records())
    pp = write(tmp_path / "protocol.json", protocol())
    o = options(root, tmp_path, analysis_protocol=pp, synthesis_input=source)
    before = plan_benchmark(o)
    result = run_benchmark(o)
    assert result["results"][0]["execution_status"] == "completed"
    write(pp, dict(protocol(), method="random"))
    assert plan_benchmark(o)["fingerprint"] != before["fingerprint"]


def test_missing_protocol_visible_not_computable(tmp_path):
    root, task = dataset(tmp_path)
    write(task / "task.json", {"profile": "T1", "source_review_pmid": "synthetic-review-no-real-pmid"})
    bind_synthetic_policy(root.parent, task)
    result = run_benchmark(options(root, tmp_path))
    item = result["results"][0]
    assert item["execution_status"] == "excluded_by_scoring_policy"
    assert "analysis_protocol_missing" in item["scoring_policy"]["blocked_reasons"]
    assert "artifacts" not in item


def artifact(tmp_path):
    from metaagent.synthesis import run_synthesis
    output = run_synthesis(records(), protocol())
    return write(tmp_path / "synthesis_result.json", output), output


def reference(output, **kwargs):
    """Synthetic comparator labels; not independent annotation of a real study."""
    value = {"annotation_status": "adjudicated", "reference_kind": "original_study_reproduction",
             "analysis_id": "a", "protocol_sha256": output["protocol_sha256"],
             "parameter_type": "serial_interval", "estimate_measure": "mean", "unit": "days", "method": "fixed",
             "point_estimate": 4.5, "absolute_tolerance": 0.1,
             "source_url": "https://example.org/paper", "source_location": "Table 1"}
    value.update(kwargs)
    return value


def test_verified_matching_reference_only_and_no_invented_ci(tmp_path):
    path, output = artifact(tmp_path)
    ref = write(tmp_path / "synthesis_reference.json", reference(output))
    score = evaluate_synthesis_artifact(path, ref, scoring_context=synthetic_comparison_context())
    assert score["comparison_status"] == "verified_reference_comparison"
    assert score["comparison"]["point_absolute_error"] == .5
    assert score["comparison"]["point_within_declared_tolerance"] is False
    assert "interval_endpoint_absolute_errors" not in score["comparison"]


@pytest.mark.parametrize("change", [
    {"annotation_status": "source_transcribed"}, {"protocol_sha256": "other"},
    {"unit": "hours"}, {"analysis_id": "different"}, {"method": "random"},
    {"source_location": None}, {"reference_kind": None},
])
def test_incomparable_or_unverified_reference_not_scored(tmp_path, change):
    path, output = artifact(tmp_path)
    ref = write(tmp_path / "ref.json", reference(output, **change))
    score = evaluate_synthesis_artifact(path, ref, scoring_context=synthetic_comparison_context())
    assert score["comparison_status"] == "comparison_not_available"
    assert "comparison" not in score


def test_e2e_reports_synthesis_artifact_without_promoting_source_transcription(tmp_path, monkeypatch):
    root, task = dataset(tmp_path)
    path, output = artifact(tmp_path)
    write(task / "synthesis_reference.json", reference(output, annotation_status="source_transcribed"))
    monkeypatch.setenv("WORKFLOW_LLM_API_KEY", "synthetic-test-key")
    o = BenchmarkOptions(dataset_root=root, output_dir=tmp_path / "out", run_id="e2e", modes=("e2e",),
                         model="fake", api_base="https://example.org/v1")

    def fake_workflow(o):
        return {"status": "complete", "artifacts": {"synthesis_result": {"path": str(path)}}}

    result = run_benchmark(o, workflow_runner=fake_workflow, workflow_options_factory=lambda **kwargs: kwargs)
    item = result["results"][0]
    assert item["synthesis"]["execution_status"] == "single_estimate"
    assert item["synthesis"]["comparison_status"] == "diagnostic_unscored"
    assert str(path) in item["prediction_artifact_hashes"]


def test_cli_exposes_independent_synthesis_without_model_options(tmp_path):
    from metaagent.evaluation.cli import evaluation
    root, _ = dataset(tmp_path)
    result = CliRunner().invoke(evaluation, ["benchmark", "--dataset-root", str(root), "--mode", "synthesis", "--run-id", "cli", "--plan", "--json"])
    assert result.exit_code == 0, result.output
    assert '"synthesis"' in result.output


def test_missing_protocol_low_level_result_remains_protocol_pending():
    from metaagent.synthesis import run_synthesis
    result = run_synthesis(records(), None)
    assert result["status"] == "protocol_pending"
    assert result["result"] is None
    assert result["protocol_gaps"]


def test_missing_result_low_level_comparator_does_not_invent_output():
    result = evaluate_synthesis_artifact(None, scoring_context=synthetic_comparison_context())
    assert result["execution_status"] == "not_run"
    assert result["comparison_status"] == "comparison_not_available"
    assert result["result"] is None


@pytest.mark.parametrize("damage,expected", [
    ("missing_policy", "blocked_missing_release_policy"),
    ("policy_hash", "blocked_missing_release_policy"),
    ("task_identity", "blocked_profile_source_identity"),
])
def test_benchmark_release_policy_fail_closed_before_execution(tmp_path, damage, expected):
    root, task = dataset(tmp_path)
    release = root.parent
    if damage == "missing_policy":
        (release / "scoring_policy.json").unlink()
    elif damage == "policy_hash":
        value = json.loads((release / "scoring_policy.json").read_text())
        value["unexpected_change"] = True
        write(release / "scoring_policy.json", value)  # Manifest hash intentionally remains bound to original bytes.
    else:
        value = json.loads((task / "task.json").read_text())
        value["source_review_pmid"] = "different-synthetic-source"
        write(task / "task.json", value)  # Do not rebind the policy to the changed identity.
    result = run_benchmark(options(root, tmp_path))
    item = result["results"][0]
    assert item["execution_status"] == "excluded_by_scoring_policy"
    assert item["scoring_policy"]["status"] == expected
    assert not item["scoring_policy"]["execution_allowed"]
    assert not item["scoring_policy"]["comparison_allowed"]
    assert "artifacts" not in item


def test_main_release_hashes_never_promote_unverified_reference(tmp_path):
    from metaagent.benchmark.release import release_context, score_selection
    root, task = dataset(tmp_path)
    release = root.parent
    path, output = artifact(tmp_path)
    write(task / "reference_provenance.json", {"point": 4.5, "source_interval": {"kind": "not_reported", "level": None}})
    write(task / "synthesis_reference.json", reference(output, annotation_status="source_transcribed",
        source_review_pmid="synthetic-review-no-real-pmid", input_sha256=output["input_sha256"]))
    assert release_context(release)["valid"] is True
    # A syntactically valid release is still blocked before oracle evaluation
    # when it does not declare a target-analysis membership scope.
    scoped_out = score_selection(release, "T1", task_dir=task)
    assert scoped_out["status"] == "blocked_target_analysis_scope_mismatch"
    assert not scoped_out["execution_allowed"] and not scoped_out["comparison_allowed"]

    # Bind a software-only target scope, including the updated task/policy
    # hashes, so the next assertion reaches the independent-reference guard.
    # This does not adjudicate or promote the source_transcribed fixture.
    task_definition = json.loads((task / "task.json").read_text())
    task_definition["ground_truth_scope"] = "target_parameter_analysis_report_membership"
    write(task / "task.json", task_definition)
    bind_synthetic_policy(release, task)
    policy = json.loads((release / "scoring_policy.json").read_text())
    policy["profiles"]["T1"]["screening"] = {
        "reference_kind": "synthetic_target_analysis_membership_software_fixture"}
    write(release / "scoring_policy.json", policy)
    digest = hashlib.sha256((release / "scoring_policy.json").read_bytes()).hexdigest()
    for directory in (release, root):
        manifest = json.loads((directory / "manifest.json").read_text())
        manifest["scoring_policy_sha256"] = digest
        write(directory / "manifest.json", manifest)
    assert release_context(release)["valid"] is True
    decision = score_selection(release, "T1", task_dir=task)
    assert decision["status"] == "pending_analysis_artifacts"
    assert decision["blocked_reasons"] == ["independently_verified_synthesis_reference_missing"]
    assert not decision["execution_allowed"] and not decision["comparison_allowed"]
    score = evaluate_synthesis_artifact(path, task / "synthesis_reference.json")
    assert score["comparison_status"] == "excluded_by_scoring_policy"
    assert "comparison" not in score
    result = run_benchmark(options(release, tmp_path))
    assert result["results"][0]["execution_status"] == "excluded_by_scoring_policy"
