#!/usr/bin/env python3
"""Second-pass recall guard for the coding full-text filter experiment."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "e2e"))

import run_coding_fulltext_filter_experiment as base  # noqa: E402
from metaagent.screening.engine import init_llm_model, screen_papers_batch_async  # noqa: E402


def _load_source_rows(tracking: pd.DataFrame) -> dict[tuple[str, str], dict[str, Any]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for _, track_row in tracking.iterrows():
        profile = str(track_row["profile"]).upper()
        selected = base._selected_records(Path(str(track_row["run_dir"])))
        for row_raw in selected.to_dict("records"):
            row = base._clean_record(row_raw)
            pmid = str(row.get("PMID") or "").strip()
            if pmid:
                rows[(profile, pmid)] = row
    return rows


async def _screen_guard(
    papers: list[dict[str, Any]],
    *,
    research_question: str,
    llm_model: Any,
    batch_size: int,
    batch_concurrency: int,
    batch_mode: str,
    screening_config: dict[str, Any],
    stage: str,
) -> None:
    if not papers:
        return
    await screen_papers_batch_async(
        papers,
        research_question,
        llm_model,
        batch_size=batch_size,
        batch_concurrency=batch_concurrency,
        batch_mode=batch_mode,
        screening_config=screening_config,
        screening_stage=stage,
        content_label="Full-text content (Markdown; excerpted only when needed)",
        content_key="fulltext_markdown",
        content_fallback="(Full-text content unavailable.)",
        strategy="5d",
        prefer_llm_tier=True,
    )


def _guard_decision_row(
    first: dict[str, Any],
    source: dict[str, Any],
    screened: dict[str, Any],
    *,
    fulltext_path: str,
    fulltext_chars: int,
    prompt_chars: int,
    content_mode: str,
) -> dict[str, Any]:
    row = dict(first)
    row.update(
        {
            "guard_status": "screened" if screened.get("llm_suggest") != "error" else "error",
            "guard_fulltext_path": fulltext_path,
            "guard_fulltext_chars": fulltext_chars,
            "guard_prompt_chars": prompt_chars,
            "guard_content_mode": content_mode,
            "guard_llm_suggest": screened.get("llm_suggest", ""),
            "guard_llm_tier": base._normalize_tier(screened.get("llm_tier"), screened.get("llm_suggest")),
            "guard_confidence": screened.get("confidence", ""),
            "guard_overall_score": screened.get("overall_score", ""),
            "guard_disease_score": screened.get("disease_score", ""),
            "guard_population_score": screened.get("population_score", ""),
            "guard_location_score": screened.get("location_score", ""),
            "guard_evidence_score": screened.get("evidence_score", ""),
            "guard_parameter_score": screened.get("parameter_score", ""),
            "guard_overall_justification": screened.get("overall_justification", ""),
            "guard_parameter_justification": screened.get("parameter_justification", ""),
            "guard_evidence_justification": screened.get("evidence_justification", ""),
            "guard_prompt_tokens": screened.get("prompt_tokens", ""),
            "guard_completion_tokens": screened.get("completion_tokens", ""),
            "guard_total_tokens": screened.get("total_tokens", ""),
            "guard_wall_time_ms": screened.get("wall_time_ms", ""),
        }
    )
    row["Title"] = source.get("Title", row.get("Title", ""))
    return row


def _summarize_policy(
    all_decisions: pd.DataFrame,
    guard: pd.DataFrame,
    *,
    policy: str,
    drop_original_tiers: set[str],
    guard_drop_tiers: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    guard_key = {
        (str(row["profile"]).upper(), str(row["PMID"]).strip()): row
        for row in guard.to_dict("records")
    }
    rows = []
    for row in all_decisions.to_dict("records"):
        profile = str(row["profile"]).upper()
        pmid = str(row["PMID"]).strip()
        guard_row = guard_key.get((profile, pmid))
        guard_tier = str(guard_row.get("guard_llm_tier") or "") if guard_row else ""
        first_u = row.get("fulltext_status") == "screened" and row.get("ft_llm_tier") == "U"
        original_ok = row.get("original_llm_tier") in drop_original_tiers
        drop = bool(first_u and original_ok and guard_tier in guard_drop_tiers)
        rows.append({**row, "policy": policy, "guard_tier": guard_tier, "drop": drop})
    decisions = pd.DataFrame(rows)

    profile_rows = []
    for (profile, disease, topic), group in decisions.groupby(["profile", "disease", "topic"], sort=False):
        selected = set(group["PMID"].astype(str))
        gt = set(group.loc[group["is_ground_truth"].astype(bool), "PMID"].astype(str))
        drop_pmids = set(group.loc[group["drop"], "PMID"].astype(str))
        final = selected - drop_pmids
        tp_base = len(selected & gt)
        tp_final = len(final & gt)
        profile_rows.append(
            {
                "policy": policy,
                "profile": profile,
                "disease": disease,
                "topic": topic,
                "selected_base": len(selected),
                "gt_selected": len(gt),
                "tp_base": tp_base,
                "fp_base": len(selected - gt),
                "fulltext_screened": int((group["fulltext_status"] == "screened").sum()),
                "first_u_count": int((group["ft_llm_tier"] == "U").sum()),
                "guard_screened": int(group["guard_tier"].isin(["S", "P", "U"]).sum()),
                "dropped_total": len(drop_pmids),
                "dropped_tp": len(drop_pmids & gt),
                "dropped_fp": len(drop_pmids - gt),
                "selected_final": len(final),
                "tp_final": tp_final,
                "fp_final": len(final - gt),
                "recall_final_selected_gt": tp_final / tp_base if tp_base else None,
                "nns_base": len(selected) / tp_base if tp_base else None,
                "nns_final": len(final) / tp_final if tp_final else None,
            }
        )
    return decisions, pd.DataFrame(profile_rows)


def _pooled(profile_summary: pd.DataFrame, total_gt: int = 668) -> pd.DataFrame:
    rows = []
    for policy, group in profile_summary.groupby("policy", sort=False):
        selected_base = int(group["selected_base"].sum())
        tp_base = int(group["tp_base"].sum())
        selected_final = int(group["selected_final"].sum())
        tp_final = int(group["tp_final"].sum())
        rows.append(
            {
                "policy": policy,
                "profiles": int(len(group)),
                "selected_base": selected_base,
                "tp_base": tp_base,
                "fp_base": int(group["fp_base"].sum()),
                "recall_base": tp_base / total_gt,
                "nns_base": selected_base / tp_base,
                "guard_screened": int(group["guard_screened"].sum()),
                "dropped_total": int(group["dropped_total"].sum()),
                "dropped_tp": int(group["dropped_tp"].sum()),
                "dropped_fp": int(group["dropped_fp"].sum()),
                "selected_final": selected_final,
                "tp_final": tp_final,
                "fp_final": int(group["fp_final"].sum()),
                "recall_final": tp_final / total_gt,
                "nns_final": selected_final / tp_final if tp_final else None,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-dir", type=Path, required=True)
    parser.add_argument("--tracking-csv", type=Path, default=base.TRACKING_CSV)
    parser.add_argument("--profiles", nargs="*", default=[])
    parser.add_argument("--provider", default="openrouter")
    parser.add_argument("--model", default="z-ai/glm-5.1")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--batch-concurrency", type=int, default=4)
    parser.add_argument("--batch-mode", choices=["single", "multi"], default="single")
    parser.add_argument("--max-fulltext-chars", type=int, default=10000)
    parser.add_argument("--stage", default="coding_fulltext_recall_guard_llm")
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()

    experiment_dir = args.experiment_dir.resolve()
    first_path = experiment_dir / "fulltext_filter_decisions.csv"
    if not first_path.exists():
        raise FileNotFoundError(first_path)
    guard_path = experiment_dir / "fulltext_filter_recall_guard_decisions.csv"
    first = pd.read_csv(first_path)
    tracking = base._load_tracking(args.tracking_csv.resolve(), args.profiles)
    source_rows = _load_source_rows(tracking)

    if guard_path.exists() and not args.fresh:
        existing_guard = pd.read_csv(guard_path)
    else:
        existing_guard = pd.DataFrame()
    existing_keys = {
        (str(row["profile"]).upper(), str(row["PMID"]).strip())
        for row in existing_guard.to_dict("records")
    } if not existing_guard.empty else set()

    candidates = first[
        first["fulltext_status"].eq("screened") & first["ft_llm_tier"].eq("U")
    ].copy()
    if args.profiles:
        wanted = {p.upper() for p in args.profiles}
        candidates = candidates[candidates["profile"].astype(str).str.upper().isin(wanted)]

    llm_model = init_llm_model(
        model_override=args.model or None,
        provider_override=args.provider or None,
        temperature_override=args.temperature,
    )

    guard_rows: list[dict[str, Any]] = []
    if not existing_guard.empty and not args.fresh:
        guard_rows.extend(existing_guard.to_dict("records"))

    for profile, group in candidates.groupby(candidates["profile"].astype(str).str.upper(), sort=False):
        profile_obj = tracking[tracking["profile"].astype(str).str.upper().eq(profile)].iloc[0]
        disease = str(profile_obj["disease"])
        topic = str(profile_obj["topic"])
        screening_config, research_question = base._profile_config(profile)

        papers: list[dict[str, Any]] = []
        first_by_pmid: dict[str, dict[str, Any]] = {}
        meta_by_pmid: dict[str, tuple[str, int, int, str]] = {}
        for first_row in group.to_dict("records"):
            pmid = str(first_row.get("PMID") or "").strip()
            if (profile, pmid) in existing_keys:
                continue
            source = source_rows.get((profile, pmid))
            if not source:
                continue
            markdown, markdown_path = base._read_cached_markdown(pmid)
            if not markdown.strip():
                continue
            prompt_text, mode = base._condense_fulltext(markdown, topic, args.max_fulltext_chars)
            paper = deepcopy(source)
            paper["fulltext_markdown"] = prompt_text
            paper["screening_stage"] = "full_text"
            papers.append(paper)
            first_by_pmid[pmid] = first_row
            meta_by_pmid[pmid] = (markdown_path, len(markdown), len(prompt_text), mode)

        if not papers:
            continue
        print(f"\n[{profile}] recall guard candidates={len(papers)}")
        asyncio.run(
            _screen_guard(
                papers,
                research_question=research_question,
                llm_model=llm_model,
                batch_size=args.batch_size,
                batch_concurrency=args.batch_concurrency,
                batch_mode=args.batch_mode,
                screening_config=screening_config,
                stage=args.stage,
            )
        )
        for screened in papers:
            pmid = str(screened.get("PMID") or "").strip()
            source = source_rows[(profile, pmid)]
            path, full_chars, prompt_chars, mode = meta_by_pmid[pmid]
            guard_rows.append(
                _guard_decision_row(
                    first_by_pmid[pmid],
                    source,
                    screened,
                    fulltext_path=path,
                    fulltext_chars=full_chars,
                    prompt_chars=prompt_chars,
                    content_mode=mode,
                )
            )
        pd.DataFrame(guard_rows).to_csv(guard_path, index=False)

    guard = pd.DataFrame(guard_rows)
    guard.to_csv(guard_path, index=False)

    policies = [
        ("after_guard_possible_only", {"P"}, {"U"}),
        ("after_guard_all_u", {"S", "P"}, {"U"}),
    ]
    all_profile = []
    for policy, original_tiers, guard_drop_tiers in policies:
        decisions, profile_summary = _summarize_policy(
            first,
            guard,
            policy=policy,
            drop_original_tiers=original_tiers,
            guard_drop_tiers=guard_drop_tiers,
        )
        decisions.to_csv(experiment_dir / f"fulltext_filter_recall_guard_{policy}_decisions.csv", index=False)
        all_profile.append(profile_summary)

    profile_summary = pd.concat(all_profile, ignore_index=True)
    pooled = _pooled(profile_summary)
    profile_summary.to_csv(experiment_dir / "fulltext_filter_recall_guard_policy_profile.csv", index=False)
    pooled.to_csv(experiment_dir / "fulltext_filter_recall_guard_policy_pooled.csv", index=False)
    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "experiment_dir": str(experiment_dir),
        "stage": args.stage,
        "provider": args.provider,
        "model": args.model,
        "max_fulltext_chars": args.max_fulltext_chars,
    }
    (experiment_dir / "fulltext_filter_recall_guard_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print("\nRecall-guard pooled summary:")
    print(pooled.to_string(index=False))
    print(f"\n[OK] wrote {experiment_dir}")


if __name__ == "__main__":
    main()
