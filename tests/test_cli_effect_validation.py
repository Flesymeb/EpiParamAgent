"""Real CLI subprocess developer pack validation, with no model/provider calls."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

from tools.scripts.validate_cli_effect import (
    compare_developer_reference, invoke_cli, semantic_safety, validate_pack, verify_freeze,
)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')
    return path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def pack(tmp_path):
    folder = tmp_path / 'pack'; folder.mkdir()
    source = folder / 'source.md'; source.write_text('The overall mean interval was 5 days (95% CI 4 to 6).')
    ref = {'case_id': 'test', 'record_id': 'pmid:1', 'pmid': '1', 'source_path': str(source),
           'source_sha256': sha(source), 'source_scope': 'synthetic_test_only',
           'annotation_status': 'developer_source_checked_provisional', 'independent_human_gold': False,
           'primary_evidence': {'start': 0, 'end': len(source.read_text()), 'quote': source.read_text()},
           'scope_source_ranges': [{'start': 0, 'end': len(source.read_text())}],
           'fields': {'parameter_type': 'serial_interval', 'estimate_measure': 'mean', 'point_estimate': 5,
                      'unit': 'days', 'uncertainty_type': 'CI', 'uncertainty_level': '95%', 'uncertainty_low': 4, 'uncertainty_high': 6},
           'safety_expectation': 'ordinary_CI_mean'}
    refs = save(folder / 'references.json', {'cases': [ref]})
    task = folder / 'task.yaml'; task.write_text('task_id: synthetic\n')
    documents = folder / 'documents.jsonl'; documents.write_text(json.dumps({'record_id': 'pmid:1', 'path': str(source)}) + '\n')
    definition = save(folder / 'pack.json', {'cases': [{'id': 'test', 'task': str(task), 'documents': str(documents), 'source_scope': 'synthetic_test_only'}], 'references': str(refs)})
    save(folder / 'freeze.json', {'files': {str(p): sha(p) for p in (source, refs, task, documents, definition)}})
    return definition, ref


def prediction(reference, **extra):
    return {'record_id': 'source:opaque', 'pmid': '1', **reference['fields'],
            'field_evidence': {'point_estimate': [{'quote': reference['primary_evidence']['quote']}]}, **extra}


def workflow(tmp_path, reference, *, status='complete'):
    root = tmp_path / 'workflow'; extraction = root / 'extraction'; extraction.mkdir(parents=True)
    rows = extraction / 'coding_estimates.jsonl'; rows.write_text(json.dumps(prediction(reference)) + '\n')
    execution = save(extraction / 'execution.json', {'status': status})
    save(extraction / 'documents/doc/coverage.json', {'status': status, 'stage_a_calls': 1, 'stage_b_calls': 1,
                                                  'stage_a_logged_provider_attempts': 1, 'stage_b_logged_provider_attempts': 1})
    (extraction / 'llm_calls.jsonl').write_text('\n'.join(json.dumps({'stage': stage, 'status': 'ok', 'usage': {'input_tokens': 10, 'output_tokens': 5}, 'wall_time_ms': 50}) for stage in ('stage_a', 'stage_b')) + '\n')
    synthesis = save(root / 'synthesis_result.json', {'status': 'single_estimate', 'counts': {'selected': 1},
                     'result': {'pooled_mean': 5, 'parameter_type': 'serial_interval', 'estimate_measure': 'mean', 'unit': 'days', 'method': 'fixed'}})
    save(root / 'workflow_manifest.json', {'status': status, 'stage_results': {}, 'artifacts': {'coding_estimates': str(rows), 'coding_execution_manifest': str(execution), 'synthesis_result': str(synthesis)}})
    return root


def test_offline_mode_really_calls_cli_status_and_reports_developer_only(pack, tmp_path):
    definition, ref = pack
    run = workflow(tmp_path, ref)
    report = validate_pack(definition, tmp_path / 'reports', saved_runs={'test': run})
    item = report['cases'][0]
    assert item['cli']['command'][1:5] == ['-m', 'metaagent.cli', 'workflow', 'status']
    assert item['cli']['exit_code'] == 0 and item['cli']['json_contract_valid']
    assert item['actual_full_A_B']
    assert item['reference_comparison']['alignment_status'] == 'matched_unique_identity_scope'
    assert item['execution_evidence']['usage_totals']['input_tokens'] == 20
    assert item['execution_evidence']['usage_totals']['output_tokens'] == 10
    assert report['formal_precision_recall_f1'] is None
    assert report['reference_status'] == 'developer_source_checked_provisional_not_independent_gold'
    assert report['development_checks_passed']


def test_failed_cli_cannot_pass_using_old_matching_artifacts(pack, tmp_path, monkeypatch):
    definition, ref = pack
    run = workflow(tmp_path, ref)
    monkeypatch.setattr('tools.scripts.validate_cli_effect.invoke_cli', lambda *args: (
        {'json_contract_valid': True, 'exit_code': 1, 'status': 'failed', 'timed_out': False}, {'status': 'failed'}))
    report = validate_pack(definition, tmp_path / 'reports', saved_runs={'test': run})
    item = report['cases'][0]
    assert item['developer_reference_fields_all_agree']
    assert not item['cli_execution_acceptable']
    assert not report['development_checks_passed']


def test_corrupt_artifacts_remain_failed_case_in_denominator(pack, tmp_path):
    definition, ref = pack
    run = workflow(tmp_path, ref)
    (run / 'extraction/coding_estimates.jsonl').write_text('not json\n')
    report = validate_pack(definition, tmp_path / 'reports', saved_runs={'test': run})
    assert report['planned_cases'] == 1 and len(report['cases']) == 1
    assert report['cases'][0]['execution_status'] == 'evaluation_failed'
    assert not report['development_checks_passed']


def test_alignment_does_not_choose_nearest_number_when_multiple_scope_candidates(pack):
    _, ref = pack
    first = prediction(ref, point_estimate=5)
    second = prediction(ref, point_estimate=500)
    result = compare_developer_reference([first, second], ref)
    assert result['alignment_status'] == 'ambiguous'
    assert result['prediction_index'] is None
    assert result['fields'] == {}


def test_matching_scope_uses_exact_source_evidence_not_model_location_claim(pack):
    _, ref = pack
    row = prediction(ref)
    row['field_evidence'] = {'point_estimate': [{'quote': 'invented quotation'}]}
    row['evidence_locations'] = ['Abstract']
    result = compare_developer_reference([row], ref)
    assert result['alignment_status'] == 'scope_unresolved'


def test_primary_source_conflict_upper_bound_is_not_counted_wrong(pack):
    _, ref = pack
    ref['field_status'] = {'uncertainty_high': 'not_scored_source_conflict'}
    ref['source_conflict_values'] = {'uncertainty_high': [6, 7]}
    result = compare_developer_reference([prediction(ref, uncertainty_high=7)], ref)
    assert result['fields']['uncertainty_high']['status'] == 'not_scored_source_conflict'
    assert 'absolute_error' not in result['fields']['uncertainty_high']


def test_missing_record_and_unscheduled_cases_are_not_removed(pack, tmp_path):
    definition, ref = pack
    compared = compare_developer_reference([], ref)
    assert compared['alignment_status'] == 'missing'
    report = validate_pack(definition, tmp_path / 'out')
    assert report['planned_cases'] == 1 and report['unscheduled_cases'] == 1
    assert report['cases'][0]['execution_status'] == 'not_scheduled'
    assert not report['development_checks_passed']


def test_frozen_reference_change_fails_before_any_subprocess(pack, tmp_path):
    definition, ref = pack
    references = Path(json.loads(definition.read_text())['references'])
    references.write_text('modified reference')
    with pytest.raises(ValueError, match='Frozen'):
        validate_pack(definition, tmp_path / 'out', live=True)
    assert not (tmp_path / 'out').exists()


def test_refuses_changed_source_even_if_point_would_match(pack):
    _, ref = pack
    Path(ref['source_path']).write_text('Changed version')
    with pytest.raises(ValueError, match='source version'):
        compare_developer_reference([prediction(ref)], ref)


def test_cli_contract_failure_and_deadline_retained_as_failures(tmp_path):
    receipt, payload = invoke_cli([sys.executable, '-c', 'print("not JSON")'], tmp_path / 'invalid', 3)
    assert receipt['exit_code'] == 0 and not receipt['json_contract_valid'] and payload is None
    receipt, _ = invoke_cli([sys.executable, '-c', 'import time; time.sleep(20)'], tmp_path / 'timeout', .1)
    assert receipt['timed_out'] and receipt['exit_code'] != 0


def test_live_command_contains_only_task_and_document_not_reference(pack, tmp_path, monkeypatch):
    definition, ref = pack
    # Scheduling is tested without running models; independent offline test above
    # executes the actual CLI subprocess. No run_workflow API is used anywhere.
    captured = []
    def capture(command, directory, timeout):
        captured.append(command)
        return {'json_contract_valid': True, 'exit_code': 1, 'status': 'failed'}, {'status': 'failed'}
    monkeypatch.setattr('tools.scripts.validate_cli_effect.invoke_cli', capture)
    report = validate_pack(definition, tmp_path / 'out', live=True)
    command = captured[0]
    assert command[1:5] == ['-m', 'metaagent.cli', 'workflow', 'run']
    assert command[command.index('--ablation') + 1] == 'full'
    assert '--json' in command
    assert 'references.json' not in ' '.join(command)
    assert 'expected' not in ' '.join(command)
    assert not report['development_checks_passed']


def test_cri_safety_requires_actual_interval_refusal_and_no_result(pack, tmp_path):
    _, ref = pack
    ref['safety_expectation'] = 'CrI_must_not_be_CI'
    rows = [prediction(ref, uncertainty_type='CrI')]
    result = save(tmp_path / 'result.json', {'status': 'not_computable', 'counts': {'selected': 0}, 'result': None,
                                         'selection': [{'decision': 'review', 'reasons': ['uncertainty_type_not_authorized_or_missing']}]})
    summary = semantic_safety({'artifacts': {'synthesis_result': str(result)}}, rows, ref)
    assert summary['status'] == 'pass'
    save(result, {'status': 'complete', 'counts': {'selected': 1}, 'result': {'pooled_mean': 5}})
    assert semantic_safety({'artifacts': {'synthesis_result': str(result)}}, rows, ref)['status'] == 'fail'
    assert semantic_safety({}, rows, ref)['status'] == 'not_exercised'


def test_same_numeric_result_with_wrong_parameter_is_not_semantic_success(pack, tmp_path):
    _, ref = pack
    result = save(tmp_path / 'result.json', {'status': 'single_estimate', 'result': {
        'pooled_mean': 5, 'parameter_type': 'incubation_period', 'estimate_measure': 'mean',
        'unit': 'days', 'method': 'fixed'}})
    summary = semantic_safety({'artifacts': {'synthesis_result': str(result)}}, [prediction(ref)], ref)
    assert summary['point_absolute_error'] == 0
    assert summary['status'] == 'fail'


def test_committed_pack_provisional_references_and_quote_budget():
    root = Path(__file__).resolve().parents[1]
    references = json.loads((root / 'configs/validation/references.json').read_text())['cases']
    assert len(references) == 3
    for ref in references:
        quote = ref['primary_evidence']
        assert len(quote['quote'].split()) <= 25
        assert ref['annotation_status'] == 'developer_source_checked_provisional'
        assert not ref['independent_human_gold']
    assert next(r for r in references if r['pmid'] == '32150748')['source_scope'] == 'primary_abstract_only'


def test_source_snapshots_match_frozen_hashes_and_offsets_when_available():
    root = Path(__file__).resolve().parents[1]
    references = json.loads((root / 'configs/validation/references.json').read_text())['cases']
    if any(not (root / ref['source_path']).is_file() for ref in references):
        pytest.skip('Ignored primary-source snapshots absent; see configs/validation/SOURCE_RECOVERY.md')
    verify_freeze(root / 'configs/validation/pack.json')
    for ref in references:
        quote = ref['primary_evidence']
        source = (root / ref['source_path']).read_text()
        assert source[quote['start']:quote['end']] == quote['quote']
