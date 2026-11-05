"""Evidence-driven protocol logic and the actual async engine route (no API calls)."""
import asyncio
import json

import pytest

from metaagent.screening.protocol import reduce_assessments, render_protocol_messages, validate_protocol


def protocol(logic=None, criteria=None):
    return {"version": "test-v1", "criteria": criteria or [
        {"id": "disease", "description": "Disease X"},
        {"id": "SI", "description": "Reports serial interval"},
        {"id": "IP", "description": "Reports incubation period"},
    ], "logic": logic or {"all": ["disease", {"any": ["SI", "IP"]}]}}


def decision(statuses, quotes=None, identity="one"):
    return {"record_id": identity, "assessments": [
        {"criterion_id": k, "status": v, "evidence": (quotes or {}).get(k, ""), "reason": "test"}
        for k, v in statuses.items()
    ], "proposed_route": "retain"}


def test_multioutcome_review_not_narrowed_to_analysis_target():
    result = reduce_assessments(protocol(), decision(
        {"disease": "met", "SI": "not_met", "IP": "met"},
        {"disease": "Disease X", "SI": "No SI estimate", "IP": "IP was 5 days"}),
        "Disease X. No SI estimate. IP was 5 days.")
    assert result["route"] == "retain"


def test_absence_or_unmatched_quote_cannot_be_grounded_negative():
    result = reduce_assessments(protocol(), decision(
        {"disease": "met", "SI": "not_met", "IP": "unknown"},
        {"disease": "Disease X", "SI": "Not present in the abstract"}),
        "Disease X. Abstract not available.")
    assert result["route"] == "review"
    assert result["assessments"][1]["effective_status"] == "unknown"
    assert "missing_or_unmatched_evidence" in result["assessments"][1]["validation_flags"]


def test_explicit_required_violation_excludes_even_with_other_unknowns():
    result = reduce_assessments(protocol(), decision(
        {"disease": "not_met", "SI": "unknown", "IP": "unknown"},
        {"disease": "We studied disease Y rather than disease X"}),
        "We studied disease Y rather than disease X.")
    assert result["route"] == "exclude"
    assert not result["proposal_agrees"]


def test_model_cannot_declare_required_criterion_inapplicable():
    result = reduce_assessments(protocol(), decision(
        {"disease": "not_applicable", "SI": "met", "IP": "unknown"},
        {"SI": "SI was 2 days"}), "SI was 2 days.")
    assert result["route"] == "review"
    assert "unsupported_not_applicable" in result["assessments"][0]["validation_flags"]


def test_conditional_applicability_is_deterministic():
    p = protocol(criteria=[
        {"id": "animal", "description": "Animal study"},
        {"id": "species", "description": "Allowed species", "when": "animal"},
    ], logic={"if": "animal", "then": "species"})
    result = reduce_assessments(p, decision(
        {"animal": "not_met", "species": "unknown"},
        {"animal": "All participants were human adults"}), "All participants were human adults.")
    assert result["route"] == "retain"
    assert result["assessments"][1]["effective_status"] == "not_applicable"


def test_unknown_condition_cannot_assume_restriction_inapplicable():
    p = protocol(criteria=[
        {"id": "animal", "description": "Animal study"},
        {"id": "species", "description": "Allowed species", "when": "animal"},
    ], logic={"if": "animal", "then": "species"})
    result = reduce_assessments(p, decision({"animal": "unknown", "species": "not_applicable"}), "")
    assert result["route"] == "review"


@pytest.mark.parametrize("change", ["unknown_id", "cycle", "unused", "duplicate"])
def test_invalid_protocol_fails_before_execution(change):
    p = protocol()
    if change == "unknown_id":
        p["logic"] = "typo"
    elif change == "cycle":
        p["criteria"][0]["when"] = "SI"
        p["criteria"][1]["when"] = "disease"
    elif change == "unused":
        p["logic"] = "disease"
    else:
        p["criteria"].append(p["criteria"][0])
    with pytest.raises(ValueError):
        validate_protocol(p)


def test_duplicate_or_missing_assessments_fail():
    d = decision({"disease": "unknown", "SI": "unknown", "IP": "unknown"})
    d["assessments"][-1] = d["assessments"][0]
    with pytest.raises(ValueError):
        reduce_assessments(protocol(), d, "")


def test_prompt_has_unique_schema_and_no_assumed_constraints():
    msgs = render_protocol_messages(protocol(), [{"record_id": "one", "source": "unknown"}], "title_abstract", multi=True)
    payload = json.loads(msgs[1]["content"])
    assert "ProtocolAssessment" in payload["output_schema"]["$defs"]
    assert payload["review_protocol"] == protocol()
    assert "Do not invent geographic" in msgs[0]["content"]


class FakeModel:
    def bind(self, **kwargs):
        return self


def test_engine_uses_protocol_not_legacy_dimensions(monkeypatch):
    from metaagent.screening import engine
    calls = []

    async def invoke(model, prompt, **kwargs):
        payload = json.loads(prompt[1]["content"])
        calls.append(payload)
        assert "ground_truth" not in payload["records"][0]["source"]
        return decision({"disease": "met", "SI": "unknown", "IP": "met"},
                        {"disease": "Disease X", "IP": "IP was 5 days"}), {"prompt_tokens": 10}

    monkeypatch.setattr(engine, "invoke_with_retry_async", invoke)
    rows = [{"record_id": "one", "Title": "Disease X", "Abstract": "IP was 5 days", "ground_truth": "secret reference"}]
    asyncio.run(engine.screen_papers_batch_async(rows, "A different analysis target", FakeModel(),
                screening_config={"review_protocol": protocol()}))
    assert len(calls) == 1
    assert rows[0]["llm_suggest"] == "strong_candidate"
    assert rows[0]["llm_tier"] == "S"
    assert rows[0]["parameter_score"] == ""
    assert rows[0]["criterion_assessments"][2]["effective_status"] == "met"


@pytest.mark.parametrize("kind", ["wrong_id", "duplicate", "missing"])
def test_engine_invalid_multi_identity_marks_errors_not_exclusions(monkeypatch, kind):
    from metaagent.screening import engine

    async def invoke(model, prompt, **kwargs):
        first = decision({"disease": "unknown", "SI": "unknown", "IP": "unknown"})
        second = decision({"disease": "unknown", "SI": "unknown", "IP": "unknown"}, identity="two")
        if kind == "wrong_id":
            second["record_id"] = "someone_else"
        elif kind == "duplicate":
            second = first
        values = [first] if kind == "missing" else [first, second]
        return {"records": values}, {}

    monkeypatch.setattr(engine, "invoke_with_retry_async", invoke)
    rows = [{"record_id": "one", "Title": "Disease X"}, {"record_id": "two", "Title": "Other study"}]
    asyncio.run(engine.screen_papers_batch_async(rows, "question", FakeModel(), batch_mode="multi",
                batch_size=2, screening_config={"review_protocol": protocol()}))
    assert all(r["llm_suggest"] == "error" for r in rows)
    assert all("protocol_error" in r for r in rows)


def test_engine_unknowns_remain_possible_with_no_abstract(monkeypatch):
    from metaagent.screening import engine

    async def invoke(model, prompt, **kwargs):
        return decision({"disease": "unknown", "SI": "unknown", "IP": "unknown"}), {}

    monkeypatch.setattr(engine, "invoke_with_retry_async", invoke)
    rows = [{"record_id": "one", "Title": "Outbreak report"}]
    asyncio.run(engine.screen_papers_batch_async(rows, "question", FakeModel(),
                screening_config={"review_protocol": protocol()}))
    assert rows[0]["llm_suggest"] == "possible_candidate"


def test_engine_valid_multi_reordered_results_match_exact_identity(monkeypatch):
    from metaagent.screening import engine

    async def invoke(model, prompt, **kwargs):
        one = decision({"disease": "not_met", "SI": "unknown", "IP": "unknown"},
                       {"disease": "Disease Y only"}, identity="one")
        two = decision({"disease": "met", "SI": "unknown", "IP": "met"},
                       {"disease": "Disease X", "IP": "IP was 5 days"}, identity="two")
        return {"records": [two, one]}, {"prompt_tokens": 20}

    monkeypatch.setattr(engine, "invoke_with_retry_async", invoke)
    rows = [{"record_id": "one", "Title": "Disease Y only"},
            {"record_id": "two", "Title": "Disease X", "Abstract": "IP was 5 days", "protocol_error": "old"}]
    asyncio.run(engine.screen_papers_batch_async(rows, "question", FakeModel(), batch_mode="multi",
                batch_size=2, screening_config={"review_protocol": protocol()}))
    assert rows[0]["llm_suggest"] == "unlikely_candidate"
    assert rows[1]["llm_suggest"] == "strong_candidate"
    assert rows[1]["prompt_tokens"] == 10
    assert "protocol_error" not in rows[1]


def test_absence_from_truncated_bundle_cannot_exclude():
    p = {"version": "1", "criteria": [{"id": "outcome", "description": "Reports SI"}], "logic": "outcome"}
    d = {"record_id": "one", "assessments": [{"criterion_id": "outcome", "status": "not_met", "evidence_basis": "absence", "reason": "No estimate found"}]}
    partial = reduce_assessments(p, d, "Methods only", stage="full_text", coverage={"complete": True, "truncated": True})
    assert partial["route"] == "review"
    full = reduce_assessments(p, d, "Full supplied text", stage="full_text", coverage={"complete": True, "truncated": False, "missing_materials": []})
    assert full["route"] == "exclude"


def test_required_supplement_missing_defeats_complete_flag():
    p = {"version": "1", "criteria": [{"id": "outcome", "description": "Reports SI"}], "logic": "outcome"}
    d = {"record_id": "one", "assessments": [{"criterion_id": "outcome", "status": "not_met", "evidence_basis": "absence", "reason": "No estimate found"}]}
    result = reduce_assessments(p, d, "Main text", stage="full_text", coverage={"complete": True, "truncated": False, "required_materials": ["main", "supplement"], "provided_materials": ["main"]})
    assert result["route"] == "review"


def test_standalone_protocol_cli_same_engine_without_profile(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from metaagent.screening.cli import screening
    from metaagent.screening import engine
    import yaml

    input_path = tmp_path / "records.jsonl"
    input_path.write_text(json.dumps({"record_id": "one", "title": "Disease X", "abstract": "IP was 5 days"}) + "\n")
    protocol_path = tmp_path / "protocol.yaml"
    protocol_path.write_text(yaml.safe_dump(protocol()))
    out = tmp_path / "results.jsonl"
    monkeypatch.setattr(engine, "init_llm_model", lambda **kw: FakeModel())

    async def invoke(model, messages, **kwargs):
        return decision({"disease": "met", "SI": "unknown", "IP": "met"}, {"disease": "Disease X", "IP": "IP was 5 days"}), {}

    monkeypatch.setattr(engine, "invoke_with_retry_async", invoke)
    result = CliRunner().invoke(screening, ["protocol-run", "--input", str(input_path), "--protocol", str(protocol_path), "--out", str(out)])
    assert result.exit_code == 0, result.output
    row = json.loads(out.read_text())
    assert row["llm_tier"] == "S"
    assert row["protocol_decision"]["route"] == "retain"
    assert out.with_suffix(".jsonl.manifest.json").is_file()


class ScriptedProtocolModel:
    """Use the real audited invocation wrapper with deterministic local responses."""
    def __init__(self, responses):
        self.responses = iter(responses)
        self.prompts = []

    def bind(self, **kwargs):
        return self

    async def ainvoke(self, prompt, **kwargs):
        from types import SimpleNamespace
        self.prompts.append(prompt)
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(content=json.dumps(value), usage_metadata={"input_tokens": 10, "output_tokens": 5}, response_metadata={"test": "offline"})


def correction_fixture():
    p = {"version": "correction-v1", "criteria": [
        {"id": "disease", "description": "The report studies disease X in humans."},
        {"id": "original", "description": "The report contains original human observations."}],
        "logic": {"all": ["disease", "original"]}}
    bad = {"record_id": "one", "assessments": [
        {"criterion_id": c["id"], "status": "met", "evidence": c["description"], "reason": "Model reasoning is not source evidence"}
        for c in p["criteria"]], "proposed_route": "retain"}
    good = {"record_id": "one", "assessments": [
        {"criterion_id": "disease", "status": "met", "evidence": "40 patients with disease X", "reason": "Direct source statement"},
        {"criterion_id": "original", "status": "met", "evidence": "We followed 40 patients", "reason": "Original follow-up"}],
        "proposed_route": "retain"}
    row = {"record_id": "one", "Title": "Study", "fulltext": "We followed 40 patients with disease X prospectively.",
           "Abstract": "DO NOT SUBSTITUTE THIS ABSTRACT", "fulltext_coverage": {"complete": False, "truncated": False}}
    return p, bad, good, row


def test_invalid_claim_evidence_corrected_once_with_same_fulltext_and_actual_audit(tmp_path):
    from metaagent.screening import engine
    p, bad, good, row = correction_fixture()
    model = ScriptedProtocolModel([bad, good])
    audit = tmp_path / "calls.jsonl"
    asyncio.run(engine.screen_papers_batch_async([row], "question", model, screening_stage="full_text", content_key="fulltext",
                screening_config={"review_protocol": p, "call_log": str(audit)}))
    assert len(model.prompts) == 2
    first = json.loads(model.prompts[0][1]["content"])
    repair = json.loads(model.prompts[1][1]["content"])
    assert repair["records"] == first["records"]
    assert "We followed 40 patients" in repair["records"][0]["source"]
    assert "DO NOT SUBSTITUTE" not in repair["records"][0]["source"]
    assert repair["validation_feedback"][0]["criteria"][0]["invalid_evidence"] == p["criteria"][0]["description"]
    assert row["protocol_decision"]["route"] == "retain"
    assert row["evidence_correction"]["status"] == "corrected"
    assert all(a["evidence_verified"] for a in row["criterion_assessments"])
    calls = [json.loads(line) for line in audit.read_text().splitlines()]
    assert [c["purpose"] for c in calls] == ["initial", "evidence_correction"]
    assert all(c["status"] == "ok" and c["record_ids"] == ["one"] for c in calls)
    assert calls[0]["request_sha256"] != calls[1]["request_sha256"]
    assert json.loads(calls[0]["raw_response"]) == bad
    assert json.loads(calls[1]["raw_response"]) == good


@pytest.mark.parametrize("repair", ["still_invalid", "transport_error", "wrong_id"])
def test_evidence_correction_failure_stays_review_no_third_call(tmp_path, repair):
    from metaagent.screening import engine
    p, bad, good, row = correction_fixture()
    response = bad if repair == "still_invalid" else RuntimeError("offline transport failure") if repair == "transport_error" else dict(good, record_id="other")
    model = ScriptedProtocolModel([bad, response])
    audit = tmp_path / "calls.jsonl"
    asyncio.run(engine.screen_papers_batch_async([row], "question", model, screening_stage="full_text", content_key="fulltext",
                screening_config={"review_protocol": p, "call_log": str(audit)}))
    assert len(model.prompts) == 2
    assert row["protocol_decision"]["route"] == "review"
    assert row["llm_suggest"] == "possible_candidate"
    assert all(a["effective_status"] == "unknown" for a in row["criterion_assessments"])
    assert row["evidence_correction"]["attempts"] == 1
    assert len(audit.read_text().splitlines()) == 2


def test_correction_cannot_overwrite_already_grounded_assessment():
    from metaagent.screening import engine
    p, bad, good, row = correction_fixture()
    initial = json.loads(json.dumps(bad))
    initial["assessments"][0] = good["assessments"][0]
    changed = json.loads(json.dumps(good))
    changed["assessments"][0].update(status="not_met", evidence="Model's ungrounded reversal")
    model = ScriptedProtocolModel([initial, changed])
    asyncio.run(engine.screen_papers_batch_async([row], "question", model, screening_stage="full_text", content_key="fulltext",
                screening_config={"review_protocol": p}))
    assert row["protocol_decision"]["route"] == "retain"
    assert row["criterion_assessments"][0]["evidence"] == good["assessments"][0]["evidence"]
    assert row["criterion_assessments"][0]["status"] == "met"
    payload = json.loads(model.prompts[1][1]["content"])
    assert [v["criterion_id"] for v in payload["validation_feedback"][0]["criteria"]] == ["original"]


def test_corrected_evidence_call_cost_is_added_not_replaced(monkeypatch):
    from metaagent.screening import engine
    p, bad, good, row = correction_fixture()
    replies = iter([(bad, {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14, "wall_time_ms": 30}),
                    (good, {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28, "wall_time_ms": 50})])
    options = []

    async def invoke(model, prompt, **kwargs):
        options.append(kwargs)
        return next(replies)

    monkeypatch.setattr(engine, "invoke_with_retry_async", invoke)
    asyncio.run(engine.screen_papers_batch_async([row], "question", FakeModel(), screening_stage="full_text", content_key="fulltext",
                screening_config={"review_protocol": p}))
    assert row["prompt_tokens"] == 30
    assert row["completion_tokens"] == 12
    assert row["total_tokens"] == 42
    assert row["wall_time_ms"] == 80
    assert options[1]["max_retries"] == 1


def test_batch_evidence_correction_targets_only_failed_record_with_exact_source(tmp_path):
    from metaagent.screening import engine
    p, bad, good, row = correction_fixture()
    valid = dict(good, record_id="two")
    other = dict(row, record_id="two", fulltext="We followed 40 patients with disease X in another cohort.")
    model = ScriptedProtocolModel([{"records": [bad, valid]}, {"records": [good]}])
    audit = tmp_path / "calls.jsonl"
    asyncio.run(engine.screen_papers_batch_async([row, other], "question", model, screening_stage="full_text", content_key="fulltext",
                batch_mode="multi", batch_size=2, screening_config={"review_protocol": p, "call_log": str(audit)}))
    repair = json.loads(model.prompts[1][1]["content"])
    initial = json.loads(model.prompts[0][1]["content"])
    assert repair["records"] == [initial["records"][0]]
    assert row["llm_tier"] == other["llm_tier"] == "S"
    assert "evidence_correction" not in other
    events = [json.loads(line) for line in audit.read_text().splitlines()]
    assert events[0]["record_ids"] == ["one", "two"]
    assert events[1]["record_ids"] == ["one"]


def test_multi_correction_cost_only_attributed_to_affected_record(monkeypatch):
    from metaagent.screening import engine
    p, bad, good, row = correction_fixture()
    other = dict(row, record_id="two")
    replies = iter([({"records": [bad, dict(good, record_id="two")]}, {"prompt_tokens": 20, "completion_tokens": 4, "total_tokens": 24, "wall_time_ms": 10}),
                    ({"records": [good]}, {"prompt_tokens": 30, "completion_tokens": 6, "total_tokens": 36, "wall_time_ms": 50})])

    async def invoke(model, prompt, **kwargs):
        return next(replies)

    monkeypatch.setattr(engine, "invoke_with_retry_async", invoke)
    asyncio.run(engine.screen_papers_batch_async([row, other], "question", FakeModel(), screening_stage="full_text", content_key="fulltext",
                batch_mode="multi", batch_size=2, screening_config={"review_protocol": p}))
    assert row["prompt_tokens"] == 40
    assert row["total_tokens"] == 48
    assert other["prompt_tokens"] == 10
    assert other["total_tokens"] == 12
    assert row["wall_time_ms"] == 60
    assert other["wall_time_ms"] == 10


def latex_correction_fixture():
    p = {"version": "latex-v1", "criteria": [{"id": "outcome", "description": "Reports an interval estimate"}], "logic": "outcome"}
    text = ("Methods and results. The incubation period was estimated from exposure histories. "
            r"The mean incubation period was 7.6 days $9 5 \%$ credible interval 6.5 to 9.9. "
            "Full table details follow.")
    bad = {"record_id": "latex", "assessments": [{"criterion_id": "outcome", "status": "met", "evidence": "The mean incubation period was 7.6 days 95% credible interval 6.5 to 9.9.", "reason": "Reports the estimate"}], "proposed_route": "retain"}
    good = {"record_id": "latex", "assessments": [{"criterion_id": "outcome", "status": "met", "evidence": "The incubation period was estimated from exposure histories.", "reason": "Short raw clause establishes estimated parameter"}], "proposed_route": "retain"}
    row = {"record_id": "latex", "Title": "原始全文", "fulltext": text,
           "fulltext_coverage": {"complete": False, "truncated": False}}
    return p, bad, good, row


def test_same_source_locator_keeps_raw_latex_markdown_and_unicode_offsets():
    from metaagent.screening.protocol import evidence_source_context
    source = "前缀中文\n### Results\n" + latex_correction_fixture()[3]["fulltext"]
    invalid_quote = latex_correction_fixture()[1]["assessments"][0]["evidence"]
    located = evidence_source_context(source, invalid_quote)
    assert located is not None
    assert located["source_context"] == source[located["context_start"]:located["context_end"]]
    assert located["matching_text"] == source[located["match_start"]:located["match_end"]]
    assert r"$9 5 \%$" in located["source_context"]
    assert "### Results" in located["source_context"]
    assert evidence_source_context("empty evidence", "") is None


def test_latex_normalization_failure_repair_chooses_short_raw_clause():
    from metaagent.screening import engine
    p, bad, good, row = latex_correction_fixture()
    model = ScriptedProtocolModel([bad, good])
    asyncio.run(engine.screen_papers_batch_async([row], "question", model, screening_stage="full_text", content_key="fulltext",
                screening_config={"review_protocol": p}))
    repair = json.loads(model.prompts[1][1]["content"])
    located = repair["validation_feedback"][0]["criteria"][0]["same_source_locator"]
    source = repair["records"][0]["source"]
    assert located["source_context"] == source[located["context_start"]:located["context_end"]]
    assert r"$9 5 \%$" in located["source_context"]
    assert "5-15 word clause" in repair["correction_task"]
    assert "never clean up math" in repair["correction_task"]
    assert row["criterion_assessments"][0]["evidence"] == good["assessments"][0]["evidence"]
    assert row["protocol_decision"]["route"] == "retain"
    assert len(model.prompts) == 2


def test_source_locator_does_not_auto_accept_normalized_latex_quote():
    from metaagent.screening import engine
    p, bad, _, row = latex_correction_fixture()
    model = ScriptedProtocolModel([bad, bad])
    asyncio.run(engine.screen_papers_batch_async([row], "question", model, screening_stage="full_text", content_key="fulltext",
                screening_config={"review_protocol": p}))
    assert len(model.prompts) == 2
    assert row["protocol_decision"]["route"] == "review"
    assert row["criterion_assessments"][0]["evidence_verified"] is False
    assert "missing_or_unmatched_evidence" in row["criterion_assessments"][0]["validation_flags"]
