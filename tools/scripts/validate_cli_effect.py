"""Frozen three-case CLI developer validation; references never enter model commands.

Default mode invokes `workflow status --json` for explicitly supplied saved runs.
Only --live may run models, always by a real CLI subprocess, sequentially.
This pack is not independently adjudicated gold and does not report formal P/R/F1.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from metaagent.evaluation.benchmark_metrics import _field, _matches, _normalized, canonicalize_records, record_identity


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def verify_freeze(pack_path):
    frozen_path = pack_path.parent / 'freeze.json'
    frozen = json.loads(frozen_path.read_text())
    for name, expected in frozen['files'].items():
        path = ROOT / name
        if not path.is_file() or sha(path) != expected:
            raise ValueError('Frozen developer input/reference/source changed: ' + name)
    return {'path': str(frozen_path), 'sha256': sha(frozen_path), 'files': len(frozen['files'])}


def invoke_cli(command, directory, timeout):
    """Capture the actual process exit, complete stdout/stderr and JSON contract."""
    directory.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding='utf-8', errors='replace', start_new_session=True)
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
    (directory / 'cli.stdout.txt').write_text(stdout)
    (directory / 'cli.stderr.txt').write_text(stderr)
    try:
        payload = json.loads(stdout)
        json_ok = isinstance(payload, dict) and isinstance(payload.get('status'), str)
    except (ValueError, TypeError):
        payload, json_ok = None, False
    receipt = {'command': command, 'exit_code': process.returncode, 'timed_out': timed_out,
               'wall_time_s': time.monotonic() - started, 'json_contract_valid': json_ok,
               'stdout_sha256': sha(directory / 'cli.stdout.txt'), 'stderr_sha256': sha(directory / 'cli.stderr.txt'),
               'status': payload.get('status') if json_ok else 'invalid_json_contract'}
    write(directory / 'cli_receipt.json', receipt)
    return receipt, payload


def artifact_path(manifest, key):
    value = manifest.get('artifacts', {}).get(key)
    value = value.get('path') if isinstance(value, dict) else value
    return Path(value) if isinstance(value, str) else None


def read_rows(path):
    if path is None or not path.is_file():
        return []
    if path.suffix == '.jsonl':
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if path.suffix == '.xlsx':
        import pandas as pd
        frame = pd.read_excel(path, dtype=object)
        return frame.where(frame.notna(), None).to_dict('records')
    value = json.loads(path.read_text())
    return value if isinstance(value, list) else value.get('records', [])


def scope_grounded(row, reference, text):
    """Predeclared source-region scope, never target numeric proximity."""
    evidence = row.get('field_evidence') or row.get('_field_evidence') or {}
    if isinstance(evidence, str):
        try:
            evidence = json.loads(evidence)
        except ValueError:
            return False
    values = evidence.get('point_estimate', []) if isinstance(evidence, dict) else []
    values = values if isinstance(values, list) else [values]
    for entry in values:
        quote = entry if isinstance(entry, str) else entry.get('quote', entry.get('text', '')) if isinstance(entry, dict) else ''
        if not quote:
            continue
        for match in re.finditer(re.escape(quote), text):
            if any(match.start() < r['end'] and match.end() > r['start'] for r in reference['scope_source_ranges']):
                return True
    return False


def compare_developer_reference(predictions, reference):
    source = ROOT / reference['source_path']
    if sha(source) != reference['source_sha256']:
        raise ValueError('Reference source version hash changed')
    text = source.read_text()
    evidence = reference['primary_evidence']
    if text[evidence['start']:evidence['end']] != evidence['quote']:
        raise ValueError('Frozen reference quotation does not match its source offset')
    anchors, normalized = canonicalize_records([{'record_id': reference['record_id'], 'pmid': reference['pmid'], 'doi': reference.get('doi')}], predictions)
    identity = record_identity(anchors[0])
    target = []
    for index, row in enumerate(normalized):
        if record_identity(row) != identity:
            continue
        if all(_matches(reference['fields'][field], _field(row, field), field, {}) for field in ('parameter_type', 'estimate_measure')):
            target.append(index)
    scoped = [index for index in target if scope_grounded(normalized[index], reference, text)]
    # Repeated identical records are still ambiguous. Do not optimize a pairing
    # using the known point or choose the closest interval.
    selected = scoped[0] if len(scoped) == 1 else None
    outcome = 'matched_unique_identity_scope' if selected is not None else 'ambiguous' if len(scoped) > 1 else 'scope_unresolved' if target else 'missing'
    fields = {}
    if selected is not None:
        row = normalized[selected]
        for field, expected in reference['fields'].items():
            actual = _field(row, field)
            if reference.get('field_status', {}).get(field) == 'not_scored_source_conflict':
                fields[field] = {'status': 'not_scored_source_conflict', 'predicted': actual,
                                 'source_values': reference.get('source_conflict_values', {}).get(field, [])}
                continue
            match = _matches(expected, actual, field, {'tolerance': reference.get('absolute_tolerance', 1e-6)})
            item = {'status': 'agree' if match else 'different_or_missing', 'expected': expected, 'predicted': actual}
            if field in {'point_estimate', 'uncertainty_low', 'uncertainty_high'} and isinstance(actual, (int, float)):
                item['absolute_error'] = abs(float(actual) - float(expected))
            fields[field] = item
    conflict_rows = [normalized[i] for i in scoped]
    conflict_text = ' '.join(str(r.get(key, '')) for r in conflict_rows for key in ('notes', 'review_notes', 'review_flags', 'conflicts'))
    return {'reference_status': reference['annotation_status'], 'independent_human_gold': False,
            'comparison_kind': 'developer_source_agreement_not_formal_accuracy', 'alignment_status': outcome,
            'candidate_prediction_indices': scoped, 'identity_candidate_indices': target, 'prediction_index': selected,
            'prediction_rows': len(predictions), 'extra_prediction_rows_pending_annotation': len(predictions) - (1 if selected is not None else 0),
            'fields': fields, 'matching_rule': 'canonical report ID + parameter + statistic + predeclared exact-source regions; never numeric nearness',
            'source_scope': reference['source_scope'], 'source_conflicts': reference.get('source_conflicts', []),
            'explicit_source_conflict_flag': bool(re.search(r'conflict|discrepan|disagree|inconsisten', conflict_text, re.I)) if reference.get('source_conflicts') else None,
            'any_scoped_record_pending_review': any(r.get('needs_review') is True for r in conflict_rows),
            'formal_precision_recall_f1': None}


def execution_evidence(manifest):
    evidence = {'stage_a_calls': None, 'stage_b_calls': None, 'stage_a_provider_attempts': None, 'stage_b_provider_attempts': None,
                'raw_call_audits': [], 'usage_totals': {}, 'usage_unobserved_calls': 0, 'model_service_wall_time_ms': 0,
                'coding_coverage': []}
    pointer = artifact_path(manifest, 'coding_execution_manifest')
    if pointer and pointer.is_file():
        coverage_files = sorted((pointer.parent / 'documents').glob('*/coverage.json'))
        if coverage_files:
            evidence['coding_coverage'] = [{'path': str(p), 'sha256': sha(p), 'coverage': json.loads(p.read_text())} for p in coverage_files]
            for output, field in [('stage_a_calls', 'stage_a_calls'), ('stage_b_calls', 'stage_b_calls'), ('stage_a_provider_attempts', 'stage_a_logged_provider_attempts'), ('stage_b_provider_attempts', 'stage_b_logged_provider_attempts')]:
                values = [c['coverage'].get(field) for c in evidence['coding_coverage']]
                evidence[output] = sum(values) if all(isinstance(v, int) for v in values) else None
        log = pointer.parent / 'llm_calls.jsonl'
        if log.is_file():
            evidence['raw_call_audits'].append({'module': 'coding', 'path': str(log), 'sha256': sha(log)})
    for stage in manifest.get('stage_results', {}).values():
        for value in stage.get('artifacts', {}).values():
            p = Path(value) if isinstance(value, str) else None
            if p and p.name in {'screening_calls.jsonl', 'synthesis_calls.jsonl'} and p.is_file():
                evidence['raw_call_audits'].append({'module': p.name.split('_')[0], 'path': str(p), 'sha256': sha(p)})
    seen = set()
    for receipt in evidence['raw_call_audits']:
        if receipt['path'] in seen:
            continue
        seen.add(receipt['path'])
        for event in read_rows(Path(receipt['path'])):
            usage = event.get('usage')
            if not isinstance(usage, dict):
                evidence['usage_unobserved_calls'] += 1
            else:
                for key in ('input_tokens', 'output_tokens', 'prompt_tokens', 'completion_tokens', 'total_tokens'):
                    if isinstance(usage.get(key), (float, int)):
                        evidence['usage_totals'][key] = evidence['usage_totals'].get(key, 0) + usage[key]
            evidence['model_service_wall_time_ms'] += event.get('wall_time_ms') or 0
    return evidence


def audit_offsets(run_dir):
    return {str(path): path.stat().st_size for path in Path(run_dir).rglob('*calls.jsonl') if path.is_file()} if Path(run_dir).exists() else {}


def invocation_audit_delta(run_dir, before):
    counts, usage, unobserved, logs = {}, {}, 0, []
    for path in Path(run_dir).rglob('*calls.jsonl'):
        if not path.is_file():
            continue
        start = before.get(str(path), 0)
        if path.stat().st_size < start:
            start = 0
        with path.open('rb') as handle:
            handle.seek(start)
            raw = handle.read()
        if not raw:
            continue
        events = [json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
        logs.append({'path': str(path), 'offset_start': start, 'offset_end': path.stat().st_size, 'sha256': sha(path), 'events': len(events)})
        for event in events:
            stage = event.get('stage', event.get('module', 'unknown'))
            counts[stage] = counts.get(stage, 0) + 1
            observed = event.get('usage')
            if not isinstance(observed, dict):
                unobserved += 1
            else:
                for key in ('input_tokens', 'output_tokens', 'prompt_tokens', 'completion_tokens', 'total_tokens'):
                    if isinstance(observed.get(key), (float, int)):
                        usage[key] = usage.get(key, 0) + observed[key]
    return {'new_provider_attempts_by_stage': counts, 'new_usage_totals': usage,
            'new_calls_with_unobserved_usage': unobserved, 'raw_log_slices': logs}


def semantic_safety(manifest, predictions, reference):
    path = artifact_path(manifest, 'synthesis_result')
    if path is None or not path.is_file():
        return {'status': 'not_exercised', 'reason': 'No declared synthesis result artifact'}
    result = json.loads(path.read_text())
    kind = reference['safety_expectation']
    if kind == 'CrI_must_not_be_CI':
        cri_rows = [row for row in predictions if _normalized(_field(row, 'uncertainty_type'), 'uncertainty_type') == 'cri']
        refusal_rows = [d for d in result.get('selection', []) if 'uncertainty_type_not_authorized_or_missing' in d.get('reasons', [])]
        passed = bool(cri_rows) and bool(refusal_rows) and result.get('result') is None and result.get('counts', {}).get('selected') == 0
        return {'status': 'pass' if passed else 'fail', 'rule': kind, 'cri_prediction_rows': len(cri_rows),
                'synthesis_status': result.get('status'), 'selected': result.get('counts', {}).get('selected'),
                'pooled_result_present': result.get('result') is not None, 'unauthorized_uncertainty_refusals': len(refusal_rows),
                'source_conflict_remains_unadjudicated': bool(reference.get('source_conflicts'))}
    actual = result.get('result')
    if not isinstance(actual, dict):
        return {'status': 'not_computable', 'rule': kind, 'synthesis_status': result.get('status')}
    point = actual.get('pooled_mean', actual.get('point_estimate'))
    passed = _matches(reference['fields']['point_estimate'], point, 'point_estimate', {})
    identity_fields_agree = all(_matches(reference['fields'][field], actual.get(field), field, {})
                                for field in ('parameter_type', 'estimate_measure', 'unit'))
    passed = passed and identity_fields_agree
    if kind == 'median_not_mean':
        passed = passed and actual.get('estimate_measure') == 'median' and actual.get('method') == 'median'
    return {'status': 'pass' if passed else 'fail', 'rule': kind, 'synthesis_status': result.get('status'),
            'parameter_type': actual.get('parameter_type'), 'estimate_measure': actual.get('estimate_measure'),
            'method': actual.get('method'), 'point_absolute_error': abs(float(point) - reference['fields']['point_estimate']) if isinstance(point, (int, float)) else None,
            'parameter_statistic_unit_agree': identity_fields_agree,
            'primary_interval_compared_to_synthesis_interval': False if kind == 'median_not_mean' else 'not_scored_here'}


def validate_pack(pack_path, output, *, saved_runs=None, live=False, cases=None, python=None, timeout=1200):
    pack_path, output = Path(pack_path), Path(output)
    frozen = verify_freeze(pack_path)
    pack = json.loads(pack_path.read_text())
    selected = [case for case in pack['cases'] if not cases or case['id'] in cases]
    if cases and set(cases) - {c['id'] for c in pack['cases']}:
        raise ValueError('Unknown developer case')
    saved_runs = saved_runs or {}
    if set(saved_runs) - {c['id'] for c in pack['cases']}:
        raise ValueError('Unknown saved-run developer case')
    if timeout <= 0:
        raise ValueError('CLI timeout must be positive')
    if live and saved_runs:
        raise ValueError('Use live execution or saved-run comparison, not both')
    reference_rows = json.loads((ROOT / pack['references']).read_text())['cases']
    references = {row['case_id']: row for row in reference_rows}
    output.mkdir(parents=True, exist_ok=True)
    attempt = output / ('validation_' + datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ'))
    attempt.mkdir()
    write(attempt / 'frozen_inputs.json', {'receipt': frozen, 'manifest': json.loads((pack_path.parent / 'freeze.json').read_text())})
    reports = []
    for case in selected:
        case_output = attempt / case['id']
        base = [str(python or sys.executable), '-m', 'metaagent.cli', 'workflow']
        run_dir = output / case['id'] / 'workflow' if live else Path(saved_runs[case['id']]) if case['id'] in saved_runs else None
        if run_dir is None:
            reports.append({'case_id': case['id'], 'execution_status': 'not_scheduled', 'reference_comparison': {'alignment_status': 'missing'}, 'semantic_safety': {'status': 'not_exercised'}, 'case_coverage': case['source_scope']})
            continue
        if live:
            command = base + ['run', '--task-config', str(ROOT / case['task']), '--document-manifest', str(ROOT / case['documents']), '--start-at', 'coding', '--stop-after', 'pooling', '--ablation', 'full', '--output-dir', str(run_dir), '--json']
        else:
            command = base + ['status', '--run-dir', str(run_dir), '--json']
        offsets = audit_offsets(run_dir)
        manifest_path = run_dir / 'workflow_manifest.json'
        receipt = {}
        try:
            receipt, payload = invoke_cli(command, case_output, timeout)
            manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
            predictions = read_rows(artifact_path(manifest, 'coding_estimates') or artifact_path(manifest, 'coding_predictions'))
            comparison = compare_developer_reference(predictions, references[case['id']])
            safety = semantic_safety(manifest, predictions, references[case['id']])
            audit = execution_evidence(manifest)
            report = {'case_id': case['id'], 'case_coverage': case['source_scope'], 'execution_status': manifest.get('status', receipt['status']),
                      'cli': receipt, 'workflow_manifest': str(manifest_path), 'manifest_sha256': sha(manifest_path) if manifest_path.is_file() else None,
                      'reference_comparison': comparison, 'semantic_safety': safety, 'execution_evidence': audit,
                      'actual_full_A_B': (audit['stage_a_calls'] or 0) > 0 and (audit['stage_b_calls'] or 0) > 0 and (audit['stage_a_provider_attempts'] or 0) > 0 and (audit['stage_b_provider_attempts'] or 0) > 0,
                      'stage_reuse': {name: stage.get('reused') for name, stage in manifest.get('stage_results', {}).items()},
                      'invocation_audit_delta': invocation_audit_delta(run_dir, offsets),
                      'cached_run_replay_not_new_model_calls': not live or (bool(manifest.get('stage_results')) and all(stage.get('reused') for stage in manifest.get('stage_results', {}).values()))}
        except (OSError, ValueError, TypeError) as exc:
            report = {'case_id': case['id'], 'execution_status': 'evaluation_failed', 'cli': receipt, 'error_type': type(exc).__name__, 'error': str(exc)}
        comparison = report.get('reference_comparison', {})
        scored = [v for v in comparison.get('fields', {}).values() if v.get('status') != 'not_scored_source_conflict']
        report['developer_reference_fields_all_agree'] = bool(scored) and all(v.get('status') == 'agree' for v in scored)
        expected_refusal = references[case['id']]['safety_expectation'] == 'CrI_must_not_be_CI'
        # A successful field comparison against a stale artifact cannot erase a
        # crashed/failed invocation. Only the predeclared CrI safety case may
        # legitimately return partial/nonzero after refusing analysis.
        cli = report.get('cli', {})
        report['cli_execution_acceptable'] = bool(cli.get('json_contract_valid') and not cli.get('timed_out') and (
            (cli.get('exit_code') == 0 and report['execution_status'] == 'complete') or
            (expected_refusal and cli.get('exit_code') == 1 and cli.get('status') == 'partial'
             and report['execution_status'] == 'partial' and report.get('semantic_safety', {}).get('status') == 'pass')))
        report['development_checks_passed'] = bool(report['cli_execution_acceptable'] and report.get('actual_full_A_B')
            and comparison.get('alignment_status') == 'matched_unique_identity_scope' and report['developer_reference_fields_all_agree']
            and report.get('semantic_safety', {}).get('status') == 'pass'
            and (not comparison.get('source_conflicts') or comparison.get('explicit_source_conflict_flag')))
        reports.append(report)
        write(case_output / 'case_report.json', report)
    summary = {'schema_version': '1', 'purpose': 'developer_validation_only_not_formal_22_SR_benchmark',
               'validator_sha256': sha(Path(__file__)),
               'metric_helper_sha256': sha(ROOT / 'metaagent/evaluation/benchmark_metrics.py'),
               'reference_status': 'developer_source_checked_provisional_not_independent_gold', 'frozen_pack': frozen,
               'mode': 'live_CLI_subprocess' if live else 'saved_run_CLI_status_and_offline_comparison',
               'planned_cases': len(selected), 'unscheduled_cases': sum(r['execution_status'] == 'not_scheduled' for r in reports),
               'cases': reports, 'development_checks_passed': bool(reports) and all(r.get('development_checks_passed') for r in reports), 'formal_precision_recall_f1': None, 'report_dir': str(attempt)}
    write(attempt / 'report.json', summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack', type=Path, default=ROOT / 'configs/validation/pack.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'runs/cli_effect_validation_20261104')
    parser.add_argument('--run', action='append', default=[], metavar='CASE=WORKFLOW_DIR')
    parser.add_argument('--case', action='append', default=[])
    parser.add_argument('--live', action='store_true', help='Explicitly permit sequential model-running CLI subprocesses')
    parser.add_argument('--python', type=Path, default=Path(sys.executable))
    parser.add_argument('--timeout', type=float, default=1200)
    args = parser.parse_args(argv)
    runs = {}
    for value in args.run:
        identity, sep, path = value.partition('=')
        if not sep or not identity or identity in runs:
            parser.error('--run requires unique CASE=WORKFLOW_DIR entries')
        runs[identity] = path
    try:
        report = validate_pack(args.pack, args.output, saved_runs=runs, live=args.live, cases=args.case, python=args.python, timeout=args.timeout)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if report['unscheduled_cases'] == 0 and report['development_checks_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
