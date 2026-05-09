#!/usr/bin/env python3
"""Test hardened prompt on p4 and p6 with concurrency=3."""
import sys, asyncio, csv
from pathlib import Path

REPO = Path("/home/yanhaoyang/AILab/Meta-Analysis/MetaAgent-Epi")
sys.path.insert(0, str(REPO))
from evaluation.ab_test_multi import run_one

async def main():
    for pnum, rq, df, pf in [
        (4, "What are the fatality and severity outcomes of SARS-CoV-2 infection?",
         "(COVID-19 OR COVID19 OR SARS-CoV-2 OR SARS-COV-2 OR 2019-nCoV OR coronavirus OR coronavirus disease 2019)",
         "(mortality OR fatality OR case fatality rate OR CFR OR IFR OR death rate OR died OR ICU admission OR intensive care OR mechanical ventilation OR clinical characteristic*)"),
        (6, "What is the mortality or case fatality rate of COVID-19?",
         "(COVID-19 OR COVID 19 OR COVID-2019 OR 2019-nCoV OR 2019nCoV OR SARS-CoV-2 OR severe acute respiratory syndrome coronavirus 2 OR ((Wuhan AND coronavirus)))",
         "(mortality OR case fatality rate OR mortality rate OR death rate)"),
    ]:
        m = await run_one("covid19", "fatality", pnum, rq, df, pf, prefer_llm_tier=True)
        gt = set()
        gt_path = REPO / "dataset" / "covid19" / "screening" / "fatality" / f"p{pnum}" / "ground_truth.csv"
        with open(gt_path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                for col in ("PMID", "gt_pmid"):
                    v = (r.get(col, "") or "").strip()
                    if v.isdigit(): gt.add(v); break

        out_f = REPO / "evaluation" / "screening" / "covid19" / "fatality" / f"p{pnum}" / "experiments" / "ab_tier_test" / f"project_{pnum}_screened_llm_tier.csv"
        with open(out_f, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))

        e1 = [r for r in rows if r.get("evidence_score") in ("1", "1.0")]
        e1_p = [r for r in e1 if r["llm_suggest"] == "possible_candidate"]
        e1_u = [r for r in e1 if r["llm_suggest"] == "unlikely_candidate"]

        # Compare with previous v3
        # Compute code-threshold equivalent
        from metaagent.screening.models import ScreeningDecision, DimensionAssessment, classify_screening_decision
        def safe_int(v):
            try: return int(float(v))
            except: return 0
        code_inc = 0; llm_inc = 0
        code_tp = 0; llm_tp = 0
        for r in rows:
            if r.get("llm_suggest") == "error": continue
            dec = ScreeningDecision(
                disease_relevance=DimensionAssessment(score=safe_int(r.get("disease_score",0)), justification=""),
                population_relevance=DimensionAssessment(score=safe_int(r.get("population_score",0)), justification=""),
                location_relevance=DimensionAssessment(score=safe_int(r.get("location_score",0)), justification=""),
                original_evidence=DimensionAssessment(score=safe_int(r.get("evidence_score",0)), justification=""),
                parameter_relevance=DimensionAssessment(score=safe_int(r.get("parameter_score",0)), justification=""),
                overall_justification="", tier=r.get("llm_tier","").strip() or None,
            )
            cl = classify_screening_decision(dec, prefer_llm_tier=False)
            ll = classify_screening_decision(dec, prefer_llm_tier=True)
            is_gt = r["PMID"] in gt
            if cl in ("strong_candidate","possible_candidate"):
                code_inc += 1
                if is_gt: code_tp += 1
            if ll in ("strong_candidate","possible_candidate"):
                llm_inc += 1
                if is_gt: llm_tp += 1

        cr = code_tp/len(gt); cp = code_tp/code_inc if code_inc else 0; cf1 = 2*cr*cp/(cr+cp) if (cr+cp) else 0
        lr = llm_tp/len(gt); lp = llm_tp/llm_inc if llm_inc else 0; lf1 = 2*lr*lp/(lr+lp) if (lr+lp) else 0

        print(f"p{pnum}: GT={len(gt)} pool={m['total']}")
        print(f"  Code-thr: R={cr:.3f} P={cp:.3f} F1={cf1:.3f} Inc={code_inc}")
        print(f"  LLMv4:   R={lr:.3f} P={lp:.3f} F1={lf1:.3f} Inc={llm_inc} S={m['S']} P={m['P']} U={m['U']}")
        print(f"  E=1→P: {len(e1_p)} (was many in v3)  E=1→U: {len(e1_u)}")
        print()

asyncio.run(main())
