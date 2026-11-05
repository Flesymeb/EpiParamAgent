"""Independent numeric oracles for registered synthesis methods and guards."""
import json
import math
from pathlib import Path

import pytest
from scipy.stats import beta, norm

from metaagent.synthesis import run_analyses, run_synthesis, write_synthesis_artifacts


def protocol(method="median", **overrides):
    value = dict(analysis_id="demo", parameter_type="SI", estimate_measure="median", unit="days", method=method,
                 independence={"unit": "cohort_id"})
    value.update(overrides)
    return value


def rows(values):
    return [dict(estimate_id=f"e{i}", record_id=f"r{i}", cohort_id=f"c{i}", parameter_type="SI", estimate_measure="median", unit="days", point_estimate=v) for i, v in enumerate(values)]


def count_protocol(method="binomial", **kw):
    value = protocol(method, parameter_type="CFR", estimate_measure="count_only", unit="proportion",
                     binomial_rules={"interval_method": "wilson", "zero_event_policy": "none"})
    value.update(kw)
    return value


def counts(events, ns):
    return [dict(estimate_id=f"e{i}", record_id=f"r{i}", cohort_id=f"c{i}", parameter_type="CFR", estimate_measure="count_only", unit="NR", point_estimate=None,
                 deaths=x, denominator_count=n) for i, (x, n) in enumerate(zip(events, ns))]


def test_descriptive_median_not_mean_and_no_invented_uncertainty():
    result = run_synthesis(rows([1, 2, 100]), protocol())
    assert result["status"] == "complete"
    assert result["result"]["pooled_mean"] == 2
    assert result["result"]["summary_statistic"] == "median"
    assert result["result"]["estimate_measure"] == "median"
    assert result["result"]["ci_lower"] is None
    assert result["result"]["interval_status"] == "not_requested"
    assert result["selected_estimates"][2]["source_raw"]["point_estimate"] == 100


def test_median_order_statistic_interval_exact_small_sample_boundary():
    result = run_synthesis(rows(list(range(1, 11))), protocol(median_interval_method="order_statistic"))
    assert result["result"]["pooled_mean"] == 5.5
    assert result["result"]["ci_lower"] == 2
    assert result["result"]["ci_upper"] == 9
    small = run_synthesis(rows([1, 2, 3]), protocol(median_interval_method="order_statistic"))
    assert small["result"]["ci_lower"] is None
    assert small["result"]["interval_status"] == "insufficient_sample_for_finite_order_interval"


def test_zero_event_binomial_wilson_known_limit():
    result = run_synthesis(counts([0], [40]), count_protocol())
    z2 = norm.ppf(.975) ** 2
    assert result["status"] == "single_estimate"
    assert result["result"]["pooled_mean"] == 0
    assert result["result"]["ci_lower"] == pytest.approx(0)
    assert result["result"]["ci_upper"] == pytest.approx(z2 / (40 + z2))
    assert result["selected_estimates"][0]["source_raw"]["point_estimate"] is None
    assert result["selection"][0]["transformations"][0]["events"] == 0


def test_aggregate_binomial_clopper_pearson_counts_oracle():
    p = count_protocol(binomial_rules={"interval_method": "clopper_pearson", "zero_event_policy": "none"}, unit="%")
    result = run_synthesis(counts([2, 3], [20, 30]), p)
    assert result["result"]["pooled_mean"] == 10
    assert result["result"]["total_events"] == 5
    assert result["result"]["ci_lower"] == pytest.approx(beta.ppf(.025, 5, 46) * 100)
    assert result["result"]["ci_upper"] == pytest.approx(beta.ppf(.975, 6, 45) * 100)
    assert sum(r["weight"] for r in result["forest_data"]) == pytest.approx(1)


def test_logit_fixed_known_equal_risk_and_explicit_zero_correction():
    p = count_protocol("logit_fixed")
    result = run_synthesis(counts([2, 3], [20, 30]), p)
    assert result["result"]["pooled_mean"] == pytest.approx(.1)
    assert result["result"]["pooled_logit"] == pytest.approx(math.log(.1 / .9))
    assert run_synthesis(counts([0], [20]), p)["status"] == "not_computable"
    p["binomial_rules"].update(zero_event_policy="continuity", continuity_correction=.5)
    corrected = run_synthesis(counts([0], [20]), p)
    assert corrected["result"]["pooled_mean"] == pytest.approx(.5 / 21)
    assert corrected["selected_estimates"][0]["source_raw"]["deaths"] == 0
    assert corrected["selection"][0]["transformations"][1]["added_to_each_cell"] == .5


def test_counts_invalid_or_unmatched_do_not_enter_any_method():
    for method in ("binomial", "logit_fixed"):
        assert run_synthesis(counts([21], [20]), count_protocol(method))["status"] == "not_computable"
        assert run_synthesis(counts([1.5], [20]), count_protocol(method))["status"] == "not_computable"
    assert run_synthesis(counts([0], [40]), count_protocol(binomial_rules=None))["status"] == "protocol_pending"


def test_stratum_and_explicit_time_filters_before_dependence_check():
    data = rows([2, 4, 6])
    data[0].update(stratum="adult", period="2020-01-01")
    data[1].update(stratum="adult", period="2021-06-01")
    data[2].update(stratum="child", period="2021-06-01")
    p = protocol(filters={"stratum": ["adult"], "period": {"gte": "2021-01-01", "lte": "2021-12-31"}})
    result = run_synthesis(data, p)
    assert result["status"] == "single_estimate"
    assert result["selected_estimates"][0]["estimate_id"] == "e1"
    assert result["counts"]["excluded"] == 2


def test_leave_one_out_and_prespecified_sensitivity_and_plot_artifacts(tmp_path):
    p = protocol(leave_one_out=True, sensitivity=[{"name": "exclude_large", "exclude_estimate_ids": ["e2"]}])
    result = run_synthesis(rows([1, 2, 100]), p)
    assert len(result["sensitivity_results"]) == 4
    assert result["sensitivity_results"][0]["result"]["pooled_mean"] == 1.5
    artifacts = write_synthesis_artifacts(result, tmp_path)
    assert Path(artifacts["forest_png"]).stat().st_size > 0
    assert Path(artifacts["forest_pdf"]).stat().st_size > 0
    assert Path(artifacts["study_weights"]).exists()
    assert Path(artifacts["sensitivity_results"]).exists()
    assert "interval" in (tmp_path / "report.md").read_text().lower()
    json.dumps(result, allow_nan=False)


def test_multiple_analyses_preserve_failure_and_safe_artifact_paths(tmp_path):
    p1 = protocol(analysis_id="../../not_a_path")
    p2 = protocol(analysis_id="missing", filters={"stratum": ["missing"]})
    summary, artifacts = run_analyses(rows([1, 2]), [p1, p2], tmp_path)
    assert summary["status"] == "partial"
    assert summary["n_computable"] == 1
    assert Path(artifacts["synthesis_result"]).parent == tmp_path
    assert (tmp_path / "analysis_001" / "synthesis_result.json").exists()
    with pytest.raises(ValueError):
        run_analyses(rows([1]), [p1, p1])


def test_optional_llm_report_numeric_references_are_resolved_not_trusted():
    p = protocol(llm_report=True)
    def invoke(_):
        return {"claims": [{"text_template": "The synthesis estimate is {{n0}}.", "numeric_refs": [{"name": "n0", "path": "/result/pooled_mean"}], "citation_ids": []}]}
    result = run_synthesis(rows([1, 2, 100]), p, llm_invoke=invoke)
    assert result["llm_report"]["status"] == "accepted"
    assert result["llm_report"]["claims"][0]["text"] == "The synthesis estimate is 2.0."
    def hallucinate(_):
        return {"claims": [{"text_template": "The treatment cures every patient.", "numeric_refs": [], "citation_ids": []}]}
    rejected = run_synthesis(rows([1, 2, 100]), p, llm_invoke=hallucinate)
    assert rejected["llm_report"]["status"] == "rejected_or_unavailable"
    assert rejected["result"] == result["result"]


def test_optional_llm_selection_cannot_override_deterministic_eligibility():
    p = protocol(llm_selection=True)
    data = rows([1, 2])
    data[1]["eligible_for_target"] = False
    def invoke(_):
        return {"decisions": [{"estimate_id": "e0", "decision": "select", "reason": "Matches scope", "rule_refs": ["filters"]},
                              {"estimate_id": "e1", "decision": "select", "reason": "Prefer larger sample", "rule_refs": ["filters"]}]}
    result = run_synthesis(data, p, llm_invoke=invoke)
    assert result["llm_selection"]["status"] == "rejected_or_unavailable"
    assert result["counts"]["selected"] == 1


def test_random_effects_tau_and_weights_against_two_study_oracle():
    data = rows([1, 3])
    for row in data:
        row.update(estimate_measure="mean", uncertainty_type="SE", uncertainty_high=1)
    for method in ("random", "reml"):
        p = protocol(method, estimate_measure="mean", uncertainty_rules={"allowed_types": ["SE"]})
        result = run_synthesis(data, p)
        assert result["status"] == "complete"
        assert result["result"]["pooled_mean"] == pytest.approx(2)
        assert result["result"]["tau2"] == pytest.approx(1, abs=1e-5)
        assert result["result"]["se_pooled"] == pytest.approx(1, abs=1e-5)
        assert [r["weight"] for r in result["forest_data"]] == pytest.approx([.5, .5])


def test_invalid_date_filter_is_review_and_invalid_operator_is_protocol_gap():
    data = rows([1])
    data[0]["date"] = "unknown-format"
    result = run_synthesis(data, protocol(filters={"date": {"gte": "2021-01-01"}}))
    assert result["counts"]["review"] == 1
    assert result["counts"]["excluded"] == 0
    assert run_synthesis(data, protocol(filters={"date": {"in": 1}}))["status"] == "protocol_pending"


def test_failed_rerun_removes_only_stale_derived_outputs(tmp_path):
    write_synthesis_artifacts(run_synthesis(rows([1, 2]), protocol()), tmp_path)
    assert (tmp_path / "forest.png").exists()
    (tmp_path / "user_note.txt").write_text("preserve")
    write_synthesis_artifacts(run_synthesis(rows([1]), {}), tmp_path)
    assert not (tmp_path / "forest.png").exists()
    assert not (tmp_path / "study_weights.jsonl").exists()
    assert (tmp_path / "user_note.txt").read_text() == "preserve"


@pytest.mark.parametrize("rule", [
    {"typo": "adult"}, {}, {"eq": {"nested": "adult"}}, {"in": "adult"},
    {"not_in": [None]}, {"gte": True}, {"gte": "not-a-date"},
    {"gte": 2, "lte": 1}, {"gte": 1, "lte": "2021-01-01"},
    {"lte": float("inf")}, ["adult", {"nested": "value"}],
])
def test_invalid_filter_contracts_are_protocol_pending_before_selection(rule):
    data = rows([1])
    data[0]["population"] = "adult"
    result = run_synthesis(data, protocol(filters={"population": rule}))
    assert result["status"] == "protocol_pending"
    assert result["selection"] == []
    assert result["result"] is None
    assert any("Invalid filter for population" in gap for gap in result["protocol_gaps"])


def test_direct_private_filter_guard_cannot_silently_accept_unknown_operator():
    from metaagent.synthesis.engine import _matches_filter
    with pytest.raises(ValueError, match="unsupported"):
        _matches_filter("adult", {"typo": "adult"})


def test_incompatible_sensitivity_method_cannot_use_absent_count_fields():
    result = run_synthesis(rows([1, 2]), protocol(sensitivity=[{"name": "invalid_family", "method": "logit_random"}]))
    item = result["sensitivity_results"][0]
    assert item["status"] == "not_computable"
    assert item["reason"] == "incompatible_sensitivity_method"
    assert item["result"] is None
