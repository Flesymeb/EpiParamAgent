import asyncio
import json
from pathlib import Path

import pytest

from tools.scripts import prepare_downstream_experiment
from metaagent.coding import cli as coding_cli
from metaagent.coding.pipeline import extraction as coding_extraction
from metaagent.screening import cli as screening_cli
from metaagent.screening import engine
from metaagent.screening import fulltext_pipeline
from metaagent.screening.models import BinaryDecision
from metaagent.screening.profile_registry import resolve_profile_paths
from metaagent.screening.staging import partition_papers
from workbench.backend.app.services import extraction_service


class _FakeLLM:
    def with_structured_output(self, schema):
        return schema


def _papers(n: int) -> list[dict[str, str]]:
    return [
        {
            "PMID": str(1000 + i),
            "Title": f"Paper {i}",
            "Abstract": "COVID-19 reproduction number estimate.",
            "Keywords": "COVID-19; R0",
        }
        for i in range(n)
    ]


def test_screening_concurrency_limits_in_flight_llm_requests(monkeypatch):
    active = 0
    max_active = 0

    async def fake_invoke(_llm, _prompt, *args, **kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return BinaryDecision(include=True, justification="ok", confidence=0.9), {}

    monkeypatch.setattr(engine, "invoke_with_retry_async", fake_invoke)

    asyncio.run(
        engine.screen_papers_batch_async(
            _papers(4),
            "What is the R0 of COVID-19?",
            _FakeLLM(),
            batch_size=4,
            batch_concurrency=1,
            strategy="binary",
        )
    )

    assert max_active == 1


def test_screening_individual_retry_writes_structured_result(monkeypatch):
    calls = 0

    class BadMessage:
        content = "{not valid json"

    async def fake_invoke(_llm, _prompt, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls <= 2:
            return BadMessage(), {}
        return BinaryDecision(include=True, justification="retry ok", confidence=0.9), {}

    monkeypatch.setattr(engine, "invoke_with_retry_async", fake_invoke)
    papers = _papers(2)

    asyncio.run(
        engine.screen_papers_batch_async(
            papers,
            "What is the R0 of COVID-19?",
            _FakeLLM(),
            batch_size=2,
            batch_concurrency=1,
            strategy="binary",
        )
    )

    assert [p["llm_suggest"] for p in papers] == ["strong_candidate", "strong_candidate"]


def test_profile_paths_resolve_to_current_evaluation_layout(tmp_path):
    _, paths = resolve_profile_paths(project_root=tmp_path, profile_name="P7")

    assert paths.project_dir == (
        tmp_path
        / "evaluation"
        / "covid19"
        / "reproduction_number"
        / "ground_truth"
        / "p7"
    )
    assert paths.raw_file.name == "project_7_raw.csv"
    assert paths.ground_truth_file.name == "project_7_groundtruth.csv"


def test_fulltext_only_routes_all_papers_to_fulltext_bucket():
    papers = _papers(2)

    state = partition_papers(
        papers=papers,
        screening_config={},
        auto_fulltext=False,
        fulltext_only=True,
    )

    assert state["papers_title_abstract"] == []
    assert state["papers_title_only"] == []
    assert state["papers_without_abstract"] == papers
    assert {paper["screening_stage"] for paper in papers} == {"pending_fulltext"}


def test_fulltext_only_reuses_markdown_cache_variants(tmp_path, monkeypatch):
    cache_dir = tmp_path / "paper_pool" / "markdown"
    paper_dir = cache_dir / "PMID_123"
    paper_dir.mkdir(parents=True)
    (paper_dir / "fulltext.md").write_text("cached full text", encoding="utf-8")
    monkeypatch.setattr(fulltext_pipeline, "MD_CACHE_DIR", cache_dir)

    papers = [
        {
            "PMID": "123",
            "Title": "Cached paper",
            "Abstract": "has abstract but fulltext-only should use cache",
        }
    ]

    state = partition_papers(
        papers=papers,
        screening_config={},
        auto_fulltext=False,
        fulltext_only=True,
    )

    assert state["fulltext_cached"] == papers
    assert papers[0]["fulltext_markdown"] == "cached full text"
    assert papers[0]["fulltext_path"].endswith("fulltext.md")


@pytest.mark.parametrize(
    "script_name",
    ["screening_prepare_raw", "screening_llm_batch", "screening_report_academic"],
)
def test_screening_cli_legacy_script_aliases_support_help(script_name):
    screening_cli._run_script(script_name, ["--help"])


def test_coding_extract_normalizes_all_stage_to_both(monkeypatch):
    captured = {}

    def fake_run_script(script_path: Path, argv: list[str]) -> None:
        captured["script_path"] = script_path
        captured["argv"] = argv

    monkeypatch.setattr(coding_cli, "_run_script", fake_run_script)

    coding_cli.extract.callback(
        "mpox",
        "reproduction_number",
        "MP9",
        "all",
        "pmc_only",
        None,
        None,
    )

    stage_idx = captured["argv"].index("--stage")
    assert captured["argv"][stage_idx + 1] == "both"


def test_extraction_service_reads_input_count_from_manifest(tmp_path):
    manifest = tmp_path / "run_manifest_coding_sheet_extraction_20260505_000000.json"
    manifest.write_text(
        json.dumps(
            {
                "timestamp_utc": "2026-05-05T00:00:00Z",
                "workflow": "coding_sheet_extraction",
                "params": {"stage": "both"},
                "outputs": [],
                "extra": {"input_count": 3, "record_count": 2},
            }
        ),
        encoding="utf-8",
    )

    run_id = extraction_service._manifest_id(manifest)
    detail = extraction_service.get_run(tmp_path, run_id)

    assert detail is not None
    assert detail["metrics"][0] == {"label": "Input Papers", "value": 3}


def test_coding_pipeline_uses_root_paper_pool():
    pdf_dir, md_dir = coding_extraction._paper_pool_dirs()
    repo_root = Path(__file__).resolve().parents[1]

    assert pdf_dir == repo_root / "paper_pool" / "pdfs"
    assert md_dir == repo_root / "paper_pool" / "markdown"


def test_coding_pdf_load_reuses_existing_markdown_variants(tmp_path, monkeypatch):
    pdf_dir = tmp_path / "paper_pool" / "pdfs"
    md_dir = tmp_path / "paper_pool" / "markdown"
    pdf_dir.mkdir(parents=True)
    md_dir.mkdir(parents=True)
    pdf_path = pdf_dir / "PMID_123.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    legacy_md = md_dir / "PMID_123" / "PMID_123.md"
    legacy_md.parent.mkdir(parents=True)
    legacy_md.write_text("cached markdown", encoding="utf-8")

    monkeypatch.setattr(coding_extraction, "_paper_pool_dirs", lambda: (pdf_dir, md_dir))

    def fail_if_mineru_runs(*args, **kwargs):
        raise AssertionError("MinerU should not run when markdown cache exists")

    monkeypatch.setattr(
        "tools.mineru.pdf_reader.extract_pdf_markdown_mineru",
        fail_if_mineru_runs,
    )

    assert coding_extraction._load_markdown_from_pdf(pdf_path, "123") == "cached markdown"


def test_coding_tools_path_points_to_repo_tools(monkeypatch):
    import sys

    repo_tools = str(Path(__file__).resolve().parents[1] / "tools")
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != repo_tools])

    coding_extraction._ensure_tools_on_path()

    assert sys.path[0] == repo_tools


def test_downstream_experiment_defaults_to_root_paper_pool(tmp_path, monkeypatch):
    screened = tmp_path / "screened.csv"
    screened.write_text("PMID,llm_suggest\n123,strong_candidate\n", encoding="utf-8")
    gt = tmp_path / "gt.csv"
    gt.write_text("gt_pmid\n123\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    monkeypatch.setattr(
        "sys.argv",
        [
            "prepare_downstream_experiment.py",
            "--screened-csv",
            str(screened),
            "--gt-csv",
            str(gt),
            "--out-dir",
            str(out_dir),
        ],
    )

    prepare_downstream_experiment.main()

    payload = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    repo_root = Path(__file__).resolve().parents[1]
    assert payload["paper_pool_pdf_dir"] == str(repo_root / "paper_pool" / "pdfs")
