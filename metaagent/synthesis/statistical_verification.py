"""Independent statistical oracle; does not import the production pooling code."""
from __future__ import annotations
import math
from scipy.optimize import brentq
from scipy.stats import chi2, norm, t
VERSION = 'synthesis-statistics-v1'
METHOD_ALIASES = {'fixed':'fixed','inverse_variance_fixed':'fixed','random':'random','dl':'random','dersimonian_laird':'random','random_effects':'random','random-effects':'random','reml':'reml','restricted_maximum_likelihood':'reml'}
INTERVALS = {'normal','hk','modified_hk'}


def method_capabilities():
    return {'version':VERSION,'aliases':METHOD_ALIASES,'interval_methods':sorted(INTERVALS),
            'prediction_interval':'t_k_minus_2','minimum_hk_estimates':2,'minimum_prediction_estimates':3,
            'scope':'independent inverse-variance effects on the declared analysis scale',
            'unsupported_is_verified':False,'missing_uncertainty_is_imputed':False}


def independent_meta(values, standard_errors, *, method, ci_level=.95, interval_method='normal', prediction_interval=False):
    """Recompute fixed/DL/REML using a score-root rather than production optimizer."""
    method = METHOD_ALIASES.get(str(method).casefold())
    if method is None or interval_method not in INTERVALS:raise ValueError('Unsupported independent numeric method or interval')
    if isinstance(ci_level,bool) or not 0 < float(ci_level) < 1:raise ValueError('ci_level must be an explicit probability')
    if len(values) != len(standard_errors) or not values:raise ValueError('Provide matched nonempty value/SE arrays')
    y,ses=[float(v) for v in values],[float(v) for v in standard_errors]
    if any(isinstance(v,bool) or not math.isfinite(n) for v,n in zip(values,y)) or any(isinstance(s,bool) or not math.isfinite(n) or n<=0 for s,n in zip(standard_errors,ses)):
        raise ValueError('Effects must be finite; SEs must be positive finite numbers')
    variances=[s*s for s in ses]
    if any(not math.isfinite(v) or v<=0 for v in variances):raise ValueError('Unrepresentable sampling variance')
    k=len(y);w0=[1/v for v in variances];total0=math.fsum(w0)
    mean0=math.fsum(w*a for w,a in zip(w0,y))/total0
    q=math.fsum(w*(a-mean0)**2 for w,a in zip(w0,y));tau=0.
    convergence={'method':'closed_form','converged':True,'boundary':True}
    if method=='random' and k>1:
        c=total0-math.fsum(w*w for w in w0)/total0
        tau=max(0.,(q-k+1)/c) if c>0 else 0.
    elif method=='reml' and k>1:
        def score(value):
            ws=[1/(v+value) for v in variances];total=math.fsum(ws)
            centre=math.fsum(w*a for w,a in zip(ws,y))/total
            return math.fsum(w*w*(a-centre)**2 for w,a in zip(ws,y))-total+math.fsum(w*w for w in ws)/total
        upper=max(max(variances),max((a-mean0)**2 for a in y),1e-12)*100
        for _ in range(100):
            if score(upper)<0:break
            upper*=2
        else:raise ArithmeticError('REML score root could not be bracketed')
        # REML may have multiple stationary points; a nonpositive boundary score
        # alone does not establish the global maximum. Enumerate sign crossings.
        lower=max(min(variances)*1e-10,upper*1e-16)
        grid=[0.]+[math.exp(math.log(lower)+(math.log(upper)-math.log(lower))*i/511) for i in range(512)]
        candidates=[0.]
        for left,right in zip(grid,grid[1:]):
            if score(left)*score(right)<0:
                candidates.append(float(brentq(score,left,right,xtol=max(1e-14,upper*1e-13),rtol=1e-12)))
        def objective(value):
            ws=[1/(v+value) for v in variances];total=math.fsum(ws)
            centre=math.fsum(w*a for w,a in zip(ws,y))/total
            return math.fsum(math.log(v+value) for v in variances)+math.log(total)+math.fsum(w*(a-centre)**2 for w,a in zip(ws,y))
        tau=min(candidates,key=objective)
        convergence={'method':'independent_reml_score_root','converged':True,'boundary':tau==0,'score':score(tau)}
    convergence['boundary']=tau==0
    ws=[1/(v+tau) for v in variances];total=math.fsum(ws)
    centre=math.fsum(w*a for w,a in zip(ws,y))/total;variance=1/total;scale=1.
    if interval_method!='normal':
        if method=='fixed' or k<2:raise ValueError('HK requires random effects and at least two independent estimates')
        scale=math.fsum(w*(a-centre)**2 for w,a in zip(ws,y))/(k-1)
        if interval_method=='modified_hk':scale=max(1.,scale)
    interval_se=math.sqrt(scale*variance)
    critical=float(norm.ppf((1+float(ci_level))/2) if interval_method=='normal' else t.ppf((1+float(ci_level))/2,k-1))
    if not math.isfinite(critical) or critical<=0:raise ArithmeticError('Unrepresentable confidence quantile')
    result={'point_estimate':centre,'se_pooled':math.sqrt(variance),'interval_se':interval_se,
        'ci_lower':centre-critical*interval_se,'ci_upper':centre+critical*interval_se,'ci_level':float(ci_level),
        'interval_method':interval_method,'interval_type':'CI','tau2':tau,'Q':q,'df':k-1,
        'i2':max(0.,(q-k+1)/q*100) if q>0 and k>1 else 0.,'p_het':float(chi2.sf(q,k-1)) if k>1 else None,
        'weights':[w/total for w in ws],'n_studies':k,'hk_scale':scale,
        'tau_estimator':'none' if method=='fixed' else 'DL' if method=='random' else 'REML','convergence':convergence}
    if prediction_interval:
        if method=='fixed' or k<3:
            result['prediction_interval']={'status':'not_computable','reason':'random_effects_and_at_least_three_independent_estimates_required'}
        else:
            radius=float(t.ppf((1+float(ci_level))/2,k-2))*math.sqrt(tau+interval_se**2)
            if not math.isfinite(radius):raise ArithmeticError('Unrepresentable prediction interval')
            result['prediction_interval']={'status':'computed','lower':centre-radius,'upper':centre+radius,'level':float(ci_level),'method':'t_k_minus_2','df':k-2,'assumption':'approximate_normal_random_effect_distribution'}
    def finite(item):
        if isinstance(item,float) and not math.isfinite(item):raise ArithmeticError('Unrepresentable statistical output')
        if isinstance(item,dict):
            for value in item.values():finite(value)
        if isinstance(item,list):
            for value in item:finite(value)
    finite(result)
    return result


def verify_meta_result(contributions, method, result):
    """Compare actual results against a separate numeric implementation."""
    canonical=METHOD_ALIASES.get(str(method.get('name','')).casefold())
    if canonical is None:return {'status':'not_supported','version':VERSION,'reason':'method_has_no_independent_numeric_oracle'}
    expected_tau='none' if canonical=='fixed' else 'DL' if canonical=='random' else 'REML'
    if method.get('tau_estimator') is not None and str(method['tau_estimator']).casefold()!=expected_tau.casefold():raise ValueError('Declared tau estimator conflicts with method name')
    if not contributions or any('se_used' not in c for c in contributions):raise ValueError('Recognized inverse-variance methods require every SE')
    interval,level=method.get('interval_method'),method.get('ci_level');has_ci=result.get('ci_lower') is not None
    if has_ci and (interval is None or level is None):raise ValueError('Independent interval verification requires explicit interval method and confidence level')
    expected=independent_meta([c['value_used'] for c in contributions],[c['se_used'] for c in contributions],method=canonical,
        ci_level=.95 if level is None else level,interval_method=interval or 'normal',prediction_interval=bool(method.get('prediction_interval',False)))
    if result.get('interval_method',interval)!=interval:raise ValueError('Executed interval method differs from plan')
    if result.get('tau_estimator',expected_tau)!=expected_tau:raise ValueError('Executed tau estimator differs from plan')
    if method.get('log_transform'):
        raw=[float(c['value_used']) for c in contributions]
        if any(a<=0 for a in raw):raise ValueError('Log-scale analysis requires positive effects')
        expected=independent_meta([math.log(a) for a in raw],[float(c['se_used'])/a for c,a in zip(contributions,raw)],
            method=canonical,ci_level=.95 if level is None else level,interval_method=interval or 'normal',prediction_interval=bool(method.get('prediction_interval',False)))
        for key in ('point_estimate','ci_lower','ci_upper'):expected[key]=math.exp(expected[key])
        if expected.get('prediction_interval',{}).get('status')=='computed':
            for key in ('lower','upper'):expected['prediction_interval'][key]=math.exp(expected['prediction_interval'][key])
    checks={'point_estimate':expected['point_estimate']}
    if canonical!='fixed':checks['tau2']=expected['tau2']
    if has_ci:
        if result.get('interval_type')!='CI' or not math.isclose(float(result.get('ci_level',-1)),float(level),rel_tol=1e-12):raise ValueError('Verified intervals must be labeled CI at the planned level')
        checks.update(ci_lower=expected['ci_lower'],ci_upper=expected['ci_upper'])
    for key,number in checks.items():
        actual=result.get(key)
        if isinstance(actual,bool) or actual is None or not math.isfinite(float(actual)) or not math.isclose(float(actual),number,rel_tol=2e-5 if canonical=='reml' else 1e-8,abs_tol=1e-7):raise ValueError('Independent numeric cross-check failed: '+key)
    for key in ('Q','i2','se_pooled'):
        if key=='se_pooled' and method.get('log_transform'):continue
        if key in result and (isinstance(result[key],bool) or result[key] is None or not math.isclose(float(result[key]),expected[key],rel_tol=2e-5,abs_tol=1e-7)):raise ValueError('Independent numeric cross-check failed: '+key)
    for contribution,weight in zip(contributions,expected['weights']):
        if 'weight' in contribution and not math.isclose(float(contribution['weight']),weight,rel_tol=2e-5,abs_tol=1e-7):raise ValueError('input_id='+str(contribution.get('input_id','unknown'))+': Independent study-weight cross-check failed; contribution.weight must be normalized to sum1 across studies, not raw inverse variance')
    if result.get('prediction_interval') is not None and not method.get('prediction_interval'):raise ValueError('Prediction interval must be declared before execution')
    if method.get('prediction_interval'):
        actual,predicted=result.get('prediction_interval',{}),expected['prediction_interval']
        if actual.get('status')!=predicted['status'] or predicted['status']=='computed' and (actual.get('method')!=predicted['method'] or actual.get('df')!=predicted['df'] or actual.get('level')!=predicted['level']):raise ValueError('Independent prediction-interval declaration cross-check failed')
        if predicted['status']=='computed' and any(not math.isclose(float(actual.get(k,math.inf)),predicted[k],rel_tol=2e-5,abs_tol=1e-7) for k in ('lower','upper')):raise ValueError('Independent prediction-interval cross-check failed')
    return {'status':'verified','version':VERSION,'method':canonical,'checked':list(checks),'convergence':expected['convergence'],'scope':'numerical_consistency_not_scientific_eligibility_or_independence'}
