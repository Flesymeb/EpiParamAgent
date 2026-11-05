"""Strict entity/field scoring uses audited identity, not target numeric similarity."""
from metaagent.evaluation.benchmark_metrics import coding_metrics


def record(**kwargs):
    return dict(record_id="report", parameter_type="serial_interval", estimate_measure="mean",
                cohort_id="cohort", population="adults", point_estimate=5, unit="days", **kwargs)


def reference(**kwargs):
    value = record()
    value.update(validation_status="adjudicated", scored_fields=["parameter_type", "estimate_measure", "point_estimate", "unit"])
    value.update(kwargs)
    return value


def prediction(**kwargs):
    value = record()
    value.update(kwargs)
    return value


def test_multicohort_identity_not_numeric_nearness():
    refs = [reference(cohort_id="A", point_estimate=5), reference(cohort_id="B", point_estimate=9)]
    preds = [prediction(cohort_id="B", point_estimate=5), prediction(cohort_id="A", point_estimate=9)]
    metrics = coding_metrics(refs, preds)
    assert [c["prediction_index"] for c in metrics["comparisons"]] == [1, 0]
    assert metrics["strict_record_metrics"]["true_positive"] == 0
    assert metrics["strict_record_metrics"]["false_positive"] == 2
    assert metrics["strict_record_metrics"]["false_negative"] == 2
    assert metrics["strict_record_metrics"]["f1"] == 0


def test_multistatistic_identity_does_not_merge_mean_median():
    refs = [reference(point_estimate=5), reference(estimate_measure="median", point_estimate=4)]
    preds = [prediction(estimate_measure="median", point_estimate=4), prediction(point_estimate=5)]
    metrics = coding_metrics(refs, preds)
    assert metrics["strict_record_metrics"]["true_positive"] == 2
    assert metrics["strict_record_metrics"]["precision"] == 1
    assert metrics["strict_record_metrics"]["recall"] == 1


def test_extra_prediction_is_pending_without_exhaustive_annotations():
    refs = [reference()]
    preds = [prediction(), prediction(cohort_id="other")]
    metrics = coding_metrics(refs, preds)["strict_record_metrics"]
    assert metrics["true_positive"] == 1
    assert metrics["false_positive"] == 0
    assert metrics["pending_prediction_rows"] == 1
    assert metrics["precision"] is None and metrics["f1"] is None


def test_extra_prediction_fp_only_in_verified_exhaustive_parameter_scope():
    refs = [reference(exhaustive_annotation=True)]
    preds = [prediction(), prediction(cohort_id="other")]
    metrics = coding_metrics(refs, preds)["strict_record_metrics"]
    assert metrics["true_positive"] == 1
    assert metrics["false_positive"] == 1
    assert metrics["precision"] == .5
    assert metrics["f1"] == 2 / 3


def test_negative_report_scope_via_annotation_manifest():
    annotations = [{"record_id": "report", "parameter_type": "serial_interval", "validation_status": "verified", "exhaustive_annotation": True}]
    metrics = coding_metrics([], [prediction()], report_annotations=annotations)["strict_record_metrics"]
    assert metrics["false_positive"] == 1
    assert metrics["pending_prediction_rows"] == 0


def test_provisional_annotation_cannot_make_extra_prediction_fp():
    annotations = [{"record_id": "report", "parameter_type": "serial_interval", "validation_status": "source_transcribed", "exhaustive_annotation": True}]
    metrics = coding_metrics([], [prediction()], report_annotations=annotations)["strict_record_metrics"]
    assert metrics["false_positive"] == 0
    assert metrics["pending_prediction_rows"] == 1


def test_field_absence_hallucination_scored_without_fabricating_gold():
    refs = [reference(field_states={"uncertainty_low": "verified_not_reported", "uncertainty_high": "verified_not_reported"})]
    preds = [prediction(uncertainty_low=4, uncertainty_high=6)]
    metrics = coding_metrics(refs, preds)
    assert metrics["absence_metrics"]["unsupported_fills"] == 2
    assert metrics["strict_record_metrics"]["false_positive"] == 1
    assert metrics["strict_record_metrics"]["false_negative"] == 1


def test_pending_fields_do_not_become_absence_or_numeric_gold():
    refs = [reference(uncertainty_low=4, field_states={"uncertainty_low": "pending"})]
    metrics = coding_metrics(refs, [prediction(uncertainty_low=1)])
    assert "uncertainty_low" not in metrics["field_metrics"]
    assert metrics["strict_record_metrics"]["true_positive"] == 1
    assert metrics["absence_metrics"]["unsupported_fill_rate"] is None


def test_zero_deaths_count_only_is_scored():
    refs = [reference(parameter_type="CFR", estimate_measure="count_only", point_estimate=None,
                      deaths=0, denominator_count=40, denominator_type="confirmed_cases", record_kind="count_only",
                      scored_fields=["parameter_type", "deaths", "denominator_count", "denominator_type"])]
    preds = [prediction(parameter_type="CFR", estimate_measure="count_only", point_estimate=None,
                        deaths=0, denominator_count=40, denominator_type="confirmed_cases", record_kind="count_only")]
    metrics = coding_metrics(refs, preds)
    assert metrics["count_only_metrics"] == {"scored_rows": 1, "correct_rows": 1}
    assert metrics["strict_record_metrics"]["true_positive"] == 1


def test_ambiguous_identical_identity_does_not_align_using_values():
    refs = [reference(point_estimate=5), reference(point_estimate=9)]
    preds = [prediction(point_estimate=9), prediction(point_estimate=5)]
    metrics = coding_metrics(refs, preds)
    assert metrics["matched_reference_rows"] == 0
    assert metrics["strict_record_metrics"]["false_negative"] == 2
    assert metrics["strict_record_metrics"]["pending_prediction_rows"] == 2


def test_explicit_identity_scores_wrong_field_as_error():
    refs = [reference(extraction_id="estimate-one")]
    preds = [prediction(estimate_id="estimate-one", parameter_type="incubation_period")]
    metrics = coding_metrics(refs, preds)
    assert metrics["matched_reference_rows"] == 1
    assert metrics["strict_record_metrics"]["false_positive"] == 1


def test_semantic_accepted_values_are_explicit_not_fuzzy_guesses():
    refs = [reference(accepted_values={"population": ["adults", "adult population"]}, scored_fields=["parameter_type", "population", "point_estimate"])]
    preds = [prediction(population="adult population")]
    metrics = coding_metrics(refs, preds)
    assert metrics["strict_record_metrics"]["true_positive"] == 1
    assert "literal normalized agreement" in metrics["record_exact_metric_definition"]


def test_explicit_id_anchor_resolves_otherwise_ambiguous_residual():
    refs = [reference(extraction_id="known", point_estimate=5), reference(point_estimate=9)]
    preds = [prediction(estimate_id="known", point_estimate=5), prediction(point_estimate=9)]
    metrics = coding_metrics(refs, preds)
    assert metrics["strict_record_metrics"]["true_positive"] == 2
