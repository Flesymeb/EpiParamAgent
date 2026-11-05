"""Actual loopback requests and derived metadata coverage; no external services."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import xml.etree.ElementTree as ET
import pytest
from click.testing import CliRunner
from langchain_openai import ChatOpenAI
from metaagent.screening.engine import screen_papers_batch_async
from metaagent.screening.metadata_completion import (
    MetadataLedger,
    compatible,
    parse_pubmed_xml,
    run_completion,
)

XML = b"""<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>Official complete title</ArticleTitle><Abstract><AbstractText Label="METHODS">Explicit source abstract.</AbstractText></Abstract><Journal><Title>Test Journal</Title><JournalIssue><PubDate><Year>2024</Year><Month>Feb</Month></PubDate></JournalIssue></Journal><Language>eng</Language><PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList></Article><KeywordList><Keyword>author keyword</Keyword></KeywordList><MeshHeadingList><MeshHeading><DescriptorName>Index term</DescriptorName></MeshHeading></MeshHeadingList></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1234/right</ArticleId></ArticleIdList><ReferenceList><Reference><ArticleIdList><ArticleId IdType="doi">10.1234/cited</ArticleId></ArticleIdList></Reference></ReferenceList></PubmedData></PubmedArticle></PubmedArticleSet>"""


@pytest.mark.parametrize("batch_mode", ["single", "multi"])
def test_real_wire_context_and_blinded_roster(batch_mode):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append(body)
            request = json.loads(body["messages"][1]["content"])
            records = [
                {
                    "record_id": r["record_id"],
                    "assessments": [
                        {
                            "criterion_id": "reported",
                            "status": "met",
                            "evidence": "Reports serial interval",
                            "reason": "Explicit source statement.",
                        }
                    ],
                    "proposed_route": "retain",
                }
                for r in request["records"]
            ]
            answer = {"records": records} if batch_mode == "multi" else records[0]
            payload = {
                "id": "test",
                "object": "chat.completion",
                "created": 0,
                "model": "offline",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": json.dumps(answer)},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        llm = ChatOpenAI(
            model="offline",
            api_key="synthetic",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            max_retries=0,
        )
        rows = [
            {
                "record_id": "sr:999:ref:bib1",
                "title": "Source title",
                "abstract": "Reports serial interval in people.",
                "keywords": ["author keyword"],
                "mesh_terms": {
                    "meshHeadingList": {
                        "meshHeading": [
                            {
                                "descriptorName": "Index term",
                                "qualifierNameList": {
                                    "qualifierName": ["epidemiology"]
                                },
                                "historical_label": "DO_NOT_SEND_NATIVE_LABEL",
                            }
                        ]
                    }
                },
                "language": ["eng"],
                "publication_date": "2024-Feb",
                "publication_types": ["Journal Article"],
                "historical_label": "DO_NOT_SEND_LABEL",
                "coding_reference": {"point": "DO_NOT_SEND_NUMBER"},
                "fulltext_coverage": {
                    "complete": False,
                    "historical_label": "DO_NOT_SEND_COVERAGE",
                },
                "origin_route": "manual_rescue_positive",
            }
        ]
        protocol = {
            "version": "wire-test",
            "criteria": [
                {
                    "id": "reported",
                    "description": "Reports serial interval OR incubation period",
                }
            ],
            "logic": "reported",
            "reference_table": "DO_NOT_SEND_PROTOCOL_REFERENCE",
        }
        result = asyncio.run(
            screen_papers_batch_async(
                rows,
                "Downstream incubation question",
                llm,
                screening_config={"review_protocol": protocol},
                batch_mode=batch_mode,
                batch_size=2,
            )
        )
        assert result[0]["llm_tier"] == "S"
        assert result[0]["record_id"] == "sr:999:ref:bib1"
        assert result[0]["protocol_decision"]["record_id"] == "sr:999:ref:bib1"
        assert len(received) == 1
        wire = json.dumps(received[0], ensure_ascii=False)
        for value in (
            "Downstream incubation question",
            "Reports serial interval OR incubation period",
            "Source title",
            "Reports serial interval in people.",
            "author keyword",
            "Index term",
            "epidemiology",
            "eng",
            "2024-Feb",
            "Journal Article",
        ):
            assert value in wire
        for value in (
            "sr:999",
            "bib1",
            "DO_NOT_SEND_LABEL",
            "DO_NOT_SEND_NUMBER",
            "DO_NOT_SEND_NATIVE_LABEL",
            "manual_rescue_positive",
            "coding_reference",
            "historical_label",
            "DO_NOT_SEND_COVERAGE",
            "DO_NOT_SEND_PROTOCOL_REFERENCE",
        ):
            assert value not in wire
        assert "background" in wire.lower() and "indexing" in wire.lower()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_pubmed_parser_preserves_direct_ids_and_literals():
    record = list(parse_pubmed_xml(XML))[0]
    assert record["doi"] == "10.1234/right"
    assert record["keywords"] == ["author keyword"] and record["mesh_terms"] == [
        "Index term"
    ]
    assert record["language"] == ["eng"] and record["publication_date"] == "2024-Feb"
    assert record["abstract"] == "METHODS: Explicit source abstract."


def test_version_doi_conflicts_remain_unknown(tmp_path):
    ledger = MetadataLedger(tmp_path / "ledger.sqlite")
    ledger.add(
        {
            "record_id": "same",
            "doi": "10.1234/a",
            "source_version": "v2",
            "abstract": "wrong version",
        },
        {"route": "source"},
    )
    row = {"record_id": "same", "doi": "10.1234/a", "source_version": "v1"}
    assert not compatible(
        row, {"record_id": "same", "doi": "10.1234/b", "source_version": "v1"}
    )
    assert "abstract" not in ledger.enrich(row, {})
    ledger.db.close()


def test_offline_whole_denominator_preserved_model_view_blind(tmp_path):
    root = tmp_path / "release"
    profile = root / "profiles" / "P1"
    profile.mkdir(parents=True)
    cache = tmp_path / "xml"
    cache.mkdir()
    (cache / "batch.xml").write_bytes(XML)
    rows = [
        {
            "record_id": "sr:999:ref:1",
            "pmid": "123",
            "doi": "10.1234/right",
            "title": "Preserved input title",
            "historical_label": "positive",
            "expected_point": 42,
        },
        {"record_id": "unknown", "pmid": "456", "title": "Unknown abstract"},
    ]
    original = "".join(json.dumps(r) + "\n" for r in rows)
    for name in ("raw_search.jsonl", "raw_pool.jsonl"):
        (profile / name).write_text(original)
    out = tmp_path / "derived"
    report = run_completion(root, out, xml_roots=[cache])
    assert report["rows"] == 4 and report["input_hashes_unchanged"]
    assert report["field_missing_after"]["abstract"] == 2
    enriched = [
        json.loads(s)
        for s in (out / "enriched/profiles/P1/raw_pool.jsonl").read_text().splitlines()
    ]
    visible = [
        json.loads(s)
        for s in (out / "model_inputs/profiles/P1/raw_pool.jsonl")
        .read_text()
        .splitlines()
    ]
    assert enriched[0]["title"] == "Preserved input title"
    assert enriched[0]["abstract"] == "METHODS: Explicit source abstract."
    assert (
        enriched[0]["metadata_completion_sources"]["keywords"]["route"]
        == "local_pubmed_xml"
    )
    assert "abstract" not in enriched[1]
    assert "historical_label" not in visible[0] and "expected_point" not in visible[0]
    assert "sr:999" not in json.dumps(visible)
    first = (out / "model_inputs/profiles/P1/raw_pool.jsonl").read_bytes()
    again = run_completion(root, out, xml_roots=[cache])
    assert (
        again["requests_this_invocation"] == 0
        and (out / "model_inputs/profiles/P1/raw_pool.jsonl").read_bytes() == first
    )
    assert (profile / "raw_pool.jsonl").read_text() == original


def test_enrich_cli_offline_and_explicit_resume(tmp_path):
    from tools.literature.cli import literature

    root = tmp_path / "release"
    profile = root / "profiles/P"
    profile.mkdir(parents=True)
    (profile / "raw_pool.jsonl").write_text(
        '{"record_id":"one","title":"Only title"}\n'
    )
    out = tmp_path / "derived"
    runner = CliRunner()
    args = ["enrich", "--dataset-root", str(root), "--out", str(out)]
    assert runner.invoke(literature, args).exit_code == 0
    assert runner.invoke(literature, args).exit_code != 0
    assert runner.invoke(literature, args + ["--resume"]).exit_code == 0


def test_pubmed_client_retains_metadata():
    from tools.pubmed.client import PubMedClient

    record = PubMedClient()._parse_article(ET.fromstring(XML).find("PubmedArticle"))
    assert record is not None
    value = record.to_dict()
    assert value["keywords"] == ["author keyword"] and value["mesh_terms"] == [
        "Index term"
    ]
    assert value["language"] == ["eng"] and value["publication_date"] == "2024-Feb"


def test_online_success_resumes_without_repeating_and_preserves_existing(
    tmp_path, monkeypatch
):
    import httpx
    import metaagent.screening.metadata_completion as completion

    root = tmp_path / "release"
    profile = root / "profiles/P"
    profile.mkdir(parents=True)
    (profile / "raw_pool.jsonl").write_text(
        '{"pmid":"123","doi":"10.1234/right","record_id":"r","abstract":"Existing text"}\n'
    )
    calls = []

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, params):
            calls.append((url, params))
            return httpx.Response(200, content=XML, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "Client", Client)
    monkeypatch.setattr(completion.time, "sleep", lambda _: None)
    out = tmp_path / "derived"
    first = run_completion(root, out, online=True)
    assert first["requests_this_invocation"] == 1 and len(calls) == 1
    row = json.loads((out / "enriched/profiles/P/raw_pool.jsonl").read_text())
    assert row["abstract"] == "Existing text" and row["keywords"] == ["author keyword"]
    assert row["metadata_completion_sources"]["keywords"]["route"] == "online_pubmed"
    assert run_completion(root, out, online=True)["requests_this_invocation"] == 0
    assert len(calls) == 1


def test_changed_resume_input_fails_before_mutation(tmp_path):
    root = tmp_path / "release"
    profile = root / "profiles/P"
    profile.mkdir(parents=True)
    path = profile / "raw_pool.jsonl"
    path.write_text('{"record_id":"one"}\n')
    out = tmp_path / "derived"
    run_completion(root, out)
    previous = (out / "enriched/profiles/P/raw_pool.jsonl").read_bytes()
    path.write_text('{"record_id":"changed"}\n')
    with pytest.raises(ValueError, match="bytes changed"):
        run_completion(root, out)
    assert (out / "enriched/profiles/P/raw_pool.jsonl").read_bytes() == previous


def test_placeholder_title_preserved_with_authoritative_title_beside_it(tmp_path):
    ledger = MetadataLedger(tmp_path / "ledger.sqlite")
    row = {
        "record_id": "one",
        "pmid": "123",
        "doi": "10.1234/right",
        "title": "Smith et al.",
    }
    ledger.add(row, {"route": "local_bibliography"})
    ledger.add(
        list(parse_pubmed_xml(XML))[0],
        {"route": "local_pubmed_xml", "sha256": "fixture"},
    )
    result = ledger.enrich(row, {})
    assert (
        result["title"] == "Smith et al."
        and result["official_title"] == "Official complete title"
    )
    assert (
        result["metadata_completion_sources"]["official_title"]["sha256"] == "fixture"
    )
    ledger.db.close()


def test_europe_pmc_adapter_keeps_returned_metadata(monkeypatch):
    from tools.literature.sources import search

    data = {
        "hitCount": 1,
        "nextCursorMark": "end",
        "resultList": {
            "result": [
                {
                    "id": "123",
                    "source": "MED",
                    "title": "Title",
                    "keywordList": {"keyword": ["keyword"]},
                    "meshHeadingList": {"meshHeading": [{"descriptorName": "MeSH"}]},
                    "language": "eng",
                    "firstPublicationDate": "2024-02-01",
                    "pubTypeList": {"pubType": ["Journal Article"]},
                }
            ]
        },
    }
    monkeypatch.setattr("tools.literature.sources._get", lambda *args: data)
    row = search("europepmc", "query", 1)[0][0]
    assert row["keywords"] == ["keyword"] and row["mesh_terms"] == ["MeSH"]
    assert row["language"] == "eng" and row["publication_date"] == "2024-02-01"


def test_workspace_writer_lease_blocks_concurrent_resume(tmp_path):
    import fcntl

    root = tmp_path / "release"
    profile = root / "profiles/P"
    profile.mkdir(parents=True)
    (profile / "raw_pool.jsonl").write_text('{"record_id":"one"}\n')
    out = tmp_path / "derived"
    out.mkdir()
    with (out / ".completion.lock").open("a") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="already running"):
            run_completion(root, out)
    assert not (out / "metadata.sqlite3").exists()


def test_standalone_protocol_cli_question_and_aliases(tmp_path, monkeypatch):
    from metaagent.screening.cli import screening
    import metaagent.screening.engine as engine

    source = tmp_path / "input.jsonl"
    source.write_text(
        json.dumps(
            {
                "record_id": "r",
                "title": "T",
                "abstract": "source",
                "keywords": ["keyword"],
                "language": ["eng"],
            }
        )
        + "\n"
    )
    protocol = tmp_path / "protocol.json"
    protocol.write_text(
        json.dumps(
            {
                "version": "v1",
                "criteria": [{"id": "eligible", "description": "Full review criteria"}],
                "logic": "eligible",
            }
        )
    )
    captured = []
    monkeypatch.setattr(engine, "init_llm_model", lambda **kw: object())

    async def run(rows, question, llm, **kwargs):
        captured.append((rows, question, kwargs))
        return rows

    monkeypatch.setattr(engine, "screen_papers_batch_async", run)
    result = CliRunner().invoke(
        screening,
        [
            "protocol-run",
            "--input",
            str(source),
            "--protocol",
            str(protocol),
            "--out",
            str(tmp_path / "out.jsonl"),
            "--research-question",
            "Explicit user question",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured[0][1] == "Explicit user question"
    assert captured[0][0][0]["Keywords"] == ["keyword"]
    assert captured[0][2]["screening_config"]["review_protocol"]["logic"] == "eligible"


def _standalone_task(tmp_path, monkeypatch):
    import yaml

    monkeypatch.setattr("metaagent.config.load_runtime_env", lambda **kw: None)
    for module in ("QUERY", "SCREENING", "CODING", "SYNTHESIS"):
        monkeypatch.setenv(module + "_LLM_PROVIDER", "openai")
        monkeypatch.setenv(module + "_LLM_MODEL", "offline")
        monkeypatch.setenv(module + "_LLM_API_BASE", "http://127.0.0.1:9/v1")
        monkeypatch.setenv(module + "_LLM_API_KEY", "synthetic")
    task = tmp_path / "task.yaml"
    task.write_text(
        yaml.safe_dump(
            {
                "version": "1",
                "task_id": "fixture",
                "disease": "X",
                "topic": "serial_interval",
                "research_question": "Full review SI or IP",
                "review_protocol": {
                    "version": "v1",
                    "criteria": [
                        {"id": "outcome", "description": "SI or IP estimates"}
                    ],
                    "logic": "outcome",
                },
                "codebook": "not-needed-for-screening.yaml",
                "coding": {"backend": "llm"},
                "synthesis": {"backend": "deterministic"},
            }
        )
    )
    source = tmp_path / "bibliography.jsonl"
    source.write_text(
        '{"record_id":"doi:10.1234/test","doi":"10.1234/test","title":"Available source","abstract":"Available abstract"}\n'
    )
    return task, source


def test_canonical_screening_task_dryrun_no_output_write(tmp_path, monkeypatch):
    from metaagent.screening.cli import screening

    task, source = _standalone_task(tmp_path, monkeypatch)
    out = tmp_path / "screened"
    result = CliRunner().invoke(
        screening,
        [
            "task",
            "--task-config",
            str(task),
            "--input",
            str(source),
            "--output-dir",
            str(out),
            "--dry-run",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["stages"] == ["screening"] and payload["dry_run"] is True
    assert not out.exists()
    assert "synthetic" not in result.output


def test_canonical_screening_task_dispatches_same_runner(tmp_path, monkeypatch):
    from metaagent.screening.cli import screening

    task, source = _standalone_task(tmp_path, monkeypatch)
    captured = []

    def run(options):
        captured.append(options)
        return {
            "status": "complete",
            "stages": ["screening"],
            "profile": "fixture",
            "pool_kind": "raw_pool",
            "output_dir": str(options.output_dir),
        }

    monkeypatch.setattr("metaagent.workflow_runner.run_workflow", run)
    result = CliRunner().invoke(
        screening,
        [
            "task",
            "--task-config",
            str(task),
            "--input",
            str(source),
            "--input-mode",
            "raw_pool",
            "--output-dir",
            str(tmp_path / "screened"),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["status"] == "complete" and len(captured) == 1
    assert captured[0].start_at == captured[0].stop_after == "screening"
    assert captured[0].raw_input == source and captured[0].task_config == task
    assert captured[0].limit is None


def test_legacy_screening_doi_only_does_not_require_pubmed(tmp_path, monkeypatch):
    from metaagent.screening.cli import screening

    source = tmp_path / "doi.csv"
    source.write_text(
        "DOI,Title,Abstract\n10.1234/test,Available title,Available abstract\n"
    )
    calls = []
    monkeypatch.setattr(
        "metaagent.screening.cli._preflight_screening_llm", lambda **kw: None
    )
    monkeypatch.setattr(
        "metaagent.screening.cli._run_script",
        lambda script, argv: calls.append((script, argv)),
    )
    monkeypatch.setattr(
        "metaagent.screening.cli._enrich_input_metadata",
        lambda *a: pytest.fail("DOI-only row sent to PubMed completion"),
    )
    result = CliRunner().invoke(
        screening,
        [
            "run",
            "--input",
            str(source),
            "--research-question",
            "User question",
            "--fix-missing",
            "--no-interactive",
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls[0][0] == "screening_llm_batch"
    assert (
        source.read_text()
        == "DOI,Title,Abstract\n10.1234/test,Available title,Available abstract\n"
    )


def test_native_mesh_qualifier_containers_preserved_without_unknown_keys():
    from metaagent.screening.context import metadata_text

    native = {
        "meshHeadingList": {
            "meshHeading": [
                {
                    "descriptorName": "Monkeypox",
                    "qualifierName": ["epidemiology"],
                    "historical_label": "MUST_NOT_PASS",
                },
                {
                    "DescriptorName": "Transmission",
                    "qualifierNameList": [
                        {"QualifierName": "prevention and control", "majorTopicYN": "Y"}
                    ],
                },
            ]
        },
        "reference": {"qualifierName": "MUST_NOT_PASS_EITHER"},
    }
    assert (
        metadata_text(native)
        == "Monkeypox; epidemiology; Transmission; prevention and control"
    )


@pytest.mark.parametrize("batch_mode,stage", [
    ("multi", "title_abstract"), ("single", "title_abstract"), ("single", "title_only"),
])
def test_legacy_wire_preserves_complete_source_metadata_without_roster_labels(batch_mode, stage):
    """Exercise actual 5D requests, rather than the separate protocol path."""
    import copy
    import re
    import httpx

    received = []
    rows = [
        {
            "PMID": "123",
            "record_id": "sr:DO_NOT_SEND_SR:ref:DO_NOT_SEND_REF",
            "title": "Preserved short input title",
            "official_title": "Official complete source title",
            "abstract": "Original source abstract about observed outbreak cases.",
            "year": "2024",
            "publication_date": "2024-Feb-09",
            "Create Date": "2024-02-12",
            "authors": ["Ada Author", "Ben Author"],
            "journal": "Original Source Journal",
            "Citation": "Original Source Journal. 2024;2:10-15.",
            "language": ["eng", "fra"],
            "keywords": ["Author supplied keyword"],
            "publication_types": ["Journal Article"],
            "mesh_terms": {
                "meshHeadingList": {
                    "meshHeading": [{
                        "DescriptorName": "Native descriptor",
                        "qualifierNameList": [{"QualifierName": "Native qualifier"}],
                        "historical_label": "DO_NOT_SEND_NATIVE_LABEL",
                    }]
                }
            },
            "historical_label": "DO_NOT_SEND_LABEL",
            "ground_truth": {"include": "DO_NOT_SEND_TRUTH"},
            "coding_reference": {"point": "DO_NOT_SEND_VALUE"},
            "source_entry_ids": ["DO_NOT_SEND_SOURCE_ENTRY"],
        },
        {"PMID": "124", "title": "Other independent source", "abstract": "Second abstract."},
    ]
    original = copy.deepcopy(rows)

    def respond(request):
        body = json.loads(request.content)
        received.append(body)
        content = body["messages"][-1]["content"]
        ids = re.findall(r"^Paper ID: (.+)$", content, re.MULTILINE)
        decision = {
            name: {"score": 2, "justification": "Synthetic transport-only response."}
            for name in ("disease_relevance", "population_relevance", "location_relevance",
                         "original_evidence", "parameter_relevance")
        }
        decision["overall_justification"] = "Synthetic transport-only response."
        decision["tier"] = "P"
        answer = {"papers": [{"paper_id": i, "decision": decision} for i in ids]} if batch_mode == "multi" else decision
        return httpx.Response(200, json={
            "id": "synthetic", "object": "chat.completion", "created": 0,
            "model": "offline", "choices": [{"index": 0,
                "message": {"role": "assistant", "content": json.dumps(answer)},
                "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        })

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            llm = ChatOpenAI(model="offline", api_key="synthetic", base_url="http://offline.invalid/v1",
                             max_retries=0, http_async_client=client)
            return await screen_papers_batch_async(
                rows, "Explicit common research question", llm,
                batch_mode=batch_mode, screening_stage=stage, batch_size=2, batch_concurrency=1,
            )

    result = asyncio.run(run())
    assert len(received) == (1 if batch_mode == "multi" else 2) and len(result) == 2
    assert all(r.get("llm_suggest") != "error" for r in result)
    body = received[0]
    content = body["messages"][-1]["content"]
    assert "Research question: Explicit common research question" in content
    if batch_mode == "multi":
        first = content.split("--- BEGIN PAPER 123 ---", 1)[1].split("--- END PAPER 123 ---", 1)[0]
        second = content.split("--- BEGIN PAPER 124 ---", 1)[1].split("--- END PAPER 124 ---", 1)[0]
    else:
        texts = [request["messages"][-1]["content"] for request in received]
        first = next(text for text in texts if "Title: Preserved short input title" in text)
        second = next(text for text in texts if "Title: Other independent source" in text)
    for literal in (
        "Title: Preserved short input title", "Official title: Official complete source title",
        "Publication Year: 2024", "Publication Date: 2024-Feb-09", "Create Date: 2024-02-12",
        "Ada Author", "Ben Author", "Journal/Book: Original Source Journal",
        "Citation: Original Source Journal. 2024;2:10-15.", "Language: eng; fra",
        "Author supplied keyword", "Journal Article", "Native descriptor; Native qualifier",
        "Original source abstract about observed outbreak cases.",
    ):
        assert literal in first
        assert literal not in second
    assert "Official title: (Not available)" in second
    assert "Language: (Not available)" in second
    wire = json.dumps(received)
    for forbidden in ("DO_NOT_SEND", "ground_truth", "historical_label", "coding_reference", "source_entry_ids"):
        assert forbidden not in wire
    for key, value in original[0].items():
        assert result[0][key] == value
