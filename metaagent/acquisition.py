"""Identity-bound PDF acquisition shared by workflow and independent Coding.

Bibliographic identity/version only: no eligibility labels or reference estimates
are consumed. PDF assets are immutable by hash; registry aliases never authorize
an unrelated legacy PMID filename or a later preprint version.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import unicodedata
from urllib.parse import quote, unquote, urlsplit
import xml.etree.ElementTree as ET

import requests

from tools.mineru.cache import pool_root

MAX_PDF_BYTES = 50 * 1024 * 1024


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _atomic(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    import uuid
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_bytes(value if isinstance(value, bytes) else (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode())
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def _doi(value):
    # Publisher PDFs can encode common ligatures (for example, ``ﬁ`` in
    # ``ofid``) in extracted text. Normalize compatibility characters before
    # comparing a DOI that is otherwise printed correctly in the PDF header.
    # Publisher text layers also render the hyphen of a DOI page range as an
    # en/em dash; a DOI is ASCII by definition, so those dashes are folded to
    # the ASCII hyphen before comparison.
    value = unicodedata.normalize('NFKC', str(value or '')).strip().lower()
    value = re.sub(r'[‐‑‒–—―−]', '-', value)
    return re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)', '', value).rstrip('.,;')


def _normal(value):
    import html
    value = re.sub(r'<[^>]+>','',html.unescape(value))
    value = unicodedata.normalize('NFKD', value).casefold()
    # A year range printed with an en dash means the same as one printed with
    # the word "to" (for example ``1996-1997`` and ``1996 to 1997``). Both
    # sides of a comparison are folded the same way, so this only removes a
    # typography difference between a document and its bibliographic record.
    value = re.sub(r'(?<=\d)\s*[‐‑‒–—―−]\s*(?=\d)', ' to ', value)
    return ''.join(c for c in value if c.isalnum())


def _same_pdf_article_doi(observed, expected):
    """Recognize bounded publisher DOI-label defects and same-article links."""
    observed, expected = _doi(observed), _doi(expected)
    if observed == expected:
        return True
    if not expected or '/' not in expected:
        return False
    suffix = expected.split('/', 1)[1]
    # Some CDC PDFs visibly repeat the complete suffix in their DOI label.
    if len(suffix) >= 6 and observed == expected + suffix:
        return True
    # PNAS prints its supplementary-resource URL next to the article DOI.
    return bool(expected.startswith('10.1073/pnas.') and
                re.fullmatch(re.escape(expected) + r'/-/dcsupplemental(?:[./?#][a-z0-9._/?#=-]*)?', observed))


def _identity(row):
    record_id = str(row.get('record_id') or '')
    pmid = str(row.get('pmid') or row.get('PMID') or (record_id[5:] if re.fullmatch(r'pmid:\d+',record_id) else '')).strip()
    if pmid and not pmid.isdigit():
        raise ValueError('PMID must be numeric')
    record_doi = re.sub(r':v\d+$','',record_id[4:],flags=re.I) if record_id.startswith('doi:10.') else ''
    if not record_doi and re.match(r'^(?:medrxiv|biorxiv):10\.',record_id):
        record_doi=re.sub(r':v\d+$','',record_id.split(':',1)[1],flags=re.I)
    doi = _doi(row.get('doi') or row.get('DOI') or record_doi)
    embedded_version=None
    embedded=re.fullmatch(r'(10\.1101/.+?)(v\d+)',doi,re.I)
    if embedded:
        doi=embedded.group(1);embedded_version=embedded.group(2).lower()
    if doi and not re.fullmatch(r'10\.\d{4,9}/\S+', doi):
        raise ValueError('Invalid DOI')
    version = str(row.get('preprint_version') or row.get('source_version') or row.get('version') or '').strip().lower()
    if not version:
        match = re.search(r':(v\d+)$', str(row.get('record_id') or ''), re.I)
        version = match.group(1).lower() if match else ''
    if embedded_version:
        if version and version!=embedded_version:
            raise ValueError('Version-qualified preprint DOI conflicts with the requested version')
        version=embedded_version
    for field in ('fulltext_url','pdf_url','download_url','url'):
        parsed=urlsplit(str(row.get(field) or ''))
        if parsed.hostname in {'www.medrxiv.org','medrxiv.org','www.biorxiv.org','biorxiv.org'}:
            match=re.search(r'/content/(10\.\d{4,9}/.+?)(v\d+)(?:\.full\.pdf|\.full|\.pdf)?$',parsed.path,re.I)
            if match:
                preprint_doi=_doi(match.group(1));preprint_version=match.group(2).lower()
                if doi and doi!=preprint_doi:
                    # A row that names a formal publication and carries the
                    # preprint it was published from states provenance, not a
                    # conflict: the document still has to carry the expected
                    # DOI, and a preprint file cannot stand in for it. A
                    # preprint row that points at a different preprint is a
                    # real conflict.
                    if str(doi).startswith('10.1101/'):raise ValueError('Preprint URL conflicts with expected DOI')
                    continue
                if version and version!=preprint_version:raise ValueError('Preprint URL conflicts with requested version')
                doi=doi or preprint_doi;version=version or preprint_version
            dated=re.search(r'/early/(\d{4})/(\d{2})/(\d{2})/',parsed.path)
            if dated and doi.startswith('10.1101/') and not version:
                version='posted-'+'-'.join(dated.groups())
    if version and re.fullmatch(r'\d+', version): version = 'v'+version
    if version and not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,63}',version):
        raise ValueError('Source version must be a safe version identifier')
    return {'pmid': pmid or None, 'doi': doi or None, 'version': version or None,
            'title': str(row.get('title') or row.get('Title') or '').strip()}


def _key(identity, row):
    if identity['doi']:
        key='doi:'+identity['doi']+(':'+identity['version'] if identity['version'] else '')
        if row.get('role') in {'supplement','supplementary','appendix'}:
            key+=':supplement:'+str(row.get('record_id') or row.get('source_id') or row.get('fulltext_url') or '')
        return key
    if identity['pmid']:
        return 'pmid:'+identity['pmid']
    return str(row.get('record_id') or 'url:'+hashlib.sha256(str(row.get('fulltext_url') or row.get('url')).encode()).hexdigest())


def _registry_path(identity, row):
    return pool_root()/'registry/documents'/(hashlib.sha256(_key(identity,row).encode()).hexdigest()+'.json')


def _public_url(value):
    parsed = urlsplit(str(value or ''))
    if parsed.scheme not in {'https','http'} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError('A public absolute HTTP(S) document URL is required')
    if any(re.search(r'(token|api.?key|secret|signature)', part.split('=')[0], re.I) for part in parsed.query.split('&') if part):
        raise ValueError('Credential-bearing document URLs are not supported')
    return str(value)


def _versioned_url(url, identity):
    parsed=urlsplit(url)
    if parsed.hostname not in {'www.medrxiv.org','medrxiv.org','www.biorxiv.org','biorxiv.org'}:
        return False
    if not identity['doi'] or not identity['version']:return False
    if identity['version'].startswith('posted-'):
        date=identity['version'][7:].replace('-','/')
        suffix=identity['doi'].split('/',1)[1]
        return bool('/early/'+date+'/' in parsed.path and re.search(r'/'+re.escape(suffix)+r'(?:\.\d+)?\.full\.pdf$',parsed.path,re.I))
    return bool(re.search(re.escape(identity['doi'])+re.escape(identity['version'])+r'(?:[./]|$)', parsed.path, re.I))


def _article_layout_identity(page, identity):
    """Require a standalone title heading and own DOI label in one column."""
    from collections import Counter
    import fitz
    title=identity['title'];expected=_normal(title)
    if not expected:return None
    # A record that carries a DOI is identified by that DOI, so the title has to
    # be a full title before layout evidence may stand in for a DOI label. A
    # record without a DOI has nothing but its title, so the layout evidence is
    # collected for it as well; the caller still requires an official record
    # that binds the PMID and the title before the evidence is accepted.
    if identity['doi'] and (len(re.findall(r'\w+',title))<6 or len(title)<35):return None
    blocks=[];sizes=Counter()
    for raw in page.get_text('dict',sort=False)['blocks']:
        lines=[];spans=[]
        for line in raw.get('lines',[]):
            lines.append({'text':''.join(s['text'] for s in line['spans']),'bbox':line['bbox']});spans.extend(line['spans'])
        if not spans:continue
        for span in spans:sizes[round(span['size'],1)]+=len(_normal(span['text']))
        blocks.append({'text':' '.join(l['text'] for l in lines),'bbox':raw['bbox'],'lines':lines,'spans':spans})
    if not sizes:return None
    body_size=sizes.most_common(1)[0][0]
    reference=re.compile(r'^\s*(?:references|bibliography|literature cited)\s*\d*\s*$',re.I)
    preprint_header=any(re.search(r"(?:medrxiv|biorxiv)\s+preprint",b["text"],re.I) for b in blocks)
    candidates=list(blocks)
    ordered=sorted(blocks,key=lambda b:(b['bbox'][1],b['bbox'][0]))
    def heading(block):
        spans=[v for v in block['spans'] if len(_normal(v['text']))>=3]
        return bool(spans and (min(v['size'] for v in spans)>=body_size*1.15 or
                    min(v['size'] for v in spans)>=body_size*1.05 and all(v['flags'] & 16 for v in spans)))
    def heading_run(block):
        """The heading-sized text of a block.

        A scanned journal page often prints a small banner line in the same
        text block as the article title below it — "Bulletin of the World
        Health Organization, 58 (2): 165-182 (1980)" above "Human monkeypox,
        1970-79".  The banner is not part of the title, so the title is the
        heading-sized run of the block.  The run still has to equal the
        expected title exactly, so this only widens where a title is looked
        for, not what counts as a title.
        """
        spans=[v for v in block['spans'] if len(_normal(v['text']))>=3]
        if not spans:return None
        big=[v for v in spans if v['size']>=body_size*1.15]
        if big:return ''.join(v['text'] for v in big)
        if min(v['size'] for v in spans)>=body_size*1.05 and all(v['flags'] & 16 for v in spans):
            return ''.join(v['text'] for v in spans)
        return None
    for index,first in enumerate(ordered):
        if not heading(first) or not expected.startswith(_normal(first['text'])):continue
        joined=dict(first);joined['spans']=list(first['spans'])
        for following in ordered[index+1:]:
            a=fitz.Rect(joined['bbox']);b=fitz.Rect(following['bbox'])
            if b.y0-a.y1>80:break
            if min(a.x1,b.x1)-max(a.x0,b.x0)<=min(a.width,b.width)*.25:continue
            if not heading(following):break
            combined=joined['text']+' '+following['text']
            if not expected.startswith(_normal(combined)):break
            joined={**joined,'text':combined,'bbox':list(a|b),'spans':joined['spans']+following['spans']}
            candidates.append(joined)
    for block in candidates:
        box=fitz.Rect(block['bbox'])
        if box.y0>page.rect.height*.65:continue
        run=heading_run(block)
        if run is None or _normal(run)!=expected:continue
        major=[s['size'] for s in block['spans'] if len(_normal(s['text']))>=3]
        def same_column(bbox):
            region=fitz.Rect(bbox)
            return min(region.x1,box.x1)-max(region.x0,box.x0)>min(region.width,box.width)*.25
        lines=[l for b in blocks for l in b['lines'] if same_column(l['bbox'])]
        ends=[l['bbox'][1] for l in lines if l['bbox'][1]>=box.y1 and reference.fullmatch(l['text'])]
        end=min(ends,default=page.rect.height)
        prior=any(l['bbox'][1]<box.y0 and reference.fullmatch(l['text']) for l in lines)
        section=' '.join(l['text'] for l in lines if box.y1<=l['bbox'][1]<end)
        if prior and not re.search(r'author affiliations|received|accepted|abstract|correspondence|copyright|©',section,re.I):continue
        compound=bool(prior or box.y0>page.rect.height*.25)
        own=[];matched_bbox=None
        for line in lines:
            y=line['bbox'][1]
            if y>=end or (prior and y<box.y0 and not preprint_header):continue
            labelled=bool(re.match(r'^\s*(?:doi\s*[: ]|https?://(?:dx\.)?doi\.org/|(?:medrxiv|biorxiv)\s+preprint.*doi)',line['text'],re.I))
            if not labelled:continue
            found=[_doi(v) for v in re.findall(r'10\.\d{4,9}/[^\s<>]+',line['text'],re.I)]
            own.extend(found)
            if identity['doi'] and identity['doi'] in re.sub(r'\s+','',line['text']).casefold():matched_bbox=list(line['bbox'])
        return {'mode':'standalone_heading_and_own_doi_label' if matched_bbox else
                ('standalone_heading_requires_official_record_binding' if not identity['doi'] else 'standalone_heading_requires_official_doi_binding'),
                'title_text':run,'title_bbox':list(box),'doi_bbox':matched_bbox,'own_doi_identifiers':own,
                'title_font_min':min(major),'body_font_mode':body_size,'preceding_material_in_title_column':compound,
                'scope_instruction':'The requested article begins at this title. Exclude preceding material in its column; another column on the same page may already continue the requested article.' if compound else 'The requested article begins at this title.'}
    return None


def _doi_label_present(pdf, doi):
    """True when the expected DOI is printed as a DOI label in the document.

    Some publishers print a document's own DOI label on its closing page
    rather than on the first article page, for example the correspondence
    block that ends a journal letter. A DOI that only appears inside a
    References list is a citation and never counts, so every page's reference
    list is excluded before the search.
    """
    if not doi:return False
    target=_doi(doi)
    if not target:return False
    pattern=re.compile(r'(?:doi\s*[:：]\s*|doi\.org/|https?://(?:dx\.)?doi\.org/)'+re.escape(target),re.I)
    reference_heading=r'(?im)^\s*(?:references|bibliography|literature cited)\s*\d*\s*$'
    for candidate in pdf:
        body=candidate.get_text(sort=True)
        body=re.split(reference_heading,body,maxsplit=1)[0]
        if pattern.search(body):return True
        # A CJK typesetter often prints the document's own DOI label in
        # full-width characters and sets spaces around the slash, for example
        # "ＤＯＩ:１０.１６４６２ / ｊ.ｃｎｋｉ.ｚｈｊｂｋｚ.２０２２.０１.０１９".
        # The label is still the document's own DOI, so the compatibility
        # characters are folded and the typesetter's spacing around the
        # slash is removed before the same label-anchored match is made. The
        # expected DOI is unchanged, and a DOI that appears only inside the
        # reference list is still excluded above.
        folded=unicodedata.normalize('NFKC',body)
        folded=re.sub(r'\s*/\s*','/',folded)
        if pattern.search(folded):return True
    return False


def _title_block_match(page, expected):
    """True when the expected title is carried by one block in the article's own top region.

    A two-column layout — a supplement contents page, an abstract book — is
    read in interleaved column order, so the lines of a title are split by the
    neighbouring column's text and the title never appears as one run in the
    page's sorted text. The title is still there, as one block in one column,
    so the blocks are checked directly. Every page's reference list is
    excluded, exactly as in the sorted-text comparison, so a cited title is
    still never identity evidence.
    """
    import fitz
    if not expected:
        return False
    reference_heading = re.compile(r'(?i)^\s*(?:references|bibliography|literature cited)\s*\d*\s*$')
    blocks = []
    for raw in page.get_text('dict', sort=False)['blocks']:
        lines = [{'text': ''.join(s['text'] for s in line['spans']), 'bbox': list(line['bbox'])}
                 for line in raw.get('lines', [])]
        if not lines:
            continue
        blocks.append({'text': ' '.join(line['text'] for line in lines), 'bbox': list(raw['bbox'])})
    if not blocks:
        return False
    limit = page.rect.height * .65

    def in_reference_section(block):
        return any(
            reference_heading.match(other['text'].strip())
            and other['bbox'][1] < block['bbox'][1]
            and abs(other['bbox'][0] - block['bbox'][0]) < 60
            for other in blocks
        )

    for index, block in enumerate(blocks):
        if block['bbox'][1] > limit or reference_heading.match(block['text'].strip()):
            continue
        if in_reference_section(block):
            continue
        if _normal(block['text']) == expected:
            return True
        # A title that the publisher split over consecutive blocks in one column.
        # A publisher that centers the title sets each line further to the
        # right than the one above it, so the continuation of a centered
        # title is identified by its horizontal centre falling inside the
        # span already collected, not by sharing the first line's left edge.
        span = list(block['bbox'])
        joined = block['text']
        for following in blocks[index + 1:]:
            if following['bbox'][1] > limit:
                break
            if following['bbox'][1] - span[3] > 30:
                break
            centre = (following['bbox'][0] + following['bbox'][2]) / 2
            inside = span[0] <= centre <= span[2]
            if not inside and abs(following['bbox'][0] - span[0]) > 60:
                break
            if not expected.startswith(_normal(joined)):
                break
            joined = joined + ' ' + following['text']
            span = [min(span[0], following['bbox'][0]), min(span[1], following['bbox'][1]),
                    max(span[2], following['bbox'][2]), max(span[3], following['bbox'][3])]
            if _normal(joined) == expected:
                return True
    return False


def inspect_pdf_identity(path, row, *, source_url=None, downloaded=False):
    """Read-only PDF identity check. Never accept filename as bibliographic proof."""
    import fitz
    path=Path(path);identity=_identity(row)
    if not path.is_file() or path.stat().st_size>MAX_PDF_BYTES or not path.read_bytes().startswith(b'%PDF-'):
        raise ValueError('Document is not a supported bounded PDF')
    # A journal in another language is indexed under a translated title, in
    # square brackets, while the document is printed under its original title.
    # The official record keeps that original title beside the translation, so
    # the document's own printed title is checked against the record's
    # vernacular title as well. Both are official titles of the same article.
    binding=row.get('_official_identity_binding') or {}
    ncbi_valid=(binding.get('provider')=='ncbi_efetch' and
                str(binding.get('pmid'))==str(identity['pmid']) and
                _normal(binding.get('title',''))==_normal(identity['title']) and
                re.fullmatch(r'[0-9a-f]{64}',str(binding.get('response_sha256',''))))
    vernacular=_normal(binding.get('vernacular_title','')) if ncbi_valid else ''
    with fitz.open(path) as pdf:
        if not pdf.page_count:raise ValueError('Empty PDF')
        pages=pdf.page_count
        article_page=0
        # Recognized repository/publisher distribution covers are not article
        # identity evidence. Inspect the actual first article page instead.
        while article_page<min(2,pages-1):
            cover=pdf[article_page].get_text(sort=True)
            folded=cover.casefold()
            is_cover=('hal id:' in folded and 'submitted on' in folded or
                      'elsevier has created' in folded and ('information center' in folded or 'resource centre' in folded))
            if not is_cover:break
            article_page+=1
        page=pdf[article_page]
        layout_identity=_article_layout_identity(page,identity)
        text=page.get_text(sort=True)
        first_page=text
        header=page.get_text(clip=fitz.Rect(0,0,page.rect.width,page.rect.height*.65),sort=True)
        label_doi_match=_doi_label_present(pdf,identity['doi'])
        block_title_match=_title_block_match(page,_normal(identity['title']))
        vernacular_block_match=_title_block_match(page,vernacular) if vernacular else False
    # A cited title/DOI in References is never a document's own identity. This
    # cut applies even on the first article page of a short report.
    reference_heading=r'(?im)^\s*(?:references|bibliography|literature cited)\s*\d*\s*$'
    text=re.split(reference_heading,text,maxsplit=1)[0]
    header=re.split(reference_heading,header,maxsplit=1)[0]
    leading_lines=[line.strip() for line in first_page.splitlines() if line.strip()][:12]
    supplemental=any(re.fullmatch(r'(?:supplementary (?:material|materials|information|appendix)|supplemental (?:material|materials|digital content)|supporting information|(?:technical|online|supplementary|supplemental) appendix|appendix)(?:\s*[A-Z0-9.:-]*)?',line,re.I) for line in leading_lines)
    if supplemental and row.get('role') not in {'supplement','supplementary','appendix'}:
        raise ValueError('PDF is supplementary material, not the requested primary report')
    compact=re.sub(r'\s+','',text).casefold()
    # The DOI may be printed as its own label on a later page of the article
    # instead of on the first one. Both forms are the publisher's own DOI
    # label, and the expected DOI still has to be the one that is printed.
    doi_match=bool(identity['doi'] and identity['doi'] in compact) or bool(label_doi_match)
    # Full supplied titles bind independently; short citation aliases are not titles.
    full_title=len(re.findall(r'\w+',identity['title']))>=6 and len(identity['title'])>=35
    vernacular_match=bool(vernacular and (vernacular in _normal(header) or vernacular_block_match))
    # A two-column page interleaves the columns in reading order, so the title
    # is looked for in the page's own blocks as well as in the sorted text.
    title_match=bool(full_title and (_normal(identity['title']) in _normal(header) or block_title_match or vernacular_match))
    doi_binding=None
    europepmc_valid=(binding.get('provider')=='europepmc' and binding.get('doi')==identity['doi'] and
                     (not identity['pmid'] or str(binding.get('pmid'))==identity['pmid']) and
                     _normal(binding.get('title',''))==_normal(identity['title']) and
                     re.fullmatch(r'[0-9a-f]{64}',str(binding.get('response_sha256',''))))
    pmc_aws_valid=False
    if binding.get('provider')=='pmc_aws':
        parsed_source=urlsplit(str(source_url or ''))
        source_md5=re.search(r'(?:^|&)md5=([0-9a-f]{32})(?:&|$)',parsed_source.query,re.I)
        expected_md5=str(binding.get('pdf_md5') or '').lower()
        actual_md5=hashlib.md5(path.read_bytes()).hexdigest()
        expected_prefix=f"{binding.get('pmcid')}.{binding.get('version')}/"
        pmc_aws_valid=bool(
            parsed_source.scheme=='https' and parsed_source.hostname=='pmc-oa-opendata.s3.amazonaws.com' and
            str(binding.get('doi') or '').lower()==str(identity['doi'] or '').lower() and
            str(binding.get('pmcid') or '')==str(row.get('pmcid') or row.get('PMCID') or '') and
            _normal(binding.get('title',''))==_normal(identity['title']) and
            binding.get('is_pmc_openaccess') is True and binding.get('is_manuscript') is False and
            binding.get('is_retracted') is False and
            re.fullmatch(r'[0-9a-f]{64}',str(binding.get('metadata_sha256',''))) and
            source_md5 and source_md5.group(1).lower()==expected_md5==actual_md5 and
            unquote(parsed_source.path.lstrip('/')).startswith(expected_prefix)
        )
    if layout_identity:
        layout_identity['page']=article_page+1
        own=layout_identity['own_doi_identifiers']
        # An own-header DOI can only conflict with an expected DOI. A record
        # without a DOI has nothing to compare it against; its own DOI labels
        # stay in the evidence instead of failing the document.
        if identity['doi'] and any(not _same_pdf_article_doi(value, identity['doi']) for value in own):
            raise ValueError('PDF own-header DOI conflicts with expected publication; metadata cannot substitute another version')
        if layout_identity['doi_bbox']:
            doi_match=title_match=True
        else:
            valid=europepmc_valid or pmc_aws_valid
            if valid:
                title_match=True
                if source_url and urlsplit(source_url).hostname in {'www.medrxiv.org','medrxiv.org','www.biorxiv.org','biorxiv.org'} and not str(identity['doi'] or '').startswith('10.1101/'):
                    raise ValueError('A preprint source URL cannot substitute a formal publication DOI')
                doi_binding={'type':'official_metadata_plus_own_title',**binding}
            else:layout_identity=None
    # Some publisher PDFs omit the DOI from their first-page text layer or
    # encode title punctuation with a nonstandard glyph. Accept only when a
    # matching official Europe PMC/PMC AWS record binds the DOI, version and
    # PDF checksum, and the first-page PDF carries either the expected DOI or
    # the expected full title. A conflicting own-header DOI is still rejected.
    if not doi_binding and (europepmc_valid or pmc_aws_valid) and (doi_match or title_match):
        title_match=True
        doi_binding={'type':'official_metadata_plus_pdf_checksum' if pmc_aws_valid else 'official_metadata_plus_own_title',**binding}
    if identity['doi'] and not doi_match and not doi_binding:
        raise ValueError('PDF DOI does not match the expected publication')
    if full_title and not title_match:
        raise ValueError('PDF title does not match the expected publication (a reference DOI alone is insufficient)')
    if identity['pmid'] and not (doi_match or title_match):
        raise ValueError('PMID PDF requires a matching expected DOI or full title; filename is not identity evidence')
    version_evidence=None
    if identity['version']:
        date=str(row.get('version_date') or (identity['version'][7:] if identity['version'].startswith('posted-') else ''))
        if date:
            expected=datetime.strptime(date,'%Y-%m-%d').strftime('%B %d, %Y')
            expected=re.sub(r'\b0(\d),',r'\1,',expected)
            posted=re.findall(r'this\s+version\s+posted\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})',text,re.I)
            if not any(_normal(value)==_normal(expected) for value in posted):
                raise ValueError('PDF preprint posting date does not match the requested version')
            version_evidence={'type':'pdf_posting_date','date':date}
        elif downloaded and source_url and _versioned_url(source_url,identity):
            version_evidence={'type':'official_versioned_download','url':source_url}
        else:
            raise ValueError('Preprint version requires verified posting date or an actual official versioned download')
    return {'status':'verified' if doi_match or title_match else 'explicit_user_pdf',
            'doi_binding':doi_binding,
            'expected':identity,'doi_match':doi_match,'title_match':title_match,'version_evidence':version_evidence,
            'identity_article_page':article_page+1,'identity_title_region':'own_heading_blocks' if layout_identity else 'first_article_page_top_65_percent',
            'identity_doi_region':'official_metadata_binding_not_pdf_text' if doi_binding else 'own_header_doi_label_same_column' if layout_identity else 'document_doi_label_excluding_references' if label_doi_match else 'first_article_page_excluding_references',
            'article_boundary_hint':layout_identity,
            'document_kind':'supplement' if supplemental else 'primary_or_unclassified',
            'pdf_sha256':_sha(path),'bytes':path.stat().st_size,'pages':pages}


def _fulltext_urls(hit):
    """The official record's own list of full-text URLs, in either shape."""
    entries=hit.get('fullTextUrlList') or []
    if isinstance(entries,dict):entries=entries.get('fullTextUrl') or []
    return [v for v in entries if isinstance(v,dict)]


def _metadata(row, *, allow_network):
    """Resolve identifiers through official Europe PMC metadata, without labels."""
    identity=_identity(row);result=dict(row)
    if not allow_network:return result
    if identity['pmid']:
        query='EXT_ID:'+identity['pmid']+' AND SRC:MED'
    elif identity['doi']:
        query='DOI:"'+identity['doi']+'"'
    else:return result
    response=requests.get('https://www.ebi.ac.uk/europepmc/webservices/rest/search',
                          params={'query':query,'format':'json','resultType':'core'},timeout=20)
    response.raise_for_status()
    hits=response.json().get('resultList',{}).get('result',[])
    if identity['pmid']:
        hits=[h for h in hits if str(h.get('id'))==identity['pmid'] or str(h.get('pmid'))==identity['pmid']]
    if not hits:return result
    hit=hits[0];observed=_doi(hit.get('doi'))
    if identity['doi'] and observed and observed!=identity['doi']:
        # A record can carry more than one DOI.  EID registered the same
        # article twice while it was migrating its archive, and Europe PMC
        # lists both of them in the record's own full-text URL list.  That list
        # is the official record's own statement that the requested DOI belongs
        # to this record, so a DOI that appears there is accepted; a DOI that
        # the record does not list is still a conflict.
        listed={_doi(v.get('url')) for v in _fulltext_urls(hit) if v.get('documentStyle')=='doi'}
        if identity['doi'] not in listed:
            raise ValueError('Official PMID metadata conflicts with the requested DOI')
        result['_official_record_also_lists_doi']=sorted(listed)
    declared_title=identity['title'];official_title=hit.get('title') or ''
    if len(declared_title)>=35 and len(re.findall(r'\w+',declared_title))>=6 and official_title and _normal(declared_title)!=_normal(official_title):
        raise ValueError('Official bibliographic metadata conflicts with the explicitly declared full title')
    result['doi']=identity['doi'] or observed or None
    if identity['version']:result['preprint_version']=identity['version']
    result['title']=hit.get('title') or identity['title']
    result['pmcid']=result.get('pmcid') or hit.get('pmcid')
    result['_metadata_source']='europepmc'
    result['_official_identity_binding']={'provider':'europepmc','pmid':str(hit.get('id')) if hit.get('source')=='MED' else hit.get('pmid'),
        'doi':result['doi'],'title':result['title'],'lookup_url':'https://www.ebi.ac.uk/europepmc/webservices/rest/search',
        'response_sha256':hashlib.sha256(json.dumps(hit,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}
    result['_metadata_fulltext_urls']=[v.get('url') for v in (hit.get('fullTextUrlList') or {}).get('fullTextUrl',[]) if v.get('documentStyle')=='pdf' and v.get('availability')=='Open access']
    return result


def _preprint_date(row, *, allow_network):
    identity=_identity(row)
    if str(identity['version'] or '').startswith('posted-'):
        return {**row,'version_date':identity['version'][7:]}
    if row.get('version_date') or not str(identity['doi'] or '').startswith('10.1101/') or not allow_network:
        return row
    if not identity['version']:
        raise ValueError('Original preprint version is undeclared; provide vN or an official frozen posting-date URL, never assume latest')
    server='medrxiv' if 'medrxiv' in str(row.get('record_id','')).lower() or 'medrxiv' in str(row.get('fulltext_url','')).lower() else 'biorxiv'
    # medRxiv and bioRxiv share a DOI prefix; a supplied official URL/record ID
    # selects its server. Without one, try medRxiv first, then bioRxiv.
    servers=[server] if server=='medrxiv' else ['medrxiv','biorxiv']
    for server in servers:
        response=requests.get(f'https://api.biorxiv.org/details/{server}/{identity["doi"]}',timeout=20)
        response.raise_for_status()
        matching=[item for item in response.json().get('collection',[]) if _doi(item.get('doi'))==identity['doi'] and str(item.get('version','')).isdigit()]
        for item in matching:
            if 'v'+str(item.get('version'))==identity['version']:
                return {**row,'doi':identity['doi'],'preprint_version':'v'+str(item['version']),
                        'version_date':item['date'],'preprint_server':server,'_version_metadata_source':response.url}
    raise ValueError('Requested original preprint version is not present in the official version history')


def register_pdf(row, pdf_path, *, source_url=None, downloaded=False, allow_alias_conflicts=False):
    """Validate and atomically register a known PDF without overwriting old bytes."""
    identity=_identity(row)
    if str(identity['doi'] or '').startswith('10.1101/') and not identity['version']:
        raise ValueError('Preprint registration requires a specific version or frozen official posting-date URL')
    verified=inspect_pdf_identity(pdf_path,row,source_url=source_url,downloaded=downloaded)
    verified['pmid_binding'] = ('official_metadata' if row.get('_metadata_source')=='europepmc' else 'operator_import_assertion') if identity['pmid'] else 'not_applicable'
    digest=verified['pdf_sha256'];root=pool_root();canonical=root/'pdfs/by_sha256'/(digest+'.pdf')
    if canonical.exists() and _sha(canonical)!=digest:raise ValueError('Content-addressed PDF asset is corrupt')
    if not canonical.exists():_atomic(canonical,Path(pdf_path).read_bytes())
    aliases=[]
    supplement=row.get('role') in {'supplement','supplementary','appendix'}
    if identity['pmid'] and not supplement:aliases.append(root/'pdfs'/('PMID_'+identity['pmid']+'.pdf'))
    if identity['doi']:aliases.append(root/'pdfs'/('DOI_'+hashlib.sha256(identity['doi'].encode()).hexdigest()[:20]+('_'+identity['version'] if identity['version'] else '')+('_supp_'+hashlib.sha256(_key(identity,row).encode()).hexdigest()[:12] if supplement else '')+'.pdf'))
    conflicts=[]
    for alias in aliases:
        if alias.exists() and _sha(alias)!=digest:
            # Never overwrite/quarantine an unrelated publication without an
            # explicit operator decision. Immutable assets remain untouched.
            if not allow_alias_conflicts:
                raise ValueError('Existing PDF identity alias conflicts with verified source; explicit quarantine is required')
            conflicts.append({'path':str(alias),'sha256':_sha(alias),'status':'stale_alias_preserved'})
    aliases=[alias for alias in aliases if not any(str(alias)==entry['path'] for entry in conflicts)]
    for alias in aliases:
        if not alias.exists():_atomic(alias,canonical.read_bytes())
    info={'schema_version':1,'identity_key':_key(identity,row),'identity':identity,'verification':verified,
          'pdf_path':str(canonical),'pdf_aliases':[str(p) for p in aliases],
          'stale_alias_conflicts':conflicts,
          'source_url':source_url,'source_metadata':row.get('_pdf_source_witness'),'version_date':row.get('version_date') or (verified.get('version_evidence') or {}).get('date'),
          'registered_at':datetime.now(timezone.utc).isoformat()}
    path=_registry_path(identity,row);_atomic(path,info)
    alias_keys=[row.get('record_id')]
    if identity['pmid'] and not supplement:alias_keys.append('pmid:'+identity['pmid'])
    for key in alias_keys:
        if key:_atomic(root/'registry/aliases'/(hashlib.sha256(str(key).encode()).hexdigest()+'.json'),{'identity_key':info['identity_key'],'registry_path':str(path)})
    return info


def _cached(row):
    identity=_identity(row)
    # The request must bind a preprint version before observing any cached
    # registry/alias. A cached vN is evidence about that asset, not a version
    # declaration by this caller; do not backfill the request from observations.
    if str(identity['doi'] or '').startswith('10.1101/') and not identity['version']:
        raise ValueError('Original preprint version is undeclared; provide vN or an official frozen posting-date URL, never infer it from cached observations')
    path=_registry_path(identity,row)
    exact_binding=path.is_file()
    if not path.is_file() and (row.get('record_id') or identity['pmid']):
        for key in (row.get('record_id'),'pmid:'+identity['pmid'] if identity['pmid'] else None):
            if not key:continue
            alias=pool_root()/'registry/aliases'/(hashlib.sha256(str(key).encode()).hexdigest()+'.json')
            if alias.is_file():
                path=Path(json.loads(alias.read_text())['registry_path']);break
    if not path.is_file():return None
    info=json.loads(path.read_text());observed=info['identity']
    for key in ('pmid','doi'):
        if identity[key] and identity[key]!=observed.get(key):raise ValueError('Registry identity/version conflicts with requested source')
    if identity['version'] and identity['version']!=observed.get('version'):
        # A generic record alias can point to another valid version. It is not
        # an exact cache hit for this request, so acquire the requested version;
        # never substitute the aliased version or mutate its immutable assets.
        if not exact_binding and identity['doi'] and identity['doi']==observed.get('doi'):
            return None
        raise ValueError('Registry identity/version conflicts with requested source')
    declared_title=identity['title'];stored_title=observed.get('title') or ''
    full_declared=len(declared_title)>=35 and len(re.findall(r'\w+',declared_title))>=6
    full_stored=len(stored_title)>=35 and len(re.findall(r'\w+',stored_title))>=6
    if full_declared and full_stored and _normal(declared_title)!=_normal(stored_title):
        raise ValueError('Cached publication identity conflicts with the explicitly declared full title')
    if info['verification']['status']!='verified':return None
    pdf=Path(info['pdf_path'])
    if not pdf.is_file() or _sha(pdf)!=info['verification']['pdf_sha256']:raise ValueError('Registered PDF is missing or its hash changed')
    verify_row={**row,**{k:v for k,v in observed.items() if v is not None},'version_date':info.get('version_date')}
    if full_declared:verify_row['title']=declared_title
    binding=info['verification'].get('doi_binding') or {}
    if binding.get('type') in {'official_metadata_plus_own_title','official_metadata_plus_pdf_checksum'}:
        verify_row['_official_identity_binding']=binding
        if binding.get('provider')=='pmc_aws':
            verify_row['pmcid']=binding.get('pmcid')
    fresh_verification=inspect_pdf_identity(pdf,verify_row,source_url=info.get('source_url'),downloaded=info['verification'].get('version_evidence',{}).get('type')=='official_versioned_download' if info['verification'].get('version_evidence') else False)
    info['verification']={**info['verification'],**fresh_verification}
    for value in info.get('pdf_aliases') or []:
        alias=Path(value)
        if not alias.resolve().is_relative_to(pool_root()/'pdfs'):
            raise ValueError('Registered PDF alias is outside the paper pool')
        if alias.exists() and _sha(alias)!=info['verification']['pdf_sha256']:
            raise ValueError('Registered PDF alias contains conflicting source bytes; quarantine is required')
        if not alias.exists():_atomic(alias,pdf.read_bytes())
    return info


def _download(url):
    url=_public_url(url)
    with requests.get(url,timeout=45,stream=True,headers={'User-Agent':'MetaAgent-Epi/0.3 (open-access fulltext)'}) as response:
        response.raise_for_status();content=bytearray()
        for chunk in response.iter_content(65536):
            content.extend(chunk)
            if len(content)>MAX_PDF_BYTES:raise ValueError('Document exceeds the download byte budget')
        resolved=_public_url(response.url)
    return bytes(content),resolved


def _candidate_urls(row):
    identity=_identity(row);seen=set()
    candidates=[]
    for name in ('fulltext_url','pdf_url','download_url','url'):
        value=row.get(name)
        if value and (name!='url' or '.pdf' in str(value).lower()):candidates.append((str(value),'explicit_url'))
    if identity['doi'] and identity['doi'].startswith('10.1101/') and re.fullmatch(r'v\d+',identity['version'] or ''):
        for server in ([row['preprint_server']] if row.get('preprint_server') else ['medrxiv','biorxiv']):
            candidates.append((f'https://www.{server}.org/content/{identity["doi"]}{identity["version"]}.full.pdf','official_preprint'))
    for value in row.get('_metadata_fulltext_urls') or []:candidates.append((value,'europepmc_oa'))
    for value,route in candidates:
        if value not in seen:
            seen.add(value);yield value,route
    candidates=[]
    pmcid=str(row.get('pmcid') or row.get('PMCID') or '')
    if pmcid and not re.fullmatch(r'PMC\d+',pmcid,re.I):raise ValueError('Invalid PMCID')
    cloud_status=None
    if not identity['version'] and not str(identity['doi'] or '').startswith('10.1101/'):
        from metaagent.pmc_cloud import resolve_pmcid, discover_pmc_pdf
        if not pmcid and (identity['pmid'] or identity['doi']):
            lookup=resolve_pmcid(pmid=identity['pmid'],doi=identity['doi'],session=requests)
            row.setdefault('_discovery_attempts',[]).append({'route':'pmc_idconv','status':lookup['status'],'attempts':lookup.get('attempts',[])})
            if lookup['status']=='ready':
                pmcid=lookup['pmcid'];row['pmcid']=pmcid;row['_pmc_idconv_witness']=lookup
        if pmcid:
            cloud=discover_pmc_pdf(pmcid,session=requests);cloud_status=cloud['status']
            row.setdefault('_discovery_attempts',[]).append({'route':'pmc_cloud_discovery','status':cloud_status,'attempts':cloud.get('attempts',[])})
            if cloud_status=='ready':
                candidates.append((cloud['pdf_url'],'pmc_cloud_pdf'))
                witness=next((v for v in cloud.get('candidates',[]) if v.get('url')==cloud['pdf_url']),{})
                row.setdefault('_pdf_source_witnesses',{})[cloud['pdf_url']]={'provider':'pmc_cloud','pmcid':pmcid,**witness}
                metadata=witness.get('metadata') or {}
                row['_official_identity_binding']={
                    'provider':'pmc_aws','doi':_doi(metadata.get('doi')),'pmcid':pmcid,
                    'version':witness.get('pmc_deposit_version'),'title':metadata.get('title') or '',
                    'metadata_sha256':witness.get('metadata_response_sha256'),
                    'pdf_md5':witness.get('pdf_md5'),'is_pmc_openaccess':metadata.get('is_pmc_openaccess'),
                    'is_manuscript':metadata.get('is_manuscript'),'is_retracted':metadata.get('is_retracted'),
                    'license_code':metadata.get('license_code'),
                }
    if pmcid and cloud_status!='pending' and not identity['version'] and not str(identity['doi'] or '').startswith('10.1101/'):
        if not re.fullmatch(r'PMC\d+',pmcid,re.I):raise ValueError('Invalid PMCID')
        candidates.append((f'https://europepmc.org/articles/{pmcid}?pdf=render','europepmc_pdf'))
    for value,route in candidates:
        if value not in seen:
            seen.add(value);yield value,route
    candidates=[]
    email=os.environ.get('UNPAYWALL_EMAIL') or os.environ.get('NCBI_EMAIL')
    if identity['doi'] and email and not identity['version']:
        from tools.literature.sources import unpaywall
        try:
            data=unpaywall(identity['doi'],email)
            for location in data.get('oa_locations') or []:
                if location.get('url_for_pdf'):candidates.append((location['url_for_pdf'],'unpaywall'))
        except (requests.RequestException,ValueError) as exc:
            row.setdefault('_discovery_attempts',[]).append({'route':'unpaywall_discovery','status':'failed','error_type':type(exc).__name__})
    for value,route in candidates:
        if value not in seen:
            seen.add(value);yield value,route


def resolve_document(row, directory, *, require_pdf=True, parse=True, cache_policy='strict', allow_network=True):
    """Return one explicit per-record outcome, never silently omit a source.

    fulltext_ready includes exact parsed source/hash; failed acquisition is
    fulltext_unavailable with acquisition_attempts/failure_reason. Explicit user
    Markdown remains usable and honestly reports pdf_status=not_provided.
    """
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    row=dict(row);attempts=[]
    try:
        identity=_identity(row)
    except ValueError as exc:
        record_id=str(row.get('record_id') or 'invalid-identity:'+hashlib.sha256(json.dumps(row,sort_keys=True,default=str).encode()).hexdigest()[:20])
        failed={**row,'record_id':record_id,'record_status':'fulltext_unavailable','fulltext_path':None,
                'pdf_path':None,'pdf_status':'unavailable','failure_reason':str(exc),'failure_type':'ValueError','acquisition_attempts':[]}
        _atomic(directory/(hashlib.sha256(record_id.encode()).hexdigest()[:20]+'.acquisition.json'),failed)
        return failed
    record_id=str(row.get('record_id') or ('pmid:'+identity['pmid'] if identity['pmid'] else 'doi:'+identity['doi']+(':'+identity['version'] if identity['version'] else '') if identity['doi'] else 'document:'+hashlib.sha256(str(row.get('fulltext_path') or row.get('path') or row.get('fulltext_url') or row.get('url')).encode()).hexdigest()[:20]))
    row['record_id']=record_id;tag=hashlib.sha256(record_id.encode()).hexdigest()[:20]
    def finish(value):
        value['acquisition_attempts']=attempts
        _atomic(directory/(tag+'.acquisition.json'),value)
        return value
    try:
        local=row.get('fulltext_path') or row.get('path') or row.get('pdf_path')
        if local and Path(local).suffix.lower() in {'.md','.txt'}:
            source=Path(local).resolve()
            if not source.is_file():raise ValueError('Explicit user text document is missing')
            text=source.read_text(encoding='utf-8-sig')
            if not text.strip():raise ValueError('Explicit user text document is empty')
            target=directory/(tag+'.md');_atomic(target,text.encode())
            return finish({**row,'record_status':'fulltext_ready','fulltext_path':str(target),'pdf_path':None,'pdf_status':'not_provided','source_sha256':_sha(source),'fulltext_sha256':_sha(target),'parser_route':'provided_structured_text','access_route':'explicit_user_text','primary_document_source':str(source),'failure_reason':None})
        cached=_cached(row)
        if local:
            if not Path(local).is_file():
                raise ValueError('Explicit PDF document is missing')
            if cached and _sha(local)!=cached['verification']['pdf_sha256']:
                raise ValueError('Explicit PDF bytes differ from the registered source; specify a distinct source_version or independent paper pool rather than substituting cached bytes')
        route='identity_registry_cache'
        if cached is None:
            legacy=pool_root()/'pdfs'/('PMID_'+identity['pmid']+'.pdf') if identity['pmid'] else None
            if local and not Path(local).is_file():raise ValueError('Explicit PDF document is missing')
            candidate=Path(local).resolve() if local else legacy if legacy and legacy.is_file() else None
            # Metadata/network failures never authorize an unverified filename.
            if identity['pmid'] and allow_network or not identity['doi'] and not identity['title'] or candidate is None:
                try:row=_metadata(row,allow_network=allow_network)
                except (requests.RequestException,ValueError,ET.ParseError) as exc:
                    attempts.append({'route':'metadata','status':'failed','error_type':type(exc).__name__})
                    if identity['pmid'] or 'conflict' in str(exc).lower():raise
                if identity['pmid'] and allow_network and row.get('_metadata_source')!='europepmc':
                    raise ValueError('Official PMID metadata is unavailable; an unverified PMID alias cannot be published')
            if (identity['version'] and candidate is not None) or (str(_identity(row)['doi'] or '').startswith('10.1101/') and not _identity(row)['version']):
                row=_preprint_date(row,allow_network=allow_network)
                identity=_identity(row)
            rejected_legacy=False
            if candidate:
                try:
                    cached=register_pdf(row,candidate,source_url=row.get('source_url') or row.get('fulltext_url'))
                    route='verified_local_pdf'
                except ValueError as exc:
                    if local:
                        raise
                    rejected_legacy=True
                    attempts.append({'route':'legacy_pdf_cache','status':'cache_rejected','pdf_path':str(candidate),
                                     'pdf_sha256':_sha(candidate),'reason':str(exc)})
            if cached is None:
                if not allow_network:
                    rejected=next((attempt.get('reason') for attempt in reversed(attempts) if attempt.get('status')=='cache_rejected'),None)
                    raise ValueError('No verified local PDF and acquisition network is disabled'+(': '+rejected if rejected else ''))
                candidate_error=None
                urls=_candidate_urls(row)
                for candidate_number in range(8):
                    try:url,download_route=next(urls)
                    except StopIteration:break
                    except (requests.RequestException,ValueError,ET.ParseError) as exc:
                        attempts.append({'route':'pdf_discovery','status':'failed','error_type':type(exc).__name__});break
                    try:
                        content,resolved=_download(url)
                        blobs=[]
                        if content.startswith(b'%PDF-'):blobs=[content]
                        elif download_route=='pmc_oa_tgz':
                            with tarfile.open(fileobj=io.BytesIO(content),mode='r:gz') as archive:
                                for member in archive:
                                    if member.isfile() and member.name.lower().endswith('.pdf') and member.size<=MAX_PDF_BYTES:
                                        blobs.append(archive.extractfile(member).read(MAX_PDF_BYTES+1))
                                        if len(blobs)>30:raise ValueError('OA package exceeds PDF candidate budget')
                        else:raise ValueError('Download is not a PDF')
                        for index,blob in enumerate(blobs):
                            if download_route=='pmc_cloud_pdf':
                                witness=(row.get('_pdf_source_witnesses') or {}).get(url) or {}
                                expected=str(witness.get('pdf_md5') or '').lower()
                                actual=hashlib.md5(blob).hexdigest()
                                if not re.fullmatch(r'[0-9a-f]{32}',expected) or actual!=expected:
                                    candidate_error=ValueError('PMC Cloud PDF content does not match metadata MD5')
                                    attempts.append({'route':download_route,'status':'integrity_rejected','classification':'pmc_cloud_md5_mismatch','observed_md5':actual})
                                    continue
                            temp=directory/(tag+f'.download-{index}.pdf')
                            _atomic(temp,blob)
                            try:
                                if identity['version'] and not _versioned_url(resolved,identity):raise ValueError('Preprint versioned URL redirected to an unverified version')
                                cached=register_pdf({**row,'_pdf_source_witness':(row.get('_pdf_source_witnesses') or {}).get(url)},temp,source_url=resolved,downloaded=True,allow_alias_conflicts=rejected_legacy)
                                route=download_route;break
                            except ValueError as exc:candidate_error=exc
                            finally:temp.unlink(missing_ok=True)
                        if cached:
                            attempts.append({'route':download_route,'url':url,'status':'verified','resolved_url':resolved});break
                        raise candidate_error or ValueError('OA package contains no matching article PDF')
                    except (requests.RequestException,ValueError,tarfile.TarError) as exc:
                        candidate_error=exc;attempts.append({'route':download_route,'url':url,'status':'failed','error_type':type(exc).__name__})
                attempts.extend(row.pop('_discovery_attempts',[]))
                if cached is None:raise ValueError('No identity/version-matching open PDF could be acquired')
        pdf=Path(cached['pdf_path'])
        result={**row,'pdf_path':str(pdf),'pdf_status':'verified','pdf_sha256':cached['verification']['pdf_sha256'],
                'source_sha256':cached['verification']['pdf_sha256'],'identity_verification':cached['verification'],
                'source_version':cached['identity']['version'],'primary_document_source':cached.get('source_url') or str(pdf),
                'stale_alias_conflicts':cached.get('stale_alias_conflicts',[]),
                'article_boundary_hint':cached['verification'].get('article_boundary_hint'),
                'access_route':route,'source_metadata':cached.get('source_metadata'),'registry_path':str(_registry_path(cached['identity'],row)),'failure_reason':None}
        if parse:
            from tools.mineru.cache import parse_pdf
            parsed=parse_pdf(pdf,cached['identity']['pmid'],cache_policy=cache_policy)
            target=directory/(tag+'.md');_atomic(target,parsed.text.encode())
            result.update(record_status='fulltext_ready',fulltext_path=str(target),fulltext_sha256=_sha(target),
                          parser_route=parsed.route,parser_fingerprint=parsed.parser_fingerprint)
            cached['parser']={'route':parsed.route,'path':str(parsed.path),'fingerprint':parsed.parser_fingerprint,'markdown_sha256':_sha(parsed.path)}
            _atomic(_registry_path(cached['identity'],row),cached)
        else:result.update(record_status='pdf_ready',fulltext_path=None,parser_route='not_requested')
        return finish(result)
    except Exception as exc:
        failure = str(exc)
        for name, value in os.environ.items():
            if re.search(r'(API_KEY|TOKEN|SECRET|PASSWORD)$',name) and len(value)>=8:
                failure=failure.replace(value,'[REDACTED]')
        failure=re.sub(r'\bsk-[A-Za-z0-9_-]{8,}','[REDACTED]',failure)
        return finish({**row,**locals().get('result',{}),'record_status':'fulltext_unavailable','fulltext_path':None,
                       'pdf_path':locals().get('result',{}).get('pdf_path'),
                       'pdf_status':'verified' if locals().get('cached') else 'unavailable',
                       'failure_reason':failure,'failure_type':type(exc).__name__})
