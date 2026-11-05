"""Resource summaries from actual active attempts; unknown prices remain unknown."""
from __future__ import annotations

import json
import hashlib
import math
from pathlib import Path


def summarize_run(manifest: dict) -> dict:
    stages = {}
    for name, stage in manifest.get('stage_results', {}).items():
        events = []
        call_logs=0;unread_logs=0;malformed_events=0
        for filename,digest in stage.get('output_hashes', {}).items():
            path = Path(filename)
            if path.name not in {'llm_calls.jsonl','provider_calls.jsonl'}:continue
            call_logs+=1
            try:
                content=path.read_bytes()
                if hashlib.sha256(content).hexdigest()!=digest:
                    unread_logs+=1;continue
                provider_attempts = {}
                for line in content.decode('utf-8').splitlines():
                    if not line.strip():continue
                    try:
                        event=json.loads(line)
                        if not isinstance(event,dict):raise ValueError('event must be an object')
                        if path.name == 'provider_calls.jsonl':
                            provider_attempts[event.get('call_id', len(provider_attempts))] = event
                        else:
                            events.append(event)
                    except (ValueError,TypeError):malformed_events+=1
                events.extend(provider_attempts.values())
            except (OSError,UnicodeError):unread_logs+=1
        def counts(*keys):
            values=[]
            for event in events:
                usage=event.get('usage')
                value=next((usage[k] for k in keys if usage.get(k) is not None),None) if isinstance(usage,dict) else None
                values.append(value if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0 else None)
            return values
        def tokens(*keys):
            values=counts(*keys)
            return sum(values) if values and all(v is not None for v in values) and not unread_logs and not malformed_events else None
        def coverage(*keys):
            values=counts(*keys);known=sum(v is not None for v in values)
            return 'complete' if values and known==len(values) and not unread_logs and not malformed_events else 'partial' if known else 'unknown'
        def subtotal(*keys):
            values=[v for v in counts(*keys) if v is not None]
            return sum(values) if values else None
        stages[name] = {'status':stage.get('status'), 'reused':bool(stage.get('reused')),
                        'cold_attempt_walltime_s':stage.get('walltime_s'),
                        'current_execution_walltime_s':0 if stage.get('reused') else stage.get('walltime_s'),
                        'logged_model_calls':len(events) if call_logs and not unread_logs and not malformed_events else None,
                        'known_logged_model_calls':len(events) if call_logs else None,
                        'call_log_coverage':'partial' if unread_logs or malformed_events else 'complete' if call_logs else 'unknown',
                        'unread_or_hash_mismatched_call_logs':unread_logs,'malformed_call_events':malformed_events,
                        'model_calls_with_usage':sum(isinstance(e.get('usage'),dict) for e in events),
                        'model_calls_missing_usage':sum(not isinstance(e.get('usage'),dict) for e in events),
                        'provider_models':sorted({str(e['model']) for e in events if e.get('model')}),
                        'provider_requests_not_forwarded':sum(e.get('forwarded') is False for e in events),
                        'input_tokens':tokens('input_tokens','prompt_tokens'),
                        'output_tokens':tokens('output_tokens','completion_tokens'),
                        'input_tokens_coverage':coverage('input_tokens','prompt_tokens'),
                        'output_tokens_coverage':coverage('output_tokens','completion_tokens'),
                        'known_input_tokens_subtotal':subtotal('input_tokens','prompt_tokens'),
                        'known_output_tokens_subtotal':subtotal('output_tokens','completion_tokens'),
                        'cost_usd':None, 'pricing_status':'not_priced'}
    return {'scope':'active attempts only; cached prefix costs are not zero cold-run costs',
            'stages':stages, 'human_review_receipts':len(manifest.get('artifact_overrides',{})),
            'human_review_time_s':None, 'human_review_time_status':'not_measured'}
