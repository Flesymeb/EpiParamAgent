"""Shared-context synthesis contracts; synthetic fixtures, no reference answers."""
import copy
import json
from pathlib import Path

import pytest

from metaagent.synthesis.pi_agent import _prepare_workspace, pi_synthesis_fingerprint
from metaagent.synthesis.pi_tools import dispatch
from test_pi_synthesis_agent import ROWS, save, verified


CONTEXT = {'population': 'adults', 'parameter_type': 'incubation_period',
           'endpoint_definition': 'infection to symptom onset', 'group': None}
ESTIMAND = {'parameter_type': 'incubation_period', 'statistic': 'mean',
            'population': 'adults', 'group': None, 'timepoint': None,
            'endpoint_definition': 'infection to symptom onset', 'unit': 'days',
            'uncertainty': {'type': 'SE', 'level': None}}


def workspace(tmp_path, rows=None, context=CONTEXT):
    source = tmp_path/'methods.md'
    source.write_text('normal inverse-variance fixed-effect mean')
    return _prepare_workspace(records=copy.deepcopy(ROWS if rows is None else rows),
                              research_question='What is the mean?', review_context=context,
                              method_sources=[source], output_dir=tmp_path/'run')


def test_shared_context_is_copied_bounded_staged_and_fingerprint_bound(tmp_path):
    context = copy.deepcopy(CONTEXT)
    before = set(tmp_path.rglob('*'))
    first = pi_synthesis_fingerprint(records=ROWS, research_question='Q', review_context=context)
    assert set(tmp_path.rglob('*')) == before
    reordered = dict(reversed(list(context.items())))
    assert pi_synthesis_fingerprint(records=ROWS, research_question='Q', review_context=reordered)['fingerprint'] == first['fingerprint']
    context['population'] = 'children'
    assert first['review_context']['population'] == 'adults'
    assert pi_synthesis_fingerprint(records=ROWS, research_question='Q', review_context=context)['fingerprint'] != first['fingerprint']
    w = workspace(tmp_path)
    profile = dispatch(w, 'profile', {})
    assert profile['research_question'] == 'What is the mean?'
    assert profile['review_context'] == CONTEXT and profile['plan_contract_version'] == 2
    assert json.loads((w/'inputs/review_context.json').read_text()) == CONTEXT
    assert profile['tool_schema']['save_plan']['plan']['estimand']['uncertainty']['level'] is None
    for bad in ([], {'secret': 'sk-offline-test-credential'}, {'blob': 'x'*65537}):
        with pytest.raises(ValueError):
            pi_synthesis_fingerprint(records=ROWS, research_question='Q', review_context=bad)


def test_context_plan_requires_explicit_estimand_and_preserves_old_commit_on_error(tmp_path):
    w = workspace(tmp_path)
    with pytest.raises(ValueError, match='plan.estimand'):
        save(w)
    assert not (w/'analysis_plan.json').exists()
    save(w, estimand=ESTIMAND)
    before = {name: (w/name).read_bytes() for name in ('analysis_plan.json', 'analysis_selection.jsonl', 'plan_commit.json')}
    for change, message in (({'population': 'children'}, 'estimand'),
                            ({**ESTIMAND, 'uncertainty': {'type': 'CI', 'level': 95}}, 'probability'),
                            ({**ESTIMAND, 'unit': 'hours'}, 'unit')):
        with pytest.raises(ValueError, match=message):
            save(w, estimand=change)
        assert {name: (w/name).read_bytes() for name in before} == before
    # Unknown descriptors remain explicit; a pending plan never needs invented values.
    assert json.loads((w/'analysis_plan.json').read_text())['estimand']['group'] is None
    assert save(w, status='protocol_pending')['reproduction_status'] == 'protocol_pending'


def test_context_actual_execution_finalize_and_context_tamper_rejected(tmp_path):
    w = workspace(tmp_path)
    save(w, estimand=ESTIMAND)
    receipt = verified(w)
    final = dispatch(w, 'finalize', {'execution_id': receipt['execution_id']})
    assert final['result']['point_estimate'] == 5
    (w/'inputs/review_context.json').write_text('{"population":"changed"}')
    with pytest.raises(ValueError, match='review context changed'):
        dispatch(w, 'finalize', {'execution_id': receipt['execution_id']})


@pytest.mark.parametrize('field,left,right,key', [
    ('parameter_type', 'R0', 'Rt', 'mixed_parameters'),
    ('reproduction_number_type', 'R0', 'Rt', 'mixed_parameters'),
    ('estimate_measure', 'mean', 'median', 'mixed_statistics'),
    ('uncertainty_type', 'CI', 'CrI', 'mixed_uncertainty'),
    ('group_label', 'adults', 'children', 'mixed_groups'),
    ('stratum', 'overall', 'subgroup', 'mixed_groups'),
    ('population', 'adults', 'children', 'mixed_populations'),
    ('timepoint', 'infection', 'rash', 'mixed_timepoints'),
    ('time_window', 'baseline', 'followup', 'mixed_timepoints'),
    ('endpoint_definition', 'symptom onset', 'rash onset', 'mixed_endpoints'),
    ('clade', 'I', 'II', 'mixed_clades'),
    ('adjustment_status', 'adjusted', 'unadjusted', 'mixed_adjustment'),
    ('ci_level', .95, .90, 'mixed_interval_levels'),
])
def test_selected_context_cannot_silently_mix(tmp_path, field, left, right, key):
    rows = copy.deepcopy(ROWS)
    rows[0][field], rows[1][field] = left, right
    w = workspace(tmp_path, rows)
    with pytest.raises(ValueError, match='Heterogeneous'):
        save(w, estimand=ESTIMAND)
    # An explicit rule without assumptions AND planned sensitivity is insufficient.
    rule = {key: {'allowed': True, 'justification': 'Test-only hypothetical comparability.'}}
    with pytest.raises(ValueError, match='Heterogeneous'):
        save(w, estimand=ESTIMAND, compatibility=rule)
    saved = save(w, estimand=ESTIMAND, compatibility=rule,
                 assumptions=['Synthetic comparability assumption, not a source fact.'],
                 sensitivity=[{'name': 'Separate each original kind'}])
    assert saved['selected'] == 2
    assert json.loads((w/'inputs/table.jsonl').read_text().splitlines()[0])[field] == left


@pytest.mark.parametrize('field', ['transformations', 'assumptions', 'sensitivity', 'source_mapping'])
def test_provider_item_wrappers_are_not_repaired(tmp_path, field):
    w = workspace(tmp_path)
    with pytest.raises(ValueError, match=r'must be a list .*JSON array'):
        save(w, estimand=ESTIMAND, **{field: {'item': []}})
    assert not (w/'plan_commit.json').exists()


@pytest.mark.parametrize('field,value', [('interval_type','CrI'),('ci_level',.90)])
def test_normal_interval_cannot_relabel_credible_or_wrong_level(tmp_path,field,value):
    from metaagent.synthesis.pi_tools import validate_execution_result
    w=workspace(tmp_path);save(w,estimand=ESTIMAND);receipt=verified(w)
    proof=json.loads((w/'receipts'/f"{receipt['execution_id']}.json").read_text())
    result=json.loads((Path(proof['output_directory'])/'result.json').read_text())
    result['result'][field]=value
    with pytest.raises(ValueError,match='labeled CI'):
        validate_execution_result(w,result)


def test_prepopulated_se_does_not_erase_credible_interval_semantics(tmp_path):
    from metaagent.synthesis.pi_tools import validate_execution_result
    rows=copy.deepcopy(ROWS)
    for row in rows:row['uncertainty_type']='CrI'
    w=workspace(tmp_path,rows);save(w,estimand=ESTIMAND)
    value={'status':'complete','result':{'point_estimate':5,'unit':'days','method':'fixed'},
           'contributions':[{'input_id':r['estimate_id'],'value_used':r['point_estimate'],'se_used':1} for r in rows]}
    with pytest.raises(ValueError,match='cannot silently'):
        validate_execution_result(w,value)


def test_differing_units_cannot_pool_raw_values_or_disguise_wrong_factor(tmp_path):
    from metaagent.synthesis.pi_tools import validate_execution_result
    rows=[{'estimate_id':'h','point_estimate':72,'se':24,'unit':'hours',
           'cohort_id':'one','estimate_measure':'mean','uncertainty_type':'SE'}]
    w=workspace(tmp_path,rows)
    save(w,ids=['h'],estimand=ESTIMAND,transformations=[{'reason':'Hours to days, known factor 1/24.'}])
    value={'status':'complete','result':{'point_estimate':72,'unit':'days','method':'fixed'},
           'contributions':[{'input_id':'h','value_used':72,'se_used':24}], 'transformations':[]}
    with pytest.raises(ValueError,match='explicit point transformation'):
        validate_execution_result(w,value)
    value['transformations']=[{'input_id':'h','field':'point_estimate','before':72,'after':72,
                              'expression':'point_estimate/1','reason':'Wrong factor cannot be disguised by a ledger.'}]
    with pytest.raises(ValueError,match='source-to-target factor'):
        validate_execution_result(w,value)
    value['result']['point_estimate']=3;value['contributions'][0]['value_used']=3
    value['transformations'][0].update(after=3,expression='point_estimate/24')
    with pytest.raises(ValueError,match='Source SE'):
        validate_execution_result(w,value)
    value['contributions'][0]['se_used']=1
    value['transformations'].append({'input_id':'h','field':'se','before':24,'after':1,
                                     'expression':'se/24','reason':'Same hour-to-day factor.'})
    assert validate_execution_result(w,value)['result']['point_estimate']==3
