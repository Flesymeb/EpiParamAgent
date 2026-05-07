import pytest

from metaagent.screening.engine import (
    _build_multi_paper_user_content,
    _parse_multi_paper_result,
)
from metaagent.screening.models import ScreeningDecision


def _decision_payload(tier: str = "U") -> dict:
    dimension = {"score": 4, "justification": "directly relevant"}
    return {
        "disease_relevance": dimension,
        "population_relevance": dimension,
        "location_relevance": dimension,
        "original_evidence": dimension,
        "parameter_relevance": dimension,
        "overall_justification": "The abstract directly reports the target parameter.",
        "confidence": 0.8,
        "tier": tier,
    }


def test_build_multi_paper_user_content_keeps_per_paper_ids():
    papers = [
        (
            {"PMID": "1"},
            {
                "research_question": "RQ",
                "title": "First title",
                "keywords": "alpha",
                "content_label": "Abstract",
                "content": "First abstract",
                "pub_types": "Journal Article",
                "mesh_terms": "COVID-19",
            },
        ),
        (
            {"PMID": "2"},
            {
                "research_question": "RQ",
                "title": "Second title",
                "keywords": "beta",
                "content_label": "Abstract",
                "content": "Second abstract",
                "pub_types": "Journal Article",
                "mesh_terms": "SARS-CoV-2",
            },
        ),
    ]

    content, ids = _build_multi_paper_user_content(papers)

    assert ids == ["1", "2"]
    assert "Paper ID: 1" in content
    assert "Paper ID: 2" in content
    assert "--- BEGIN PAPER 1 ---" in content
    assert "--- END PAPER 2 ---" in content
    assert content.count("Independent case: judge only this paper") == 2
    assert content.count("Research question: RQ") == 1
    assert "First title" in content
    assert "Second abstract" in content
    assert "Return JSON only" in content


def test_parse_multi_paper_result_returns_valid_decisions_by_id():
    payload = {
        "papers": [
            {"paper_id": "1", "decision": _decision_payload("S")},
            {"paper_id": "2", "decision": _decision_payload("P")},
        ]
    }

    parsed = _parse_multi_paper_result(payload, ScreeningDecision)

    assert set(parsed) == {"1", "2"}
    assert parsed["1"].tier == "S"
    assert parsed["2"].tier == "P"


def test_parse_multi_paper_result_rejects_missing_ids():
    with pytest.raises(ValueError, match="paper_id"):
        _parse_multi_paper_result({"papers": [{"decision": _decision_payload()}]}, ScreeningDecision)
