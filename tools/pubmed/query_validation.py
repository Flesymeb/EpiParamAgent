"""Local PubMed syntax diagnostics, separate from remote term validation."""
from __future__ import annotations
import hashlib
import re
from pathlib import Path

_GUIDE = Path(__file__).with_name('query_guide.md')


def query_guide():
    return _GUIDE.read_text(encoding='utf-8')


def validate_pubmed_query(query):
    """Check syntax without claiming terms or remote matches were verified."""
    errors, warnings = [], []
    if not isinstance(query, str) or not query.strip():
        errors.append('empty_query')
        query = query if isinstance(query, str) else ''
    if len(query) > 20000:
        errors.append('query_exceeds_20000_characters')
    quoted, depth = False, 0
    for char in query:
        if char == '"':
            quoted = not quoted
        elif not quoted and char == '(':
            depth += 1
        elif not quoted and char == ')':
            depth -= 1
            if depth < 0:
                errors.append('unbalanced_parentheses')
                break
    if quoted:
        errors.append('unbalanced_quotes')
    if depth:
        errors.append('unbalanced_parentheses')
    unquoted = re.sub(r'"[^"]*"', 'TERM', query)
    in_tag = False
    tag_start = -1
    for index, char in enumerate(unquoted):
        if char == '[':
            if in_tag:
                errors.append('nested_field_tags')
            in_tag = True
            tag_start = index
        elif char == ']':
            if not in_tag:
                errors.append('unbalanced_field_tags')
            elif not unquoted[tag_start + 1:index].strip():
                errors.append('empty_field_tag')
            in_tag = False
    if in_tag or unquoted.count('[') != unquoted.count(']'):
        errors.append('unbalanced_field_tags')
    if re.search(r'\(\s*\)', unquoted):
        errors.append('empty_query_group')
    known = {'title/abstract','tiab','mesh terms','mh','pdat','dp','date - publication','all fields','all','publication type','pt','title','ti','author','au','journal','ta','pmid','uid','filter','sb','text word','tw','mesh major topic','majr'}
    tags = re.findall(r'\[([^\]]+)\]', unquoted)
    unknown = sorted({tag for tag in tags if tag.strip().casefold() not in known})
    if unknown:
        warnings.append('unrecognized_local_field_tags:' + ','.join(unknown))
    if re.search(r'(?:^|\()\s*(?:AND|OR)\b|\b(?:AND|OR|NOT)\s*(?:$|\))|\b(?:AND|OR|NOT)\s+(?:AND|OR|NOT)\b', unquoted):
        errors.append('dangling_boolean_operator')
    return {'status':'invalid' if errors else 'locally_valid','errors':sorted(set(errors)),'warnings':warnings,
            'query_sha256':hashlib.sha256(query.encode()).hexdigest(),'remote_validation':'not_performed',
            'mesh_descriptor_validation':'not_performed','guide':{'version':'query-guide-v1','sha256':hashlib.sha256(query_guide().encode()).hexdigest()}}


def verify_mesh_terms(terms, *, get=None):
    """Optionally verify exact descriptor labels using NLM's public lookup API.

    Unavailable requests remain unavailable. Never remove or substitute terms.
    Endpoint contract: https://id.nlm.nih.gov/mesh/swagger/swagger.json
    """
    from datetime import UTC, datetime
    import httpx
    if not isinstance(terms, list) or len(terms) > 24 or any(not isinstance(t, str) or not t.strip() or len(t) > 300 for t in terms):
        raise ValueError('MeSH verification requires up to24 nonempty strings of at most300 characters')
    get = get or httpx.get
    rows = []
    for term in dict.fromkeys(terms):
        item = {'term':term,'status':'unavailable'}
        try:
            response = get('https://id.nlm.nih.gov/mesh/lookup/descriptor', params={'label':term,'match':'exact','limit':10}, timeout=5.0)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list) or any(not isinstance(r, dict) or not isinstance(r.get('label'), str) or not re.fullmatch(r'https?://id\.nlm\.nih\.gov/mesh/D\d+', str(r.get('resource',''))) for r in data):
                raise ValueError('Malformed MeSH lookup response')
            matched = [r for r in data if r['label'].casefold() == term.strip().casefold()]
            item.update(status='verified_descriptor_label' if matched else 'no_exact_descriptor_label', matches=matched)
        except Exception as exc:
            item['error_type'] = type(exc).__name__
        rows.append(item)
    return {'status':'complete' if all(r['status'] != 'unavailable' for r in rows) else 'partial',
            'executed_at':datetime.now(UTC).isoformat(),'provider':'NLM MeSH descriptor lookup','terms':rows}
