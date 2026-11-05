"""Reports preserve dimension scores and model tags without a derived total."""
import copy
import csv
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner
from metaagent.screening import reporting
from metaagent.screening.prompt_loader import PROMPT_FILES, load_prompt_templates


def report(rows):
    return "\n".join(reporting._build_report_lines(
        papers=rows, research_question="Which human studies report the interval?",
        input_file=Path("input.jsonl"), output_file=Path("output.csv"),
        batch_size=2, batch_concurrency=1, batch_mode="single",
        fulltext_needed_count=0, fulltext_ready_count=0, fulltext_errors=[],
        strong=[r for r in rows if r.get("llm_suggest") == "strong_candidate"],
        possible=[r for r in rows if r.get("llm_suggest") == "possible_candidate"],
        unlikely=[r for r in rows if r.get("llm_suggest") == "unlikely_candidate"],
        errors=[r for r in rows if r.get("llm_suggest") == "error"],
        llm_cfg=SimpleNamespace(provider="offline", model="fixture")))


def test_strong_details_ignore_total_and_keep_input_order():
    rows=[{"record_id":"first", "llm_tier":"S", "llm_suggest":"strong_candidate", "overall_score":0},
          {"record_id":"other", "llm_tier":"P", "llm_suggest":"possible_candidate", "overall_score":99999},
          {"record_id":"second", "llm_tier":"S", "llm_suggest":"strong_candidate", "overall_score":None},
          {"record_id":"third", "llm_tier":"S", "llm_suggest":"strong_candidate", "overall_score":4}]
    before=copy.deepcopy(rows)
    text=report(rows)
    assert text.index("Record: first") < text.index("Record: second") < text.index("Record: third")
    assert "Record: other" not in text and "Tier: S" in text
    assert "99999" not in text and "[Score:" not in text and "overall_score" not in text
    assert rows==before


@pytest.mark.parametrize("value", [None, "", "unknown", float("nan"), True, 5])
def test_missing_dimension_is_not_zero(value):
    text=report([{"record_id":"missing", "llm_suggest":"strong_candidate", "disease_score":value, "overall_score":None}])
    assert "Dimension scores: D=N/A" in text
    assert "N/A" in next(line for line in text.splitlines() if line.startswith("│ Disease"))


def test_empty_report_and_review_flag_separate_from_tag():
    assert "Total records" in report([])
    text=report([{"record_id":"review", "llm_tier":"S", "llm_suggest":"strong_candidate",
                  "disease_score":4, "screening_requires_review":True,
                  "screening_review_flags":["missing_source"]}])
    assert "D=4" in text and "Tier: S" in text and "Review: ['missing_source']" in text


def test_save_keeps_compatibility_total_empty_and_all_records(tmp_path, monkeypatch):
    cfg=SimpleNamespace(provider="offline",model="fixture",api_base="http://unused",
                        timeout_s=1,verify_ssl=True,api_key="")
    monkeypatch.setattr(reporting,"load_llm_config",lambda *a,**k:cfg)
    monkeypatch.setattr(reporting,"load_mineru_config",lambda **k:SimpleNamespace(base_url="http://unused",endpoint="unused",timeout_s=1,api_key=""))
    def manifest(**kw):
        path=kw["output_dir"] / "manifest.json"
        path.write_text("{}")
        return path
    monkeypatch.setattr(reporting,"write_run_manifest",manifest)
    output=tmp_path/"screened.csv"
    reporting.save_screening_outputs(
        papers=[{"record_id":"one","llm_tier":"S","llm_suggest":"strong_candidate","disease_score":0},
                {"record_id":"two","llm_tier":"P","llm_suggest":"possible_candidate"}],
        output_file=output,research_question="Question",input_file=tmp_path/"input.jsonl",
        gt_file=None,gt_pmids=set(),gt_count=None,batch_size=1,batch_concurrency=1,
        profile_name=None,auto_fulltext=False,fulltext_only=False,
        fulltext_needed_count=0,fulltext_ready_count=0,fulltext_errors=[])
    with output.open(encoding="utf-8-sig") as f: rows=list(csv.DictReader(f))
    assert [r["record_id"] for r in rows]==["one","two"]
    assert all(r["overall_score"]=="" for r in rows)
    assert rows[0]["llm_tier"]=="S" and rows[0]["disease_score"]=="0"


@pytest.mark.parametrize("stage", [k for k,v in PROMPT_FILES.items() if v[0].parent.name=="5d"])
def test_shipped_prompts_keep_tier_holistic(stage):
    system,_=load_prompt_templates(stage)
    text=" ".join(system.lower().translate(str.maketrans({"–":"-","—":"-","−":"-"})).split())
    assert re.search(r"\b0\s*-\s*4\b",text)
    assert "holistic" in text and re.search(r"\bs\s*/\s*p\s*/\s*u\b",text)
    for field in ("disease_relevance","population_relevance","location_relevance","original_evidence","parameter_relevance"):
        assert field in text
    assert "overall_justification" in text and "tier" in text
    # Accept equivalent prohibitions, while retaining the resource-level guard.
    assert re.search(r"\bno weighted (?:total|score|sum)\b|\bdo not (?:calculate|compute|use)\b[^.]*\bweighted (?:total|score|sum)\b",text)
    assert re.search(r"\bno\b[^.]*\b(?:fixed dimension cutoff|fixed cutoff|numeric threshold)\b|\bnot\b[^.]*\b(?:tag thresholds|tier thresholds)\b|\bdo not\b[^.]*\b(?:fixed cutoffs|score thresholds)\b",text)
    assert not re.search(r"\bscore\s*(?:>=|≥|<=|≤)\s*[0-4]\b",text)
    assert not re.search(r"\d+(?:\.\d+)?\s*\*\s*(?:disease_relevance|population_relevance|location_relevance|original_evidence|parameter_relevance)\b",text)
    assert "The application will compute the final candidate label" not in system


def test_cli_help_default_and_explicit_compatibility():
    from metaagent.screening.cli import run
    result=CliRunner().invoke(run,["--help"])
    assert result.exit_code==0
    assert "holistic S/P/U" in result.output
    assert "legacy score thresholds" in result.output
