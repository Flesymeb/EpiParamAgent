"""Advisory diagnostics on selected independent estimates; never delete inputs."""
from __future__ import annotations
import math
from scipy.stats import t


def se_derivation_candidates(row):
    """Report routes to review, without deriving a missing value or assuming a level."""
    kind=str(row.get('uncertainty_type') or '').upper()
    low,high=row.get('uncertainty_low'),row.get('uncertainty_high')
    common={'applied':False,'requires_explicit_protocol_approval':True,'source_values_unchanged':True}
    if kind=='CI':
        return [{**common,'method':'normal_ci_width','formula':'(upper-lower)/(2*normal_quantile((1+reported_level)/2))',
                 'required_inputs':['uncertainty_low','uncertainty_high','uncertainty_level'],
                 'assumptions':['symmetric normal approximation on the declared scale; source level must be known'] }]
    if kind=='SD':
        return [{**common,'method':'sd_div_sqrt_n','formula':'reported_sd/sqrt(reported_sample_size)',
                 'required_inputs':['reported_sd','numeric_sample_size'],
                 'assumptions':['SD and sample size describe the same mean and independent sampling units']}]
    if kind in {'IQR','RANGE'} and low is not None and high is not None:
        return [{**common,'method':'distributional_summary_approximation','source_type':kind,
                 'required_inputs':['numeric_sample_size','source_summary_definition','explicit_distributional_method'],
                 'formula_status':'must_be_declared_and_independently_verified_before_use',
                 'assumptions':['not an observed SE; distributional assumptions required','median-to-mean conversion is separately justified','exploratory sensitivity analysis required']}]
    return []


def diagnostic_values(selected, protocol):
    """Return declared analysis-scale values, not patient-level pseudo-observations."""
    if protocol.method.startswith('logit_'):
        return [r['_logit'] for r in selected],[r['_logit_se'] for r in selected]
    if protocol.log_transform:
        return [math.log(r['point_estimate']) for r in selected],[r['se']/r['point_estimate'] for r in selected]
    return [r['point_estimate'] for r in selected],[r['se'] for r in selected]


def influence_diagnostics(selected, protocol, unit_factor, result):
    """Conditional-tau influence plus refitted leave-one-out sensitivity suggestions."""
    if protocol.method not in {'fixed','random','reml','logit_fixed','logit_random','logit_reml'}:
        return {'status':'not_supported','reason':'influence_requires_inverse_variance_effects'}
    if len(selected)<3:return {'status':'not_computable','reason':'at_least_three_independent_estimates_required'}
    from .methods import calculate
    y,se=diagnostic_values(selected,protocol);tau=result['tau2']
    weights=[1/(s*s+tau) for s in se];total=sum(weights)
    mean=sum(w*a for w,a in zip(weights,y))/total;rows=[]
    for i,(source,a,s,w) in enumerate(zip(selected,y,se,weights)):
        h=w/total
        residual=(a-mean)/math.sqrt((s*s+tau)*(1-h)) if h<1 else None
        cook=residual**2*h/(1-h) if residual is not None else None
        item={'estimate_id':source['estimate_id'],'conditional_standardized_residual':residual,
              'conditional_cooks_distance':cook,'leverage':h,'suggest_sensitivity':bool(residual is not None and (abs(residual)>3 or cook>4/len(selected)))}
        try:
            reduced,_=calculate(selected[:i]+selected[i+1:],protocol,unit_factor)
            item.update(leave_one_out_estimate=reduced['pooled_mean'],delta=reduced['pooled_mean']-result['pooled_mean'],
                        ci_lower=reduced['ci_lower'],ci_upper=reduced['ci_upper'],status='computed')
        except (ValueError,ArithmeticError):item.update(status='not_computable',reason='leave_one_out_method_not_computable')
        rows.append(item)
    return {'status':'computed','scale':result.get('analysis_scale','original'),
            'assumption':'conditional fixed estimated tau2 for residual/Cook diagnostics; refitted LOO estimates',
            'thresholds':{'absolute_residual':3,'cooks_distance':4/len(selected)},'automatic_exclusion':False,'rows':rows}


def publication_bias_diagnostics(selected, protocol):
    """Classic Egger intercept diagnostic; no bias correction or causal conclusion."""
    base={'n_independent_estimates':len(selected),'automatic_correction':False,
          'interpretation':'small-study association is not proof of publication bias; heterogeneity and effect-SE dependence can confound it'}
    if protocol.method not in {'fixed','random','reml'} or protocol.estimate_measure.casefold()!='mean':
        return {**base,'status':'not_applicable','reason':'classic_egger_requires_appropriate_inverse_variance_mean_effects'}
    if len(selected)<10:return {**base,'status':'not_computable','reason':'fewer_than_ten_independent_estimates'}
    y,se=diagnostic_values(selected,protocol)
    x=[1/s for s in se];z=[a/s for a,s in zip(y,se)];n=len(x)
    xm=sum(x)/n;zm=sum(z)/n;sxx=sum((a-xm)**2 for a in x)
    funnel=[{'estimate_id':r['estimate_id'],'effect':a,'se':s} for r,a,s in zip(selected,y,se)]
    if sxx<=max(x)**2*1e-14:return {**base,'status':'not_computable','reason':'insufficient_precision_variation','funnel_data':funnel}
    slope=sum((a-xm)*(b-zm) for a,b in zip(x,z))/sxx;intercept=zm-slope*xm
    residual=sum((b-intercept-slope*a)**2 for a,b in zip(x,z))
    if residual<=1e-24:return {**base,'status':'not_computable','reason':'degenerate_egger_residual_variance','funnel_data':funnel}
    intercept_se=math.sqrt(residual/(n-2)*(1/n+xm*xm/sxx));statistic=intercept/intercept_se
    return {**base,'status':'computed','method':'Egger_unweighted_SND_on_precision_intercept_t',
            'intercept':intercept,'intercept_se':intercept_se,'t':statistic,'df':n-2,
            'p_two_sided':float(2*t.sf(abs(statistic),n-2)),
            'analysis_scale':'log' if protocol.log_transform else 'original','funnel_data':funnel}
