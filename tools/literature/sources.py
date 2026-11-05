"""Small, bounded bibliographic search adapters with explicit provenance."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import html
import os
import re
from datetime import datetime, timezone
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup


def clean(value):
    return BeautifulSoup(html.unescape(str(value or '')), 'html.parser').get_text(' ', strip=True)


def doi_norm(value):
    return re.sub(r'^https?://(?:dx\.)?doi\.org/', '', str(value or '').strip(), flags=re.I).lower()


def abstract_openalex(index):
    if not isinstance(index, dict):
        return ''
    pairs = sorted((int(i), word) for word, positions in index.items() for i in positions)
    return ' '.join(word for _, word in pairs)


def _get(url, params):
    response = requests.get(url, params=params, timeout=30, headers={'User-Agent': 'MetaAgent-Epi/0.3 literature retrieval'})
    response.raise_for_status()
    return response.json()


def search(source, query, limit, *, audit=None, checkpoint=None, page_cache=None):
    """Return a bounded subset and provider total; query syntax belongs to source."""
    if limit is not None and limit < 1:
        raise ValueError('limit must be positive or None for cursor exhaustion')
    audit = audit if audit is not None else {}
    audit.update(pages=0, terminal=False, count_changed=False, complete=False)
    def fetch(url, params):
        if page_cache is None:
            return _get(url, params)
        root = Path(page_cache); root.mkdir(parents=True, exist_ok=True)
        public_params = {k:v for k,v in params.items() if k not in {'api_key', 'token'}}
        key = hashlib.sha256(json.dumps([url, public_params],sort_keys=True).encode()).hexdigest()
        path = root / (key + '.json')
        if path.exists():
            try:
                stored = json.loads(path.read_text())
                raw = json.dumps(stored['response'],sort_keys=True).encode()
                if hashlib.sha256(raw).hexdigest() == stored.get('sha256'):
                    audit['cached_pages'] = audit.get('cached_pages',0)+1
                    return stored['response']
            except (ValueError, KeyError, OSError):
                pass  # An incomplete/corrupt page is refetched, never trusted.

        data = _get(url, params)
        raw = json.dumps(data,sort_keys=True).encode()
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'response':data,'sha256':hashlib.sha256(raw).hexdigest()}))
        temporary.replace(path)
        return data
    def page(items, total, cursor, terminal):
        previous = audit.get('total_matches')
        audit['count_changed'] |= previous is not None and previous != total
        audit.update(pages=audit['pages']+1, total_matches=total, terminal=terminal)
        if checkpoint:
            checkpoint(items, dict(audit), cursor)
    if source in {'europepmc', 'medrxiv', 'biorxiv'}:
        actual = query
        if source != 'europepmc':
            actual = f'({query}) AND SRC:PPR AND PUBLISHER:{"medRxiv" if source == "medrxiv" else "bioRxiv"}'
        items, cursor, total = [], '*', None
        while limit is None or len(items) < limit:
            payload = fetch('https://www.ebi.ac.uk/europepmc/webservices/rest/search', {'query': actual, 'format':'json','resultType':'core','pageSize':min(100,limit-len(items)) if limit is not None else 100, 'cursorMark':cursor})
            total = int(payload['hitCount']); batch = payload['resultList']['result']; items.extend(batch)
            nxt = payload.get('nextCursorMark')
            terminal = not batch or not nxt or nxt == cursor
            page(batch, total, nxt, terminal)
            if terminal: break
            cursor = nxt
        rows = []
        for x in items:
            book = x.get('bookOrReportDetails') or {}; info = x.get('journalInfo') or {}; journal = info.get('journal') or {}
            fulltext = (x.get('fullTextUrlList') or {}).get('fullTextUrl') or []
            rows.append({'pmid':x.get('pmid',''), 'pmcid':x.get('pmcid',''), 'doi':doi_norm(x.get('doi')), 'title':clean(x.get('title')), 'abstract':clean(x.get('abstractText')), 'authors':x.get('authorString',''), 'journal/book':journal.get('title') or book.get('publisher',''), 'publication year':str(x.get('pubYear','')), 'pub_types':(x.get('pubTypeList') or {}).get('pubType') or ('preprint' if x.get('source') == 'PPR' else ''), 'keywords':(x.get('keywordList') or {}).get('keyword') or [], 'mesh_terms':[h.get('descriptorName') for h in (x.get('meshHeadingList') or {}).get('meshHeading',[]) if h.get('descriptorName')], 'language':x.get('language') or '', 'publication_date':x.get('firstPublicationDate') or '', 'url':f"https://europepmc.org/article/{x.get('source')}/{x.get('id')}", 'fulltext_url':next((p.get('url','') for p in fulltext if p.get('documentStyle') == 'pdf' and p.get('availability') == 'Open access'), ''), 'source_id':x.get('id','')})
        audit['complete'] = bool(audit['terminal'] and not audit['count_changed'] and len({r['source_id'] for r in rows}) == total and len(rows) == total)
        return rows, total, actual
    if source == 'openalex':
        rows, cursor, total = [], '*', None
        while limit is None or len(rows) < limit:
            params={'search':query,'per-page':min(100,limit-len(rows)) if limit is not None else 100, 'cursor':cursor}
            if os.getenv('OPENALEX_API_KEY'): params['api_key']=os.environ['OPENALEX_API_KEY']
            data=fetch('https://api.openalex.org/works',params); total=data['meta']['count']
            for x in data['results']:
                ids=x.get('ids') or {}; location=x.get('best_oa_location') or {}; primary=x.get('primary_location') or {}; src=primary.get('source') or {}
                rows.append({'pmid':str(ids.get('pmid') or '').rsplit('/',1)[-1], 'pmcid':str(ids.get('pmcid') or '').rsplit('/',1)[-1], 'doi':doi_norm(x.get('doi')), 'title':x.get('display_name') or '', 'abstract':abstract_openalex(x.get('abstract_inverted_index')), 'authors':', '.join((a.get('author') or {}).get('display_name','') for a in (x.get('authorships') or [])), 'journal/book':src.get('display_name') or '', 'publication year':str(x.get('publication_year') or ''), 'pub_types':x.get('type') or '', 'keywords':[k.get('display_name') for k in x.get('keywords',[]) if k.get('display_name')], 'language':x.get('language') or '', 'publication_date':x.get('publication_date') or '', 'url':x.get('id') or '', 'fulltext_url':location.get('pdf_url') or '', 'source_id':x.get('id') or ''})
            nxt=data['meta'].get('next_cursor')
            terminal = not data['results'] or not nxt or nxt == cursor
            page(data['results'], total, nxt, terminal)
            if terminal: break
            cursor=nxt
        audit['complete'] = bool(audit['terminal'] and not audit['count_changed'] and len({r['source_id'] for r in rows}) == total and len(rows) == total)
        return rows,total,query
    if source == 'crossref':
        rows,cursor,total=[], '*', None
        while limit is None or len(rows)<limit:
            params={'query.bibliographic':query,'rows':min(100,limit-len(rows)) if limit is not None else 100,'cursor':cursor}
            if os.getenv('CROSSREF_EMAIL'): params['mailto']=os.environ['CROSSREF_EMAIL']
            data=fetch('https://api.crossref.org/works',params)['message'];total=data['total-results'];batch=data['items']
            for x in batch:
                date=x.get('published') or {}; parts=(date.get('date-parts') or [[]])[0]
                rows.append({'doi':doi_norm(x.get('DOI')), 'title':clean((x.get('title') or [''])[0]), 'abstract':clean(x.get('abstract')), 'authors':', '.join(' '.join(filter(None,[a.get('given'),a.get('family')])) for a in (x.get('author') or [])), 'journal/book':(x.get('container-title') or [''])[0], 'publication year':str(parts[0]) if parts else '', 'pub_types':x.get('type',''), 'language':x.get('language') or '', 'publication_date':'-'.join(str(part) for part in parts), 'url':x.get('URL',''), 'source_id':x.get('DOI','')})
            nxt=data.get('next-cursor')
            terminal = not batch or not nxt or nxt == cursor
            page(batch, total, nxt, terminal)
            if terminal: break
            cursor=nxt
        audit['complete'] = bool(audit['terminal'] and not audit['count_changed'] and len({r['source_id'] for r in rows}) == total and len(rows) == total)
        return rows,total,query
    if source == 'pubmed':
        from tools.pubmed.client import PubMedClient
        if limit is None:
            raise ValueError('Unbounded PubMed requires the partitioned workflow adapter')
        client=PubMedClient(); papers=client.search(query,retmax=limit)
        rows=[{'pmid':p.id.removeprefix('pubmed:'),'pmcid':getattr(p,'pmcid',''),'doi':doi_norm(p.doi),'title':p.title,'abstract':p.abstract,'authors':', '.join(p.authors),'journal/book':p.journal_ref or '', 'publication year':str(p.published.year) if p.published.year > 1900 else '', 'url':f"https://pubmed.ncbi.nlm.nih.gov/{p.id.removeprefix('pubmed:')}/", 'keywords':getattr(p,'keywords',[]), 'mesh_terms':getattr(p,'mesh_terms',[]), 'pub_types':getattr(p,'pub_types',[]), 'language':getattr(p,'language',[]), 'publication_date':getattr(p,'publication_date',''), 'source_id':p.id} for p in papers]
        return rows,client.last_total,query
    raise ValueError('Unsupported source')


def unpaywall(doi, email):
    if not doi_norm(doi): raise ValueError('DOI is required')
    if not email or '@' not in email: raise ValueError('Set UNPAYWALL_EMAIL in .env.local')
    return _get('https://api.unpaywall.org/v2/'+quote(doi_norm(doi),safe='/'), {'email':email})


def now():
    return datetime.now(timezone.utc).isoformat()
