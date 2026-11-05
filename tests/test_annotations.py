"""No human labels are manufactured by template creation or arbitration tooling."""
import copy
import hashlib
import json

import pytest
from click.testing import CliRunner

from metaagent.annotations import (
    adjudicate, annotations, blinded_template, connected_split, digest,
    human_submission, write_revision,
)


HASH = hashlib.sha256(b"primary report").hexdigest()


def template():
    return blinded_template([{"record_id": "pmid:1", "title": "Study", "report_version": "published-v1", "document_sha256": HASH,
                              "point_estimate": 12345, "validation_status": "source_transcribed"}], ["point_estimate", "uncertainty_low"])


def record(**changes):
    value = {"item_id": "pmid:1", "record_id": "pmid:1", "estimate_id": "e1", "report_version": "published-v1", "document_sha256": HASH,
             "fields": {"point_estimate": {"status": "reported", "value": 5, "quote": "Mean was 5 days", "source_ref": {"document_sha256": HASH, "location": "Table 1"}},
                        "uncertainty_low": {"status": "verified_not_reported", "value": None, "review_note": "Reviewed main text, tables and all supplied supplements", "source_ref": {"document_sha256": HASH, "location": "Entire report bundle"}}}}
    value.update(changes)
    return value


def submission(name, row=None):
    return human_submission(template(), {"reviewer_type": "human", "independent_primary_source_review": True,
                                         "template_sha256": digest(template()), "records": [row or record()]}, name)


def test_template_blinds_source_numbers_and_all_labels():
    value = template()
    text = json.dumps(value)
    assert "12345" not in text
    assert "source_transcribed" not in text
    assert value["records"][0]["fields"]["point_estimate"]["status"] == "pending"


def test_template_hashes_actual_source_and_rejects_conflicting_declared_hash(tmp_path):
    path = tmp_path / "report.md"
    path.write_text("primary report")
    value = blinded_template([{"record_id": "a", "fulltext_path": "report.md"}], ["value"], base_dir=tmp_path)
    assert value["records"][0]["document_sha256"] == HASH
    with pytest.raises(ValueError):
        blinded_template([{"record_id": "a", "fulltext_path": "report.md", "document_sha256": "0" * 64}], ["value"], base_dir=tmp_path)


def test_model_or_unattested_submission_rejected():
    with pytest.raises(ValueError):
        human_submission(template(), {"reviewer_type": "model", "records": [record()]}, "Reviewer")


def test_two_real_supplied_reviewers_and_explicit_decisions_required():
    with pytest.raises(ValueError):
        adjudicate(template(), [submission("Reviewer A")], [record()], "Adjudicator")
    with pytest.raises(ValueError):
        adjudicate(template(), [submission("Reviewer A"), submission(" reviewer a ")], [record()], "Adjudicator")
    result = adjudicate(template(), [submission("Reviewer A"), submission("Reviewer B")], [record()], "Adjudicator C")
    final = result["records"][0]
    assert final["annotation_status"] == "adjudicated"
    assert final["fields"]["point_estimate"] == 5
    assert final["field_states"]["uncertainty_low"]["status"] == "verified_not_reported"
    assert final["identity_verification"] == "operator_supplied_self_attestation"


def test_unreviewed_fields_cannot_be_promoted_by_adjudicator_alone():
    row = record()
    row["fields"]["point_estimate"] = {"status": "pending", "value": None}
    result = adjudicate(template(), [submission("A", row), submission("B", row)], [record()], "C")
    assert result["records"][0]["annotation_status"] == "pending_review"
    assert result["records"][0]["field_states"]["point_estimate"]["status"] == "pending"


def test_changed_version_is_pending_not_verified():
    changed = record(document_sha256="0" * 64, report_version="preprint-v1")
    result = adjudicate(template(), [submission("A"), submission("B", changed)], [record()], "C")
    final = result["records"][0]
    assert final["annotation_status"] == "pending_review"
    assert "independent_review_source_version_conflict" in final["adjudication_issues"]


def test_adjudication_does_not_silently_drop_reports():
    with pytest.raises(ValueError):
        adjudicate(template(), [submission("A"), submission("B")], [], "C")


def test_missing_primary_evidence_cannot_become_adjudicated():
    row = record()
    row["fields"]["point_estimate"]["quote"] = ""
    result = adjudicate(template(), [submission("A"), submission("B")], [row], "C")
    assert result["records"][0]["field_states"]["point_estimate"]["status"] == "pending"


def test_immutable_revision_idempotence_and_tamper_detection(tmp_path):
    value = adjudicate(template(), [submission("A"), submission("B")], [record()], "C")
    path = write_revision(tmp_path, "adjudication", value, value["records"])
    assert write_revision(tmp_path, "adjudication", value, value["records"]) == path
    assert (path / "reference_adjudication.jsonl").is_file()
    (path / "reference_adjudication.jsonl").write_text("tampered")
    with pytest.raises(ValueError):
        write_revision(tmp_path, "adjudication", value, value["records"])


def test_connected_reports_and_families_never_cross_split():
    rows = [{"record_id": "r1", "study_family_id": "f1", "profile": "P1"},
            {"record_id": "r1", "profile": "P2"},
            {"record_id": "r2", "study_family_id": "f1", "profile": "P3"},
            {"record_id": "r3", "profile": "P4"}]
    value = connected_split(rows, test_fraction=.5, seed=17)
    sets = [set(value["development_indices"]), set(value["test_indices"])]
    assert any({0, 1, 2} <= group for group in sets)
    assert value == connected_split(rows, test_fraction=.5, seed=17)


def test_cli_template_submission_finalize_revision_pipeline(tmp_path):
    runner = CliRunner()
    source = tmp_path / "bibliography.jsonl"
    source.write_text(json.dumps({"record_id": "pmid:1", "title": "Study", "report_version": "published-v1", "document_sha256": HASH, "point_estimate": 12345}) + "\n")
    out = tmp_path / "annotations"
    result = runner.invoke(annotations, ["template", "--input", str(source), "--field", "point_estimate", "--field", "uncertainty_low", "--out", str(out)])
    assert result.exit_code == 0, result.output
    template_path = next(out.glob("revisions/*/artifact.json"))
    t = json.loads(template_path.read_text())
    submission_paths = []
    for reviewer in ("Reviewer A", "Reviewer B"):
        payload = {"reviewer_type": "human", "independent_primary_source_review": True, "template_sha256": digest(t), "records": [record()]}
        input_path = tmp_path / (reviewer + ".json")
        input_path.write_text(json.dumps(payload))
        result = runner.invoke(annotations, ["submit", "--template", str(template_path), "--input", str(input_path), "--reviewer", reviewer, "--out", str(out)])
        assert result.exit_code == 0, result.output
        submission_paths.append(str(result.output.strip() + "/artifact.json"))
    decisions = tmp_path / "decisions.jsonl"
    decisions.write_text(json.dumps(record()) + "\n")
    result = runner.invoke(annotations, ["finalize", "--template", str(template_path), "--submission", submission_paths[0], "--submission", submission_paths[1], "--decisions", str(decisions), "--adjudicator", "Adjudicator C", "--out", str(out)])
    assert result.exit_code == 0, result.output
    final_path = next(out.glob("revisions/*/reference_adjudication.jsonl"))
    assert json.loads(final_path.read_text())["validation_status"] == "adjudicated"


def test_independent_estimate_omissions_need_explicit_adjudicator_disposition():
    extra = record(estimate_id="e2")
    s1 = submission("A")
    s1["records"].append(extra)
    with pytest.raises(ValueError):
        adjudicate(template(), [s1, submission("B")], [record()], "C")


def test_split_assignment_does_not_depend_on_numeric_answers():
    rows = [{"record_id": f"r{i}", "profile": "P", "point_estimate": i} for i in range(10)]
    changed = [{**r, "point_estimate": 999 - r["point_estimate"]} for r in rows]
    before = connected_split(rows, test_fraction=.3, seed=42)
    after = connected_split(changed, test_fraction=.3, seed=42)
    assert before["test_indices"] == after["test_indices"]
    assert before["development_indices"] == after["development_indices"]
