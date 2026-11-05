"""Opt-in real-service smoke using invented data, never a scientific benchmark.

Primary flow: .venv/bin/python tools/scripts/smoke_workflow.py --provider selfhosted
  --llm-report --backend llm
Normal invocation runs only full (Stage A + Stage B). Stage ablations run only
when explicitly requested with --variants full without_a without_b.
Provider selection resolves only that provider's environment, then explicitly binds
all task modules. It never changes .env files or inherits another module's model.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from uuid import uuid4
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

MODULES = ('query', 'screening', 'coding', 'synthesis')
VARIANTS = ('full', 'without_a', 'without_b')
SCOPE = 'invented one-report transport smoke; not retrieval or scientific accuracy'
SYNTHETIC_TEXT = ('Synthetic study of invented disease X.\nThe mean incubation period was 5.0 days.\n'
                  'The 95% confidence interval was 4.0 to 6.0 days.\n'
                  'These results were estimated from one original human cohort.\n'
                  'This invented report is only a software transport test.')


def atomic_write_if_changed(path: Path, text: str) -> bool:
    """Keep semantic inputs byte-identical on reruns so resume remains meaningful."""
    if path.exists() and path.read_text(encoding='utf-8') == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)
    return True


def publish_receipt(root: Path, attempt: Path, summary: dict) -> dict:
    """Publish one immutable invocation receipt, then update the latest alias."""
    summary = _sanitize({**summary, 'attempt_id':attempt.name,
                         'receipt_path':str(attempt/'smoke_result.json')})
    path = attempt/'smoke_result.json'
    if path.exists():
        raise FileExistsError('Smoke invocation receipt already exists')
    text = json.dumps(summary,ensure_ascii=False,indent=2)+'\n'
    atomic_write_if_changed(path,text)
    atomic_write_if_changed(root/'smoke_result.json',text)
    return summary


def module_settings(*, provider=None, model=None, api_base=None, max_tokens=None, timeout=90, thinking=None):
    """Bind a selected provider using its own values, bypassing module defaults.

    Credentials are referenced by environment variable name, never copied to YAML.
    """
    from metaagent.config import (
        _normalize_provider, _provider_default_base, _provider_env_value,
        _provider_env_prefix, _PROVIDER_ENV_SPECS, load_runtime_env, normalize_api_base,
    )
    if (max_tokens is not None and max_tokens <= 0) or timeout <= 0:
        raise ValueError('max_tokens and timeout must be positive')
    if thinking not in {None, 'enabled', 'disabled'}:
        raise ValueError('thinking must be enabled or disabled')
    common = {'timeout_s': timeout}
    if thinking is not None:
        common['thinking'] = thinking
    if max_tokens is not None:
        common['max_tokens'] = max_tokens
    if provider is not None:
        load_runtime_env()
        provider = _normalize_provider(provider)
        resolved_model = model or _provider_env_value(provider, 'model_vars')
        resolved_base = api_base or _provider_env_value(provider, 'base_vars') or _provider_default_base(provider)
        if not resolved_model or not resolved_base:
            raise ValueError(f'Provider {provider} needs its own model and API base environment values or explicit overrides')
        prefix = _provider_env_prefix(provider)
        key_names = tuple(_PROVIDER_ENV_SPECS.get(provider, {}).get('key_vars', ())) + (f'{prefix}_API_KEY', f'{prefix}_KEY')
        key_env = next((name for name in key_names if os.environ.get(name)), key_names[0])
        common.update(provider=provider, model=resolved_model,
                      api_base=normalize_api_base(resolved_base, append_version=True), api_key_env=key_env)
    else:
        # Previous no-argument behavior: each configured module chooses its runtime.
        if model is not None:
            common['model'] = model
        if api_base is not None:
            common['api_base'] = normalize_api_base(api_base, append_version=True)
    return {name: dict(common) for name in MODULES}


def build_fixture(output: Path, *, backend='langextract', provider=None, model=None,
                  api_base=None, max_tokens=None, timeout=90, llm_report=False, thinking=None):
    """Create stable synthetic inputs and a declarative task, without service calls."""
    import fitz
    import yaml
    if backend not in {'llm', 'langextract'}:
        raise ValueError('Unknown extraction backend')
    settings = module_settings(provider=provider, model=model, api_base=api_base,
                               max_tokens=max_tokens, timeout=timeout, thinking=thinking)
    root = output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    pdf = root / 'synthetic.pdf'
    if not pdf.exists():
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((72, 72), SYNTHETIC_TEXT, fontsize=11)
            # PDF generation happens once; transient timestamps never rewrite inputs.
            with tempfile.NamedTemporaryFile(suffix='.pdf', dir=root, delete=False) as handle:
                temporary = Path(handle.name)
            doc.save(temporary)
            temporary.replace(pdf)
    fields = [('parameter_type','str'), ('estimate_measure','str'), ('point_estimate','float'),
              ('unit','str'), ('uncertainty_type','str'), ('uncertainty_level','str'),
              ('uncertainty_low','float'), ('uncertainty_high','float')]
    book = {'topic':'incubation_period', 'project':{'name':'Synthetic transport test','effect_type':'incubation_period'},
            'parameters':{'research_question':'Extract the reported mean incubation period.'},
            'fields':[{'name':name,'type':kind,'prompt':{'parameter_type':'incubation_period',
                'estimate_measure':'mean','uncertainty_type':'CI'}.get(name,name)} for name,kind in fields]}
    atomic_write_if_changed(root/'codebook.yaml', yaml.safe_dump(book, sort_keys=False))
    task = {'version':'1', 'task_id':'transport-smoke', 'disease':'invented disease X', 'topic':'incubation_period',
            'research_question':'What incubation period did the synthetic study report?', 'codebook':'codebook.yaml',
            'coding':{'backend':backend},
            'review_protocol':{'version':'smoke-v1','criteria':[{'id':'disease','description':'The report studies invented disease X.'}], 'logic':'disease'},
            'analysis_protocol':{'analysis_id':'smoke-mean','parameter_type':'incubation_period','estimate_measure':'mean',
                'unit':'days','method':'fixed','uncertainty_rules':{'allowed_types':['CI']},
                'independence':{'unit':'record_id','assert_independent_reports':True}},
            'llm':settings}
    if llm_report:
        task['analysis_protocol']['llm_report'] = True
    config = root/'task.yaml'
    atomic_write_if_changed(config, yaml.safe_dump(task, sort_keys=False))
    inputs = root/'inputs.jsonl'
    atomic_write_if_changed(inputs, json.dumps({'record_id':'synthetic-report','title':'Synthetic study of invented disease X',
        'abstract':'The original human study of invented disease X estimated a mean incubation period.',
        'fulltext_path':str(pdf),'fulltext_access':'public','fulltext_coverage':{'complete':True}})+'\n')
    return config, inputs, task


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return {}


def _runtime_view(runtime):
    # Explicit allowlist: model/endpoint metadata cannot carry credential values.
    return {key:runtime.get('llm_'+key, runtime.get(key)) for key in
            ('provider','model','api_base','max_tokens','timeout_s','thinking')}


def summarize_manifest(manifest: dict, *, elapsed_s=None) -> dict:
    """Summarize active attempts only, without copying raw model responses/errors."""
    runtime = manifest.get('config', {}).get('effective_llm_runtime', {})
    # The runner stores config inside its plan in some older manifests.
    if not runtime:
        runtime = manifest.get('plan', {}).get('config', {}).get('effective_llm_runtime', {})
    modules = {'retrieval':'query','screening':'screening','fulltext_screening':'screening',
               'coding':'coding','pooling':'synthesis'}
    summary = {'status':manifest.get('status','failed'), 'elapsed_walltime_s':elapsed_s,
               'artifacts':manifest.get('artifacts', {}), 'stages':{}, 'analyses':{}, 'scope':SCOPE}
    for name, stage in manifest.get('stage_results', {}).items():
        files = [Path(path) for path in stage.get('output_hashes', {})]
        files += [Path(value) for value in stage.get('artifacts', {}).values() if isinstance(value,str)]
        calls, coverage, observed = [], [], set()
        for path in sorted(set(files)):
            if path.name == 'llm_calls.jsonl' and path.is_file():
                for line in path.read_text(encoding='utf-8').splitlines():
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(event,dict):
                        continue
                    metadata = event.get('response_metadata') or {}
                    metadata = metadata if isinstance(metadata,dict) else {}
                    usage = event.get('usage') or {}
                    usage = usage if isinstance(usage,dict) else {}
                    actual = metadata.get('model_name') or metadata.get('model') or event.get('response_model')
                    if actual:
                        observed.add(str(actual))
                    seconds = event.get('walltime_s')
                    if seconds is None and isinstance(event.get('wall_time_ms'), (int,float)):
                        seconds = event['wall_time_ms']/1000
                    calls.append({'stage':event.get('stage') or event.get('module'),
                                  'status':event.get('status'), 'walltime_s':seconds,
                                  'requested_model':event.get('model'), 'response_model':actual,
                                  'usage':{key:value for key,value in usage.items()
                                           if key in {'input_tokens','output_tokens','prompt_tokens','completion_tokens','total_tokens'} and isinstance(value,(int,float))}})
            elif path.name == 'coverage.json':
                item = _read_json(path)
                coverage.append({key:item.get(key) for key in
                                 ('record_id','status','variant','stage_a_calls','stage_b_calls','completed_blocks')})
        reused = bool(stage.get('reused'))
        summary['stages'][name] = {'status':stage.get('status'), 'reused':reused,
            'attempt_walltime_s':stage.get('walltime_s'),
            'current_execution_walltime_s':0 if reused else stage.get('walltime_s'),
            'configured_runtime':_runtime_view(runtime.get(modules.get(name), {})),
            'observed_response_models':sorted(observed),
            'observed_model_status':'recorded' if observed else 'not_recorded',
            'logged_model_calls':len(calls), 'calls':calls, 'coding_coverage':coverage}
    for name, value in summary['artifacts'].items():
        if name.startswith('synthesis_result'):
            document = _read_json(value)
            summary['analyses'][name] = {'status':document.get('status'), 'result':document.get('result'),
                'counts':document.get('counts'), 'llm_report_status':document.get('llm_report',{}).get('status')}
    if manifest.get('error'):
        summary['error_type'] = manifest['error'].get('type')
    return summary


def _sanitize(value):
    """Last-mile redaction; summaries never include raw prompts, responses or keys."""
    secrets = sorted({secret for name,secret in os.environ.items()
                      if any(marker in name.upper() for marker in ('API_KEY','AUTH_TOKEN','SECRET')) and len(secret)>=8}, key=len, reverse=True)
    def redact(item):
        if isinstance(item,str):
            for secret in secrets:
                item=item.replace(secret,'[REDACTED]')
            return item
        if isinstance(item,dict):
            return {key:redact(data) for key,data in item.items()}
        if isinstance(item,list):
            return [redact(data) for data in item]
        return item
    return redact(value)


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('runs/service_smoke'))
    parser.add_argument('--backend', choices=['llm','langextract'], default='langextract')
    parser.add_argument('--provider', help='Provider name resolved from that provider environment only, e.g. selfhosted')
    parser.add_argument('--model', help='Explicit model override for every module')
    parser.add_argument('--api-base', help='Explicit API base override for every module')
    parser.add_argument('--thinking', choices=['enabled','disabled'], default=None, help='Explicit native thinking policy; otherwise inherit module settings.')
    parser.add_argument('--max-tokens', type=int, default=None, help='Explicit per-stage output budget; otherwise inherit each module configuration.')
    parser.add_argument('--timeout', type=int, default=90, help='Per-call timeout in seconds')
    parser.add_argument('--variants', choices=VARIANTS, nargs='+', default=['full'],
                        help='Explicit experiment variants; default: full (Stage A + Stage B). Ablations are opt-in.')
    parser.add_argument('--llm-report', action='store_true', help='Exercise synthesis LLM report validation')
    parser.add_argument('--preflight', action=argparse.BooleanOptionalAction, default=None,
                        help='Probe the selected coding service before workflow (default enabled with --provider)')
    parser.add_argument('--dry-run', action='store_true', help='Write fixture and plan without contacting services')
    return parser


def main(argv=None):
    from metaagent.workflow_runner import WorkflowOptions, WorkflowRunError, run_workflow
    parser = argument_parser()
    args = parser.parse_args(argv)
    started_at = datetime.now(UTC).isoformat()
    start = perf_counter()
    try:
        config, inputs, task = build_fixture(args.output, backend=args.backend, provider=args.provider,
            model=args.model, api_base=args.api_base, max_tokens=args.max_tokens, timeout=args.timeout, thinking=args.thinking,
            llm_report=args.llm_report)
    except ValueError as exc:
        parser.error(str(exc))
    root = args.output.resolve()
    attempt = root/'attempts'/uuid4().hex
    attempt.mkdir(parents=True,exist_ok=False)
    # Freeze non-secret invocation inputs as well as the result receipt.
    for source in (config, inputs, root/'codebook.yaml'):
        atomic_write_if_changed(attempt/source.name, source.read_text(encoding='utf-8'))
    variants = list(dict.fromkeys(args.variants))
    results = {}
    preflight = None
    if not args.dry_run and (args.preflight if args.preflight is not None else args.provider is not None):
        from metaagent.config import load_llm_config
        from metaagent.workflow_task import resolve_runtime
        from metaagent.service_health import probe_runtime
        probe_options = WorkflowOptions(profile='task', dataset_root=root, output_dir=root/'run',
            task_config=config, input_mode='raw_pool', raw_input=inputs)
        try:
            invocation, _ = resolve_runtime(probe_options, 'coding', require_credentials=True)
            cfg = load_llm_config(invocation, module_hint='coding')
            preflight = probe_runtime(cfg, timeout=min(args.timeout, 10))
            # The availability probe uses its own short question/output cap; it
            # does not exercise vendor extensions from the extraction profile.
            preflight.update(scope='transport_availability_only', extra_body_exercised=False,
                             configured_extra_body_present=bool(invocation.get('llm_extra_body')))
        except ValueError as exc:
            preflight = {'status':'not_configured','classification':'runtime_configuration_error',
                         'error_type':type(exc).__name__}
        preflight = _sanitize(preflight)
        health_text = json.dumps(preflight,ensure_ascii=False,indent=2)+'\n'
        atomic_write_if_changed(attempt/'endpoint_health.json',health_text)
        atomic_write_if_changed(root/'endpoint_health.json',health_text)
        if preflight['status'] != 'ready':
            summary = {'status':'service_unavailable','started_at':started_at,'finished_at':datetime.now(UTC).isoformat(),
                'elapsed_walltime_s':perf_counter()-start,'preflight':preflight,'variants':{},'scope':SCOPE}
            summary = publish_receipt(root,attempt,summary)
            print(json.dumps(summary,ensure_ascii=False))
            return 1
    for variant in variants:
        directory = root/('run' if variant == 'full' else 'run_'+variant)
        options = WorkflowOptions(profile='task', dataset_root=root, output_dir=directory,
            task_config=config, input_mode='raw_pool', raw_input=inputs, ablation=variant)
        run_start = perf_counter()
        if args.dry_run:
            results[variant] = {'status':'dry_run','task':str(config),'input':str(inputs),
                                'configured_runtime':task['llm'],'scope':SCOPE}
            continue
        try:
            manifest = run_workflow(options)
        except WorkflowRunError as exc:
            manifest = exc.manifest
        results[variant] = summarize_manifest(manifest, elapsed_s=perf_counter()-run_start)
        results[variant]['manifest'] = str(directory/'workflow_manifest.json')
    status = ('dry_run' if args.dry_run else 'complete' if all(r['status']=='complete' for r in results.values()) else 'partial_or_failed')
    summary = {'status':status,'started_at':started_at,'finished_at':datetime.now(UTC).isoformat(),
               'elapsed_walltime_s':perf_counter()-start,'variants':results,'scope':SCOPE}
    if preflight is not None:
        summary['preflight'] = preflight
    if len(results)==1:
        only=next(iter(results.values()))
        for key in ('artifacts','manifest','error_type'):
            if key in only:
                summary[key]=only[key]
    summary = publish_receipt(root,attempt,summary)
    print(json.dumps(summary,ensure_ascii=False))
    return 0 if status in {'complete','dry_run'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
