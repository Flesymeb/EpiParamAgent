"""Grounded, executable Pi synthesis orchestration (no model arithmetic accepted)."""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import sqlite3
import uuid
import zipfile
import xml.etree.ElementTree as ET

from .execution import file_sha
from .pi_tools import _finite, _write

DEFAULT_SETTINGS = {'max_turns': 12, 'max_tokens': 64000, 'total_timeout_s': 900, 'exec_timeout_s': 120,
                    'max_executions': 3, 'max_tool_calls': 80, 'max_output_bytes': 16777216,
                    'max_output_files': 64, 'max_log_bytes': 65536, 'memory_bytes': 2147483648}

SKILL_DIR = Path(__file__).with_name('skills')


def _skill_documents():
    """Read the skill manuals that the agent may pull on demand."""
    documents = []
    for path in sorted(SKILL_DIR.glob('*.md')) if SKILL_DIR.is_dir() else []:
        text = path.read_text(encoding='utf-8')
        name = path.stem
        description = ''
        if text.startswith('---'):
            header, _, body = text.partition('\n---')
            for line in header.splitlines()[1:]:
                if line.startswith('description:'):
                    description = line.split(':', 1)[1].strip()
            text = body.lstrip('\n')
        documents.append({'name': name, 'description': description, 'text': text})
    return documents


def _settings(settings):
    value = {**DEFAULT_SETTINGS}
    for key, item in (settings or {}).items():
        if key in {'backend', 'research_question', 'method_sources'}: continue
        if key == 'pi_command' and item is None: continue
        if key not in {*DEFAULT_SETTINGS, 'pi_command'}:
            raise ValueError('Unsupported synthesis setting: ' + str(key))
        if key == 'pi_command':
            if not isinstance(item, (str, list)): raise ValueError('pi_command must be a string or argument list')
        elif type(item) not in (int, float) or item <= 0:
            raise ValueError('Synthesis budgets must be positive finite numbers')
        value[key] = item
    _finite(value)
    if value['max_executions'] > 8 or value['max_tool_calls'] > 200:
        raise ValueError('Synthesis execution/tool budgets exceed supported bounds')
    return value


def _safe_source(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file(): raise ValueError('Source must be an existing regular file')
    if re.search(r'(^|[_.-])(gold|oracle|ground.?truth|coding_reference|synthesis_reference|expected_results)([_.-]|$)', path.name, re.I) or any(re.fullmatch(r'gold|oracle|ground.?truth', part, re.I) for part in path.parent.parts):
        raise ValueError('Gold, oracle and reference files cannot be synthesis inputs')
    if path.stat().st_size > 64 * 1024 * 1024: raise ValueError('Source exceeds the 64 MiB staging limit')
    return path.resolve()


def _read_records(input_path, records):
    if (input_path is None) == (records is None): raise ValueError('Supply exactly one of input_path or records')
    if input_path is not None:
        path = _safe_source(input_path)
        from .cli import read_estimates
        records = read_estimates(path)
    if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
        raise ValueError('Coding inputs must be a list of record objects')
    if len(records) > 100000: raise ValueError('Coding input exceeds 100000 rows')
    _finite(records)
    return records


def _credential_check(value, private=None):
    text = json.dumps(value, ensure_ascii=False)
    if re.search(r'\bsk-[A-Za-z0-9_-]{8,}', text): raise ValueError('Credential-like material cannot be staged')
    for key, secret in (private or {}).items():
        if ('key' in key.lower() or 'secret' in key.lower()) and isinstance(secret,str) and len(secret)>=8 and secret in text:
            raise ValueError('Private model credentials cannot be staged')


def _review_context(value, private=None):
    """Copy an optional shared review protocol without inventing missing fields."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError('review_context must be an object or null')
    _finite(value)
    encoded=json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False)
    if len(encoded.encode())>65536:
        raise ValueError('review_context exceeds the 64 KiB context limit')
    _credential_check(value,private)
    return json.loads(encoded)


def _source_role(path, roles):
    normalized={str(Path(key).resolve()):value for key,value in (roles or {}).items()}
    role=normalized.get(str(Path(path).resolve()),'original_methods')
    if role not in {'original_methods','primary_study'}:raise ValueError('Source role must be original_methods or primary_study')
    return role


def pi_synthesis_fingerprint(*, input_path=None, records=None, research_question='', review_context=None, method_sources=None, source_roles=None, protocol=None, settings=None, runtime_overrides=None):
    """Read-only fingerprint; empty planned input is allowed and explicitly pending."""
    rows = _read_records(input_path, records)
    review_context = _review_context(review_context, runtime_overrides)
    config = _settings(settings)
    from .pi_runtime import synthesis_generation_binding
    generation = synthesis_generation_binding(runtime_overrides)
    sources = [{'name': Path(p).name, 'sha256': file_sha(_safe_source(p)), 'role': _source_role(p,source_roles)} for p in (method_sources or [])]
    payload = {'input_sha256': file_sha(Path(input_path)) if input_path else hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest(),
               'research_question': research_question, 'review_context': review_context, 'method_sources': sources, 'protocol': protocol, 'settings': config,
               'generation_binding': generation,
               'row_count': len(rows), 'input_pending': not rows,
               'implementation': {p.name:file_sha(p) for p in [Path(__file__), Path(__file__).with_name('pi_tools.py'), Path(__file__).with_name('execution.py'), Path(__file__).with_name('engine.py'), Path(__file__).with_name('methods.py'), Path(__file__).with_name('statistical_verification.py'), Path(__file__).with_name('diagnostics.py'), Path(__file__).resolve().parents[2]/'tools/analysis/pooling.py', Path(__file__).resolve().parents[1]/'evidence_search.py', Path(__file__).resolve().parents[1]/'prompts/synthesis/statistics_guide.md', Path(__file__).with_name('pi_runtime.py'), Path(__file__).with_name('pi_extension.ts'), Path(__file__).resolve().parents[1]/'prompts/synthesis/pi_agent.md', *sorted(SKILL_DIR.glob('*.md'))]}}
    _credential_check(payload, runtime_overrides)
    return {**payload, 'fingerprint': hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()}


def _source_text(path):
    suffix = path.suffix.lower()
    if suffix in {'.txt', '.md', '.json', '.yaml', '.yml'}: return path.read_text(encoding='utf-8')
    if suffix in {'.html', '.htm'}:
        from bs4 import BeautifulSoup
        return BeautifulSoup(path.read_text(encoding='utf-8'), 'html.parser').get_text('\n')
    if suffix == '.docx':
        with zipfile.ZipFile(path) as z:
            info=z.getinfo('word/document.xml')
            if info.file_size>16*1024*1024: raise ValueError('DOCX text exceeds staging budget')
            tree=ET.fromstring(z.read(info))
        return '\n'.join(''.join(p.itertext()) for p in tree.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'))
    if suffix == '.pdf':
        import fitz
        with fitz.open(path) as pdf:
            text='\n'.join(f'[Page {i+1}]\n'+page.get_text() for i,page in enumerate(pdf))
        if len(text.strip())<40: raise ValueError('PDF has no usable local text; supply its verified cached parsed text')
        return text
    raise ValueError('Method sources support PDF, DOCX, HTML, MD and TXT')


def _prepare_workspace(*, input_path=None, records=None, research_question, review_context=None, method_sources=None, source_roles=None, output_dir, protocol=None, settings=None, runtime_overrides=None):
    rows=_read_records(input_path,records); config=_settings(settings)
    review_context=_review_context(review_context,runtime_overrides)
    if not isinstance(research_question,str) or not research_question.strip():raise ValueError('A research question is required')
    if protocol is not None and not isinstance(protocol,dict):raise ValueError('Pi accepts one protocol object or null')
    _credential_check([rows,research_question,protocol,config],runtime_overrides)
    staged_sources=[]
    for source in method_sources or []:
        source=_safe_source(source);text=_source_text(source)
        if len(text)>8*1024*1024:raise ValueError('Method source text exceeds staging budget')
        _credential_check(text,runtime_overrides);staged_sources.append((source,text,_source_role(source,source_roles)))
    workspace=Path(output_dir).resolve()/'pi_workspace'/uuid.uuid4().hex
    for directory in ('inputs','sources','helpers','skills','code','receipts','executions'):(workspace/directory).mkdir(parents=True,exist_ok=True)
    canonical=[];seen=set()
    for index,row in enumerate(rows):
        item=dict(row);candidate=item.get('estimate_id') or item.get('input_id')
        identifier=str(candidate) if candidate and str(candidate) not in seen else 'row_'+str(index+1)+'_'+hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:12]
        if identifier in seen:raise ValueError('Cannot construct unique input identities')
        seen.add(identifier);item['input_id']=identifier;canonical.append(item)
    table=workspace/'inputs/table.jsonl';table.write_text(''.join(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n' for row in canonical))
    _write(workspace/'inputs/original_records.json',rows)
    _write(workspace/'inputs/review_context.json',review_context)
    if input_path:shutil.copyfile(input_path,workspace/'inputs'/('original_input'+Path(input_path).suffix.lower()))
    columns=sorted({key for row in canonical for key in row})
    if len(columns)>256 or any(not isinstance(c,str) or len(c)>128 or '\x00' in c for c in columns):raise ValueError('Invalid or excessive coding columns')
    columns=list(dict.fromkeys(['input_id',*columns,'raw_json']))
    quote=lambda s:'"'+s.replace('"','""')+'"'
    with sqlite3.connect(workspace/'inputs/records.sqlite') as db:
        db.execute('CREATE TABLE estimates ('+', '.join(quote(c) for c in columns)+')')
        for row in canonical:
            data={**row,'raw_json':json.dumps(row,ensure_ascii=False)}
            values=[json.dumps(data[c],ensure_ascii=False) if isinstance(data.get(c),(dict,list)) else data.get(c) for c in columns]
            db.execute('INSERT INTO estimates VALUES ('+','.join('?' for _ in columns)+')',values)
    profile={'research_question':research_question,'review_context':review_context,'plan_contract_version':2 if review_context is not None else 1,'row_count':len(canonical),'columns':[{'name':c,'types':sorted({type(r[c]).__name__ for r in canonical if r.get(c) is not None}),'null_count':sum(r.get(c) is None for r in canonical)} for c in columns if c!='raw_json'],
             'sample':[{k:(str(v)[:200] if isinstance(v,(dict,list,str)) else v) for k,v in list(row.items())[:20]} for row in canonical[:3]],
             'paths':{'table':'/inputs/table.jsonl','sqlite':'/inputs/records.sqlite','plan':'/analysis_plan.json','output':'/work/result.json'}}
    _write(workspace/'inputs/profile.json',profile)
    sources=[]
    for index,(source,text,role) in enumerate(staged_sources,1):
        identifier=f'method_{index:03d}';(workspace/'sources/originals').mkdir(exist_ok=True);original=workspace/'sources/originals'/(identifier+source.suffix.lower());shutil.copyfile(source,original)
        target=workspace/'sources'/(identifier+'.txt');target.write_text(text)
        sources.append({'source_id':identifier,'role':role,'name':source.name,'text_path':str(target.relative_to(workspace)),'original_path':str(original.relative_to(workspace)),'original_sha256':file_sha(source),'text_sha256':file_sha(target),'characters':len(text)})
    if protocol is not None:
        target=workspace/'sources/protocol.txt';_write(target,protocol)
        sources.append({'source_id':'protocol','role':'protocol','name':'explicit protocol','text_path':'sources/protocol.txt','original_path':'sources/protocol.txt','original_sha256':file_sha(target),'text_sha256':file_sha(target),'characters':len(target.read_text())})
    # The helper is a local deterministic option, not a restriction on generated methods.
    for package in ('metaagent','metaagent/synthesis','tools','tools/analysis'):
        directory=workspace/'helpers'/package;directory.mkdir(parents=True,exist_ok=True);(directory/'__init__.py').write_text('')
    for filename in ('engine.py','methods.py','plots.py','statistical_verification.py','diagnostics.py'):
        shutil.copyfile(Path(__file__).with_name(filename),workspace/'helpers/metaagent/synthesis'/filename)
    project=Path(__file__).resolve().parents[2]
    shutil.copyfile(project/'tools/analysis/pooling.py',workspace/'helpers/tools/analysis/pooling.py')
    (workspace/'helpers/epi_synthesis_helpers.py').write_text('from metaagent.synthesis.engine import run_synthesis\n')
    skills=[]
    for document in _skill_documents():
        target=workspace/'skills'/(document['name']+'.md');target.write_text(document['text'])
        skills.append({'name':document['name'],'description':document['description'],'path':str(target.relative_to(workspace)),
                       'sha256':file_sha(target),'characters':len(document['text'])})
    _write(workspace/'workspace.json',{'research_question':research_question,'review_context':review_context,'plan_contract_version':2 if review_context is not None else 1,'review_context_sha256':file_sha(workspace/'inputs/review_context.json'),'sources':sources,'skills':skills,'input_sha256':file_sha(table),'original_input_sha256':file_sha(Path(input_path)) if input_path else None,'original_input_path':str(Path(input_path).resolve()) if input_path else None,'row_count':len(rows)})
    _write(workspace/'run_settings.json',config)
    return workspace


def _failure_artifacts(output, error):
    """A rejected attempt never replaces an existing claimed result."""
    directory=output/'attempt_diagnostics'/uuid.uuid4().hex
    directory.mkdir(parents=True,exist_ok=True)
    value={'status':'failed','result':None,'error':error,'artifacts':{'synthesis_result':str(directory/'synthesis_result.json'),'synthesis_report':str(directory/'report.md')}}
    _write(directory/'synthesis_result.json',value)
    (directory/'report.md').write_text('# Pi synthesis attempt\n\nStatus: failed\n\n'+error['message']+'\n')
    return value


def _public_error(exc, private):
    message=re.sub(r'\bsk-[A-Za-z0-9_-]{8,}','[REDACTED]',str(exc))
    for key,secret in (private or {}).items():
        if ('key' in key.lower() or 'secret' in key.lower()) and isinstance(secret,str) and len(secret)>=8:
            message=message.replace(secret,'[REDACTED]')
    return {'type':type(exc).__name__,'message':message[:500]}


def _runtime_diagnostic(value, private):
    """Preserve actionable transport errors while redacting credential strings."""
    if isinstance(value,str):return _public_error(ValueError(value),private)['message']
    if isinstance(value,dict):return {key:_runtime_diagnostic(item,private) for key,item in value.items()}
    if isinstance(value,list):return [_runtime_diagnostic(item,private) for item in value]
    return value


def _verified_reuse(workspace, final):
    from .pi_tools import finalize
    value=json.loads(final.read_text())
    if value.get('status')!='complete':return None
    # Recheck all code/input/plan/output hashes; never trust status alone.
    finalize(workspace,{'execution_id':value['execution_id']})
    return json.loads(final.read_text())


def run_pi_synthesis(*, input_path=None, records=None, research_question, review_context=None, method_sources=None, source_roles=None, output_dir, protocol=None, settings=None, runtime_overrides=None, resume=False):
    """Run Pi against bounded tools, with input-bound output claims and continuation.

    Complete verified same-input results are reused. An incomplete same-input
    run requires resume=True and continues its existing workspace/session.
    Different inputs require a different output directory.
    """
    import fcntl
    output=Path(output_dir).resolve();workspace=None;session={};artifacts={};claim=None;owned=False
    try:
        fingerprint=pi_synthesis_fingerprint(input_path=input_path,records=records,research_question=research_question,review_context=review_context,method_sources=method_sources,source_roles=source_roles,protocol=protocol,settings=settings,runtime_overrides=runtime_overrides)
        _credential_check([research_question,protocol,settings],runtime_overrides)
    except Exception as exc:
        return _failure_artifacts(output,_public_error(exc,runtime_overrides))
    output.mkdir(parents=True,exist_ok=True)
    lock=(output/'.pi_synthesis.lock').open('a')
    try:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('This output directory already has an active Pi synthesis run')
        manifest=output/'pi_synthesis_manifest.json'
        if manifest.exists():
            claim=json.loads(manifest.read_text())
            if claim['fingerprint']!=fingerprint['fingerprint']:
                raise ValueError('Output directory is claimed by different input/question/methods/settings; choose a new output directory')
            workspace=Path(claim['workspace']).resolve()
            if not workspace.is_relative_to(output) or workspace.is_symlink() or not workspace.is_dir():raise ValueError('Invalid existing workspace claim')
            final=workspace/'final_result.json'
            if final.exists():
                reused=_verified_reuse(workspace,final)
                if reused is not None:
                    reused['reused']=True
                    return reused
            if not resume:raise ValueError('An incomplete same-input run exists; pass --resume to continue its workspace and Pi session')
        else:
            if (output/'synthesis_result.json').exists():raise ValueError('Output directory contains an unclaimed synthesis result; choose a new output directory')
            workspace=_prepare_workspace(input_path=input_path,records=records,research_question=research_question,review_context=review_context,method_sources=method_sources,source_roles=source_roles,output_dir=output,protocol=protocol,settings=settings,runtime_overrides=runtime_overrides)
            claim={'fingerprint':fingerprint['fingerprint'],'input_bindings':fingerprint,'workspace':str(workspace),'status':'running'}
        owned=True
        claim['status']='running';_write(manifest,claim)
        options=_settings(settings)
        continuation=claim.get('session_path')
        if resume and not continuation:
            found=sorted((workspace/'pi/sessions').glob('*.jsonl'),key=lambda p:p.stat().st_mtime) if (workspace/'pi/sessions').exists() else []
            if found:continuation=str(found[-1])
        if resume and continuation and Path(continuation).is_file():options['session_path']=continuation
        prompt_path=Path(__file__).resolve().parents[1]/'prompts/synthesis/pi_agent.md'
        prompt=prompt_path.read_text()+'\n'+prompt_path.with_name('statistics_guide.md').read_text()+'\n\nResearch question:\n'+research_question+'\n\nBegin with profile; do not ask for an entire coding table in the prompt.'
        if resume:prompt+='\nContinue the existing workspace plan/code/receipts; do not restart completed work. Tool and execution limits include prior attempts.'
        from .pi_runtime import run_pi_session
        session=run_pi_session(workspace,prompt,options,runtime_overrides=runtime_overrides,completion_guard=True)
        if session.get('session_path'):claim['session_path']=session['session_path']
        meta=json.loads((workspace/'workspace.json').read_text())
        if meta['input_sha256']!=file_sha(workspace/'inputs/table.jsonl') or meta.get('review_context_sha256') and meta['review_context_sha256']!=file_sha(workspace/'inputs/review_context.json') or input_path and meta['original_input_sha256']!=file_sha(Path(input_path)):
            raise ValueError('Original or staged coding input changed during the run')
        final=workspace/'final_result.json'
        if final.is_file():
            from .pi_tools import finalize
            final_value=json.loads(final.read_text())
            finalize(workspace,{'execution_id':final_value['execution_id']})
            result=json.loads(final.read_text());_finite(result)
            artifacts.update(result.get('artifacts',{}))
        else:
            plan=json.loads((workspace/'analysis_plan.json').read_text()) if (workspace/'analysis_plan.json').exists() else {}
            status=plan.get('reproduction_status') if plan.get('reproduction_status') in {'protocol_pending','not_computable'} else 'failed'
            reason='No verified, repeated execution was finalized'
            diagnostic={key:_runtime_diagnostic(session.get(key),runtime_overrides) for key in ('error','abort_reason') if session.get(key)}
            if diagnostic:reason+='; runtime failure: '+json.dumps(diagnostic,ensure_ascii=False)
            result={'status':status,'result':None,'reason':reason,'reproduction_status':plan.get('reproduction_status'),'counts':{'input':meta['row_count']},'validation':{'scientific_correctness':'not_independently_verified'}}
        for key,name in (('session_path','pi_session'),('events_path','pi_events'),('provider_calls_path','pi_provider_calls')):
            path=session.get(key)
            if path and Path(path).is_file() and Path(path).resolve().is_relative_to(output):artifacts[name]=str(path)
        for filename,key in [('analysis_plan.json','analysis_plan'),('analysis_selection.jsonl','analysis_selection'),('tool_events.jsonl','pi_tool_events')]:
            if (workspace/filename).is_file():artifacts.setdefault(key,str(workspace/filename))
        result['pi_runtime']={**{key:session.get(key) for key in ('status','pi_version','usage','budget')},'error':_runtime_diagnostic(session.get('error'),runtime_overrides),'abort_reason':_runtime_diagnostic(session.get('abort_reason'),runtime_overrides),'usage_scope':'current_rpc_attempt'}
        result['workspace']=str(workspace);result['reused']=False
        result['artifacts']={k:v for k,v in artifacts.items() if v}
        if 'synthesis_result' not in result['artifacts']:result['artifacts']['synthesis_result']=str(output/'synthesis_result.json')
        if 'synthesis_report' not in result['artifacts']:
            (output/'report.md').write_text(f"# Pi synthesis\n\nStatus: {result['status']}\n\n"+result.get('reason','')+'\n')
            result['artifacts']['synthesis_report']=str(output/'report.md')
        _write(output/'synthesis_result.json',result)
        claim.update(status=result['status'],result_path=str(output/'synthesis_result.json'));_write(manifest,claim)
        return result
    except Exception as exc:
        error=_public_error(exc,runtime_overrides)
        if owned and claim:
            claim['status']='failed';claim['last_error']=error;_write(output/'pi_synthesis_manifest.json',claim)
        return _failure_artifacts(output,error)
    finally:
        lock.close()
