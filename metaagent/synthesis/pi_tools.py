"""Restricted workspace tools for Pi; stdin/stdout is one JSON document."""
from __future__ import annotations

import ast
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys

from .execution import execute_code, file_sha

TOOL_SCHEMA = {
    'method_capabilities': {},
    'compute_meta': {'contract':'Use saved plan selection and explicit method options; computes from reported SE/CI/SD only; cannot publish a final result'},
    'evidence_search': {'terms':['literal phrase'], 'source_id':'optional known source', 'limit':20, 'max_excerpt_chars':1600},
    'profile': {}, 'query': {'sql': 'SELECT columns FROM estimates WHERE ...', 'parameters': [], 'limit': 100, 'offset': 0},
    'evidence': {'source_id': 'method_001', 'offset': 0, 'length': 5000},
    'save_plan': {'plan': {'research_question': 'same question',
        'estimand': {'parameter_type': 'incubation_period|serial_interval|R0|Rt|Re|other explicit kind|NR',
                     'statistic': 'mean|median|proportion|other explicit statistic|NR',
                     'population': 'target population or NR', 'group': 'eligible group/stratum or NR',
                     'timepoint': 'time origin/window or NR', 'endpoint_definition': 'event definitions or NR',
                     'unit': 'days', 'uncertainty': {'type': 'CI|CrI|SE|SD|IQR|range|other|NR', 'level': None}},
        'method': {'name': 'fixed', 'unit': 'days', 'interval_method': 'normal', 'ci_level': 0.95, 'tau_estimator':'none', 'prediction_interval':False, 'log_transform':False, 'influence_diagnostics':False, 'publication_bias':False},
        'source_mapping': [{'source_id': 'method_001', 'quote': 'exact method source quote'}],
        'selection': {'selected_input_ids': ['existing input_id'], 'rationale': 'eligibility and independence rule',
                      'dependence': {'strategy': 'explicit strategy when cohorts are unknown/repeated', 'justification': 'source-backed independence/dependence rationale'}},
        'compatibility': {'mixed_statistics': {'allowed': True, 'justification': 'only when scientifically justified, with assumptions and sensitivity'},
                          'mixed_uncertainty': {'allowed': True, 'justification': 'explicit uncertainty comparability rationale'},
                          'mixed_parameters': {'allowed': True, 'justification': 'explicit parameter compatibility rationale'},
                          'mixed_groups': {'allowed': True, 'justification': 'explicit subgroup/stratum comparability rationale'},
                          'mixed_timepoints': {'allowed': True, 'justification': 'explicit origin/window comparability rationale'},
                          'mixed_endpoints': {'allowed': True, 'justification': 'explicit endpoint comparability rationale'},
                          'mixed_populations': {'allowed': True, 'justification': 'explicit target population comparability rationale'},
                          'mixed_clades': {'allowed': True, 'justification': 'explicit clade comparability rationale'},
                          'mixed_adjustment': {'allowed': True, 'justification': 'explicit adjusted/unadjusted comparability rationale'},
                          'mixed_interval_levels': {'allowed': True, 'justification': 'explicit source interval-level harmonization rationale'}},
        'transformations': [], 'assumptions': [], 'sensitivity': [], 'reproduction_status': 'reproduction|exploratory|protocol_pending|not_computable'}},
    'write_code': {'language': 'python', 'code': 'Read /inputs/table.jsonl and /analysis_plan.json; write /work/result.json'},
    'run_code': {}, 'finalize': {'execution_id': 'verified execution id returned by run_code'},
}


def _json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _write(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('Nonfinite result values are forbidden')
    if isinstance(value, dict):
        for item in value.values(): _finite(item)
    if isinstance(value, list):
        for item in value: _finite(item)


def _number(value):
    if isinstance(value, bool): return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError, OverflowError): return None


def _review_flag(value):
    """Parse CSV/JSON flags without treating the string 'False' as an issue.

    Unknown nonempty values conservatively remain pending. JSON-encoded empty
    issue lists/maps are common CSV cells and have the same meaning as []/{}.
    """
    if value is None:return False
    if isinstance(value,bool):return value
    if isinstance(value,(int,float)):
        return value != 0
    if isinstance(value,str):
        token=value.strip().casefold()
        if token in {'','false','0','no'}:return False
        if token in {'true','1','yes'}:return True
        try:
            decoded=json.loads(value)
            if isinstance(decoded,(list,dict)):return bool(decoded)
        except (ValueError,TypeError):pass
        return True
    return bool(value)


def _review_pending(row):
    return _review_flag(row.get('needs_review')) or _review_flag(row.get('review_flags'))


def _rows(workspace):
    return [json.loads(line) for line in (workspace / 'inputs/table.jsonl').read_text().splitlines() if line.strip()]


def _query(workspace, sql, parameters=(), *, limit=100, offset=0):
    if not isinstance(sql, str) or len(sql) > 20000 or not re.match(r'^\s*(SELECT|WITH)\b', sql, re.I):
        raise ValueError('query accepts bounded read-only SELECT/WITH SQL')
    connection = sqlite3.connect('file:' + str(workspace / 'inputs/records.sqlite') + '?mode=ro', uri=True)
    allowed_functions = {'count','sum','avg','min','max','total','coalesce','ifnull','nullif','abs','round','lower','upper','length','trim','substr','json_extract','json_type','json_array_length','like'}
    def authorize(action, one, two, *_):
        if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_RECURSIVE}: return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION and str(two or one).lower() in allowed_functions: return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY
    connection.set_authorizer(authorize)
    connection.set_progress_handler(lambda: 1 if (counter.__setitem__(0, counter[0]+1) or counter[0]>1000) else 0, 1000)
    counter = [0]
    try:
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1024*1024)
        cursor = connection.execute('SELECT * FROM (' + sql.rstrip().rstrip(';') + ') LIMIT ? OFFSET ?', [*parameters, limit, offset])
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]
    finally:
        connection.close()


def _clip(value, length=1200):
    if isinstance(value, str): return value[:length] + (' …' if len(value)>length else '')
    if isinstance(value, dict): return {k:_clip(v,length) for k,v in value.items()}
    if isinstance(value, list): return [_clip(v,length) for v in value[:200]]
    return value


def _source_mapping(workspace, mapping):
    sources = {s['source_id']:s for s in _json(workspace / 'workspace.json')['sources']}
    for item in mapping:
        if not isinstance(item,dict) or item.get('source_id') not in sources:
            raise ValueError('Method/source mapping refers to an unknown source')
        quote = item.get('quote')
        text = (workspace / sources[item['source_id']]['text_path']).read_text()
        if not isinstance(quote,str) or not quote.strip() or quote not in text:
            raise ValueError('Method/source quotations must be exact staged source text')


def _validate_estimand(plan, meta):
    """Require explicit target semantics for shared-context plans, never fill them."""
    required = meta.get('plan_contract_version', 1) >= 2 and plan.get('reproduction_status') not in {'protocol_pending','not_computable'}
    estimand = plan.get('estimand')
    if estimand is None and not required:
        return  # Legacy callers without a shared review context remain readable.
    if not isinstance(estimand,dict):
        raise ValueError('plan.estimand must be an object defining the common analysis target; unknown fields may be NR/null')
    keys = {'parameter_type','statistic','population','group','timepoint','endpoint_definition','unit','uncertainty'}
    if keys - estimand.keys():
        raise ValueError('plan.estimand requires parameter_type, statistic, population, group, timepoint, endpoint_definition, unit and uncertainty; use NR/null rather than invent missing information')
    uncertainty = estimand['uncertainty']
    if not isinstance(uncertainty,dict) or not {'type','level'} <= uncertainty.keys():
        raise ValueError('plan.estimand.uncertainty requires {type: CI|CrI|SE|SD|IQR|range|NR, level: explicit probability or null}')
    level = uncertainty['level']
    if level is not None and (_number(level) is None or not 0 < float(level) < 1):
        raise ValueError('plan.estimand.uncertainty.level must be a probability in (0,1) or null; no default confidence level')
    unit = estimand.get('unit')
    if unit not in (None,'','NR') and str(unit).strip().casefold() != str(plan['method'].get('unit','')).strip().casefold():
        raise ValueError('plan.estimand.unit must equal method.unit; conversions belong in the explicit transformation ledger')


def save_plan(workspace, payload):
    plan = payload.get('plan')
    if not isinstance(plan,dict): raise ValueError('save_plan requires plan object')
    meta = _json(workspace / 'workspace.json')
    if plan.get('research_question') != meta['research_question']: raise ValueError('Analysis plan cannot change the research question')
    if not isinstance(plan.get('method'),dict) or not plan['method'].get('name'): raise ValueError('Declare a statistical method')
    from .statistical_verification import METHOD_ALIASES, INTERVALS
    method=plan['method'];canonical=METHOD_ALIASES.get(str(method['name']).casefold())
    if method.get('interval_method') is not None and method['interval_method'] not in INTERVALS:
        if canonical is not None:raise ValueError('Known inverse-variance method requires normal, hk or modified_hk interval')
    if method.get('ci_level') is not None and (_number(method['ci_level']) is None or not 0<float(method['ci_level'])<1):raise ValueError('ci_level must be an explicit probability')
    for option in ('prediction_interval','log_transform','influence_diagnostics','publication_bias'):
        if option in method and not isinstance(method[option],bool):raise ValueError(option+' must be a JSON boolean')
    if canonical is not None and method.get('tau_estimator') is not None:
        tau='none' if canonical=='fixed' else 'DL' if canonical=='random' else 'REML'
        if str(method['tau_estimator']).casefold()!=tau.casefold():raise ValueError('Declared tau estimator conflicts with method name')
    status = plan.get('reproduction_status')
    if status not in {'reproduction','exploratory','protocol_pending','not_computable'}: raise ValueError('Declare reproduction_status')
    for key in ('transformations','assumptions','sensitivity','source_mapping'):
        if not isinstance(plan.get(key,[]),list): raise ValueError(key+' must be a list (JSON array): use [] when empty or [{...}] for objects; never {"item": [...]} or an empty string')
        plan.setdefault(key,[])
    _validate_estimand(plan, meta)
    _source_mapping(workspace, plan['source_mapping'])
    if status == 'reproduction' and not plan['source_mapping']: raise ValueError('Reproduction requires exact method/source mapping')
    if status == 'exploratory' and (not plan['assumptions'] or not plan['sensitivity']):
        raise ValueError('Exploratory analysis requires explicit assumptions and sensitivity checks')
    selection = plan.get('selection',{})
    if not isinstance(selection,dict) or not selection.get('rationale'): raise ValueError('Selection needs an explicit rationale')
    if 'selected_input_ids' in selection and 'sql' in selection: raise ValueError('Use selection IDs or SQL, not both')
    rows = _rows(workspace); known = {r['input_id']:r for r in rows}
    if 'sql' in selection:
        selected = _query(workspace,selection['sql'],selection.get('parameters',[]),limit=len(rows)+1)
        if any(set(r)!={'input_id'} for r in selected): raise ValueError('Selection SQL must return only input_id')
        ids = [r['input_id'] for r in selected]
    else: ids = selection.get('selected_input_ids',[])
    if not isinstance(ids,list) or any(not isinstance(i,str) or i not in known for i in ids) or len(ids)!=len(set(ids)):
        raise ValueError('Selection must use unique existing input IDs, never invented rows')
    if status not in {'protocol_pending','not_computable'} and not ids: raise ValueError('Computable plan needs selected inputs')
    selected_rows = [known[i] for i in ids]
    cohorts = [r.get('cohort_id') for r in selected_rows]
    unknown_cohorts = any(c in (None, '', 'NR') for c in cohorts)
    named_cohorts = [str(c) for c in cohorts if c not in (None, '', 'NR')]
    repeated_cohorts = len(set(named_cohorts)) != len(named_cohorts)
    dependence = selection.get('dependence', {})
    if len(selected_rows)>1 and (unknown_cohorts or repeated_cohorts):
        if not isinstance(dependence,dict) or not dependence.get('strategy') or not dependence.get('justification'):
            raise ValueError('Unknown/repeated cohort identities require selection.dependence={strategy: ..., justification: ...} inside plan.selection; include explicit assumptions and sensitivity')
        if not plan['assumptions'] or not plan['sensitivity']:
            raise ValueError('Uncertain dependence requires explicit assumptions and sensitivity analysis')
    compatibility = plan.get('compatibility',{})
    for key, field in (('mixed_statistics','estimate_measure'),('mixed_uncertainty','uncertainty_type'),
                       ('mixed_parameters','parameter_type'),('mixed_parameters','reproduction_number_type'),
                       ('mixed_groups','group_label'),('mixed_groups','stratum'),
                       ('mixed_populations','population'),('mixed_timepoints','timepoint'),
                       ('mixed_timepoints','time_window'),('mixed_endpoints','endpoint_definition'),
                       ('mixed_clades','clade'),('mixed_adjustment','adjustment_status'),
                       ('mixed_interval_levels','ci_level'),('mixed_interval_levels','uncertainty_level')):
        values = {str(r.get(field)).casefold() for r in selected_rows if r.get(field) not in (None,'','NR')}
        if len(values)>1:
            rule = compatibility.get(key,{})
            if not isinstance(rule,dict) or rule.get('allowed') is not True or not rule.get('justification') or not plan['assumptions'] or not plan['sensitivity']:
                raise ValueError('Heterogeneous '+field+' requires plan.compatibility.'+key+'={allowed:true,justification:...}, explicit assumptions and sensitivity; no default mixing')
    plan['selection'] = {**selection,'selected_input_ids':ids}
    _finite(plan)
    reasons=selection.get('reasons',{})
    if not isinstance(reasons,dict) or any(k not in known or not isinstance(v,str) or not v.strip() for k,v in reasons.items()):
        raise ValueError('Per-input selection reasons must bind existing IDs and nonempty text')
    decisions = [{'input_id':r['input_id'],'estimate_id':r.get('estimate_id'),'record_id':r.get('record_id'),
                  'decision':'selected' if r['input_id'] in set(ids) else 'excluded','reason':reasons.get(r['input_id'],selection['rationale'])} for r in rows]
    # Validate the whole request before publishing either file. The commit binds
    # both files, so interrupted publication is rejected by the execution gate.
    selection_text=''.join(json.dumps(d,ensure_ascii=False)+'\n' for d in decisions)
    _write(workspace / 'analysis_plan.json',plan)
    temporary=workspace/'analysis_selection.jsonl.tmp';temporary.write_text(selection_text);temporary.replace(workspace/'analysis_selection.jsonl')
    _write(workspace/'plan_commit.json',{'plan_sha256':file_sha(workspace/'analysis_plan.json'),'selection_sha256':file_sha(workspace/'analysis_selection.jsonl')})
    return {'plan_sha256':file_sha(workspace/'analysis_plan.json'),'selected':len(ids),'excluded':len(rows)-len(ids),
            'reproduction_status':status,'plan_path':'/analysis_plan.json'}


def _expression(expression, row):
    tree = ast.parse(expression,mode='eval')
    if len(list(ast.walk(tree)))>100: raise ValueError('Transformation expression is too complex')
    def evaluate(node):
        if isinstance(node,ast.Constant) and type(node.value) in (int,float): return node.value
        if isinstance(node,ast.Name) and _number(row.get(node.id)) is not None: return _number(row[node.id])
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.USub,ast.UAdd)):
            v=evaluate(node.operand);return -v if isinstance(node.op,ast.USub) else v
        if isinstance(node,ast.BinOp):
            a,b=evaluate(node.left),evaluate(node.right)
            if isinstance(node.op,ast.Add):return a+b
            if isinstance(node.op,ast.Sub):return a-b
            if isinstance(node.op,ast.Mult):return a*b
            if isinstance(node.op,ast.Div):return a/b
            if isinstance(node.op,ast.Pow) and abs(b)<=10:return a**b
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and len(node.args)==1 and not node.keywords:
            f={'sqrt':math.sqrt,'log':math.log,'exp':math.exp,'abs':abs}.get(node.func.id)
            if f:return f(evaluate(node.args[0]))
        raise ValueError('Unsupported transformation expression; use scalar input fields and arithmetic/log/exp/sqrt/abs')
    value=evaluate(tree.body)
    if _number(value) is None:raise ValueError('Invalid transformation value')
    return value


def validate_execution_result(workspace, value):
    if not isinstance(value,dict): raise ValueError('result.json must be an object')
    _finite(value)
    if value.get('status') not in {'complete','partial','not_computable','protocol_pending'}:raise ValueError('Declare an honest result status')
    plan=_json(workspace/'analysis_plan.json');rows={r['input_id']:r for r in _rows(workspace)};ids=plan['selection']['selected_input_ids']
    contributions=value.get('contributions',[])
    if not isinstance(contributions,list):raise ValueError('contributions must be a list')
    seen=[r.get('input_id') for r in contributions if isinstance(r,dict)]
    if len(seen)!=len(contributions) or len(seen)!=len(set(seen)) or set(seen)!=set(ids):
        raise ValueError('Contribution IDs must exactly match planned selected inputs')
    ledger=value.get('transformations',[])
    if not isinstance(ledger,list):raise ValueError('Provide an explicit transformation ledger')
    if ledger and not plan['transformations']:raise ValueError('Transformations must first be declared in the analysis plan')
    changes={}
    for change in ledger:
        if not isinstance(change,dict) or change.get('input_id') not in ids or not change.get('field') or not change.get('expression'):
            raise ValueError('Transformation must bind a selected input/field and auditable expression')
        row=rows[change['input_id']];key=(change['input_id'],change['field'])
        if key in changes:raise ValueError('Duplicate transformation target')
        if change.get('before')!=row.get(change['field']):raise ValueError('input_id='+change['input_id']+', field='+str(change['field'])+': Transformation before value differs from original input')
        actual=_expression(change['expression'],row)
        if _number(change.get('after')) is None or not math.isclose(actual,float(change['after']),rel_tol=1e-9,abs_tol=1e-10):
            raise ValueError('input_id='+change['input_id']+', field='+str(change['field'])+': Transformation does not reproduce its declared value')
        if not change.get('reason'):
            raise ValueError('Every transformation needs a scientific/unit rationale')
        changes[key]=change['after']
    for contribution in contributions:
        row=rows[contribution['input_id']]
        if 'value_used' not in contribution:raise ValueError('Each contribution needs value_used')
        used=_number(contribution['value_used']);original=_number(row.get('point_estimate'))
        transformed=changes.get((contribution['input_id'],'point_estimate'),original)
        if used is None or transformed is None or not math.isclose(used,float(transformed),rel_tol=1e-9,abs_tol=1e-10):
            raise ValueError('Contribution value is not an original or audited transformed point')
        unit = str(row.get('unit') or '').strip().casefold()
        target_unit = str(plan['method'].get('unit') or '').strip().casefold()
        from .engine import _UNITS
        source_scale, target_scale = _UNITS.get(unit), _UNITS.get(target_unit)
        factor = 1.0
        if unit != target_unit:
            if source_scale is None or target_scale is None or source_scale[0] != target_scale[0]:
                raise ValueError('Unknown or incompatible unit conversion cannot be inferred; use a scientifically supported common unit')
            factor = source_scale[1] / target_scale[1]
        if factor != 1:
            if (contribution['input_id'],'point_estimate') not in changes:
                raise ValueError('Differing input units require an explicit point transformation ledger')
            if original is None or not math.isclose(used, original*factor, rel_tol=1e-9, abs_tol=1e-10):
                raise ValueError('Unit conversion does not match the independently verified source-to-target factor; statistic conversions cannot be hidden inside unit conversion')
        if 'se_used' in contribution:
            uncertainty=str(row.get('uncertainty_type') or '').upper()
            if uncertainty not in {'','NR','SE','CI','SD'}:
                rule=plan.get('compatibility',{}).get('mixed_uncertainty',{})
                if not isinstance(rule,dict) or rule.get('allowed') is not True or not rule.get('justification') or not plan['assumptions'] or not value.get('sensitivity'):
                    raise ValueError('Non-CI/SE/SD uncertainty cannot silently become a frequentist SE; declare compatibility, assumptions and sensitivity')
            original_se=_number(row.get('se'))
            if original_se is None and str(row.get('uncertainty_type','')).upper()=='SE':original_se=_number(row.get('uncertainty_high'))
            se=changes.get((contribution['input_id'],'se'),original_se)
            if se is None and (contribution['input_id'],'se') not in changes:
                raise ValueError('input_id='+contribution['input_id']+': missing se derivation: no directly reported SE; provide an explicit CI/SD-to-SE transformation ledger even when the source unit already matches the analysis unit. Do not invent missing uncertainty or sample size.')
            if factor != 1 and original_se is not None:
                if (contribution['input_id'],'se') not in changes or _number(se) is None or not math.isclose(float(se),original_se*abs(factor),rel_tol=1e-9,abs_tol=1e-10):
                    raise ValueError('input_id='+contribution['input_id']+': Source SE must use the same unit conversion factor in an explicit SE ledger')
            if uncertainty in {'CI','SD'}:
                from .engine import UncertaintyRules, _se
                candidate, _, reason = _se(row,UncertaintyRules(allowed_types=[uncertainty]))
                # A directly reported SE may differ slightly from rounded source
                # intervals. Derived ledgers must reproduce the declared formula.
                tolerance=1e-8 if (contribution['input_id'],'se') in changes else 0.15
                if reason or candidate is None or se is None or not math.isclose(float(se),candidate*abs(factor),rel_tol=tolerance,abs_tol=1e-10):
                    raise ValueError('input_id='+contribution['input_id']+': SE derivation conflicts with reported uncertainty/level/sample size; reason='+(reason or 'declared SE differs from source CI/SD derivation after the source-to-analysis unit conversion'))
            if se is None or _number(contribution['se_used']) is None or se<=0 or not math.isclose(float(se),float(contribution['se_used']),rel_tol=1e-9):
                raise ValueError('input_id='+contribution['input_id']+': SE is missing or lacks an explicit auditable derivation matching se_used; SE must be positive and agree with its source or ledger')
    result=value.get('result')
    if value['status'] in {'complete','partial'}:
        if not isinstance(result,dict) or _number(result.get('point_estimate')) is None or not result.get('unit') or not result.get('method'):
            raise ValueError('Complete result needs a finite point, unit and method')
        if result['method'] != plan['method']['name'] or result['unit'] != plan['method'].get('unit'):
            raise ValueError('Executed result method/unit must match the saved plan')
        lower,upper=result.get('ci_lower'),result.get('ci_upper')
        if (lower is None)!=(upper is None) or lower is not None and (_number(lower) is None or _number(upper) is None or lower>upper):
            raise ValueError('Interval endpoints must be finite, paired and ordered')
        from .statistical_verification import METHOD_ALIASES, verify_meta_result
        canonical=METHOD_ALIASES.get(str(plan['method']['name']).casefold())
        if canonical is not None:
            statistics={str(rows[i].get('estimate_measure') or '').casefold() for i in ids}
            if any(stat not in {'mean',''} for stat in statistics):
                rule=plan.get('compatibility',{}).get('mixed_statistics',{})
                if not isinstance(rule,dict) or rule.get('allowed') is not True or not rule.get('justification') or not plan['assumptions'] or not value.get('sensitivity'):
                    raise ValueError('Non-mean statistics cannot silently become an inverse-variance mean')
        value['independent_verification']=verify_meta_result(contributions,plan['method'],result)
    elif result is not None:raise ValueError('Noncomputable status cannot expose a numeric result')
    if plan['reproduction_status']=='exploratory' and not value.get('sensitivity'):
        raise ValueError('Exploratory execution must include its declared sensitivity results')
    for check in value.get('sensitivity',[]):
        if not isinstance(check,dict) or not check.get('name'):
            raise ValueError('Sensitivity outputs need named structured checks')
        check_ids=check.get('selected_input_ids',[])
        if not isinstance(check_ids,list) or len(set(check_ids))!=len(check_ids) or any(i not in rows for i in check_ids):
            raise ValueError('Sensitivity contributions cannot invent input IDs')
    return value


def run_code(workspace, payload):
    if not (workspace/'analysis_plan.json').exists():raise ValueError('Save the structured analysis plan first')
    commit=_json(workspace/'plan_commit.json')
    if commit!={'plan_sha256':file_sha(workspace/'analysis_plan.json'),'selection_sha256':file_sha(workspace/'analysis_selection.jsonl')}:raise ValueError('Plan/selection publication is incomplete; save the plan again')
    state=_json(workspace/'code/current.json');settings=_json(workspace/'run_settings.json')
    existing=list((workspace/'receipts').glob('*.json')) if (workspace/'receipts').exists() else []
    if len(existing)>=2*int(settings.get('max_executions',3)):raise ValueError('Code execution budget exhausted')
    code=workspace/state['path'];first=execute_code(workspace,code,settings,language=state['language'])
    if first['status']!='complete':return {'status':'failed','execution':first}
    try:
        value=validate_execution_result(workspace,_json(Path(first['output_directory'])/'result.json'))
        second=execute_code(workspace,code,settings,language=state['language'])
        if second['status']!='complete':raise ValueError('Repeated execution failed')
        repeat=validate_execution_result(workspace,_json(Path(second['output_directory'])/'result.json'))
        if json.dumps(value,sort_keys=True,allow_nan=False)!=json.dumps(repeat,sort_keys=True,allow_nan=False):
            raise ValueError('Code reruns produced inconsistent numeric/selection/ledger results')
        first.update(validation_status='verified',repeat_execution_id=second['execution_id'],result_sha256=file_sha(Path(first['output_directory'])/'result.json'))
    except Exception as exc:
        first.update(validation_status='failed',validation_error=str(exc))
    _write(workspace/'receipts'/f"{first['execution_id']}.json",first)
    return {'status':'verified' if first.get('validation_status')=='verified' else 'failed','execution_id':first['execution_id'],
            'validation_error':first.get('validation_error'),'stdout_tail':first['stdout_tail'][-4000:],'stderr_tail':first['stderr_tail'][-4000:],
            'result_summary':value.get('result') if first.get('validation_status')=='verified' else None}


def finalize(workspace, payload):
    identifier=payload.get('execution_id','')
    if not isinstance(identifier,str) or not re.fullmatch('[a-f0-9]{32}',identifier):raise ValueError('Use a verified execution_id')
    receipt_path=workspace/'receipts'/f'{identifier}.json';receipt=_json(receipt_path)
    if receipt.get('validation_status')!='verified':raise ValueError('Only a successfully executed and repeated result can be finalized')
    current=_json(workspace/'code/current.json')
    meta=_json(workspace/'workspace.json')
    if meta.get('review_context_sha256') and file_sha(workspace/'inputs/review_context.json')!=meta['review_context_sha256']:
        raise ValueError('Shared review context changed after staging; do not reuse this analysis')
    for source in meta['sources']:
        if file_sha(workspace/source['text_path'])!=source['text_sha256'] or file_sha(workspace/source['original_path'])!=source['original_sha256']:
            raise ValueError('Staged method source changed after execution')
    if receipt.get('workspace_sha256')!=file_sha(workspace/'workspace.json'):raise ValueError('Workspace/source bindings changed after execution')
    if receipt['plan_sha256']!=file_sha(workspace/'analysis_plan.json') or receipt['code_sha256']!=file_sha(workspace/current['path']) or receipt['input_sha256']!=file_sha(workspace/'inputs/table.jsonl'):
        raise ValueError('Code, plan or input changed after execution; rerun before finalizing')
    output=Path(receipt['output_directory']);result_path=output/'result.json'
    if result_path.is_symlink() or file_sha(result_path)!=receipt['result_sha256']:raise ValueError('Executed result changed after verification')
    for name,meta in receipt['outputs'].items():
        p=output/name
        if p.is_symlink() or not p.resolve().is_relative_to(output) or file_sha(p)!=meta['sha256']:raise ValueError('Execution artifact changed after verification')
    value=validate_execution_result(workspace,_json(result_path));plan=_json(workspace/'analysis_plan.json');raw={r['input_id']:r for r in _rows(workspace)}
    value.update(reproduction_status=plan['reproduction_status'],research_question=plan['research_question'],
                 validation={'numeric_provenance':'sandbox_executed_and_repeated','scientific_correctness':'not_independently_verified'},
                 execution_id=identifier,input_sha256=receipt['input_sha256'],code_sha256=receipt['code_sha256'],plan_sha256=receipt['plan_sha256'])
    value['estimand']=plan.get('estimand')
    value['analysis_method']=plan['method']
    value['method_sources']=_json(workspace/'workspace.json')['sources']
    for c in value['contributions']:
        c['source_raw']=raw[c['input_id']]
        c['source_row_sha256']=hashlib.sha256(json.dumps(raw[c['input_id']],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    unresolved=sum(_review_pending(raw[c['input_id']]) for c in value['contributions'])
    value['counts']={'input':len(raw),'selected':len(value['contributions']),'excluded':len(raw)-len(value['contributions']),'selected_needs_review':unresolved,'independent_studies':None}
    if value['status']=='complete' and unresolved:value['status']='partial'
    public=workspace/'published';public.mkdir(exist_ok=True)
    _write(public/'synthesis_result.json',value);_write(public/'transformation_ledger.json',value.get('transformations',[]))
    shutil.copyfile(workspace/'analysis_plan.json',public/'analysis_plan.json');shutil.copyfile(workspace/'analysis_selection.jsonl',public/'analysis_selection.jsonl')
    shutil.copyfile(workspace/current['path'],public/('analysis.py' if current['language']=='python' else 'analysis.R'));shutil.copyfile(receipt_path,public/'execution_receipt.json')
    lines=['# Synthesis execution report','',f"Status: {value['status']}",f"Reproduction status: {plan['reproduction_status']}",'',
           'Independent numeric verification: '+value.get('independent_verification',{}).get('status','not_supported'),
           'Numbers below come only from the sandbox execution artifact.','',json.dumps(value.get('result'),ensure_ascii=False,indent=2),
           '',f"Contributions: {len(value['contributions'])}",'','Assumptions:',json.dumps(plan['assumptions'],ensure_ascii=False,indent=2),
           '', 'Scientific correctness has not been independently verified. Exploratory results do not establish original-SR reproduction.']
    (public/'report.md').write_text('\n'.join(lines)+'\n')
    artifacts={'synthesis_result':str(public/'synthesis_result.json'),'synthesis_report':str(public/'report.md'),'analysis_plan':str(public/'analysis_plan.json'),
               'analysis_selection':str(public/'analysis_selection.jsonl'),'transformation_ledger':str(public/'transformation_ledger.json'),
               'analysis_code':str(public/('analysis.py' if current['language']=='python' else 'analysis.R')),'execution_receipt':str(public/'execution_receipt.json')}
    for name,key in (('forest.png','forest_png'),('forest.pdf','forest_pdf')):
        if name in receipt['outputs']:
            shutil.copyfile(output/name,public/name);artifacts[key]=str(public/name)
    value['artifacts']=artifacts;_write(workspace/'final_result.json',value)
    return {'status':value['status'],'result':value.get('result'),'artifacts':artifacts}


def compute_meta(workspace):
    """Bounded calculation helper; final publication still requires executed code."""
    from types import SimpleNamespace
    from .engine import UncertaintyRules, _UNITS, _se
    from .methods import calculate
    from .statistical_verification import METHOD_ALIASES
    if not (workspace/'analysis_plan.json').is_file():raise ValueError('Save the analysis plan before compute_meta')
    plan=_json(workspace/'analysis_plan.json');method=plan['method'];canonical=METHOD_ALIASES.get(str(method['name']).casefold())
    if canonical is None:raise ValueError('compute_meta supports fixed, DL random and REML; inspect method_capabilities')
    if 'ci_level' not in method or 'interval_method' not in method:raise ValueError('Declare ci_level and interval_method before compute_meta')
    target=_UNITS.get(str(method.get('unit','')).casefold())
    if target is None:raise ValueError('Unsupported canonical unit')
    by_id={r['input_id']:r for r in _rows(workspace)};selected=[];derivations=[]
    for identifier in plan['selection']['selected_input_ids']:
        source=by_id[identifier];unit=_UNITS.get(str(source.get('unit','')).casefold())
        if unit is None or unit[0]!=target[0]:raise ValueError('Unknown or incompatible source unit')
        factor=unit[1]/target[1]
        point=_number(source.get('point_estimate'))
        if point is None:raise ValueError('Missing point estimate; helper never derives a missing point')
        se,derivation,reason=_se(source,UncertaintyRules(allowed_types=['SE','CI','SD']))
        if reason:raise ValueError('Unsupported uncertainty for '+identifier+': '+reason)
        selected.append(dict(source,point_estimate=point*factor,se=se*abs(factor),estimate_id=identifier))
        derivations.append({'input_id':identifier,'value_used':point*factor,'se_used':se*abs(factor),'unit_factor':factor,'se_derivation':derivation})
    cohorts=[row.get('cohort_id') for row in selected]
    if len(selected)>1 and (any(c in (None,'','NR') for c in cohorts) or len(set(map(str,cohorts)))!=len(cohorts)):
        raise ValueError('compute_meta requires known distinct cohorts; use explicit generated dependence-model code otherwise')
    p=SimpleNamespace(method=canonical,ci_level=float(method['ci_level']),interval_method=method['interval_method'],
        prediction_interval=bool(method.get('prediction_interval',False)),log_transform=bool(method.get('log_transform',False)),unit=method['unit'],
        parameter_type=(plan.get('estimand') or {}).get('parameter_type','NR'),estimate_measure=(plan.get('estimand') or {}).get('statistic','mean'))
    result,forest=calculate(selected,p,target[1])
    from .engine import _safe
    result,forest=_safe(result),_safe(forest)
    result['method']=method['name']
    diagnostics={}
    if method.get('influence_diagnostics'):
        from .diagnostics import influence_diagnostics
        diagnostics['influence_diagnostics']=_safe(influence_diagnostics(selected,p,target[1],result))
    if method.get('publication_bias'):
        from .diagnostics import publication_bias_diagnostics
        diagnostics['publication_bias']=_safe(publication_bias_diagnostics(selected,p))
    return {**diagnostics,'status':'calculated_candidate','publication':'requires_write_code_run_code_finalize',
        'plan_sha256':file_sha(workspace/'analysis_plan.json'),'result':result,'contributions':derivations,'forest_data':forest}


def dispatch(workspace: Path, action: str, payload: dict):
    workspace=Path(workspace).resolve()
    if not (workspace/'workspace.json').is_file():raise ValueError('Uninitialized synthesis workspace')
    settings=_json(workspace/'run_settings.json');history=workspace/'tool_events.jsonl'
    count=sum(1 for _ in history.open()) if history.exists() else 0
    if count>=int(settings.get('max_tool_calls',80)):raise ValueError('Workspace tool-call budget exhausted')
    with history.open('a') as h:h.write(json.dumps({'action':action})+'\n')
    if not isinstance(payload,dict):raise ValueError('Tool payload must be an object')
    if action=='profile':return {**_json(workspace/'inputs/profile.json'),'sources':_json(workspace/'workspace.json')['sources'],'tool_schema':TOOL_SCHEMA,
                               'json_contract':'Arrays are JSON lists: [] or [{...}], never {"item": [...]} or empty strings. Read the exact research_question and review_context here.'}
    if action=='method_capabilities':
        from .statistical_verification import method_capabilities
        return method_capabilities()
    if action=='compute_meta':
        if payload:raise ValueError('compute_meta takes no arguments; uses saved plan and immutable source rows')
        return compute_meta(workspace)
    if action=='evidence_search':
        from metaagent.evidence_search import search_evidence
        sources=_json(workspace/'workspace.json')['sources']
        if payload.get('source_id'):
            sources=[s for s in sources if s['source_id']==payload['source_id']]
            if not sources:raise ValueError('Unknown source_id')
        supplied=[]
        for source in sources:
            path=workspace/source['text_path']
            if file_sha(path)!=source['text_sha256']:raise ValueError('Staged evidence source changed')
            supplied.append({'source_id':source['source_id'],'text':path.read_text()})
        return search_evidence(supplied,payload.get('terms'),limit=payload.get('limit',20),max_excerpt_chars=payload.get('max_excerpt_chars',1600))
    if action=='query':
        limit=min(200,max(1,int(payload.get('limit',100))));offset=max(0,int(payload.get('offset',0)))
        result=_query(workspace,payload.get('sql'),payload.get('parameters',[]),limit=limit,offset=offset)
        clipped=_clip(result);data=json.dumps(clipped,ensure_ascii=False)
        while len(data)>64000 and clipped:clipped.pop();data=json.dumps(clipped,ensure_ascii=False)
        return {'rows':clipped,'returned':len(clipped),'offset':offset,'next_offset':offset+len(clipped),'bounded':True}
    if action=='evidence':
        source=next((s for s in _json(workspace/'workspace.json')['sources'] if s['source_id']==payload.get('source_id')),None)
        if not source:raise ValueError('Unknown source_id')
        start=max(0,int(payload.get('offset',0)));length=min(8000,max(1,int(payload.get('length',5000))));text=(workspace/source['text_path']).read_text()
        return {'source_id':source['source_id'],'offset':start,'text':text[start:start+length],'next_offset':min(len(text),start+length),'total_characters':len(text),'original_sha256':source['original_sha256']}
    if action=='save_plan':return save_plan(workspace,payload)
    if action=='write_code':
        code=payload.get('code');language=payload.get('language','python')
        if language not in {'python','r'} or not isinstance(code,str) or not code.strip() or len(code)>100000:raise ValueError('Provide bounded Python or R source code')
        if re.search(r'\bsk-[A-Za-z0-9_-]{8,}',code):raise ValueError('Credential-like material is forbidden in generated code')
        path=workspace/'code'/('analysis.py' if language=='python' else 'analysis.R');path.write_text(code)
        _write(workspace/'code/current.json',{'language':language,'path':str(path.relative_to(workspace))})
        return {'code_sha256':file_sha(path),'language':language,'sandbox_paths':{'table':'/inputs/table.jsonl','sqlite':'/inputs/records.sqlite','plan':'/analysis_plan.json','sources':'/sources','output':'/work/result.json'}}
    if action=='run_code':return run_code(workspace,payload)
    if action=='finalize':return finalize(workspace,payload)
    raise ValueError('Unknown synthesis tool action')


def main():
    try:
        raw=sys.stdin.read(262145)
        if len(raw)>262144:raise ValueError('Tool input exceeds budget')
        request=json.loads(raw);action=request.get('action')
        result=dispatch(Path(os.environ['METAAGENT_SYNTHESIS_WORKSPACE']),action,request.get('payload',{}))
        response={'ok':True,'action':action,'result':result}
    except Exception as exc:
        response={'ok':False,'error':{'type':type(exc).__name__,'message':str(exc),'recoverable':True}}
    sys.stdout.write(json.dumps(response,ensure_ascii=False,allow_nan=False)+'\n')


if __name__=='__main__':main()
