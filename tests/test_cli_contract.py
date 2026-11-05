"""Offline CLI contracts exercise real plans, pooling, persistence and failures."""
import json
import socket
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from metaagent.cli import main


@pytest.fixture
def task(tmp_path, monkeypatch):
    monkeypatch.setattr('metaagent.config.load_runtime_env', lambda **kw: None)
    monkeypatch.setenv('METAAGENT_PAPER_POOL', str(tmp_path / 'paper_pool'))
    for module in ('QUERY', 'SCREENING', 'CODING', 'SYNTHESIS'):
        monkeypatch.setenv(f'{module}_LLM_PROVIDER', 'openai')
        monkeypatch.setenv(f'{module}_LLM_MODEL', 'offline-test-model')
        monkeypatch.setenv(f'{module}_LLM_API_BASE', 'http://localhost:1/v1')
        monkeypatch.setenv(f'{module}_LLM_API_KEY', 'offline-not-a-real-credential')
    (tmp_path / 'codebook.yaml').write_text(yaml.safe_dump({
        'project': {'name': 'CLI software fixture'},
        'fields': [{'name': 'point_estimate', 'type': 'float'}],
    }))
    value = {
        'version': '1', 'task_id': 'cli-software-fixture', 'disease': 'synthetic',
        'topic': 'serial_interval', 'research_question': 'Software test only',
        'codebook': 'codebook.yaml', 'coding': {'backend': 'llm'},
        'review_protocol': {'version': 'v1', 'criteria': [
            {'id': 'target', 'description': 'Matches the synthetic target'}], 'logic': 'target'},
        'search': {'pubmed': 'synthetic'},
        'analysis_protocol': {
            'analysis_id': 'test-mean', 'parameter_type': 'serial_interval',
            'estimate_measure': 'mean', 'unit': 'days', 'method': 'fixed',
            'uncertainty_rules': {'allowed_types': ['SE']},
            'independence': {'unit': 'cohort_id'},
        },
    }
    path = tmp_path / 'task.yaml'
    path.write_text(yaml.safe_dump(value))
    return path


def invoke(*args):
    return CliRunner().invoke(main, list(map(str, args)))


def modify_task(task, change):
    value = yaml.safe_load(task.read_text())
    change(value)
    task.write_text(yaml.safe_dump(value))


def estimates(task, *, missing_se=False):
    rows = [dict(estimate_id=str(i), record_id=f'report:{i}', cohort_id=f'cohort:{i}',
                 parameter_type='serial_interval', estimate_measure='mean', unit='days',
                 point_estimate=value, uncertainty_type='SE',
                 uncertainty_high=None if missing_se and i == 1 else 1)
            for i, value in enumerate((4, 6))]
    path = task.parent / 'estimates.jsonl'
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    return path


def test_validate_and_plan_are_local_and_do_not_write(task, monkeypatch):
    def network_forbidden(*args, **kw):
        pytest.fail('Local validation/plan attempted a network connection')
    monkeypatch.setattr(socket.socket, 'connect', network_forbidden)
    before = {p.relative_to(task.parent): p.read_bytes() for p in task.parent.rglob('*') if p.is_file()}
    result = invoke('workflow', 'validate', '--task-config', task, '--json')
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)['status'] == 'valid'
    result = invoke('workflow', 'plan', '--task-config', task, '--output-dir', task.parent / 'not-created', '--json')
    assert result.exit_code == 0, result.output
    plan = json.loads(result.stdout)
    assert plan['config']['ablation'] == 'full'
    assert plan['local_validation']['backend_installed'] is True
    after = {p.relative_to(task.parent): p.read_bytes() for p in task.parent.rglob('*') if p.is_file()}
    assert after == before
    assert not (task.parent / 'not-created').exists()


@pytest.mark.parametrize('change,expected', [
    (lambda p: p['analysis_protocol'].update(method='made_up'), 'Unsupported method'),
    (lambda p: p['analysis_protocol'].pop('uncertainty_rules'), 'uncertainty'),
    (lambda p: p['analysis_protocol'].update(filters={'population': {'typo': 'adult'}}), 'filter'),
])
def test_validate_rejects_invalid_analysis(task, change, expected):
    modify_task(task, change)
    result = invoke('workflow', 'validate', '--task-config', task, '--json')
    assert result.exit_code == 1, result.output
    failure = json.loads(result.stdout)
    assert failure['status'] == 'failed'
    assert expected.lower() in failure['error']['message'].lower()
    assert failure['error']['suggestion']


def test_validate_missing_backend_is_not_valid(task, monkeypatch):
    import importlib.util
    original = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, 'find_spec', lambda name, *a, **kw: None if name == 'langextract' else original(name, *a, **kw))
    modify_task(task, lambda p: p['coding'].update(backend='langextract'))
    result = invoke('workflow', 'validate', '--task-config', task, '--json')
    assert result.exit_code == 1
    assert 'not installed' in json.loads(result.stdout)['error']['message']
    # Selecting only retrieval does not need an extraction installation.
    result = invoke('workflow', 'plan', '--task-config', task, '--stop-after', 'retrieval', '--output-dir', task.parent / 'unused', '--json')
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize('malformed', [True, False])
def test_task_errors_do_not_echo_pasted_credentials(task, malformed):
    fake_key = 'sk-offline-cli-sensitive-fixture-927391'
    if malformed:
        task.write_text(f'llm: [\n  api_key: {fake_key}\n')
    else:
        modify_task(task, lambda p: p.update(api_key=fake_key))
    for command in ('validate', 'plan', 'run'):
        args = ['workflow', command, '--task-config', task, '--json']
        if command != 'validate':
            args += ['--output-dir', task.parent / 'must-not-exist']
        result = invoke(*args)
        assert result.exit_code == 1, result.output
        assert fake_key not in result.stdout + result.stderr
        failure = json.loads(result.stdout)
        assert failure['error']['message']
    assert not (task.parent / 'must-not-exist').exists()


@pytest.mark.parametrize('missing_se,expected,exit_code', [(False, 'complete', 0), (True, 'partial', 1)])
def test_real_pooling_run_and_status_json_contract(task, missing_se, expected, exit_code):
    source = estimates(task, missing_se=missing_se)
    out = task.parent / 'run'
    result = invoke('workflow', 'run', '--task-config', task, '--start-at', 'pooling', '--estimates-input', source, '--output-dir', out, '--json')
    assert result.exit_code == exit_code, result.output
    manifest = json.loads(result.stdout)
    assert manifest['status'] == expected
    summary_path = Path(manifest['artifacts']['synthesis_result'])
    summary = json.loads(summary_path.read_text())
    if not missing_se:
        assert summary['result']['pooled_mean'] == pytest.approx(5)
    else:
        assert summary['counts']['review'] == 1
    for option in ('--output-dir', '--run-dir'):
        status = invoke('workflow', 'status', option, out, '--json')
        assert status.exit_code == exit_code, status.output
        state = json.loads(status.stdout)
        assert state['status'] == expected
        assert state['stages']['pooling']['outputs_verified']
    if not missing_se:
        summary_path.write_text('{}')
        status = invoke('workflow', 'status', '--output-dir', out)
        assert status.exit_code == 1
        assert json.loads(status.stdout)['status'] == 'stale'


def test_status_failed_and_missing_are_actionable(task):
    out = task.parent / 'failed'
    out.mkdir()
    (out / 'workflow_manifest.json').write_text(json.dumps({'status': 'failed', 'stage_results': {}}))
    result = invoke('workflow', 'status', '--output-dir', out, '--json')
    assert result.exit_code == 1
    assert json.loads(result.stdout)['status'] == 'failed'
    result = invoke('workflow', 'status', '--output-dir', task.parent / 'missing', '--json')
    assert result.exit_code == 1
    assert 'workflow_manifest.json' in json.loads(result.stdout)['error']['suggestion']


def test_single_status_has_legacy_and_current_options(task):
    from metaagent.workflow import workflow
    assert list(workflow.commands).count('status') == 1
    result = invoke('workflow', 'status', '--help')
    assert result.exit_code == 0
    assert all(option in result.stdout for option in ('--profile', '--run-dir', '--output-dir', '--json'))
    # Legacy profile inspection remains usable offline and does not execute stages.
    result = invoke('workflow', 'status', '--profile', 'P4', '--project-root', task.parent, '--json')
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)['profile'] == 'P4'


def test_independent_synthesis_multi_protocol_and_yaml_error(task):
    source = estimates(task)
    protocol = yaml.safe_load(task.read_text())['analysis_protocol']
    path = task.parent / 'analyses.yaml'
    path.write_text(yaml.safe_dump([protocol, {**protocol, 'analysis_id': 'second'}]))
    out = task.parent / 'multi'
    result = invoke('synthesis', 'run', '--input', source, '--protocol', path, '--output', out, '--json')
    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert summary['status'] == 'complete'
    assert len(summary['analyses']) == 2
    assert (out / 'analysis_001' / 'synthesis_result.json').exists()
    assert (out / 'analysis_002' / 'forest.png').exists()
    path.write_text('api_key: sk-offline-do-not-echo\nwrong: [')
    result = invoke('synthesis', 'run', '--input', source, '--protocol', path, '--output', task.parent / 'bad', '--json')
    assert result.exit_code == 1
    assert 'sk-offline-do-not-echo' not in result.output
    assert 'Invalid YAML' in json.loads(result.stdout)['error']['message']
    assert not (task.parent / 'bad').exists()


@pytest.mark.parametrize('arguments', [
    ['--start-at', 'coding', '--estimates-input', 'estimates'],
    ['--start-at', 'retrieval', '--document-manifest', 'documents'],
    ['--start-at', 'pooling', '--estimates-input', 'estimates', '--document-manifest', 'documents'],
])
def test_plan_rejects_incompatible_module_inputs_before_writes(task, arguments):
    source = estimates(task)
    documents = task.parent / 'documents.jsonl'
    documents.write_text('')
    arguments = [str(source) if arg == 'estimates' else str(documents) if arg == 'documents' else arg for arg in arguments]
    out = task.parent / 'invalid-input-run'
    for command in ('plan', 'run'):
        result = invoke('workflow', command, '--task-config', task, '--output-dir', out, '--json', *arguments)
        assert result.exit_code == 1, result.output
        assert json.loads(result.stdout)['status'] == 'failed'
        assert not out.exists()


def test_validate_rejects_invalid_codebook_type(task):
    book = task.parent / 'codebook.yaml'
    book.write_text(yaml.safe_dump({'fields': [{'name': 'point_estimate', 'type': 'imaginary_number'}]}))
    result = invoke('workflow', 'validate', '--task-config', task, '--json')
    assert result.exit_code == 1, result.output
    assert 'type' in json.loads(result.stdout)['error']['message'].lower()


def test_failed_stage_returns_manifest_and_actionable_json(task):
    out = task.parent / 'failed-stage'
    result = invoke('workflow', 'run', '--task-config', task, '--start-at', 'pooling', '--output-dir', out, '--json')
    assert result.exit_code == 1, result.output
    failure = json.loads(result.stdout)
    assert failure['status'] == 'failed'
    assert failure['stage_results']['pooling']['status'] == 'failed'
    assert 'workflow status' in failure['error']['suggestion']
    assert json.loads((out / 'workflow_manifest.json').read_text())['status'] == 'failed'


def test_json_plan_redirects_core_diagnostics_without_replacing_real_plan(task, monkeypatch):
    import metaagent.workflow_runner as runner
    original = runner.plan_workflow
    def diagnostic_plan(options):
        print('diagnostic from a dependency')
        return original(options)
    monkeypatch.setattr(runner, 'plan_workflow', diagnostic_plan)
    result = invoke('workflow', 'plan', '--task-config', task, '--output-dir', task.parent / 'unused', '--json')
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)['config']['ablation'] == 'full'
    assert 'diagnostic from a dependency' in result.stderr
    assert 'diagnostic from a dependency' not in result.stdout


def test_profile_and_native_task_coding_defaults_are_consistent(task):
    from metaagent.workflow_runner import WorkflowOptions
    from metaagent.workflow_task import CodingSettings, resolve_coding
    modify_task(task, lambda p: p.pop('coding'))
    common = dict(profile='task', dataset_root=task.parent, output_dir=task.parent / 'unused')
    expected = CodingSettings().model_dump()
    assert expected['backend'] == 'langextract'
    assert resolve_coding(WorkflowOptions(**common)) == expected
    assert resolve_coding(WorkflowOptions(**common, task_config=task)) == expected
    assert resolve_coding(WorkflowOptions(**common, extraction_backend='llm'))['backend'] == 'llm'


def test_invalid_method_error_redacts_unconfigured_key_token(task):
    fake_key = 'sk-unconfigured-method-offline-sensitive-928391'
    modify_task(task, lambda p: p['analysis_protocol'].update(method=fake_key))
    for command in ('validate', 'plan', 'run'):
        arguments = ['workflow', command, '--task-config', task, '--json']
        if command != 'validate':
            arguments += ['--output-dir', task.parent / 'must-not-exist']
        result = invoke(*arguments)
        assert result.exit_code == 1, result.output
        assert fake_key not in result.stdout + result.stderr
        error = json.loads(result.stdout)['error']
        assert 'Unsupported method' in error['message']
        assert '[REDACTED]' in error['message']
    assert not (task.parent / 'must-not-exist').exists()


@pytest.mark.parametrize('multiple', [False, True])
def test_pending_synthesis_protocol_diagnostics_redact_before_artifact_writes(task, multiple):
    fake_key = 'sk-unconfigured-synthesis-method-sensitive-28172'
    source = estimates(task)
    valid = yaml.safe_load(task.read_text())['analysis_protocol']
    invalid = {**valid, 'analysis_id': 'invalid', 'method': fake_key}
    protocol = task.parent / 'pending.yaml'
    protocol.write_text(yaml.safe_dump([invalid, valid] if multiple else invalid))
    original = protocol.read_bytes()
    out = task.parent / 'pending'
    result = invoke('synthesis', 'run', '--input', source, '--protocol', protocol, '--output', out, '--json')
    assert result.exit_code == 1, result.output
    assert fake_key not in result.stdout + result.stderr
    summary = json.loads(result.stdout)
    pending = summary['analyses'][0] if multiple else summary
    assert pending['status'] == 'protocol_pending'
    assert pending['protocol_gaps'] == ['Unsupported method: [REDACTED]']
    if multiple:
        assert summary['analyses'][1]['result']['pooled_mean'] == pytest.approx(5)
        assert summary['analyses'][1]['selected_estimates'][0]['estimate_id'] == '0'
    for artifact in out.rglob('*'):
        if artifact.is_file() and artifact.suffix in {'.json', '.jsonl', '.md'}:
            assert fake_key.encode() not in artifact.read_bytes()
    assert protocol.read_bytes() == original
