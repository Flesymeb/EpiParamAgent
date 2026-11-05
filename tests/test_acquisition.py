"""Offline identity/version-bound acquisition tests; no model/service required."""
from pathlib import Path
from types import SimpleNamespace
import hashlib,json
import fitz
import pytest
import requests

from metaagent import acquisition as acq


@pytest.fixture
def pool(tmp_path,monkeypatch):
    p=tmp_path/'paper_pool';monkeypatch.setenv('METAAGENT_PAPER_POOL',str(p))
    monkeypatch.delenv('UNPAYWALL_EMAIL',raising=False);monkeypatch.delenv('NCBI_EMAIL',raising=False)
    monkeypatch.setattr(requests,'get',lambda *a,**k:pytest.fail('unexpected acquisition network'))
    monkeypatch.setattr('metaagent.pmc_cloud.resolve_pmcid',lambda **kw:{'status':'unavailable','attempts':[]})
    monkeypatch.setattr('metaagent.pmc_cloud.discover_pmc_pdf',lambda *a,**kw:{'status':'unavailable','attempts':[]})
    return p


def pdf(path,doi='10.1234/test.paper',title='A sufficiently specific original research publication title',posted=None):
    doc=fitz.open();page=doc.new_page();text=title+'\nhttps://doi.org/'+doi
    if posted:text+='\nthis version posted '+posted+'.'
    page.insert_text((30,30),text,fontsize=10);doc.save(path);doc.close();return path


@pytest.fixture
def parser(tmp_path,monkeypatch):
    calls=[]
    def parse(path,pmid=None,*,cache_policy=None):
        calls.append((str(path),pmid,cache_policy))
        md=tmp_path/'parsed.md';md.write_text('Actual supplied PDF text, parsed through shared MinerU.')
        return SimpleNamespace(text=md.read_text(),path=md,route='mineru_content_cache',parser_fingerprint='test-parser-fp')
    monkeypatch.setattr('tools.mineru.cache.parse_pdf',parse)
    return calls


def test_verified_registry_rechecks_hash_then_uses_shared_strict_parser(tmp_path,pool,parser):
    source=pdf(tmp_path/'paper.pdf');row={'record_id':'pmid:123','pmid':'123','doi':'10.1234/test.paper'}
    info=acq.register_pdf(row,source)
    result=acq.resolve_document(row,tmp_path/'out',allow_network=False)
    assert result['record_status']=='fulltext_ready'
    assert result['access_route']=='identity_registry_cache' and result['pdf_status']=='verified'
    assert result['pdf_sha256']==hashlib.sha256(source.read_bytes()).hexdigest()
    assert parser==[(info['pdf_path'],'123','strict')]
    assert Path(result['fulltext_path']).read_text().startswith('Actual')
    Path(info['pdf_path']).write_bytes(b'changed')
    failed=acq.resolve_document(row,tmp_path/'again',allow_network=False)
    assert failed['record_status']=='fulltext_unavailable' and 'hash changed' in failed['failure_reason']
    assert len(parser)==1


def test_escaped_metadata_markup_does_not_create_a_false_title_conflict():
    plain='COVID-19 UK Lockdown Forecasts and R 0.'
    escaped='COVID-19 UK Lockdown Forecasts and R &lt;sub&gt;&lt;i&gt;0&lt;/i&gt;&lt;/sub&gt;.'
    assert acq._normal(plain)==acq._normal(escaped)
    assert acq._normal(plain)!=acq._normal(escaped.replace('0','1'))


def test_wrong_legacy_pmid_filename_never_authorizes_unrelated_pdf(tmp_path,pool,parser):
    alias=pool/'pdfs/PMID_123.pdf';alias.parent.mkdir(parents=True)
    pdf(alias,doi='10.9999/wrong.source')
    before=alias.read_bytes()
    result=acq.resolve_document({'record_id':'pmid:123','pmid':'123','doi':'10.1234/test.paper'},tmp_path/'out',allow_network=False)
    assert result['record_status']=='fulltext_unavailable'
    assert 'DOI does not match' in result['failure_reason'] and not parser
    assert alias.read_bytes()==before
    assert list((tmp_path/'out').glob('*.acquisition.json'))


def test_versioned_local_preprint_binds_posting_date_and_version_alias(tmp_path,pool,parser):
    source=pdf(tmp_path/'v1.pdf',doi='10.1101/2022.06.22.22276713',posted='June 23, 2022')
    row={'record_id':'medrxiv:10.1101/2022.06.22.22276713:v1','doi':'10.1101/2022.06.22.22276713','version_date':'2022-06-23'}
    info=acq.register_pdf(row,source)
    assert info['identity']['version']=='v1'
    assert info['verification']['version_evidence']['date']=='2022-06-23'
    result=acq.resolve_document(row,tmp_path/'out',allow_network=False)
    assert result['source_version']=='v1' and result['record_status']=='fulltext_ready'
    bad={**row,'record_id':'medrxiv:10.1101/2022.06.22.22276713:v2','version':'v2','version_date':'2022-10-28','path':str(source)}
    failed=acq.resolve_document(bad,tmp_path/'v2out',allow_network=False)
    assert failed['record_status']=='fulltext_unavailable' and 'posting date' in failed['failure_reason']
    assert len(parser)==1


def test_explicit_markdown_is_honest_about_missing_pdf(tmp_path,pool,parser):
    source=tmp_path/'provided.md';source.write_text('Explicitly supplied original text.')
    result=acq.resolve_document({'record_id':'local:a','path':str(source)},tmp_path/'out')
    assert result['record_status']=='fulltext_ready' and result['pdf_path'] is None
    assert result['pdf_status']=='not_provided' and result['access_route']=='explicit_user_text' and not parser


class Response:
    def __init__(self,content=b'',data=None,url='https://official.example/paper.pdf',status=200):
        self.content=content;self.data=data;self.url=url;self.status_code=status
    def json(self):return self.data
    def raise_for_status(self):
        if self.status_code>=400:raise requests.HTTPError('HTTP '+str(self.status_code))
    def iter_content(self,size):yield self.content
    def __enter__(self):return self
    def __exit__(self,*_):pass


def test_identity_only_doi_manifest_downloads_pdf_and_parses(tmp_path,pool,parser,monkeypatch):
    content=pdf(tmp_path/'download.pdf').read_bytes();calls=[]
    def get(url,**kwargs):
        calls.append(url)
        if '/search' in url:return Response(data={'resultList':{'result':[]}},url=url)
        return Response(content,url=url)
    monkeypatch.setattr(requests,'get',get)
    result=acq.resolve_document({'record_id':'doi:10.1234/test.paper','doi':'10.1234/test.paper','fulltext_url':'https://official.example/paper.pdf'},tmp_path/'out')
    assert result['record_status']=='fulltext_ready' and result['pdf_status']=='verified'
    assert Path(result['pdf_path']).read_bytes()==content and len(parser)==1
    assert result['acquisition_attempts'][-1]['status']=='verified'


def test_pure_pmid_resolves_official_metadata_before_fetch(tmp_path,pool,parser,monkeypatch):
    content=pdf(tmp_path/'download.pdf').read_bytes()
    def get(url,**kwargs):
        if '/search' in url:return Response(data={'resultList':{'result':[{'id':'123','doi':'10.1234/test.paper','title':'A sufficiently specific original research publication title','fullTextUrlList':{'fullTextUrl':[{'url':'https://official.example/paper.pdf','documentStyle':'pdf','availability':'Open access'}]}}]}},url=url)
        return Response(content,url=url)
    monkeypatch.setattr(requests,'get',get)
    result=acq.resolve_document({'record_id':'pmid:123','pmid':'123'},tmp_path/'out')
    assert result['record_status']=='fulltext_ready'
    assert result['identity_verification']['expected']['doi']=='10.1234/test.paper'
    assert result['identity_verification']['pmid_binding']=='official_metadata'


def test_pmid_doi_conflict_is_explicit_not_rebound(tmp_path,pool,parser,monkeypatch):
    alias=pool/'pdfs/PMID_123.pdf';alias.parent.mkdir(parents=True);pdf(alias)
    monkeypatch.setattr(requests,'get',lambda url,**kw:Response(data={'resultList':{'result':[{'id':'123','doi':'10.9999/different'}]}},url=url))
    result=acq.resolve_document({'record_id':'pmid:123','pmid':'123','doi':'10.1234/test.paper'},tmp_path/'out')
    assert result['record_status']=='fulltext_unavailable' and 'conflicts' in result['failure_reason']
    assert not (pool/'registry').exists() and not parser


def test_versioned_preprint_redirect_to_newer_version_is_rejected(tmp_path,pool,parser,monkeypatch):
    content=pdf(tmp_path/'v2.pdf',doi='10.1101/2022.06.22.22276713',posted='October 28, 2022').read_bytes()
    def get(url,**kw):
        if '/search' in url:return Response(data={'resultList':{'result':[]}},url=url)
        return Response(content,url='https://www.medrxiv.org/content/10.1101/2022.06.22.22276713v2.full.pdf')
    monkeypatch.setattr(requests,'get',get)
    result=acq.resolve_document({'record_id':'medrxiv:10.1101/2022.06.22.22276713:v1','doi':'10.1101/2022.06.22.22276713'},tmp_path/'out')
    assert result['record_status']=='fulltext_unavailable' and not parser
    assert not (pool/'registry').exists()


def test_mineru_failure_keeps_verified_pdf_receipt(tmp_path,pool,monkeypatch):
    source=pdf(tmp_path/'source.pdf');row={'record_id':'doi:10.1234/test.paper','doi':'10.1234/test.paper'}
    acq.register_pdf(row,source)
    def fail(*a,**kw):raise RuntimeError('MinerU unavailable')
    monkeypatch.setattr('tools.mineru.cache.parse_pdf',fail)
    result=acq.resolve_document(row,tmp_path/'out',allow_network=False)
    assert result['record_status']=='fulltext_unavailable' and result['pdf_status']=='verified'
    assert Path(result['pdf_path']).is_file() and result['pdf_sha256']
    assert result['failure_reason']=='MinerU unavailable'


def test_full_title_prevents_reference_doi_false_identity(tmp_path,pool):
    source=pdf(tmp_path/'unrelated.pdf',title='An unrelated study referencing another publication DOI')
    with pytest.raises(ValueError,match='title does not match'):
        acq.inspect_pdf_identity(source,{'doi':'10.1234/test.paper','title':'A sufficiently specific original research publication title'})


def test_official_preprint_url_alone_derives_version_pinned_identity(tmp_path,pool,parser,monkeypatch):
    content=pdf(tmp_path/'v1.pdf',doi='10.1101/2022.06.22.22276713',posted='June 23, 2022').read_bytes()
    url='https://www.medrxiv.org/content/10.1101/2022.06.22.22276713v1.full.pdf'
    def get(value,**kw):
        if '/search' in value:return Response(data={'resultList':{'result':[]}},url=value)
        return Response(content,url=value)
    monkeypatch.setattr(requests,'get',get)
    result=acq.resolve_document({'fulltext_url':url},tmp_path/'out')
    assert result['record_status']=='fulltext_ready' and result['source_version']=='v1'
    assert result['identity_verification']['expected']['doi']=='10.1101/2022.06.22.22276713'
    assert result['identity_verification']['version_evidence']['type']=='official_versioned_download'


def test_missing_pmid_alias_restored_from_verified_hash_without_download(tmp_path,pool,parser):
    source=pdf(tmp_path/'source.pdf');row={'pmid':'123','doi':'10.1234/test.paper'}
    acq.register_pdf(row,source)
    alias=pool/'pdfs/PMID_123.pdf';alias.unlink()
    result=acq.resolve_document(row,tmp_path/'out',allow_network=False)
    assert result['record_status']=='fulltext_ready' and alias.read_bytes()==source.read_bytes()


def test_source_version_cannot_escape_alias_directory(tmp_path,pool):
    source=pdf(tmp_path/'source.pdf')
    with pytest.raises(ValueError,match='safe version'):
        acq.register_pdf({'doi':'10.1234/test.paper','version':'../../outside'},source)
    assert not (pool/'registry').exists()


def test_unversioned_preprint_import_is_not_silently_latest(tmp_path,pool):
    source=pdf(tmp_path/'preprint.pdf',doi='10.1101/2020.01.23.20018549',posted='January 28, 2020')
    with pytest.raises(ValueError,match='specific version'):
        acq.register_pdf({'doi':'10.1101/2020.01.23.20018549'},source)
    assert not (pool/'registry').exists()


def test_frozen_official_early_url_binds_posting_date_without_guessing_v_number(tmp_path,pool,parser):
    source=pdf(tmp_path/'early.pdf',doi='10.1101/2020.01.23.20018549',posted='January 28, 2020')
    url='https://www.medrxiv.org/content/medrxiv/early/2020/01/28/2020.01.23.20018549.full.pdf'
    row={'doi':'10.1101/2020.01.23.20018549','fulltext_url':url}
    info=acq.register_pdf(row,source,source_url=url,downloaded=True)
    assert info['identity']['version']=='posted-2020-01-28'
    assert info['verification']['version_evidence']['date']=='2020-01-28'
    result=acq.resolve_document(row,tmp_path/'out',allow_network=False)
    assert result['record_status']=='fulltext_ready' and result['source_version']=='posted-2020-01-28'
    mismatched={**row,'fulltext_url':url.replace('/01/28/','/02/01/')}
    assert acq.resolve_document(mismatched,tmp_path/'bad',allow_network=False)['record_status']=='fulltext_unavailable'


def test_supplement_only_pdf_cannot_satisfy_primary_report(tmp_path,pool):
    source=pdf(tmp_path/'supplement.pdf',title='Supplementary Material')
    with pytest.raises(ValueError,match='not the requested primary'):
        acq.register_pdf({'doi':'10.1234/test.paper'},source)
    info=acq.register_pdf({'doi':'10.1234/test.paper','role':'supplement'},source)
    assert info['verification']['document_kind']=='supplement'


@pytest.mark.parametrize('redirect_date,expected',[('2020/01/28','fulltext_ready'),('2020/02/01','fulltext_unavailable')])
def test_actual_frozen_date_download_requires_original_date_and_literal_pdf_posting(tmp_path,pool,parser,monkeypatch,redirect_date,expected):
    doi='10.1101/2020.01.23.20018549'
    content=pdf(tmp_path/'actual.pdf',doi=doi,posted='January 28, 2020').read_bytes()
    url='https://www.medrxiv.org/content/medrxiv/early/2020/01/28/2020.01.23.20018549.full.pdf'
    def get(value,**kw):
        if '/search' in value:return Response(data={'resultList':{'result':[]}},url=value)
        return Response(content,url=value.replace('2020/01/28',redirect_date))
    monkeypatch.setattr(requests,'get',get)
    result=acq.resolve_document({'record_id':'doi:'+doi,'doi':doi,'fulltext_url':url},tmp_path/'out')
    assert result['record_status']==expected
    if expected=='fulltext_ready':
        assert result['source_version']=='posted-2020-01-28'
        assert result['identity_verification']['version_evidence']['date']=='2020-01-28'
        assert len(parser)==1
    else:assert not parser and not (pool/'registry').exists()


def test_rejected_implicit_legacy_downloads_correct_canonical_and_next_cache_hit(tmp_path,pool,parser,monkeypatch):
    wrong=pool/'pdfs/PMID_123.pdf';wrong.parent.mkdir(parents=True);pdf(wrong,doi='10.9999/wrong.article')
    wrong_bytes=wrong.read_bytes();correct=pdf(tmp_path/'correct.pdf').read_bytes();calls=[]
    def get(url,**kw):
        calls.append(url)
        if '/search' in url:return Response(data={'resultList':{'result':[{'id':'123','doi':'10.1234/test.paper','title':'A sufficiently specific original research publication title','fullTextUrlList':{'fullTextUrl':[{'url':'https://official.example/correct.pdf','documentStyle':'pdf','availability':'Open access'}]}}]}},url=url)
        return Response(correct,url=url)
    monkeypatch.setattr(requests,'get',get)
    row={'record_id':'pmid:123','pmid':'123','doi':'10.1234/test.paper'}
    result=acq.resolve_document(row,tmp_path/'out')
    assert result['record_status']=='fulltext_ready' and Path(result['pdf_path']).read_bytes()==correct
    assert result['stale_alias_conflicts'][0]['path']==str(wrong)
    assert wrong.read_bytes()==wrong_bytes
    assert any(a['status']=='cache_rejected' for a in result['acquisition_attempts'])
    monkeypatch.setattr(requests,'get',lambda *a,**kw:pytest.fail('strict canonical registry hit must not download'))
    cached=acq.resolve_document(row,tmp_path/'second')
    assert cached['record_status']=='fulltext_ready' and cached['access_route']=='identity_registry_cache'
    assert cached['pdf_path']==result['pdf_path'] and wrong.read_bytes()==wrong_bytes


def test_rejected_legacy_and_wrong_download_still_fail(tmp_path,pool,parser,monkeypatch):
    wrong=pool/'pdfs/PMID_123.pdf';wrong.parent.mkdir(parents=True);pdf(wrong,doi='10.9999/wrong.article');content=wrong.read_bytes()
    def get(url,**kw):
        if '/search' in url:return Response(data={'resultList':{'result':[{'id':'123','doi':'10.1234/test.paper','title':'A sufficiently specific original research publication title','fullTextUrlList':{'fullTextUrl':[{'url':'https://official.example/wrong.pdf','documentStyle':'pdf','availability':'Open access'}]}}]}},url=url)
        return Response(content,url=url)
    monkeypatch.setattr(requests,'get',get)
    result=acq.resolve_document({'pmid':'123','doi':'10.1234/test.paper'},tmp_path/'out')
    assert result['record_status']=='fulltext_unavailable' and not parser
    assert wrong.read_bytes()==content and not list((pool/'registry/documents').glob('*.json'))


def test_explicit_wrong_local_pdf_remains_failure_without_download_fallback(tmp_path,pool,parser,monkeypatch):
    source=pdf(tmp_path/'explicit.pdf',doi='10.9999/wrong.article')
    monkeypatch.setattr(requests,'get',lambda *a,**kw:pytest.fail('explicit wrong local input must not be silently replaced'))
    result=acq.resolve_document({'record_id':'local','doi':'10.1234/test.paper','path':str(source)},tmp_path/'out')
    assert result['record_status']=='fulltext_unavailable' and not parser


def test_undeclared_original_preprint_version_never_selects_latest(tmp_path,pool,parser,monkeypatch):
    calls=[]
    def get(url,**kw):
        calls.append(url)
        return Response(data={'resultList':{'result':[]}},url=url)
    monkeypatch.setattr(requests,'get',get)
    result=acq.resolve_document({'doi':'10.1101/2020.01.23.20018549'},tmp_path/'out')
    assert result['record_status']=='fulltext_unavailable' and 'version is undeclared' in result['failure_reason']
    assert not any('/details/' in value for value in calls) and not parser


def test_explicit_full_title_conflict_cannot_be_rewritten_to_official_title(tmp_path,pool,parser,monkeypatch):
    title='An explicitly different original report title requiring human review'
    monkeypatch.setattr(requests,'get',lambda url,**kw:Response(data={'resultList':{'result':[{'id':'123','doi':'10.1234/test.paper','title':'A sufficiently specific original research publication title'}]}},url=url))
    result=acq.resolve_document({'pmid':'123','doi':'10.1234/test.paper','title':title},tmp_path/'out')
    assert result['record_status']=='fulltext_unavailable' and 'conflicts' in result['failure_reason']
    assert result['title']==title and not parser


@pytest.mark.parametrize('row',[{'doi':'10.1101/2020.05.13.20099614v2'}, {'record_id':'doi:10.1101/2020.05.13.20099614v2'}])
def test_version_qualified_preprint_doi_normalizes_without_guessing(row):
    identity=acq._identity(row)
    assert identity['doi']=='10.1101/2020.05.13.20099614' and identity['version']=='v2'
    with pytest.raises(ValueError,match='conflicts'):
        acq._identity({**row,'preprint_version':'v1'})
    journal=acq._identity({'doi':'10.1234/a-real-doi-ending-v2'})
    assert journal['doi']=='10.1234/a-real-doi-ending-v2' and journal['version'] is None


def test_reference_only_doi_and_full_title_are_not_own_identity(tmp_path,pool):
    expected_title='A sufficiently specific original research publication title'
    source=tmp_path/'wrong-citing-correct.pdf'
    with fitz.open() as doc:
        doc.new_page().insert_text((30,30),'An unrelated original paper with a different own identity\nhttps://doi.org/10.9999/own.wrong')
        doc.new_page().insert_text((30,30),'References\n'+expected_title+'\nhttps://doi.org/10.1234/test.paper')
        doc.save(source)
    with pytest.raises(ValueError,match='DOI does not match'):
        acq.register_pdf({'doi':'10.1234/test.paper','title':expected_title},source)
    assert not (pool/'registry').exists()


def test_conflicting_full_title_cannot_be_washed_by_cached_identity(tmp_path,pool,parser):
    source=pdf(tmp_path/'valid.pdf');row={'doi':'10.1234/test.paper','title':'A sufficiently specific original research publication title'}
    acq.register_pdf(row,source)
    result=acq.resolve_document({**row,'title':'A completely unrelated full study title with different scientific subject'},tmp_path/'out',allow_network=False)
    assert result['record_status']=='fulltext_unavailable' and 'conflicts' in result['failure_reason']
    assert not parser


def test_conflicting_version_assertions_have_per_record_failure_receipt(tmp_path,pool):
    result=acq.resolve_document({'record_id':'preprint-conflict','doi':'10.1101/2020.05.13.20099614v2','preprint_version':'v1'},tmp_path/'out')
    assert result['record_status']=='fulltext_unavailable' and 'conflicts' in result['failure_reason']
    assert len(list((tmp_path/'out').glob('*.acquisition.json')))==1


def test_generic_alias_to_other_version_is_miss_then_fetches_requested_original(tmp_path,pool,parser,monkeypatch):
    doi='10.1101/2020.01.23.20018549';generic='medrxiv:'+doi
    newer=pdf(tmp_path/'newer.pdf',doi=doi,posted='February 1, 2020')
    old=acq.register_pdf({'record_id':generic,'doi':doi,'preprint_version':'v2','version_date':'2020-02-01'},newer)
    registry=acq._registry_path(old['identity'],{'record_id':generic});old_registry=registry.read_bytes();old_pdf=Path(old['pdf_path']).read_bytes()
    original=pdf(tmp_path/'original.pdf',doi=doi,posted='January 28, 2020').read_bytes();requests_seen=[]
    def get(url,**kw):
        requests_seen.append(url)
        if '/search' in url:return Response(data={'resultList':{'result':[]}},url=url)
        return Response(original,url=url)
    monkeypatch.setattr(requests,'get',get)
    row={'record_id':generic,'doi':doi,'preprint_version':'v1','version_date':'2020-01-28','fulltext_url':'https://www.medrxiv.org/content/'+doi+'v1.full.pdf'}
    result=acq.resolve_document(row,tmp_path/'out',parse=False)
    assert result['record_status']=='pdf_ready' and result['source_version']=='v1'
    assert Path(result['pdf_path']).read_bytes()==original and any('v1.full.pdf' in url for url in requests_seen)
    assert registry.read_bytes()==old_registry and Path(old['pdf_path']).read_bytes()==old_pdf
    monkeypatch.setattr(requests,'get',lambda *a,**k:pytest.fail('exact requested version now cached'))
    assert acq.resolve_document(row,tmp_path/'again',parse=False)['access_route']=='identity_registry_cache'


@pytest.mark.parametrize('explicit_case',['same_identity_different_bytes','same_bytes','missing_file'])
def test_explicit_local_pdf_is_not_ignored_on_registry_hit(tmp_path,pool,parser,explicit_case):
    original=pdf(tmp_path/'cached.pdf')
    row={'record_id':'doi:10.1234/test.paper','doi':'10.1234/test.paper','title':'A sufficiently specific original research publication title'}
    info=acq.register_pdf(row,original)
    registry=acq._registry_path(info['identity'],row)
    before_registry=registry.read_bytes();before_pdf=Path(info['pdf_path']).read_bytes()
    selected=tmp_path/'explicit.pdf'
    if explicit_case=='same_bytes':selected.write_bytes(original.read_bytes())
    elif explicit_case=='same_identity_different_bytes':
        pdf(selected)
        assert selected.read_bytes()!=original.read_bytes()
        assert acq.inspect_pdf_identity(selected,row)['status']=='verified'
    result=acq.resolve_document({**row,'pdf_path':str(selected)},tmp_path/'out',parse=False,allow_network=False)
    if explicit_case=='same_bytes':
        assert result['record_status']=='pdf_ready' and result['access_route']=='identity_registry_cache'
        assert result['pdf_sha256']==acq._sha(selected)
    else:
        assert result['record_status']=='fulltext_unavailable'
        expected='bytes differ' if explicit_case=='same_identity_different_bytes' else 'is missing'
        assert expected in result['failure_reason']
    assert registry.read_bytes()==before_registry and Path(info['pdf_path']).read_bytes()==before_pdf
    assert not parser


def layout_pdf(path,*,prior_references=False,citation_only=False,cover=False,doi='10.1234/test.paper'):
    title='A sufficiently specific original research publication title';doc=fitz.open()
    if cover:
        page=doc.new_page();page.insert_text((40,40),'HAL Id: repository-001\nSubmitted on 1 Jan 2022')
    page=doc.new_page(width=600,height=800)
    if prior_references:page.insert_text((40,45),'References',fontsize=11)
    page.insert_textbox(fitz.Rect(40,70,280,170),'Prior material and reference information from another report. '*4,fontsize=9)
    page.insert_textbox(fitz.Rect(40,210,280,280),title,fontsize=16)
    if not citation_only:page.insert_text((40,305),'Author affiliations: Original research institute.',fontsize=9)
    if doi:page.insert_text((40,355),'DOI: https://doi.org/'+doi,fontsize=9)
    page.insert_textbox(fitz.Rect(40,390,280,700),'The requested report describes original measurements and methods. '*10,fontsize=10)
    page.insert_textbox(fitz.Rect(310,210,560,700),'The other column continues this same original report and its methods. '*10,fontsize=10)
    doc.save(path);doc.close();return path


@pytest.mark.parametrize('cover',[False,True])
def test_heading_blocks_survive_interleaved_columns_and_cover(tmp_path,pool,cover):
    path=layout_pdf(tmp_path/'columns.pdf',cover=cover)
    row={'pmid':'123','doi':'10.1234/test.paper','title':'A sufficiently specific original research publication title'}
    result=acq.inspect_pdf_identity(path,row);assert result['status']=='verified' and result['title_match'] and result['doi_match']
    hint=result['article_boundary_hint'];assert hint['mode']=='standalone_heading_and_own_doi_label'
    assert hint['page']==(2 if cover else 1) and hint['title_bbox'][1]>200
    info=acq.register_pdf(row,path);loaded=acq.resolve_document(row,tmp_path/'out',parse=False,allow_network=False)
    assert loaded['record_status']=='pdf_ready' and loaded['article_boundary_hint']==hint
    assert info['verification']['pdf_sha256']==hashlib.sha256(path.read_bytes()).hexdigest()


def test_new_article_after_prior_references_has_target_boundary(tmp_path,pool):
    path=layout_pdf(tmp_path/'compound.pdf',prior_references=True)
    result=acq.inspect_pdf_identity(path,{'doi':'10.1234/test.paper','title':'A sufficiently specific original research publication title'})
    assert result['status']=='verified' and result['article_boundary_hint']['preceding_material_in_title_column']
    assert 'another column' in result['article_boundary_hint']['scope_instruction']


def test_reference_only_large_title_without_article_metadata_still_rejected(tmp_path,pool):
    path=layout_pdf(tmp_path/'reference-only.pdf',prior_references=True,citation_only=True)
    with pytest.raises(ValueError,match='does not match'):
        acq.inspect_pdf_identity(path,{'doi':'10.1234/test.paper','title':'A sufficiently specific original research publication title'})


def test_missing_printed_doi_requires_official_binding_and_own_heading(tmp_path,pool,monkeypatch):
    path=layout_pdf(tmp_path/'no-printed-doi.pdf',doi=None)
    row={'record_id':'pmid:123','pmid':'123','doi':'10.1234/test.paper','title':'A sufficiently specific original research publication title','pdf_path':str(path)}
    with pytest.raises(ValueError,match='DOI does not match'):acq.inspect_pdf_identity(path,row)
    hit={'id':'123','source':'MED','doi':row['doi'],'title':row['title']}
    monkeypatch.setattr(requests,'get',lambda *a,**kw:Response(data={'resultList':{'result':[hit]}}))
    result=acq.resolve_document(row,tmp_path/'out',parse=False,allow_network=True)
    assert result['record_status']=='pdf_ready',result
    evidence=result['identity_verification'];assert evidence['doi_match'] is False
    assert evidence['title_match'] and evidence['doi_binding']['type']=='official_metadata_plus_own_title'
    assert evidence['doi_binding']['provider']=='europepmc' and len(evidence['doi_binding']['response_sha256'])==64
    monkeypatch.setattr(requests,'get',lambda *a,**kw:pytest.fail('Cache revalidation must remain offline'))
    again=acq.resolve_document({k:v for k,v in row.items() if k!='pdf_path'},tmp_path/'again',parse=False,allow_network=False)
    assert again['record_status']=='pdf_ready' and again['identity_verification']['doi_match'] is False


def test_metadata_never_overrides_conflicting_own_preprint_doi(tmp_path,pool,monkeypatch):
    path=layout_pdf(tmp_path/'different-version.pdf',doi='10.1101/2020.01.01.12345')
    row={'pmid':'123','doi':'10.1234/test.paper','title':'A sufficiently specific original research publication title','pdf_path':str(path)}
    monkeypatch.setattr(requests,'get',lambda *a,**kw:Response(data={'resultList':{'result':[{'id':'123','source':'MED','doi':row['doi'],'title':row['title']}]}}))
    result=acq.resolve_document(row,tmp_path/'out',parse=False,allow_network=True)
    assert result['record_status']=='fulltext_unavailable' and 'own-header DOI conflicts' in result['failure_reason']


def test_cloud_checksum_identity_survives_offline_cache_recheck(tmp_path,pool):
    title='A sufficiently specific original research publication title'
    source=tmp_path/'cloud.pdf'
    doc=fitz.open();page=doc.new_page();page.insert_text((30,30),title,fontsize=10)
    doc.save(source);doc.close()
    md5=hashlib.md5(source.read_bytes()).hexdigest()
    url='https://pmc-oa-opendata.s3.amazonaws.com/PMC123.1/main.pdf?md5='+md5
    row={'pmid':'123','doi':'10.1234/test.paper','title':title,'pmcid':'PMC123',
         '_official_identity_binding':{'provider':'pmc_aws','doi':'10.1234/test.paper',
             'title':title,'pmcid':'PMC123','version':1,'metadata_sha256':'a'*64,
             'pdf_md5':md5,'is_pmc_openaccess':True,'is_manuscript':False,'is_retracted':False}}
    info=acq.register_pdf(row,source,source_url=url,downloaded=True)
    assert info['verification']['doi_binding']['type']=='official_metadata_plus_pdf_checksum'
    again=acq.resolve_document({'pmid':'123','doi':row['doi'],'title':title},tmp_path/'again',parse=False,allow_network=False)
    assert again['record_status']=='pdf_ready',again
    assert again['identity_verification']['doi_binding']['pdf_md5']==md5
    # Cached metadata still cannot authorize a damaged immutable PDF.
    Path(info['pdf_path']).write_bytes(b'changed')
    failed=acq.resolve_document(row,tmp_path/'failed',parse=False,allow_network=False)
    assert failed['record_status']=='fulltext_unavailable' and 'hash changed' in failed['failure_reason']


def test_low_title_never_hides_conflicting_preprint_doi_above_it(tmp_path,pool,monkeypatch):
    source=layout_pdf(tmp_path/'low-title.pdf',doi=None);doc=fitz.open(source)
    doc[0].insert_text((40,25),'medRxiv preprint doi: https://doi.org/10.1101/2020.01.01.12345',fontsize=9)
    path=tmp_path/'conflicting-header.pdf';doc.save(path);doc.close()
    row={'pmid':'123','doi':'10.1234/test.paper','title':'A sufficiently specific original research publication title','pdf_path':str(path)}
    monkeypatch.setattr(requests,'get',lambda *a,**kw:Response(data={'resultList':{'result':[{'id':'123','source':'MED','doi':row['doi'],'title':row['title']}]}}))
    result=acq.resolve_document(row,tmp_path/'out',parse=False,allow_network=True)
    assert result['record_status']=='fulltext_unavailable' and 'own-header DOI conflicts' in result['failure_reason']


def test_cloud_exact_candidate_precedes_retired_api_preserves_witness(tmp_path,pool,monkeypatch):
    source=pdf(tmp_path/'source.pdf');url='https://pmc-oa-opendata.s3.amazonaws.com/PMC123.1/main.pdf'
    witness={'url':url,'key':'PMC123.1/main.pdf','pmc_deposit_version':'1','license_code':'cc-by','is_manuscript':False,'metadata':{'pmcid':'PMC123'},'metadata_response_sha256':'a'*64,'pdf_md5':hashlib.md5(source.read_bytes()).hexdigest()}
    monkeypatch.setattr('metaagent.pmc_cloud.discover_pmc_pdf',lambda *a,**kw:{'status':'ready','pdf_url':url,'candidates':[witness],'attempts':[]})
    def get(target,**kwargs):
        if target.startswith('https://www.ebi.ac.uk/'):return Response(data={'resultList':{'result':[{'id':'123','source':'MED','doi':'10.1234/test.paper','title':'A sufficiently specific original research publication title','pmcid':'PMC123'}]}})
        if target==url:return Response(content=source.read_bytes(),url=url)
        pytest.fail('Unexpected fallback/retired route: '+target)
    monkeypatch.setattr(requests,'get',get)
    result=acq.resolve_document({'pmid':'123','doi':'10.1234/test.paper'},tmp_path/'out',parse=False)
    assert result['record_status']=='pdf_ready' and result['access_route']=='pmc_cloud_pdf',result
    assert result['source_version'] is None and result['source_metadata']['pmc_deposit_version']=='1'
    cached=acq.resolve_document({'pmid':'123','doi':'10.1234/test.paper'},tmp_path/'again',parse=False,allow_network=False)
    assert cached['source_metadata']==result['source_metadata']


def test_cloud_pending_does_not_fall_through_to_bare_pmc_latest(pool,monkeypatch):
    monkeypatch.setattr('metaagent.pmc_cloud.discover_pmc_pdf',lambda *a,**kw:{'status':'pending','attempts':[]})
    assert list(acq._candidate_urls({'doi':'10.1234/test.paper','pmcid':'PMC123'}))==[]


def test_explicit_preprint_version_never_uses_automatic_pmc_formal_pdf(pool,monkeypatch):
    monkeypatch.setattr('metaagent.pmc_cloud.discover_pmc_pdf',lambda *a,**kw:pytest.fail('Do not map a preprint version to a PMC deposit'))
    candidates=list(acq._candidate_urls({'doi':'10.1101/2020.01.01.12345','preprint_version':'v1','pmcid':'PMC123'}))
    assert candidates and all(route=='official_preprint' for _,route in candidates)


def test_plain_appendix_is_never_registered_as_primary(tmp_path,pool):
    path=tmp_path/'appendix.pdf';doc=fitz.open();page=doc.new_page();page.insert_text((30,30),'Appendix\nA sufficiently specific original research publication title\nDOI: 10.1234/test.paper');doc.save(path);doc.close()
    row={'doi':'10.1234/test.paper','title':'A sufficiently specific original research publication title'}
    with pytest.raises(ValueError,match='supplementary material'):acq.inspect_pdf_identity(path,row)
    verification=acq.inspect_pdf_identity(path,{**row,'role':'supplement'})
    assert verification['document_kind']=='supplement'


def test_successful_known_url_never_starts_cloud_or_unpaywall(tmp_path,pool,monkeypatch):
    path=pdf(tmp_path/'known.pdf');url='https://publisher.example/known.pdf';calls=[]
    def get(target,**kwargs):
        calls.append(target)
        if target.startswith('https://www.ebi.ac.uk/'):return Response(data={'resultList':{'result':[{'id':'123','source':'MED','doi':'10.1234/test.paper','title':'A sufficiently specific original research publication title','pmcid':'PMC123'}]}})
        if target==url:return Response(content=path.read_bytes(),url=url)
        pytest.fail('Unexpected route '+target)
    monkeypatch.setattr(requests,'get',get)
    monkeypatch.setattr('metaagent.pmc_cloud.discover_pmc_pdf',lambda *a,**kw:pytest.fail('No cloud for successful explicit URL'))
    monkeypatch.setattr('metaagent.pmc_cloud.resolve_pmcid',lambda **kw:pytest.fail('No converter for successful explicit URL'))
    monkeypatch.setenv('UNPAYWALL_EMAIL','offline@example.org')
    monkeypatch.setattr('tools.literature.sources.unpaywall',lambda *a,**kw:pytest.fail('No Unpaywall for successful explicit URL'))
    result=acq.resolve_document({'pmid':'123','doi':'10.1234/test.paper','fulltext_url':url},tmp_path/'out',parse=False)
    assert result['record_status']=='pdf_ready' and result['access_route']=='explicit_url'
    assert len(calls)==2 and calls[-1]==url


def test_adjacent_title_fragments_skip_interleaved_other_column(tmp_path,pool):
    doc=fitz.open();page=doc.new_page(width=600,height=800)
    page.insert_text((40,210),'A sufficiently specific original',fontsize=16)
    page.insert_textbox(fitz.Rect(310,235,560,700),'Other-column body text describing the original report. '*12,fontsize=10)
    page.insert_text((40,250),'research publication title',fontsize=16)
    page.insert_text((40,355),'DOI: 10.1234/test.paper',fontsize=9)
    path=tmp_path/'fragmented.pdf';doc.save(path);doc.close()
    result=acq.inspect_pdf_identity(path,{'doi':'10.1234/test.paper','title':'A sufficiently specific original research publication title'})
    assert result['status']=='verified' and result['article_boundary_hint']['title_bbox'][3]>250


def test_cloud_md5_mismatch_is_rejected_before_canonical_publication(tmp_path,pool,monkeypatch):
    monkeypatch.setattr(acq,'_metadata',lambda row,**kw:row)
    source=pdf(tmp_path/'source.pdf');url='https://pmc-oa-opendata.s3.amazonaws.com/PMC123.1/main.pdf'
    monkeypatch.setattr('metaagent.pmc_cloud.discover_pmc_pdf',lambda *a,**kw:{'status':'ready','pdf_url':url,'candidates':[{'url':url,'pdf_md5':'0'*32}],'attempts':[]})
    monkeypatch.setattr(requests,'get',lambda target,**kw:Response(content=source.read_bytes(),url=target) if target==url else Response(content=b'not a PDF',url=target))
    result=acq.resolve_document({'doi':'10.1234/test.paper','title':'A sufficiently specific original research publication title','pmcid':'PMC123'},tmp_path/'out',parse=False)
    assert result['record_status']=='fulltext_unavailable'
    assert any(a.get('classification')=='pmc_cloud_md5_mismatch' for a in result['acquisition_attempts'])
    assert not list((pool/'pdfs/by_sha256').glob('*.pdf')) and not list((pool/'registry/documents').glob('*.json'))
