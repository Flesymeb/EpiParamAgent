"""Parameter guidance changes cannot alter the frozen task scopes or cutoffs."""
import hashlib
import json
from pathlib import Path

import pytest
import yaml

ROOT=Path(__file__).resolve().parents[1]
NON_NOTE_BINDINGS={
    "configs/covid19/screening_profiles/fatality.yaml":"23ea2d8d2c731eae6b15f4f623dead43cad03095814f506d735820a5ef5149b6",
    "configs/covid19/screening_profiles/serial_interval.yaml":"efda3037e4bdaa56830cd0b972596f300bd8fac168feee84376e8cadf43be762",
    "configs/covid19/screening_profiles/reproduction_number.yaml":"b2d5bab7189d5e0281eeab57dccfa78ae69acd2cd7e51e43ad5f03908bb075ee",
    "configs/mpox/screening_profiles/fatality.yaml":"56c06787008ae7b2cd0e72d77e5b3fd6bdd8a42c1db006fe0f9be3e6e128b698",
    "configs/mpox/screening_profiles/serial_interval.yaml":"826273148f3d87e28b80c8bb15c323302a4321e566148cc006452fb9c49fcc7d",
    "configs/mpox/screening_profiles/reproduction_number.yaml":"4fd459ca3bb7237d7fcdd7198c52982e19da4b47d42ae31fb6b1ce7ac33422d7",
}


def without_notes(value):
    if isinstance(value,dict):
        return {k:without_notes(v) for k,v in value.items() if k!="parameter_scoring_note"}
    if isinstance(value,list):return [without_notes(v) for v in value]
    return value


@pytest.mark.parametrize("relative,expected", NON_NOTE_BINDINGS.items())
def test_task_scope_dates_thresholds_and_ids_unchanged(relative,expected):
    value=yaml.safe_load((ROOT/relative).read_text())
    actual=hashlib.sha256(json.dumps(without_notes(value),sort_keys=True).encode()).hexdigest()
    assert actual==expected
    note=value["defaults"]["policies"]["parameter_scoring_note"]
    assert "task" in note and "title/abstract" in note and "full text" in note
    assert "source-review recall" not in note


def test_review_permission_remains_task_specific():
    cfg=yaml.safe_load((ROOT/"configs/covid19/screening_profiles/serial_interval.yaml").read_text())
    note=cfg["profiles"]["P13"]["policies"]["parameter_scoring_note"]
    assert "This task allows" in note
    assert "do not extend that permission" in note
    assert "full text" in note and "fixed inputs" in note


@pytest.mark.parametrize("name", ["fatality","reproduction_number","intervals"])
def test_guides_are_short_stage_aware_material_without_member_exceptions(name):
    text=(ROOT/"metaagent/prompts/screening/guides"/(name+".md")).read_text()
    assert len(text.split())<230
    assert "complete research question" in text
    assert "title/abstract" in text and "full text" in text
    assert "only when the task" in text or "requires the task" in text
    for forbidden in ("source-review recall","PMID","doi:","ground_truth","Score 3",'use "P"'):
        assert forbidden not in text


def test_actual_loader_does_not_load_unrelated_parameter_material():
    from metaagent.screening.prompt_loader import load_parameter_guides
    text=load_parameter_guides({"topic":"reproduction_number","parameter_focus":"R0"},"What is the basic reproduction number of COVID-19?")
    assert "# Reproduction numbers" in text
    assert "# Fatality and severity" not in text
    assert "# Transmission and disease intervals" not in text


def test_actual_loader_keeps_all_targets_in_a_multi_parameter_task():
    from metaagent.screening.prompt_loader import load_parameter_guides
    text=load_parameter_guides({"topic":"serial_interval","parameter_focus":"serial interval or reproduction number or R0"},"What are the serial intervals and R0/Rt of mpox?")
    assert "# Reproduction numbers" in text
    assert "# Transmission and disease intervals" in text
    assert "# Fatality and severity" not in text


def test_complete_research_question_can_be_broader_than_legacy_profile():
    from metaagent.screening.prompt_loader import load_parameter_guides
    text=load_parameter_guides({"topic":"serial_interval","parameter_focus":"serial interval"},"Which studies report serial interval, reproduction number, or case fatality for mpox?")
    assert "# Transmission and disease intervals" in text
    assert "# Reproduction numbers" in text
    assert "# Fatality and severity" in text
