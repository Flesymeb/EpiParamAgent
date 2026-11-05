"""Explicit deterministic synthesis estimators and their numeric provenance."""
from __future__ import annotations

import math
import statistics
from scipy.stats import beta, binom, norm, t
from tools.analysis.pooling import pool_means

METHOD_REGISTRY = {
    "ft_dl_miller_harmonic": "Freeman_Tukey_double_arcsine_DL_Miller_harmonic_N",
    "fixed": "inverse_variance_fixed", "random": "dersimonian_laird", "reml": "restricted_maximum_likelihood",
    "median": "descriptive_median_of_selected_estimates", "binomial": "common_risk_aggregate_binomial",
    "logit_fixed": "logit_inverse_variance_fixed", "logit_random": "logit_dersimonian_laird", "logit_reml": "logit_restricted_maximum_likelihood",
}


def binomial_interval(x, n, level, method):
    """Wilson score or equal-tailed Clopper-Pearson interval, including 0/n."""
    alpha = 1 - level
    if method == "clopper_pearson":
        return (0.0 if x == 0 else float(beta.ppf(alpha / 2, x, n - x + 1)),
                1.0 if x == n else float(beta.ppf(1 - alpha / 2, x + 1, n - x)))
    if method != "wilson":
        raise ValueError("An explicit binomial interval method is required")
    z = float(norm.ppf((1 + level) / 2))
    phat = x / n
    denominator = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denominator
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def _logistic(value):
    return 1 / (1 + math.exp(-value)) if value >= 0 else math.exp(value) / (1 + math.exp(value))


def _miller_inverse(theta, harmonic_n):
    """Inverse double-arcsine with Miller effective harmonic sample size."""
    boundary = math.asin(math.sqrt(1 / (harmonic_n + 1)))
    if theta <= boundary:return 0.0
    if theta >= math.pi - boundary:return 1.0
    sine = math.sin(theta)
    corrected = sine + (sine - 1 / sine) / harmonic_n
    return min(1.0,max(0.0,0.5*(1-math.copysign(1.0,math.cos(theta))*math.sqrt(max(0.0,1-corrected*corrected)))))


def _ft_dl_miller(selected, protocol, unit_factor):
    transformed=[]
    for row in selected:
        x,n=row['_events'],row['_denominator']
        theta=math.asin(math.sqrt(x/(n+1)))+math.asin(math.sqrt((x+1)/(n+1)))
        transformed.append({'point_estimate':theta,'se':math.sqrt(1/(n+0.5))})
    pooled=pool_means(transformed,method='random',log_transform=False)
    effective_n=len(selected)/sum(1/r['_denominator'] for r in selected)
    z=float(norm.ppf((1+protocol.ci_level)/2));centre=pooled['pooled_mean'];se=pooled['se_pooled']
    result={**pooled,'pooled_mean':_miller_inverse(centre,effective_n)/unit_factor,
        'ci_lower':_miller_inverse(centre-z*se,effective_n)/unit_factor,
        'ci_upper':_miller_inverse(centre+z*se,effective_n)/unit_factor,'se_pooled':None,
        'transformed_pooled_mean':centre,'transformed_se':se,'harmonic_sample_size':effective_n,
        'ci_type':'CI','ci_level':protocol.ci_level,'interval_method':'normal_on_FT_scale_then_Miller_inverse',
        'tau2_scale':'double_arcsine','back_transform':'Miller_with_harmonic_sample_size'}
    weights=[1/(t['se']**2+pooled['tau2']) for t in transformed];total=sum(weights);forest=[]
    for row,w in zip(selected,weights):
        low,high=binomial_interval(row['_events'],row['_denominator'],protocol.ci_level,protocol.binomial_rules.interval_method)
        forest.append({'estimate_id':row['estimate_id'],'point_estimate':row['_events']/row['_denominator']/unit_factor,'ci_lower':low/unit_factor,'ci_upper':high/unit_factor,'weight':w/total,'weight_kind':'inverse_variance_FT_random','source':'selected_estimates'})
    return result,forest


def calculate(selected, protocol, unit_factor):
    """Calculate on declared scale; return result and per-estimate forest data."""
    p = protocol
    z = float(norm.ppf((1 + p.ci_level) / 2))
    forest = []
    if p.method == "ft_dl_miller_harmonic":
        result,forest=_ft_dl_miller(selected,p,unit_factor)
    elif p.method == "median":
        values = sorted(r["point_estimate"] for r in selected)
        n = len(values)
        low = high = None
        if p.median_interval_method == "order_statistic":
            candidates = [k for k in range(1, (n + 1) // 2 + 1) if binom.cdf(k - 1, n, .5) <= (1 - p.ci_level) / 2]
            if candidates:
                k = max(candidates)
                low, high = values[k - 1], values[n - k]
        result = dict(pooled_mean=statistics.median(values), summary_statistic="median", ci_lower=low, ci_upper=high,
                      ci_type="CI" if low is not None else None, ci_level=p.ci_level if low is not None else None,
                      interval_method=p.median_interval_method,
                      interval_status="not_requested" if p.median_interval_method == "none" else "estimated" if low is not None else "insufficient_sample_for_finite_order_interval",
                      n_studies=n, weighting="equal_empirical_mass_not_inverse_variance")
        for r in selected:
            forest.append(dict(estimate_id=r["estimate_id"], point_estimate=r["point_estimate"], ci_lower=None, ci_upper=None,
                               weight=1 / n, weight_kind="empirical_mass", source="selected_estimates"))
    elif p.method == "binomial":
        x, n = sum(r["_events"] for r in selected), sum(r["_denominator"] for r in selected)
        low, high = binomial_interval(x, n, p.ci_level, p.binomial_rules.interval_method)
        result = dict(pooled_mean=x / n / unit_factor, ci_lower=low / unit_factor, ci_upper=high / unit_factor,
                      total_events=x, total_denominator=n, n_studies=len(selected), ci_type="CI", ci_level=p.ci_level,
                      interval_method=p.binomial_rules.interval_method, assumption="independent_binomial_observations_common_risk")
        for r in selected:
            low, high = binomial_interval(r["_events"], r["_denominator"], p.ci_level, p.binomial_rules.interval_method)
            forest.append(dict(estimate_id=r["estimate_id"], point_estimate=r["_events"] / r["_denominator"] / unit_factor,
                               ci_lower=low / unit_factor, ci_upper=high / unit_factor,
                               weight=r["_denominator"] / n, weight_kind="denominator_fraction", source="selected_estimates"))
    else:
        is_logit = p.method.startswith("logit_")
        backend_method = p.method.removeprefix("logit_")
        work = [{"point_estimate": r["_logit"] if is_logit else math.log(r["point_estimate"]) if p.log_transform else r["point_estimate"],
                 "se": r["_logit_se"] if is_logit else r["se"] / r["point_estimate"] if p.log_transform else r["se"]} for r in selected]
        result = pool_means(work, method=backend_method, log_transform=False)
        centre, pooled_se = result["pooled_mean"], result["se_pooled"]
        weights = [1/(r["se"]**2+result["tau2"]) for r in work]
        adjustment = 1.0
        if p.interval_method != "normal":
            if backend_method == "fixed" or len(work) < 2:
                raise ValueError("HK requires random effects and at least two independent estimates")
            adjustment = sum(w*(r["point_estimate"]-centre)**2 for w,r in zip(weights,work))/(len(work)-1)
            if p.interval_method == "modified_hk":adjustment = max(1.0,adjustment)
        interval_se = pooled_se * math.sqrt(adjustment)
        critical = z if p.interval_method == "normal" else float(t.ppf((1+p.ci_level)/2,len(work)-1))
        if not math.isfinite(critical):raise ArithmeticError("Unrepresentable interval quantile")
        low, high = centre-critical*interval_se, centre+critical*interval_se
        transform = (lambda a: _logistic(a)/unit_factor) if is_logit else math.exp if p.log_transform else lambda a:a
        result.update(pooled_mean=transform(centre), ci_lower=transform(low), ci_upper=transform(high),
                      ci_type="CI", ci_level=p.ci_level, interval_method=p.interval_method,
                      hk_scale=adjustment, interval_se=interval_se,
                      tau_estimator="none" if backend_method=="fixed" else "DL" if backend_method=="random" else "REML",
                      analysis_scale="logit" if is_logit else "log" if p.log_transform else "original")
        if is_logit:result.update(pooled_logit=centre,se_logit=pooled_se,se_pooled=None)
        elif p.log_transform:result.update(transformed_pooled_mean=centre,transformed_se=pooled_se,se_pooled=None)
        if p.prediction_interval:
            if backend_method=="fixed" or len(work)<3:
                result["prediction_interval"]={"status":"not_computable","reason":"random_effects_and_at_least_three_independent_estimates_required"}
            else:
                radius=float(t.ppf((1+p.ci_level)/2,len(work)-2))*math.sqrt(result["tau2"]+interval_se**2)
                if not math.isfinite(radius):raise ArithmeticError("Unrepresentable prediction interval")
                result["prediction_interval"]={"status":"computed","lower":transform(centre-radius),"upper":transform(centre+radius),
                    "level":p.ci_level,"method":"t_k_minus_2","df":len(work)-2,"assumption":"approximate_normal_random_effect_distribution_on_analysis_scale"}
        from .statistical_verification import verify_meta_result
        oracle_result={**result,"point_estimate":centre,"ci_lower":low,"ci_upper":high,"interval_type":"CI","se_pooled":pooled_se}
        if p.prediction_interval and result["prediction_interval"]["status"]=="computed":
            oracle_result["prediction_interval"]={**result["prediction_interval"],"lower":centre-radius,"upper":centre+radius}
        result["independent_verification"]=verify_meta_result(
            [{"value_used":r["point_estimate"],"se_used":r["se"]} for r in work],
            {"name":backend_method,"interval_method":p.interval_method,"ci_level":p.ci_level,"prediction_interval":p.prediction_interval},oracle_result)
        tau2 = result["tau2"]
        variances = [(r["_logit_se"] ** 2 if is_logit else (r["se"] / r["point_estimate"]) ** 2 if p.log_transform else r["se"] ** 2) for r in selected]
        weights = [1 / (variance + tau2) for variance in variances]
        total = sum(weights)
        for r, weight in zip(selected, weights):
            if is_logit:
                point = _logistic(r["_logit"]) / unit_factor
                low, high = (_logistic(r["_logit"] - z * r["_logit_se"]) / unit_factor,
                             _logistic(r["_logit"] + z * r["_logit_se"]) / unit_factor)
            elif p.log_transform:
                point = r["point_estimate"]
                low, high = math.exp(math.log(point) - z * r["se"] / point), math.exp(math.log(point) + z * r["se"] / point)
            else:
                point = r["point_estimate"]
                low, high = point - z * r["se"], point + z * r["se"]
            forest.append(dict(estimate_id=r["estimate_id"], point_estimate=point, ci_lower=low, ci_upper=high,
                               weight=weight / total, weight_kind="inverse_variance", source="selected_estimates"))
    result.update(unit=p.unit, parameter_type=p.parameter_type, estimate_measure="median" if p.method == "median" else "proportion" if p.method in {"binomial","ft_dl_miller_harmonic"} or p.method.startswith("logit_") else p.estimate_measure,
                  input_estimate_measure=p.estimate_measure, method=p.method, method_detail=METHOD_REGISTRY[p.method], log_transform=p.log_transform,
                  n_reports=len({str(r.get("record_id")) for r in selected if r.get("record_id")}), n_independent_units=len(selected), n_estimates=len(selected))
    return result, forest
