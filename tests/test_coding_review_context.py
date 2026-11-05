"""Actual standalone CLI/LangExtract/LLM prompt delivery; offline transports only."""

import importlib, json
from click.testing import CliRunner
import pytest, yaml
from test_coding_cli import cli_case, command
from test_workflow_task import task
from metaagent.coding.pipeline import extraction
from metaagent.coding.prompt_context import normalize_review_context

CONTEXT = {
    "research_question": "Which original R0 estimates address disease X?",
    "review_protocol": {
        "version": "1",
        "criteria": [
            {"id": "original", "description": "Original estimates for disease X"}
        ],
        "logic": "original",
    },
}


@pytest.mark.parametrize("backend", ["llm", "langextract"])
def test_real_CLI_A_backend_and_B_receive_same_question_protocol_and_scope(
    cli_case, monkeypatch, backend
):
    if backend == "langextract":
        pytest.importorskip("langextract")
    root, source, book, state = cli_case
    state["backend"] = backend
    context = root / "context.yaml"
    context.write_text(yaml.safe_dump(CONTEXT))
    seen = []
    original = extraction._invoke_model_content

    def wire(**kwargs):
        seen.append(
            (kwargs["stage_name"], json.dumps(kwargs["messages"], ensure_ascii=False))
        )
        return original(**kwargs)

    monkeypatch.setattr(extraction, "_invoke_model_content", wire)
    CLI = importlib.import_module("metaagent.coding.cli")
    result = CliRunner().invoke(
        CLI.coding,
        command(
            source,
            book,
            root / "review",
            "--extraction-backend",
            backend,
            "--task-context",
            str(context),
            "--extraction-scope",
            "Retain all original R0 populations and methods.",
        ),
    )
    assert result.exit_code == 0, result.output
    assert [s for s, _ in seen] == ["stage_a", "stage_b"]
    (root / "captured_model_requests.json").write_text(
        json.dumps(seen, ensure_ascii=False, indent=2)
    )
    for stage, prompt in seen:
        assert (
            CONTEXT["research_question"] in prompt
            and CONTEXT["review_protocol"]["criteria"][0]["description"] in prompt
        )
        assert "Retain all original R0 populations and methods." in prompt
        assert "reference_answer" not in prompt and "coding_gold" not in prompt
    manifest = json.loads(
        next((root / "review").glob("run_manifest*.json")).read_text()
    )
    assert manifest["params"]["review_context"] == CONTEXT


def test_standalone_question_only_is_sufficient_and_invalid_protocol_fails_before_model(
    cli_case,
):
    root, source, book, state = cli_case
    CLI = importlib.import_module("metaagent.coding.cli")
    result = CliRunner().invoke(
        CLI.coding,
        command(
            source,
            book,
            root / "question",
            "--extraction-backend",
            "llm",
            "--research-question",
            CONTEXT["research_question"],
        ),
    )
    assert result.exit_code == 0, result.output
    before = list(state["calls"])
    bad = root / "bad.yaml"
    bad.write_text("review_protocol:\n  criteria: []\n  logic: typo\n")
    result = CliRunner().invoke(
        CLI.coding, command(source, book, root / "bad", "--task-context", str(bad))
    )
    assert (
        result.exit_code != 0
        and state["calls"] == before
        and not (root / "bad").exists()
    )


def test_context_limits_and_unknown_top_level_keys_are_rejected():
    assert normalize_review_context(None) is None
    for value in (
        {"coding_gold": 4.5},
        {"research_question": "x" * 70000},
        {"review_protocol": {"criteria": [], "logic": "unknown"}},
    ):
        with pytest.raises(ValueError):
            normalize_review_context(value)


def test_workflow_normalization_preserves_bibliographic_lists_not_labels():
    from metaagent.workflow_runner import normalize_records

    row = normalize_records(
        [
            {
                "PMID": "123",
                "Title": "Study title",
                "official_title": "Official complete identity-bound title",
                "Language": ["eng", "fre"],
                "Publication Types": ["Journal Article"],
                "MeSH": [{"term": "Epidemiology"}],
                "Publication Date": "2021-04-02",
                "Publication Year": 2021,
                "Journal/Book": "Example journal",
                "Authors": ["A", "B"],
                "gold_label": "include",
                "reference_answer": 991122,
                "report_version_id": "v1",
            }
        ]
    )[0]
    assert row["language"] == ["eng", "fre"] and row["pub_types"] == ["Journal Article"]
    assert row["mesh_terms"] == [{"term": "Epidemiology"}] and row["authors"] == [
        "A",
        "B",
    ]
    assert (
        row["publication_date"] == "2021-04-02"
        and row["year"] == "2021"
        and row["journal"] == "Example journal"
    )
    assert (
        row["report_version_id"] == "v1"
        and "gold_label" not in row
        and "reference_answer" not in row
    )


def test_coding_fingerprint_binds_question_protocol_scope_not_screening_model(
    task, monkeypatch
):
    from metaagent.workflow_runner import plan_workflow, _stage_config_hash
    from test_workflow_task import options

    data = yaml.safe_load(task.read_text())
    first = plan_workflow(options(task))
    baseline = _stage_config_hash(first, "coding")
    data["research_question"] = "A changed research question?"
    task.write_text(yaml.safe_dump(data))
    second = plan_workflow(options(task))
    assert _stage_config_hash(second, "coding") != baseline
    data["review_protocol"]["criteria"][0]["description"] = (
        "Changed criterion preserving logic"
    )
    task.write_text(yaml.safe_dump(data))
    third = plan_workflow(options(task))
    assert _stage_config_hash(third, "coding") != _stage_config_hash(second, "coding")
    data["coding"]["extraction_scope"] = "Only original estimates; retain all strata."
    task.write_text(yaml.safe_dump(data))
    fourth = plan_workflow(options(task))
    assert _stage_config_hash(fourth, "coding") != _stage_config_hash(third, "coding")
    data["llm"] = {"screening": {"model": "unrelated-screening-model"}}
    task.write_text(yaml.safe_dump(data))
    assert _stage_config_hash(
        plan_workflow(options(task)), "coding"
    ) == _stage_config_hash(fourth, "coding")
    assert not options(task).output_dir.exists()


@pytest.mark.parametrize('backend',['llm','langextract'])
def test_article_boundary_hint_reaches_actual_A_and_B_requests(cli_case,monkeypatch,backend):
    if backend=='langextract':pytest.importorskip('langextract')
    import fitz,hashlib
    root,source,book,state=cli_case;state['backend']=backend
    pdf=root/'compound.pdf';doc=fitz.open();doc.new_page().insert_text((30,30),source.read_text());doc.save(pdf);doc.close()
    hint={'page':1,'title_text':'Requested original article','title_bbox':[40,220,260,280],'preceding_material_in_title_column':True,'scope_instruction':'The requested article begins at this title; exclude the neighboring report.'}
    def resolve(row,directory,**kwargs):
        return {**row,'record_status':'fulltext_ready','fulltext_path':str(source),'pdf_path':str(pdf),'pdf_sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),'source_sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),'parser_route':'mineru_content_cache','parser_fingerprint':'offline-test','article_boundary_hint':hint}
    monkeypatch.setattr('metaagent.acquisition.resolve_document',resolve)
    bundle=root/'bundle.jsonl';bundle.write_text(json.dumps({'record_id':'study:scope','doi':'10.1234/target','path':str(pdf)})+'\n')
    seen=[];original=extraction._invoke_model_content
    def invoke(**kwargs):seen.append((kwargs['stage_name'],json.dumps(kwargs['messages'])));return original(**kwargs)
    monkeypatch.setattr(extraction,'_invoke_model_content',invoke)
    CLI=importlib.import_module('metaagent.coding.cli')
    result=CliRunner().invoke(CLI.coding,['extract','--document-manifest',str(bundle),'--codebook',str(book),'--out',str(root/'scope-run'),'--extraction-backend',backend])
    assert result.exit_code==0,result.output
    assert [stage for stage,_ in seen]==['stage_a','stage_b']
    assert all('article_scope_instruction' in prompt and hint['scope_instruction'] in prompt for _,prompt in seen)
