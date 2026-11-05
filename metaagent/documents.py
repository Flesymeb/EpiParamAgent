"""Declared primary/supplement material, coverage and source-version hashes."""
from __future__ import annotations

import hashlib
from pathlib import Path


def document_bundle(row: dict) -> tuple[str, dict]:
    """Read every declared local source; unavailable sources remain visible.

    This does not infer that undeclared supplements do not exist. Only an explicit
    complete source manifest can certify coverage for absence judgments.
    """
    from tools.mineru.cache import parse_pdf
    sources = [{"path": row.get("fulltext_path"), "source_id": "main", "role": "primary"}, *(row.get("supplements") or [])]
    text, observed, missing = [], [], []
    seen = set()
    for i, source in enumerate(sources):
        identity = source.get("source_id") or f"supplement-{i}"
        if identity in seen:
            raise ValueError("Document bundle source IDs must be unique")
        seen.add(identity)
        path = Path(source["path"]) if source.get("path") else None
        if path is None or not path.is_file():
            missing.append(identity)
            continue
        if path.suffix.lower() == ".pdf":
            value = parse_pdf(path).text
        elif path.suffix.lower() in {".md", ".txt"}:
            value = path.read_text(encoding="utf-8-sig")
        else:
            missing.append(identity)
            continue
        if not value.strip():
            missing.append(identity)
            continue
        text.append(f"[Source {identity}]\n{value}")
        observed.append({"source_id": identity, "role": source.get("role", "supplement"),
                         "path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    declared = row.get("fulltext_coverage") or {}
    missing.extend(declared.get("missing_materials") or [])
    coverage = {**declared, "complete": bool(declared.get("complete") and not missing and not declared.get("truncated")),
                "truncated": bool(declared.get("truncated")), "sources": observed, "provided_materials": [source["source_id"] for source in observed],
                "missing_materials": list(dict.fromkeys(missing)), "declared_source_count": len(sources)}
    return "\n\n".join(text), coverage


def materialize_coding_document(row: dict, directory: Path) -> dict:
    """Freeze local primary/supplement inputs as text through the shared parser.

    Uploaded PDFs retain a byte-identical source copy and explicit PDF->Markdown
    provenance. Standalone Coding does not silently perform eligibility screening.
    """
    import shutil
    from tools.mineru.cache import parse_pdf
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    record_id=str(row['record_id'])
    tag=hashlib.sha256(record_id.encode()).hexdigest()[:16]
    sources=[{'path':row.get('fulltext_path'),'source_id':'main','role':'primary'},*(row.get('supplements') or [])]
    prepared=[];seen=set()
    for source in sources:
        identity=source.get('source_id') or f'supplement-{len(prepared)}'
        if identity in seen:raise ValueError('Document bundle source IDs must be unique')
        seen.add(identity)
        path=Path(source['path']).expanduser().resolve()
        if not path.is_file():raise ValueError('Declared Coding document is missing')
        suffix=path.suffix.lower()
        if suffix not in {'.pdf','.md','.txt'}:raise ValueError('Unsupported Coding document type')
        part=tag if identity=='main' else tag+'_'+hashlib.sha256(str(identity).encode()).hexdigest()[:12]
        original=directory/f'doc_{part}.source{suffix}'
        shutil.copyfile(path,original)
        source_hash=hashlib.sha256(original.read_bytes()).hexdigest()
        if suffix=='.pdf':
            parsed=parse_pdf(original)
            text=parsed.text;route=parsed.route
            fingerprint=getattr(parsed,'parser_fingerprint',None)
        else:
            text=original.read_text(encoding='utf-8-sig');route='provided_structured_text';fingerprint=None
        if not text.strip():raise ValueError('Declared Coding document has no parsed text')
        output=directory/f'doc_{part}.md'
        output.write_text(text,encoding='utf-8')
        prepared.append({'source_id':identity,'role':source.get('role','supplement'),'path':str(output),
            'source_path':str(path),'original_path':str(original),'source_sha256':source_hash,
            'fulltext_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
            'parser_route':route,'parser_fingerprint':fingerprint})
    main=prepared[0]
    return {'record_id':record_id,'pmid':row.get('pmid') if str(row.get('pmid') or '').isdigit() else None,
        'title':row.get('title') or row.get('Title'),'path':main['path'],
        'supplements':prepared[1:],'source_documents':prepared,
        'upstream_document':{k:row[k] for k in ('primary_document_source','source_sha256','parser_route') if row.get(k) is not None}}
