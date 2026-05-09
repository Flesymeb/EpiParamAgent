#!/usr/bin/env python3
"""Run multi-project A/B test (standalone, no buffering issues)."""
import sys, asyncio
sys.path.insert(0, '/home/yanhaoyang/AILab/Meta-Analysis/MetaAgent-Epi')
from evaluation.ab_test_multi import run_one

async def main():
    projects = [
        ('covid19', 'serial_interval', 12,
         'What is the serial interval and generation time of COVID-19?',
         '(SARS-CoV-2 OR COVID-19 OR 2019-nCoV OR coronavirus OR COVID19)',
         '(serial interval OR generation time OR incubation period OR latent period)'),
        ('covid19', 'fatality', 4,
         'What are the fatality and severity outcomes of SARS-CoV-2 infection?',
         '(COVID-19 OR COVID19 OR SARS-CoV-2 OR SARS-COV-2 OR 2019-nCoV OR coronavirus OR coronavirus disease 2019)',
         '(mortality OR fatality OR case fatality rate OR case fatality ratio OR CFR OR infection fatality rate OR infection fatality ratio OR IFR OR death rate OR died OR ICU admission OR intensive care OR intensive care unit OR invasive mechanical ventilation OR mechanical ventilation OR ventilation OR clinical characteristic*)'),
        ('covid19', 'reproduction_number', 17,
         'What is the basic reproduction number (R0) and effective reproduction number (Rt) of COVID-19?',
         '(SARS-CoV-2 OR COVID-19 OR 2019-nCoV OR coronavirus)',
         '(reproduction number OR R0 OR Rt OR effective reproduction number OR basic reproduction number OR transmission rate OR epidemic growth rate OR doubling time)'),
    ]

    all_metrics = []
    for disease, topic, pnum, rq, df, pf in projects:
        for prefer in [False, True]:
            m = await run_one(disease, topic, pnum, rq, df, pf, prefer)
            all_metrics.append(m)

    code = [m for m in all_metrics if not m['prefer_llm_tier']]
    llm = [m for m in all_metrics if m['prefer_llm_tier']]

    print("\n=== PER-PROJECT ===")
    for cm, lm in zip(code, llm):
        label = cm['label']
        print(f'[{label}] GT={cm["gt"]} pool={cm["total"]} | '
              f'Code: R={cm["recall"]:.3f} P={cm["precision"]:.3f} F1={cm["f1"]:.3f} S={cm["S"]}P={cm["P"]}U={cm["U"]} Err={cm["errors"]} | '
              f'LLM: R={lm["recall"]:.3f} P={lm["precision"]:.3f} F1={lm["f1"]:.3f} S={lm["S"]}P={lm["P"]}U={lm["U"]} Err={lm["errors"]}')

    ct, ci, cg, ce = sum(m['tp'] for m in code), sum(m['included'] for m in code), sum(m['gt'] for m in code), sum(m['errors'] for m in code)
    lt, li, le = sum(m['tp'] for m in llm), sum(m['included'] for m in llm), sum(m['errors'] for m in llm)
    cr, cp = ct/cg, ct/ci
    cf1 = 2*cr*cp/(cr+cp)
    lr, lp = lt/cg, lt/li
    lf1 = 2*lr*lp/(lr+lp)
    cs, csp, cu = sum(m['S'] for m in code), sum(m['P'] for m in code), sum(m['U'] for m in code)
    ls, lsp, lu = sum(m['S'] for m in llm), sum(m['P'] for m in llm), sum(m['U'] for m in llm)

    print(f'\n=== POOLED (3 projects + p14) ===')
    # Add p14 result
    p14_code = {'tp': 9, 'included': 58, 'gt': 9, 'errors': 0, 'S': 51, 'P': 7, 'U': 36, 'recall': 1.0, 'precision': 9/58, 'f1': 2*1.0*(9/58)/(1.0+9/58)}
    p14_llm  = {'tp': 9, 'included': 62, 'gt': 9, 'errors': 0, 'S': 55, 'P': 7, 'U': 32, 'recall': 1.0, 'precision': 9/62, 'f1': 2*1.0*(9/62)/(1.0+9/62)}
    ct += p14_code['tp']; ci += p14_code['included']; cg += p14_code['gt']; ce += p14_code['errors']
    cs += p14_code['S']; csp += p14_code['P']; cu += p14_code['U']
    lt += p14_llm['tp']; li += p14_llm['included']; le += p14_llm['errors']
    ls += p14_llm['S']; lsp += p14_llm['P']; lu += p14_llm['U']
    cr, cp = ct/cg, ct/ci; cf1 = 2*cr*cp/(cr+cp)
    lr, lp = lt/cg, lt/li; lf1 = 2*lr*lp/(lr+lp)

    print(f'GT={cg} pool={ci+cu+ce} | Code: R={cr:.3f} P={cp:.3f} F1={cf1:.3f} S={cs} P={csp} U={cu} Err={ce}')
    print(f'GT={cg} pool={li+lu+le} | LLM:  R={lr:.3f} P={lp:.3f} F1={lf1:.3f} S={ls} P={lsp} U={lu} Err={le}')
    print(f'Δ:    R={lr-cr:+.3f} P={lp-cp:+.3f} F1={lf1-cf1:+.3f} S={ls-cs:+d} P={lsp-csp:+d} U={lu-cu:+d}')

    if lf1 > cf1 + 0.005: print('\n✅ LLM-tier IMPROVES F1')
    elif lf1 < cf1 - 0.005: print('\n❌ LLM-tier DEGRADES F1')
    else: print('\n≈ NEGLIGIBLE difference')

asyncio.run(main())
