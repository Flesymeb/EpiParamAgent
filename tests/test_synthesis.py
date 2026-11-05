"""Boundary tests for protocol-driven synthesis; no model or service calls."""
import copy
import json
import math

import pytest
from click.testing import CliRunner

from metaagent.synthesis import run_synthesis, write_synthesis_artifacts
from metaagent.synthesis.cli import synthesis


def protocol(**overrides):
    value = dict(analysis_id="test", parameter_type="serial_interval", estimate_measure="mean", unit="days", method="fixed",
                 uncertainty_rules={"allowed_types": ["SE", "CI", "SD"]}, independence={"unit": "cohort_id"})
    value.update(overrides)
    return value


def record(**overrides):
    row = dict(estimate_id="a", record_id="report:a", cohort_id="cohort:a", parameter_type="serial_interval", estimate_measure="mean",
               point_estimate=5, unit="days", uncertainty_type="SE", uncertainty_high=1)
    row.update(overrides)
    return row


def test_valid_fixed_summary_is_finite_and_matches_independent_formula():
    rows = [record(), record(estimate_id="b", record_id="report:b", cohort_id="cohort:b", point_estimate=7)]
    result = run_synthesis(rows, protocol())
    assert result["status"] == "complete"
    assert result["result"]["pooled_mean"] == pytest.approx(6)
    assert result["result"]["se_pooled"] == pytest.approx(math.sqrt(.5))
    assert result["result"]["ci_lower"] == pytest.approx(6 - 1.959963984540054 * math.sqrt(.5))
    assert result["counts"]["independent_units"] == 2
    json.dumps(result, allow_nan=False)


def test_duplicate_family_and_ineligible_never_count_as_two_studies():
    rows = [record(eligible_for_target=False), record(estimate_id="b", eligible_for_target="false")]
    result = run_synthesis(rows, protocol())
    assert result["status"] == "not_computable"
    assert result["counts"] == dict(input=2, selected=0, excluded=2, review=0, independent_units=0)
    duplicated = run_synthesis([record(), record(estimate_id="b")], protocol())
    assert duplicated["status"] == "not_computable"
    assert duplicated["counts"]["review"] == 2


def test_overlap_requires_explicit_selection():
    rows = [record(stratum="overall"), record(estimate_id="b", stratum="icu", point_estimate=8)]
    p = protocol(independence={"unit": "cohort_id", "multiple_estimates": "select_ids", "selected_estimate_ids": ["a"]})
    result = run_synthesis(rows, p)
    assert result["status"] == "single_estimate"
    assert result["selected_estimates"][0]["estimate_id"] == "a"
    assert result["counts"]["excluded"] == 1


def test_mixed_units_require_explicit_conversion_and_preserve_input():
    rows = [record(), record(estimate_id="b", record_id="report:b", cohort_id="cohort:b", point_estimate=120, uncertainty_high=24, unit="hours")]
    original = copy.deepcopy(rows)
    without = run_synthesis(rows, protocol())
    assert without["status"] == "partial"
    assert without["counts"]["review"] == 1
    result = run_synthesis(rows, protocol(allow_unit_conversion=True))
    assert result["status"] == "complete"
    assert result["result"]["pooled_mean"] == pytest.approx(5)
    assert result["selected_estimates"][1]["se"] == pytest.approx(1)
    assert result["selection"][1]["transformations"][1]["factor"] == pytest.approx(1 / 24)
    assert rows == original


def test_missing_uncertainty_does_not_produce_success_or_invent_se():
    result = run_synthesis([record(uncertainty_type="NR", uncertainty_high=None, sample_size=100)], protocol())
    assert result["status"] == "not_computable"
    assert result["result"] is None
    json.dumps(result, allow_nan=False)


def test_missing_protocol_does_not_fall_back_to_mean_random():
    result = run_synthesis([record()], {})
    assert result["status"] == "protocol_pending"
    assert result["protocol_gaps"]
    assert result["result"] is None


def test_ci_requires_reported_level_and_cri_is_not_ci():
    assert run_synthesis([record(uncertainty_type="CI", uncertainty_low=4, uncertainty_high=6)], protocol())["status"] == "not_computable"
    assert run_synthesis([record(uncertainty_type="CrI", uncertainty_level="95%", uncertainty_low=4, uncertainty_high=6)], protocol())["status"] == "not_computable"
    valid = run_synthesis([record(uncertainty_type="CI", uncertainty_level="90%", uncertainty_low=4, uncertainty_high=6)], protocol())
    assert valid["status"] == "single_estimate"
    assert valid["selected_estimates"][0]["se"] == pytest.approx(1 / 1.6448536269514722)


def test_missing_cohort_is_not_assumed_independent():
    row = record(cohort_id=None)
    assert run_synthesis([row], protocol())["status"] == "not_computable"
    p = protocol(independence={"unit": "record_id"})
    assert run_synthesis([row], p)["status"] == "protocol_pending"
    p["independence"]["assert_independent_reports"] = True
    assert run_synthesis([row], p)["status"] == "single_estimate"


def test_without_b_producer_does_not_automatically_exclude():
    result = run_synthesis([record(producer="stage_a", semantic_review="not_run", needs_review=False)], protocol())
    assert result["status"] == "single_estimate"


def test_percentage_scope_and_unknown_units_are_explicit():
    row = record(parameter_type="CFR", estimate_measure="percentage", point_estimate=10, unit="%")
    assert run_synthesis([row], protocol())["status"] == "not_computable"
    p = protocol(parameter_type="CFR", estimate_measure="percentage", unit="%")
    assert run_synthesis([row], p)["status"] == "single_estimate"
    assert run_synthesis([record(unit="mystery")], protocol())["status"] == "not_computable"


def test_unknown_selection_ids_and_protocol_typos_are_not_ignored():
    p = protocol(independence={"unit": "cohort_id", "multiple_estimates": "select_ids", "selected_estimate_ids": ["absent"]})
    assert run_synthesis([record()], p)["status"] == "protocol_pending"
    assert run_synthesis([record()], protocol(impute_missing_se=True))["status"] == "protocol_pending"


def test_zero_deaths_kept_as_count_only_without_inventing_interval():
    row = record(estimate_measure="count_only", point_estimate=None, deaths=0, denominator_count=40)
    result = run_synthesis([row], protocol(estimate_measure="count_only"))
    assert result["status"] == "protocol_pending"
    assert result["result"] is None


def test_duplicate_estimate_ids_and_ambiguous_se_are_reviewed():
    result = run_synthesis([record(), record(cohort_id="another")], protocol())
    assert result["counts"]["review"] == 2
    result = run_synthesis([record(uncertainty_low=2, uncertainty_high=1)], protocol())
    assert result["status"] == "not_computable"


def test_log_transform_and_requested_output_confidence_level():
    result = run_synthesis([record()], protocol(log_transform=True, ci_level=.90))
    assert result["status"] == "single_estimate"
    assert result["result"]["pooled_mean"] == pytest.approx(5)
    assert result["result"]["ci_lower"] == pytest.approx(math.exp(math.log(5) - 1.6448536269514722 / 5))
    json.dumps(result, allow_nan=False)


def test_cli_writes_result_decisions_and_report_and_failure_status(tmp_path):
    inp = tmp_path / "records.json"
    pp = tmp_path / "protocol.json"
    inp.write_text(json.dumps([record()]))
    pp.write_text(json.dumps(protocol()))
    out = tmp_path / "run"
    result = CliRunner().invoke(synthesis, ["run", "--input", str(inp), "--protocol", str(pp), "--output", str(out)])
    assert result.exit_code == 0, result.output
    summary = json.loads((out / "synthesis_result.json").read_text())
    assert summary["status"] == "single_estimate"
    assert (out / "analysis_selection.jsonl").exists()
    assert "Numeric source:" in (out / "report.md").read_text()
    pp.write_text("{}")
    result = CliRunner().invoke(synthesis, ["run", "--input", str(inp), "--protocol", str(pp), "--output", str(out)])
    assert result.exit_code == 1
    assert json.loads((out / "synthesis_result.json").read_text())["status"] == "protocol_pending"


def test_unresolved_evidence_is_not_repaired_by_synthesis():
    for variant in ("stage_a", "stage_b"):
        result = run_synthesis([record(producer=variant, review_flags=["missing_evidence:point_estimate"])], protocol())
        assert result["status"] == "not_computable"
        assert result["counts"]["review"] == 1
    assert run_synthesis([record(needs_review=True)], protocol())["status"] == "not_computable"
    assert run_synthesis([record(review_notes="evidence_not_exact:unit")], protocol())["status"] == "not_computable"


def test_nonfinite_uncertainty_and_proportion_bounds_are_reviewed():
    assert run_synthesis([record(uncertainty_low=float("inf"))], protocol())["status"] == "not_computable"
    p = protocol(parameter_type="CFR", estimate_measure="percentage", unit="%")
    row = record(parameter_type="CFR", estimate_measure="percentage", unit="%", point_estimate=10,
                 uncertainty_type="CI", uncertainty_level=95, uncertainty_low=-1, uncertainty_high=20)
    assert run_synthesis([row], p)["status"] == "not_computable"
    row.update(uncertainty_type="SE", uncertainty_low=None, uncertainty_high=1, point_estimate=0)
    assert run_synthesis([row], p)["reason"] == "normal_interval_outside_proportion_bounds"
