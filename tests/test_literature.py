"""Tests for multi-source retrieval and OA PDF provenance."""
import json

from click.testing import CliRunner

from metaagent.workflow_runner import read_records
from tools.literature.cli import literature, merge
from tools.literature.sources import abstract_openalex, search


def test_merge_doi_and_reject_conflicting_pmid():
    rows = merge([
        {'source':'pubmed','source_id':'1','pmid':'1','doi':'10.1000/ABC','title':'Title'},
        {'source':'openalex','source_id':'2','doi':'https://doi.org/10.1000/abc','abstract':'Abstract'},
        {'source':'crossref','source_id':'3','pmid':'2','doi':'10.1000/abc'},
    ])
    assert len(rows) == 2
    assert rows[0]['abstract'] == 'Abstract'
    assert rows[0]['sources'] == ['pubmed','openalex']
    assert rows[1]['pmid'] == '2'


def test_source_preprint_query_and_metadata(monkeypatch):
    calls=[]
    def get(url, params):
        calls.append(params)
        return {'hitCount':1,'resultList':{'result':[{'id':'PPR1','source':'PPR','doi':'10.1/ABC','title':'<i>Mpox</i>','bookOrReportDetails':{'publisher':'medRxiv'}}]},'nextCursorMark':'end'}
    monkeypatch.setattr('tools.literature.sources._get',get)
    rows,total,actual=search('medrxiv','mpox',5)
    assert total == 1 and 'PUBLISHER:medRxiv' in actual
    assert rows[0]['title'] == 'Mpox' and rows[0]['pub_types'] == 'preprint'
    assert calls[0]['resultType'] == 'core'
    assert abstract_openalex({'second':[1], 'first':[0]}) == 'first second'


def test_search_partial_failures_and_workflow_import(monkeypatch, tmp_path):
    def fake(source, query, limit):
        if source == 'openalex': raise ConnectionError('secret should not be exposed')
        return ([{'source_id':'1','pmid':'123','title':'A'}], 2, query)
    monkeypatch.setattr('tools.literature.cli.search',fake)
    out=tmp_path/'out'
    result=CliRunner().invoke(literature,['search','--source','pubmed','--source','openalex','--query','x','--out',str(out)])
    assert result.exit_code == 1
    manifest=json.loads((out/'manifest.json').read_text())
    assert manifest['source_results'][0]['complete'] is False
    assert manifest['source_results'][1]['status'] == 'failed'
    assert 'secret should not be exposed' not in result.output
    records=read_records(out/'records.jsonl')
    assert records[0]['PMID']=='123' and records[0]['source_records'][0]['source']=='pubmed'


def test_pdf_download_provenance(monkeypatch,tmp_path):
    monkeypatch.setattr('tools.literature.cli.unpaywall',lambda doi,email:{'oa_locations':[{'url_for_pdf':'https://example.org/paper.pdf','version':'publishedVersion','license':'cc-by'}]})
    class Response:
        url='https://example.org/paper.pdf'
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def raise_for_status(self): pass
        def iter_content(self, size): yield b'%PDF-1.4\nexample'
    monkeypatch.setattr('tools.literature.cli.requests.get',lambda *a,**kw:Response())
    path=tmp_path/'paper.pdf'
    result=CliRunner().invoke(literature,['pdf','--doi','10.1/example','--out',str(path)])
    assert result.exit_code==0, result.output
    info=json.loads(path.with_suffix('.pdf.json').read_text())
    assert info['version']=='publishedVersion' and len(info['sha256'])==64
    assert path.read_bytes().startswith(b'%PDF-')
