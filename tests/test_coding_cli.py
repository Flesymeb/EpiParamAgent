"""CLI dispatch executes real parsing, stage orchestration and output contracts offline."""
import importlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
from types import SimpleNamespace

import click
from click.testing import CliRunner
import pytest
import yaml

from metaagent.coding.pipeline import extraction

CLI=importlib.import_module('metaagent.coding.cli')
ROOT=Path(__file__).resolve().parents[1]
SOURCE='The basic reproduction number R0 was 0.8.'


@pytest.fixture
def cli_case(tmp_path,monkeypatch):
    monkeypatch.setattr('metaagent.config.load_runtime_env',lambda **_:None)
    for key,value in {'CODING_LLM_PROVIDER':'openai','CODING_LLM_MODEL':'offline-model',
                      'CODING_LLM_API_BASE':'http://localhost:1/v1','CODING_LLM_API_KEY':'offline-transport-credential',
                      'CODING_LLM_EXTRA_BODY_JSON':'{"response_format":{"type":"json_object"}}'}.items():
        monkeypatch.setenv(key,value)
    source=tmp_path/'report.md';source.write_text(SOURCE)
    book=tmp_path/'codebook.yaml';book.write_text(yaml.safe_dump({'project':{'name':'reproduction_number','effect_type':'reproduction_number'},
        'fields':[{'name':'pmid','type':'str','required':True},{'name':'parameter_type','type':'str','required':True},
                  {'name':'point_estimate','type':'float'}]}))
    state={'backend':'llm','failure':False,'calls':[],'sources':[]}
    def fake_init(*_):
        assert json.loads(__import__('os').environ['CODING_LLM_EXTRA_BODY_JSON'])=={'response_format':{'type':'json_object'}}
        return object()
    monkeypatch.setattr(extraction,'init_llm',fake_init)
    def invoke(*,messages,stage_name,**_):
        state['calls'].append(stage_name)
        row={'parameter_type':'R0','point_estimate':.8,'_field_evidence':{'parameter_type':SOURCE,'point_estimate':SOURCE}}
        if stage_name=='stage_a' and state['backend']=='langextract':
            return json.dumps({'extractions':[
                {'coding_record':SOURCE,'coding_record_attributes':{'_record_id':'r','parameter_type':'R0','point_estimate':'0.8'}},
                {'field_evidence':SOURCE,'field_evidence_attributes':{'_record_id':'r','fields':['parameter_type','point_estimate']}}]})
        body=messages[-1]['content'];payload=json.loads(body.split('\nCandidates (guidance only):\n')[0])
        text='\n'.join(s['text'] for s in payload['source_segments']);state['sources'].append(text)
        if stage_name=='stage_a':
            assert 'return exactly {"records": [...]}' in messages[0]['content']
            assert 'Return a JSON array' not in messages[0]['content']
            return json.dumps({'records':[row] if SOURCE in text else []})
        candidates=json.loads(body.split('\nCandidates (guidance only):\n')[1]);ds=[{'candidate_id':r['candidate_id'],'action':'keep'} for r in candidates]
        rows=[{**row,'candidate_id':candidates[0]['candidate_id'] if candidates else None}] if SOURCE in text else []
        if state['failure'] and rows:rows[0].pop('candidate_id')
        return json.dumps({'records':rows,'dispositions':ds})
    monkeypatch.setattr(extraction,'_invoke_model_content',invoke)
    # Exercise the actual argparse script under Click dispatch. Only process
    # creation is replaced so external transports can remain offline fixtures.
    def run_script(path,argv,env_overrides=None):
        with monkeypatch.context() as context:
            context.setattr(sys,'argv',[str(path),*argv])
            for key,value in (env_overrides or {}).items():context.setenv(key,value)
            try:runpy.run_path(str(path),run_name='__main__')
            except SystemExit as exc:
                if exc.code:raise click.ClickException(f'Script exited with code {exc.code}') from exc
    monkeypatch.setattr(CLI,'_run_script',run_script)
    return tmp_path,source,book,state


def command(source,book,out,*extra):
    return ['extract','--input',str(source),'--codebook',str(book),'--out',str(out),*extra]


def test_default_cli_runs_actual_langextract_inside_A_then_B(cli_case):
    pytest.importorskip('langextract')
    root,source,book,state=cli_case;state['backend']='langextract'
    result=CliRunner().invoke(CLI.coding,command(source,book,root/'full'))
    assert result.exit_code==0,result.output
    assert state['calls']==['stage_a','stage_b']
    owner=json.loads((root/'full/coding_output_owner.json').read_text())
    assert owner['backend']=='langextract' and owner['ablation']=='full'
    assert json.loads((root/'full/coding_estimates.jsonl').read_text())['point_estimate']==.8


def test_explicit_llm_object_mode_and_ablations_cannot_share_output(cli_case):
    root,source,book,state=cli_case;runner=CliRunner();out=root/'full'
    result=runner.invoke(CLI.coding,command(source,book,out,'--extraction-backend','llm'))
    assert result.exit_code==0,result.output
    assert state['calls']==['stage_a','stage_b']
    before=(out/'coding_estimates.jsonl').read_bytes();count=len(state['calls'])
    reused=runner.invoke(CLI.coding,command(source,book,out,'--extraction-backend','llm','--ablation','without_b'))
    assert reused.exit_code!=0 and 'fresh --out' in reused.output
    assert len(state['calls'])==count and (out/'coding_estimates.jsonl').read_bytes()==before
    separate=runner.invoke(CLI.coding,command(source,book,root/'without_b','--extraction-backend','llm','--ablation','without_b'))
    assert separate.exit_code==0,separate.output
    assert state['calls']==['stage_a','stage_b','stage_a']
    assert json.loads((root/'without_b/coding_output_owner.json').read_text())['ablation']=='without_b'


def test_cli_failed_B_has_nonzero_exit_partial_diagnostics_and_no_success(cli_case):
    root,source,book,state=cli_case;state['failure']=True;out=root/'failed'
    result=CliRunner().invoke(CLI.coding,command(source,book,out,'--extraction-backend','llm'))
    assert result.exit_code!=0
    assert 'Coding and extraction completed' not in result.output
    assert state['calls']==['stage_a','stage_b','stage_b']
    assert (out/'coding_estimates.jsonl').read_text()==''
    coverage=json.loads(next((out/'documents').glob('*/coverage.json')).read_text())
    assert coverage['status']=='failed'
    executed=json.loads(next(out.glob('run_manifest*.json')).read_text())
    assert executed['extra']['error_count']==1


def test_cli_without_A_never_requires_langextract(cli_case,monkeypatch):
    root,source,book,state=cli_case
    monkeypatch.setattr('metaagent.coding.pipeline.langextract_backend.require_langextract',lambda:pytest.fail('A was removed'))
    result=CliRunner().invoke(CLI.coding,command(source,book,root/'noA','--ablation','without_a'))
    assert result.exit_code==0,result.output
    assert state['calls']==['stage_b']


def test_cli_relative_PDF_and_supplement_bundle_uses_MinerU_and_provenance(cli_case,monkeypatch):
    import fitz
    root,_,book,state=cli_case;pool=root/'pool';monkeypatch.setenv('METAAGENT_PAPER_POOL',str(pool))
    for name,text in [('main.pdf',SOURCE),('supplement.pdf','Supplement: no additional parameter estimates.')]:
        with fitz.open() as doc:
            doc.new_page().insert_text((72,72),text);doc.save(root/name)
    manifest=root/'bundle.jsonl';manifest.write_text(json.dumps({'record_id':'doi:source-report','path':'main.pdf',
        'supplements':[{'path':'supplement.pdf','source_id':'S1'}]})+'\n');parses=[]
    def mineru(path,**_):
        with fitz.open(path) as doc:text='\n'.join(page.get_text() for page in doc)
        parses.append(Path(path).read_bytes());return SimpleNamespace(markdown=text)
    monkeypatch.setattr('tools.mineru.pdf_reader.extract_pdf_markdown_mineru',mineru)
    args=['extract','--document-manifest',str(manifest),'--codebook',str(book),'--out',str(root/'bundle_out'),
          '--extraction-backend','llm','--stage-a-empty-retries','0','--extraction-scope','Only original reported R0.']
    result=CliRunner().invoke(CLI.coding,args)
    assert result.exit_code==0,result.output
    assert len(parses)==2 and all('%PDF' not in text for text in state['sources'])
    sources=[json.loads(s) for s in (root/'bundle_out/source_manifest.jsonl').read_text().splitlines()]
    assert {s['source_id'] for s in sources}=={'main','S1'}
    assert all(s['parser_route']=='mineru_parsed' and s['source_sha256'] and s['parser_fingerprint'] for s in sources)
    assert state['calls'].count('stage_a')==2 and state['calls'].count('stage_b')==2
    state['calls'].clear()
    args[args.index(str(root/'bundle_out'))]=str(root/'cached_out')
    cached=CliRunner().invoke(CLI.coding,args)
    assert cached.exit_code==0,cached.output
    assert len(parses)==2
    sources=[json.loads(s) for s in (root/'cached_out/source_manifest.jsonl').read_text().splitlines()]
    assert all(s['parser_route']=='mineru_content_cache' for s in sources)


def test_script_invalid_input_combination_fails_in_actual_subprocess(tmp_path):
    result=subprocess.run([sys.executable,str(ROOT/'tools/scripts/extract_coding.py'),'--input','x','--document-manifest','y',
                           '--out',str(tmp_path/'out'),'--codebook','missing'],capture_output=True,text=True)
    assert result.returncode==2 and 'not allowed with argument' in result.stderr
    assert not (tmp_path/'out').exists()


def test_missing_requested_PMID_does_not_report_partial_subset_complete(cli_case,monkeypatch):
    root,_,book,state=cli_case;pmids=root/'pmids.txt';pmids.write_text('12345678\n87654321\n')
    monkeypatch.setenv('METAAGENT_PAPER_POOL',str(root/'pool'))
    directory=root/'pool/pdfs';directory.mkdir(parents=True);(directory/'PMID_12345678.pdf').write_bytes(b'%PDF offline cached source')
    monkeypatch.setattr('requests.get',lambda *a,**kw: (_ for _ in ()).throw(ConnectionError('offline fixture')))
    result=CliRunner().invoke(CLI.coding,command(pmids,book,root/'missing','--extraction-backend','llm'))
    assert result.exit_code!=0 and 'Full text unavailable' in result.output
    assert not state['calls']


@pytest.mark.parametrize('bad_field',[{'name':'valid','type':'obviously_wrong'}, {'name':'invalid-name','type':'str'},
                                     {'name':'valid','type':'float','range':[10,1]}])
def test_cli_rejects_invalid_codebook_without_model_calls(cli_case,bad_field):
    root,source,book,state=cli_case;book.write_text(yaml.safe_dump({'fields':[bad_field]}))
    result=CliRunner().invoke(CLI.coding,command(source,book,root/'bad','--extraction-backend','llm'))
    assert result.exit_code!=0 and not state['calls']
    assert not (root/'bad').exists()


def test_input_directory_keeps_markdown_only_reports_and_no_DOI_fake_PMID(tmp_path):
    (tmp_path/'paper.PDF').write_bytes(b'pdf');(tmp_path/'paper.md').write_text('same report text')
    (tmp_path/'other.md').write_text('different report')
    assert {p.name for p in extraction._iter_inputs(tmp_path)}=={'paper.PDF','other.md'}
    from metaagent.coding.shared.io import infer_pmid_from_path
    assert infer_pmid_from_path(tmp_path/'DOI_10.1234_case20221103.md') is None
    assert infer_pmid_from_path(tmp_path/'PMID_12345678.pdf')=='12345678'


def test_identity_only_cli_downloads_validates_parses_and_runs_full_AB(cli_case,monkeypatch):
    import fitz
    from types import SimpleNamespace
    root,_,book,state=cli_case
    monkeypatch.setenv('METAAGENT_PAPER_POOL',str(root/'pool'))
    monkeypatch.delenv('UNPAYWALL_EMAIL',raising=False);monkeypatch.delenv('NCBI_EMAIL',raising=False)
    pdf=root/'official.pdf'
    with fitz.open() as doc:
        doc.new_page().insert_text((35,35),'https://doi.org/10.1234/cli.acquisition\n'+SOURCE)
        doc.save(pdf)
    content=pdf.read_bytes();downloads=[];parses=[]
    class Response:
        status_code=200
        def __init__(self,url):self.url=url
        def raise_for_status(self):pass
        def json(self):return {'resultList':{'result':[]}}
        def iter_content(self,size):yield content
        def __enter__(self):return self
        def __exit__(self,*_):pass
    def get(url,**kw):downloads.append(url);return Response(url)
    monkeypatch.setattr('requests.get',get)
    def mineru(path,**_):
        with fitz.open(path) as doc:text='\n'.join(page.get_text() for page in doc)
        parses.append(str(path));return SimpleNamespace(markdown=text)
    monkeypatch.setattr('tools.mineru.pdf_reader.extract_pdf_markdown_mineru',mineru)
    manifest=root/'identity.jsonl';manifest.write_text(json.dumps({'record_id':'doi:10.1234/cli.acquisition','doi':'10.1234/cli.acquisition','fulltext_url':'https://official.example/article.pdf'})+'\n')
    args=['extract','--document-manifest',str(manifest),'--codebook',str(book),'--out',str(root/'automatic'), '--extraction-backend','llm']
    first=CliRunner().invoke(CLI.coding,args)
    assert first.exit_code==0,first.output
    assert state['calls']==['stage_a','stage_b'] and len(parses)==1
    source=json.loads((root/'automatic/source_manifest.jsonl').read_text())
    assert source['pdf_sha256']==__import__('hashlib').sha256(content).hexdigest()
    assert source['source_sha256']==source['pdf_sha256'] and source['parser_route']=='mineru_parsed'
    assert Path(source['pdf_path']).is_file()
    acquisitions=[json.loads(line) for line in (root/'automatic/acquisition/acquisition_manifest.jsonl').read_text().splitlines()]
    assert acquisitions[0]['pdf_status']=='verified' and acquisitions[0]['record_status']=='fulltext_ready'
    state['calls'].clear();monkeypatch.setattr('requests.get',lambda *a,**kw:pytest.fail('verified identity cache unexpectedly downloaded'))
    args[args.index(str(root/'automatic'))]=str(root/'automatic-cached')
    second=CliRunner().invoke(CLI.coding,args)
    assert second.exit_code==0,second.output
    assert state['calls']==['stage_a','stage_b'] and len(parses)==1
    cached=json.loads((root/'automatic-cached/source_manifest.jsonl').read_text())
    assert cached['parser_route']=='mineru_content_cache'


def test_identity_only_failure_keeps_each_source_receipt_and_never_calls_AB(cli_case,monkeypatch):
    root,_,book,state=cli_case
    monkeypatch.setenv('METAAGENT_PAPER_POOL',str(root/'pool'))
    monkeypatch.setattr('requests.get',lambda *a,**kw: (_ for _ in ()).throw(ConnectionError('offline fixture')))
    manifest=root/'identities.jsonl';manifest.write_text(''.join(json.dumps({'record_id':'doi:'+doi,'doi':doi})+'\n' for doi in ('10.1234/one','10.1234/two')))
    result=CliRunner().invoke(CLI.coding,['extract','--document-manifest',str(manifest),'--codebook',str(book),'--out',str(root/'failed-acquisition'),'--extraction-backend','llm'])
    assert result.exit_code!=0 and not state['calls']
    outcomes=[json.loads(line) for line in (root/'failed-acquisition/acquisition/acquisition_manifest.jsonl').read_text().splitlines()]
    assert len(outcomes)==2 and all(row['record_status']=='fulltext_unavailable' for row in outcomes)


def test_fetch_only_identity_manifest_never_initializes_llm(cli_case,monkeypatch):
    import fitz
    from metaagent.acquisition import register_pdf
    root,_,book,state=cli_case;monkeypatch.setenv('METAAGENT_PAPER_POOL',str(root/'pool'))
    source=root/'publication.pdf'
    with fitz.open() as doc:
        doc.new_page().insert_text((30,30),'https://doi.org/10.1234/fetch.only\n'+SOURCE);doc.save(source)
    row={'record_id':'doi:10.1234/fetch.only','doi':'10.1234/fetch.only'}
    register_pdf(row,source)
    manifest=root/'fetch.jsonl';manifest.write_text(json.dumps(row)+'\n')
    monkeypatch.setattr('requests.get',lambda *a,**kw:pytest.fail('registered identity must not download'))
    monkeypatch.setattr(extraction,'init_llm',lambda *a,**kw:pytest.fail('fetch-only must not initialize LLM'))
    monkeypatch.setattr(CLI,'_preflight_coding_llm',lambda:pytest.fail('fetch-only must not require an LLM credential'))
    def mineru(path,**_):
        with fitz.open(path) as doc:text='\n'.join(page.get_text() for page in doc)
        return SimpleNamespace(markdown=text)
    monkeypatch.setattr('tools.mineru.pdf_reader.extract_pdf_markdown_mineru',mineru)
    result=CliRunner().invoke(CLI.coding,['extract','--document-manifest',str(manifest),'--stage','fetch','--codebook',str(book),'--out',str(root/'fetch-out')])
    assert result.exit_code==0,result.output
    assert not state['calls']
    status=json.loads((root/'fetch-out/acquisition/acquisition_manifest.jsonl').read_text())
    assert status['pdf_status']=='verified' and status['record_status']=='fulltext_ready'


def test_pmid_iterator_never_consumes_preserved_wrong_alias(tmp_path,monkeypatch):
    import hashlib
    pool=tmp_path/'pool';monkeypatch.setenv('METAAGENT_PAPER_POOL',str(pool))
    wrong=pool/'pdfs/PMID_12345678.pdf';wrong.parent.mkdir(parents=True);wrong.write_bytes(b'wrong original bytes')
    canonical=pool/'pdfs/by_sha256/correct.pdf';canonical.parent.mkdir();canonical.write_bytes(b'correct validated PDF bytes')
    def resolve(row,directory,**kw):
        Path(directory).mkdir(parents=True,exist_ok=True)
        return {'record_status':'pdf_ready','pdf_path':str(canonical),'pdf_sha256':hashlib.sha256(canonical.read_bytes()).hexdigest()}
    monkeypatch.setattr('metaagent.acquisition.resolve_document',resolve)
    path=tmp_path/'pmids.txt';path.write_text('12345678\n')
    inputs=list(extraction._iter_inputs(path))
    assert len(inputs)==1 and inputs[0]!=wrong and inputs[0].name=='PMID_12345678.pdf'
    assert inputs[0].read_bytes()==canonical.read_bytes() and wrong.read_bytes()==b'wrong original bytes'
    from metaagent.coding.shared.io import infer_pmid_from_path
    assert infer_pmid_from_path(inputs[0])=='12345678'
