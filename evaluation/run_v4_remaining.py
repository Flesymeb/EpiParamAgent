#!/usr/bin/env python3
"""Run v4 on all remaining COVID projects."""
import sys, asyncio, csv
from pathlib import Path

REPO = Path("/home/yanhaoyang/AILab/Meta-Analysis/MetaAgent-Epi")
sys.path.insert(0, str(REPO))
from metaagent.screening.engine import init_llm_model, screen_papers_batch_async
from metaagent.screening.models import ScreeningDecision, DimensionAssessment, classify_screening_decision

MODEL = "deepseek/deepseek-v4-pro"; PROVIDER = "openrouter"; BATCH_MODE = "single"

def safe_int(v):
    try: return int(float(v))
    except: return 0

PROJECTS = [
    ("covid19", "fatality", 5, "What seroprevalence or antibody studies can support inference of SARS-CoV-2 infection fatality rates?",
     "(COVID-19 OR COVID19 OR SARS-CoV-2 OR SARS-COV-2 OR 2019-nCoV OR coronavirus)",
     "(seroprevalence OR sero-prevalence OR seropositivity OR serological survey OR serosurvey OR seroepidemiolog* OR anti-SARS-CoV-2 antibod* OR antibody prevalence OR antibody survey)"),
    ("covid19", "reproduction_number", 8, "What is the reproduction number of COVID-19?",
     "(COVID-19 OR COVID19 OR SARS-CoV-2 OR SARS-COV-2 OR 2019-nCoV OR coronavirus)",
     "(reproduction number OR R0 OR Rt OR effective reproduction number OR basic reproduction number OR transmission rate)"),
    ("covid19", "reproduction_number", 15, "What is the reproduction number of COVID-19?",
     "(SARS-CoV-2 OR COVID-19 OR 2019-nCoV OR coronavirus)",
     "(reproduction number OR R0 OR Rt OR effective reproduction number OR basic reproduction number OR transmission rate OR epidemic growth rate OR doubling time)"),
    ("covid19", "reproduction_number", 16, "What is the reproduction number of COVID-19?",
     "(SARS-CoV-2 OR COVID-19 OR 2019-nCoV OR coronavirus)",
     "(reproduction number OR R0 OR Rt OR effective reproduction number OR transmission rate OR doubling time)"),
    ("covid19", "reproduction_number", 17, "What is the reproduction number of COVID-19?",
     "(SARS-CoV-2 OR COVID-19 OR 2019-nCoV OR coronavirus)",
     "(reproduction number OR R0 OR Rt OR effective reproduction number OR basic reproduction number OR transmission rate OR epidemic growth rate OR doubling time)"),
    ("covid19", "serial_interval", 10, "What is the serial interval of COVID-19?",
     "(COVID-19 OR COVID19 OR 2019-nCoV OR SARS-CoV-2 OR coronavirus)",
     "(serial interval OR generation time OR incubation period OR latent period)"),
    ("covid19", "serial_interval", 11, "What is the serial interval of COVID-19?",
     "(SARS-CoV-2 OR COVID-19 OR 2019-nCoV OR coronavirus)",
     "(serial interval OR generation time OR incubation period)"),
    ("covid19", "serial_interval", 14, "What is the serial interval of COVID-19?",
     "(COVID-19 OR 2019-nCoV OR coronavirus)",
     "(serial interval)"),
]

async def run_all():
    llm = init_llm_model(model_override=MODEL, provider_override=PROVIDER)
    all_results = []

    for disease, topic, pnum, rq, dfocus, pfocus in PROJECTS:
        raw = REPO / "dataset" / disease / "screening" / topic / f"p{pnum}" / "raw.csv"
        gt_path = REPO / "dataset" / disease / "screening" / topic / f"p{pnum}" / "ground_truth.csv"
        with open(raw, encoding="utf-8-sig") as f: papers = list(csv.DictReader(f))
        gt = set()
        with open(gt_path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                for col in ("PMID", "gt_pmid"):
                    v = (r.get(col, "") or "").strip()
                    if v.isdigit(): gt.add(v); break

        await screen_papers_batch_async(
            papers, research_question=rq, llm_model=llm,
            batch_size=20, batch_concurrency=3,
            batch_mode=BATCH_MODE,
            screening_stage="title_abstract", content_label="Abstract",
            content_key="Abstract",
            content_fallback="(NO ABSTRACT AVAILABLE — cannot assess evidence or parameter from title alone. Score conservatively.)",
            strategy="5d", prefer_llm_tier=True,
            screening_config={"research_question": rq, "disease_focus": dfocus, "disease_exclude": "none",
                              "parameter_focus": pfocus, "parameter_exclude": "studies that do not report the target parameter",
                              "parameter_scoring_note": "Score based on whether the paper explicitly reports the target parameter."},
        )

        code_tp = code_inc = llm_tp = llm_inc = s_n = p_n = u_n = e1_p = 0
        for r in papers:
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
            if ll == "strong_candidate": s_n += 1
            elif ll == "possible_candidate": p_n += 1
            else: u_n += 1
            if safe_int(r.get("evidence_score",0)) == 1 and ll == "possible_candidate": e1_p += 1

        cr = code_tp/len(gt); cp = code_tp/code_inc if code_inc else 0
        cf1 = 2*cr*cp/(cr+cp) if (cr+cp) else 0
        lr = llm_tp/len(gt); lp = llm_tp/llm_inc if llm_inc else 0
        lf1 = 2*lr*lp/(lr+lp) if (lr+lp) else 0

        print(f"p{pnum} {topic[:7]:<7} GT={len(gt):>3} pool={len(papers):>5} | "
              f"Code: R={cr:.3f} P={cp:.3f} F1={cf1:.3f} | "
              f"LLMv4: R={lr:.3f} P={lp:.3f} F1={lf1:.3f} | "
              f"ΔF1={lf1-cf1:+.3f} S={s_n} P={p_n} U={u_n} E1→P={e1_p}")

        all_results.append((pnum, topic, len(gt), cr, cp, cf1, lr, lp, lf1))

        out_dir = REPO / "evaluation" / "screening" / disease / topic / f"p{pnum}" / "experiments" / "ab_tier_test"
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(out_dir / f"project_{pnum}_screened_llm_tier.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(papers[0].keys())); w.writeheader(); w.writerows(papers)

    # Pooled summary
    c_gt = sum(r[2] for r in all_results)
    c_tp = sum(r[2]*r[3] for r in all_results)
    c_inc = sum(r[2]*r[3]/r[4] if r[4] else 0 for r in all_results)
    l_tp = sum(r[2]*r[6] for r in all_results)
    l_inc = sum(r[2]*r[6]/r[7] if r[7] else 0 for r in all_results)
    # Recompute properly
    c_tp2 = sum(int(r[2]*r[3]) for r in all_results)
    l_tp2 = sum(int(r[2]*r[6]) for r in all_results)
    print(f"\n=== POOLED {len(PROJECTS)} projects, ~{c_gt} GT ===")
    print("(pooled metrics approximate)")
    # Simple average
    avg_cr = sum(r[3] for r in all_results)/len(all_results)
    avg_cp = sum(r[4] for r in all_results)/len(all_results)
    avg_lr = sum(r[6] for r in all_results)/len(all_results)
    avg_lp = sum(r[7] for r in all_results)/len(all_results)
    print(f"Avg Code: R={avg_cr:.3f} P={avg_cp:.3f}")
    print(f"Avg LLMv4: R={avg_lr:.3f} P={avg_lp:.3f}")

asyncio.run(run_all())
