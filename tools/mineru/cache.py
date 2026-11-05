"""Versioned, content-bound MinerU assets with explicit legacy cache policy."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from metaagent.config import get_project_root, load_mineru_config

PARSE_OPTIONS = {'is_ocr', 'enable_formula', 'enable_table', 'language'}


@dataclass(frozen=True)
class CachedMarkdown:
    text: str
    path: Path
    route: str
    source_sha256: str | None = None
    parser_fingerprint: str | None = None
    assets_manifest: Path | None = None


def pool_root() -> Path:
    value = os.environ.get('METAAGENT_PAPER_POOL', '').strip()
    return Path(value).expanduser().resolve() if value else get_project_root() / 'paper_pool'


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for part in iter(lambda: f.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def parser_identity(*, model_version=None, params=None):
    if set(params or {})-PARSE_OPTIONS:
        raise ValueError('Unknown MinerU parsing option; connection configuration belongs in the environment')
    cfg = load_mineru_config(module_hint='coding')
    identity = {'parser':'mineru', 'cache_schema':2,
                'model_version':model_version or os.environ.get('MINERU_MODEL_VERSION','vlm'),
                'base_url':cfg.base_url, 'endpoint':cfg.endpoint,
                'options':{k:v for k,v in (params or {}).items() if k in PARSE_OPTIONS},
                'implementation':{name:_digest(Path(__file__).with_name(name)) for name in ('client.py','pdf_reader.py')}}
    fingerprint = hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    return identity, fingerprint


def _read(path, route, digest=None, fingerprint=None):
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError,UnicodeError):
        return None
    if not text.strip(): return None
    return CachedMarkdown(text,path,route,digest,fingerprint,path.parent/'metadata.json' if fingerprint else None)


def _verified(path, digest, fingerprint, route):
    try:
        metadata=json.loads((path.parent/'metadata.json').read_text())
        if metadata['pdf_sha256']!=digest or metadata['parser_fingerprint']!=fingerprint or metadata['markdown_sha256']!=_digest(path): return None
        for name, expected in metadata.get('asset_hashes',{}).items():
            asset=(path.parent/name).resolve()
            if not asset.is_relative_to(path.parent.resolve()) or _digest(asset)!=expected:return None
        return _read(path,route,digest,fingerprint)
    except (OSError,ValueError,KeyError,TypeError):
        return None


def find_cached(pmid=None,pdf_path=None,*,cache_policy=None,model_version=None,params=None):
    """Strict requires current parser/config; compatible also allows marked legacy.

    A versioned cache with a mismatched fingerprint is never a legacy fallback.
    """
    cache_policy=cache_policy or os.environ.get('MINERU_CACHE_POLICY','compatible')
    if cache_policy not in {'strict','compatible'}:raise ValueError('Unknown cache policy')
    _,fingerprint=parser_identity(model_version=model_version,params=params)
    root=pool_root();digest=_digest(Path(pdf_path)) if pdf_path is not None else None
    pmid=str(pmid or '').removeprefix('PMID_')
    directory=root/'markdown'/f'PMID_{pmid}'
    indexed=None
    if digest is None and pmid.isdigit():
        try:
            indexed=json.loads((directory/'mineru_index.json').read_text())['pdf_sha256']
            if len(indexed)!=64 or any(c not in '0123456789abcdef' for c in indexed):return None
            digest=indexed
        except (OSError,ValueError,KeyError,TypeError):pass
    if digest:
        base=root/'markdown/by_sha256'/digest
        found=_verified(base/fingerprint/'fulltext.md',digest,fingerprint,'mineru_pmid_cache' if indexed else 'mineru_content_cache')
        if found:return found
        # New format presence means mismatching/corrupt data must be reparsed.
        if base.is_dir() and any(p.is_dir() for p in base.iterdir()):return None
        if cache_policy=='compatible':
            try:
                meta=json.loads((base/'metadata.json').read_text())
                if meta.get('pdf_sha256')==digest and meta.get('markdown_sha256')==_digest(base/'fulltext.md'):
                    return _read(base/'fulltext.md','mineru_legacy_content_cache',digest)
            except (OSError,ValueError,TypeError):pass
    if cache_policy=='strict' or not pmid.isdigit():return None
    if pdf_path is not None:
        origins=list(directory.glob('*_origin.pdf'))
        candidates=origins or [root/'pdfs'/f'PMID_{pmid}.pdf']
        if not any(p.is_file() and _digest(p)==digest for p in candidates):return None
    for name in ('fulltext.md',f'PMID_{pmid}.md','full.md'):
        found=_read(directory/name,'mineru_legacy_cache' if pdf_path is not None else 'legacy_pmid_cache_unverified',digest)
        if found:return found
    return None


def _atomic(path,content):
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as f:
        f.write(content);tmp=Path(f.name)
    tmp.replace(path)


def parse_pdf(pdf_path,pmid=None,*,cache_policy=None,model_version=None,params=None):
    """Cache Markdown, original PDF, ZIP and extracted page/table/image assets."""
    pdf_path=Path(pdf_path)
    found=find_cached(pmid,pdf_path,cache_policy=cache_policy,model_version=model_version,params=params)
    if found:return found
    pdf_hash=_digest(pdf_path)
    identity,fingerprint=parser_identity(model_version=model_version,params=params)
    target=pool_root()/'markdown/by_sha256'/pdf_hash/fingerprint
    target.mkdir(parents=True,exist_ok=True)
    cfg=load_mineru_config(module_hint='coding')
    from tools.mineru.pdf_reader import extract_pdf_markdown_mineru
    with tempfile.TemporaryDirectory(prefix='mineru-',dir=target.parent) as tmp:
        staging=Path(tmp)
        result=extract_pdf_markdown_mineru(pdf_path,model_version=identity['model_version'],params=params,
                                         output_dir=staging/'assets',max_poll_s=max(600,cfg.timeout_s*10))
        if not result.markdown.strip():raise ValueError('MinerU returned empty markdown')
        if _digest(pdf_path)!=pdf_hash:raise ValueError('PDF changed while MinerU was parsing')
        shutil.copyfile(pdf_path,staging/'source.pdf')
        for item in staging.iterdir():
            dest=target/item.name
            if item.is_dir():shutil.copytree(item,dest,dirs_exist_ok=True)
            else:shutil.copyfile(item,dest)
    _atomic(target/'fulltext.md',result.markdown)
    raw=getattr(result,'raw_response',None) or {}
    data=raw.get('data') if isinstance(raw,dict) else None
    remote_version=(raw.get('model_version') or (data.get('model_version') if isinstance(data,dict) else None)) if isinstance(raw,dict) else None
    assets={str(p.relative_to(target)):_digest(p) for p in target.rglob('*') if p.is_file() and p.name not in {'metadata.json','fulltext.md'}}
    _atomic(target/'metadata.json',json.dumps({'pdf_sha256':pdf_hash,'markdown_sha256':_digest(target/'fulltext.md'),
        'parser_fingerprint':fingerprint,'parser_identity':identity,'asset_hashes':assets,
        'service_reported_model_version':str(remote_version)[:200] if remote_version else None,
        'asset_status':'full_result_preserved' if any(n.endswith('.zip') for n in assets) else 'markdown_only_service_result'},ensure_ascii=False,indent=2)+'\n')
    if str(pmid or '').isdigit():
        directory=pool_root()/'markdown'/f'PMID_{pmid}';directory.mkdir(parents=True,exist_ok=True)
        _atomic(directory/'mineru_index.json',json.dumps({'pdf_sha256':pdf_hash,'parser_fingerprint':fingerprint}))
    return CachedMarkdown(result.markdown,target/'fulltext.md','mineru_parsed',pdf_hash,fingerprint,target/'metadata.json')
