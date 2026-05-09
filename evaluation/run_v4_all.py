#!/usr/bin/env python3
"""Run v4 hardened prompt on all 5 test projects, compare vs code-threshold."""
import sys, asyncio, csv
from pathlib import Path

REPO = Path("/home/yanhaoyang/AILab/Meta-Analysis/MetaAgent-Epi")
sys.path.insert(0, str(REPO))

from metaagent.screening.engine import init_llm_model, screen_papers_batch_async
from metaagent.screening.models import ScreeningDecision, DimensionAssessment, classify_screening_decision

MODEL = "deepseek/deepseek-v4-pro"
PROVIDER = "openrouter"
BATCH_MODE = "single"

def safe_int(v):
    try: return int(float(v))
    except: return 0

PROJECTS = [
    ("covid19", "serial_interval", 12,
     "What is the serial interval and generation time of COVID-19?",
     "(SARS-CoV-2 OR COVID-19 OR 2019-nCoV OR coronavirus OR COVID19)",
     "(serial interval OR generation time OR incubation period OR latent period)"),
    ("covid19", "serial_interval", 13,
     "What is the serial interval of COVID-19?",
     "(SARS-CoV-2 OR COVID-19 OR 2019-nCoV OR SARS-CoV2 OR COVID19)",
     "(serial interval OR generation time OR incubation period)"),
    ("covid19", "reproduction_number", 7,
     "What is the reproduction number of COVID-19?",
     "(SARS-CoV-2 OR COVID-19 OR 2019-nCoV OR coronavirus)",
     "(reproduction number OR R0 OR Rt OR effective reproduction number OR basic reproduction number)"),
]

async def run_all():
    llm = init_llm_model(model_override=MODEL, provider_override=PROVIDER)

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

        print(f"\n=== p{pnum} ({topic}) GT={len(gt)} pool={len(papers)} ===")

        await screen_papers_batch_async(
            papers, research_question=rq, llm_model=llm,
            batch_size=20, batch_concurrency=3,
            batch_mode=BATCH_MODE,
            screening_stage="title_abstract", content_label="Abstract",
            content_key="Abstract",
            content_fallback="(NO ABSTRACT AVAILABLE — cannot assess evidence or parameter from title alone. Score conservatively.)",
            strategy="5d", prefer_llm_tier=True,
            screening_config={
                "research_question": rq, "disease_focus": dfocus, "disease_exclude": "none",
                "parameter_focus": pfocus,
                "parameter_exclude": "studies that do not report the target parameter",
                "parameter_scoring_note": "Score based on whether the paper explicitly reports the target parameter.",
            },
        )

        # Compute code vs LLM metrics
        code_tp = code_fp = code_inc = 0
        llm_tp = llm_fp = llm_inc = 0
        s_n = p_n = u_n = 0
        e1_p = e1_u = 0
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
                else: code_fp += 1
            if ll in ("strong_candidate","possible_candidate"):
                llm_inc += 1
                if is_gt: llm_tp += 1
                else: llm_fp += 1
            if ll == "strong_candidate": s_n += 1
            elif ll == "possible_candidate": p_n += 1
            else: u_n += 1
            # Count E=1 papers
            if safe_int(r.get("evidence_score",0)) == 1:
                if ll == "possible_candidate": e1_p += 1
                elif ll == "unlikely_candidate": e1_u += 1

        cr = code_tp/len(gt); cp = code_tp/code_inc if code_inc else 0
        cf1 = 2*cr*cp/(cr+cp) if (cr+cp) else 0
        lr = llm_tp/len(gt); lp = llm_tp/llm_inc if llm_inc else 0
        lf1 = 2*lr*lp/(lr+lp) if (lr+lp) else 0

        print(f"  Code:  R={cr:.3f} P={cp:.3f} F1={cf1:.3f} Inc={code_inc}")
        print(f"  LLMv4: R={lr:.3f} P={lp:.3f} F1={lf1:.3f} Inc={llm_inc} S={s_n} P={p_n} U={u_n}")
        print(f"  Δ:     R={lr-cr:+.3f} P={lp-cp:+.3f} F1={lf1-cf1:+.3f} Inc={llm_inc-code_inc:+d}")
        print(f"  E=1→P: {e1_p}  E=1→U: {e1_u}")

        # Save
        out_dir = REPO / "evaluation" / "screening" / disease / topic / f"p{pnum}" / "experiments" / "ab_tier_test"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_f = out_dir / f"project_{pnum}_screened_llm_tier.csv"
        with open(out_f, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(papers[0].keys()))
            w.writeheader()
            w.writerows(papers)

asyncio.run(run_all())
