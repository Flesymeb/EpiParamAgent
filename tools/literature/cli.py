"""Explicit, bounded multi-source search and OA PDF retrieval."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import click
import requests

from metaagent.config import load_runtime_env
from tools.literature.sources import doi_norm, now, search, unpaywall

SOURCES = ('pubmed','europepmc','medrxiv','biorxiv','openalex','crossref')


def merge(records):
    """Merge only shared DOI or PMID without contradictory identifiers."""
    result=[]
    for row in records:
        row=dict(row); row['doi']=doi_norm(row.get('doi')); row['pmid']=str(row.get('pmid') or '').strip()
        row['sources']=[row.pop('source')]; row['source_records']=[{'source':row['sources'][0],'source_id':row.pop('source_id','')}]
        found=[]
        for i, other in enumerate(result):
            same=(row['doi'] and row['doi']==other.get('doi')) or (row['pmid'] and row['pmid']==other.get('pmid'))
            conflict=any(row.get(k) and other.get(k) and row[k]!=other[k] for k in ('doi','pmid'))
            if same and not conflict:found.append(i)
        # Ambiguous links must remain separate for review.
        if len(found)!=1:
            result.append(row);continue
        target=result[found[0]]
        for k,v in row.items():
            if k not in {'sources','source_records'} and not target.get(k) and v:target[k]=v
        target['sources']=list(dict.fromkeys(target['sources']+row['sources']))
        target['source_records'].extend(row['source_records'])
    for row in result:
        row['source'] = ','.join(row['sources'])
        # Make ambiguous records independently addressable by the workflow.
        row['record_id']='source:'+hashlib.sha256(json.dumps(row['source_records'],sort_keys=True).encode()).hexdigest()[:20]
    return result


@click.group()
def literature():
    """Search multiple literature sources and find open PDFs."""


@literature.command('import-native')
@click.option('--input', 'inputs', multiple=True, required=True, type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option('--format', 'fmt', required=True, type=click.Choice(['ris','scopus-csv','wos-csv','wos-tsv']))
@click.option('--execution-log', required=True, type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option('--out', required=True, type=click.Path(path_type=Path, file_okay=False))
def import_native(inputs, fmt, execution_log, out):
    """Import declared complete Embase/Scopus/WoS exports and execution provenance.

    This converter does not contact paid databases. All export parts and counts
    are checked; accession numbers are never guessed to be PubMed identifiers.
    """
    from tools.benchmark_v2.import_native_export import convert_native_exports
    try:
        result = convert_native_exports(inputs, fmt=fmt, execution_log=execution_log, output_dir=out)
    except (ValueError, OSError, ImportError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Imported {result['records']} records: {out / 'records.jsonl'}")


@literature.command('search')
@click.option('--source','sources',multiple=True,type=click.Choice(SOURCES),required=True,help='Repeat for each source. Query syntax differs by source.')
@click.option('--query',required=True,help='Native query for the selected source(s).')
@click.option('--limit',type=click.IntRange(1,1000),default=100,show_default=True,help='Maximum records per source; results may be incomplete.')
@click.option('--out',type=click.Path(path_type=Path,file_okay=False),required=True,help='New output directory.')
def search_command(sources,query,limit,out):
    """Search a bounded subset and write source exports, merged JSONL and manifest."""
    load_runtime_env(); sources=list(dict.fromkeys(sources))
    if out.exists() and any(out.iterdir()): raise click.ClickException('Output directory must be empty')
    out.mkdir(parents=True,exist_ok=True); all_rows=[]; stats=[]
    for source in sources:
        try:
            rows,total,actual=search(source,query,limit)
            for row in rows:row['source']=source
            (out/(source+'.jsonl')).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
            all_rows.extend(rows)
            stats.append({'source':source,'query':actual,'total_matches':total,'retrieved':len(rows),'limit':limit,'complete':False,'reported_count_reached':total is not None and len(rows)>=total,'completion_note':'Count equality is not independently validated; bounded export is not certified complete.','status':'success'})
        except Exception as exc:
            stats.append({'source':source,'query':query,'status':'failed','error_type':type(exc).__name__})
    rows=merge(all_rows)
    (out/'records.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
    manifest={'created_at':now(),'query_input':query,'source_results':stats,'records_before_merge':len(all_rows),'records_after_merge':len(rows),'merge_policy':'exact DOI or PMID with no conflicting IDs; possible duplicates and preprint/published versions require review','query_note':'Queries are source-specific. Results are bounded and not a claim of exhaustive systematic retrieval.'}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    click.echo(json.dumps(manifest,ensure_ascii=False))
    if any(s['status']=='failed' for s in stats):raise click.exceptions.Exit(1)


@literature.command('pdf')
@click.option('--doi',required=True,help='DOI of the target article.')
@click.option('--out',type=click.Path(path_type=Path,dir_okay=False),required=True,help='New PDF file path.')
def pdf_command(doi,out):
    """Find and download an OA PDF using Unpaywall; write provenance alongside it."""
    load_runtime_env()
    if out.exists() or out.with_suffix(out.suffix+'.json').exists():raise click.ClickException('Output PDF or provenance already exists')
    try:data=unpaywall(doi,os.getenv('UNPAYWALL_EMAIL') or os.getenv('NCBI_EMAIL',''))
    except Exception as exc:raise click.ClickException(f'Unpaywall lookup failed: {type(exc).__name__}') from exc
    locations=data.get('oa_locations') or []; errors=[]
    for loc in locations:
        url=loc.get('url_for_pdf') or ''
        if urlsplit(url).scheme not in ('http','https'):continue
        try:
            with requests.get(url,timeout=40,stream=True,headers={'User-Agent':'MetaAgent-Epi/0.3'}) as response:
                response.raise_for_status(); content=bytearray()
                for chunk in response.iter_content(65536):
                    content.extend(chunk)
                    if len(content)>50*1024*1024:raise ValueError('PDF exceeds 50 MiB')
                if not content.startswith(b'%PDF-'):raise ValueError('Response is not a PDF')
            out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(content)
            info={'doi':doi_norm(doi),'source':'unpaywall','url':url,'resolved_url':response.url,'license':loc.get('license'),'version':loc.get('version'),'retrieved_at':now(),'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content)}
            out.with_suffix(out.suffix+'.json').write_text(json.dumps(info,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
            click.echo(json.dumps(info,ensure_ascii=False));return
        except (requests.RequestException,ValueError) as exc:errors.append(type(exc).__name__)
    raise click.ClickException('No downloadable OA PDF found' + (f' ({len(errors)} attempted)' if errors else ''))


@literature.command('enrich')
@click.option('--dataset-root',type=click.Path(path_type=Path,exists=True,file_okay=False),required=True)
@click.option('--out',type=click.Path(path_type=Path,file_okay=False),required=True,help='Separate derived metadata workspace; never modifies the release.')
@click.option('--online',is_flag=True,help='Permit public metadata requests; default is offline.')
@click.option('--resume',is_flag=True,help='Reuse existing ledger and completed lookups.')
@click.option('--xml-root',multiple=True,type=click.Path(path_type=Path,exists=True,file_okay=False),help='Local bibliographic XML cache to reuse first.')
@click.option('--max-requests',type=click.IntRange(0,10000),default=500,show_default=True)
def enrich_command(dataset_root,out,online,resume,xml_root,max_requests):
    """Fill absent bibliography fields with source receipts and a label-free view.

    COVERAGE_REPORT.json retains missing field denominators. MODEL_IDENTITY_MAP.jsonl
    maps opaque model keys. No scientific labels or inferred metadata are used.
    """
    from metaagent.screening.metadata_completion import run_completion
    if out.exists() and any(out.iterdir()) and not resume:
        raise click.ClickException('Output contains data; use --resume or a new --out')
    try:
        result=run_completion(dataset_root,out,online=online,xml_roots=xml_root,max_online_requests=max_requests)
    except (ValueError,OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Completed {result['rows']} rows; field coverage: {out / 'COVERAGE_REPORT.json'}")
