"""Cache identity and full-text parsing regression tests."""
from pathlib import Path
from types import SimpleNamespace

from metaagent.workflow_runner import _fetch_pmc
from tools.mineru.cache import find_cached, parse_pdf


def test_pdf_cache_is_bound_to_content_and_shared(monkeypatch, tmp_path):
    monkeypatch.setenv('METAAGENT_PAPER_POOL',str(tmp_path/'pool'))
    calls=[]
    def parse(path, **kwargs):
        calls.append(Path(path).read_bytes())
        return SimpleNamespace(markdown='Parsed '+str(len(calls)))
    monkeypatch.setattr('tools.mineru.pdf_reader.extract_pdf_markdown_mineru',parse)
    pdf=tmp_path/'a.pdf';pdf.write_bytes(b'%PDF-1.4\nfirst')
    first=parse_pdf(pdf,'123'); second=parse_pdf(pdf,'123')
    assert first.route=='mineru_parsed' and second.route=='mineru_content_cache' and len(calls)==1
    indexed=find_cached('123');assert indexed.route=='mineru_pmid_cache' and indexed.text=='Parsed 1'
    pdf.write_bytes(b'%PDF-1.4\nchanged')
    third=parse_pdf(pdf,'123');assert third.route=='mineru_parsed' and len(calls)==2
    third.path.write_text('corrupt')
    assert find_cached('123',pdf) is None


def test_legacy_cache_is_reused_and_marked(monkeypatch,tmp_path):
    monkeypatch.delenv('METAAGENT_PAPER_POOL',raising=False)
    monkeypatch.setattr('tools.mineru.cache.get_project_root',lambda:tmp_path)
    root=tmp_path/'paper_pool'
    directory=root/'markdown/PMID_321';directory.mkdir(parents=True)
    (directory/'full.md').write_text('Old parsed text')
    before=list(root.rglob('*'))
    item=find_cached('321')
    assert item and item.route=='legacy_pmid_cache_unverified'
    assert list(root.rglob('*'))==before
    pdf=tmp_path/'other.pdf';pdf.write_bytes(b'%PDF-different')
    assert find_cached('321',pdf) is None


def test_workflow_does_not_authorize_legacy_markdown_without_verified_pdf(monkeypatch,tmp_path):
    monkeypatch.setenv('METAAGENT_PAPER_POOL',str(tmp_path/'pool'))
    directory=tmp_path/'pool/markdown/PMID_123';directory.mkdir(parents=True)
    (directory/'full.md').write_text('Cached paper text')
    import requests
    monkeypatch.setattr(requests,'get',lambda *a,**k: (_ for _ in ()).throw(AssertionError('network requested')))
    out=tmp_path/'out';out.mkdir()
    result=_fetch_pmc({'record_id':'pmid:123','pmid':'123'},out)
    assert result['record_status']=='fulltext_unavailable' and result['fulltext_path'] is None
    assert result['pdf_status']=='unavailable'
    assert (directory/'full.md').read_text()=='Cached paper text'
    assert list(out.glob('*.acquisition.json'))


def test_workflow_pdf_calls_mineru_then_reuses(monkeypatch,tmp_path):
    monkeypatch.setenv('METAAGENT_PAPER_POOL',str(tmp_path/'pool'))
    calls=[]
    def parse(path, **kwargs):
        calls.append(path);return SimpleNamespace(markdown='Full PDF text')
    monkeypatch.setattr('tools.mineru.pdf_reader.extract_pdf_markdown_mineru',parse)
    import fitz
    from metaagent.acquisition import register_pdf
    pdf=tmp_path/'paper.pdf'
    with fitz.open() as doc:
        page=doc.new_page();page.insert_text((30,30),'Original primary report\nhttps://doi.org/10.1234/true.source');doc.save(pdf)
    row={'record_id':'pmid:123','pmid':'123','doi':'10.1234/true.source'}
    registered=register_pdf(row,pdf)
    assert registered['verification']['doi_match'] is True
    import requests
    monkeypatch.setattr(requests,'get',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('Verified registry must not need a service call')))
    first=tmp_path/'one';first.mkdir();second=tmp_path/'two';second.mkdir()
    assert _fetch_pmc(row,first)['parser_route']=='mineru_parsed'
    assert _fetch_pmc(row,second)['parser_route']=='mineru_content_cache'
    assert len(calls)==1


def test_pmc_xml_alone_is_not_a_verified_pdf(monkeypatch,tmp_path):
    monkeypatch.setattr('metaagent.pmc_cloud.discover_pmc_pdf',lambda *a,**kw:{'status':'unavailable','attempts':[]})
    monkeypatch.setattr('metaagent.pmc_cloud.resolve_pmcid',lambda **kw:{'status':'unavailable','attempts':[]})
    monkeypatch.setenv('METAAGENT_PAPER_POOL',str(tmp_path/'pool'))
    monkeypatch.delenv('UNPAYWALL_EMAIL',raising=False);monkeypatch.delenv('NCBI_EMAIL',raising=False)
    import requests
    class Response:
        status_code=200
        content=b'<article><body><p>PMC text</p></body></article>'
        headers={'Content-Type':'application/xml'}
        url='https://europepmc.org/articles/PMC123?pdf=render'
        def raise_for_status(self): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def iter_content(self,chunk_size): yield self.content
    monkeypatch.setattr(requests,'get',lambda *a,**k:Response())
    out=tmp_path/'out';out.mkdir()
    row=_fetch_pmc({'record_id':'x','pmcid':'PMC123'},out)
    assert row['record_status']=='fulltext_unavailable' and row['fulltext_path'] is None
    assert row['pdf_status']=='unavailable' and 'PDF' in row['failure_reason']
    assert list(out.glob('*.acquisition.json'))


def test_parser_version_options_and_assets_invalidate_cache(monkeypatch,tmp_path):
    import json
    monkeypatch.setenv('METAAGENT_PAPER_POOL',str(tmp_path/'pool'))
    calls=[]
    def parse(path,**kwargs):
        calls.append(kwargs)
        assets=kwargs['output_dir'];assets.mkdir()
        (assets/'result.zip').write_bytes(b'result-archive')
        (assets/'content_list.json').write_text('[{"page_idx":0,"type":"table"}]')
        return SimpleNamespace(markdown='Versioned text')
    monkeypatch.setattr('tools.mineru.pdf_reader.extract_pdf_markdown_mineru',parse)
    pdf=tmp_path/'source.pdf';pdf.write_bytes(b'%PDF-content')
    first=parse_pdf(pdf,'123',cache_policy='strict',model_version='vlm-v1')
    assert first.parser_fingerprint and first.assets_manifest
    assert parse_pdf(pdf,'123',cache_policy='strict',model_version='vlm-v1').route=='mineru_content_cache'
    second=parse_pdf(pdf,'123',cache_policy='strict',model_version='vlm-v2')
    assert len(calls)==2 and second.path!=first.path
    third=parse_pdf(pdf,'123',cache_policy='strict',model_version='vlm-v2',params={'enable_table':False})
    assert len(calls)==3 and third.path!=second.path
    metadata=json.loads(third.assets_manifest.read_text())
    assert 'assets/result.zip' in metadata['asset_hashes']
    assert metadata['asset_status']=='full_result_preserved'
    (third.path.parent/'assets/content_list.json').write_text('corrupt')
    assert find_cached('123',pdf,cache_policy='strict',model_version='vlm-v2',params={'enable_table':False}) is None


def test_strict_cache_does_not_accept_legacy_pmid(monkeypatch,tmp_path):
    monkeypatch.setenv('METAAGENT_PAPER_POOL',str(tmp_path/'pool'))
    directory=tmp_path/'pool/markdown/PMID_123';directory.mkdir(parents=True)
    (directory/'full.md').write_text('Unverified historical input')
    assert find_cached('123',cache_policy='compatible')
    assert find_cached('123',cache_policy='strict') is None


def test_mineru_zip_preserves_archive_and_assets(monkeypatch,tmp_path):
    from io import BytesIO
    import zipfile
    from tools.mineru.client import _download_zip_extract_markdown
    buffer=BytesIO()
    with zipfile.ZipFile(buffer,'w') as archive:
        archive.writestr('full.md','Original source')
        archive.writestr('content_list.json','[]')
        archive.writestr('images/table.png',b'PNG')
    monkeypatch.setattr('tools.mineru.client._request_with_retry',lambda *a,**k:SimpleNamespace(status_code=200,content=buffer.getvalue()))
    assets=tmp_path/'assets'
    assert _download_zip_extract_markdown('https://example.invalid/result',token=None,timeout_s=1,save_to=assets)=='Original source'
    assert (assets/'result.zip').is_file() and (assets/'images/table.png').read_bytes()==b'PNG'


def test_workflow_rejects_conflicting_pdf_identity_before_parsing(monkeypatch,tmp_path):
    import fitz
    import requests
    monkeypatch.setenv('METAAGENT_PAPER_POOL',str(tmp_path/'pool'))
    pdf=tmp_path/'wrong.pdf'
    with fitz.open() as doc:
        page=doc.new_page();page.insert_text((30,30),'Different primary report\nhttps://doi.org/10.9999/unrelated');doc.save(pdf)
    monkeypatch.setattr(requests,'get',lambda *a,**kw:(_ for _ in ()).throw(requests.ConnectionError('No external network')))
    monkeypatch.setattr('tools.mineru.cache.parse_pdf',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('Wrong source must never enter MinerU')))
    row=_fetch_pmc({'record_id':'doi:10.1234/expected','doi':'10.1234/expected','fulltext_path':str(pdf)},tmp_path/'out')
    assert row['record_status']=='fulltext_unavailable' and 'DOI does not match' in row['failure_reason']
    assert row['fulltext_path'] is None and pdf.read_bytes().startswith(b'%PDF')
