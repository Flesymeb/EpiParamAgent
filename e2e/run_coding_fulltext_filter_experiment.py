#!/usr/bin/env python3
"""Evaluate a coding-prep full-text screening filter on E2E S/P candidates.

The experiment is intentionally non-destructive: it reads each E2E
``screening_selected_records.csv`` and writes new full-text screening decisions
plus policy summaries under one output directory.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import shutil
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metaagent.coding.pipeline.extraction import (  # noqa: E402
    _markdown_cache_path,
    _paper_pool_dirs,
)
from metaagent.screening.engine import (  # noqa: E402
    init_llm_model,
    load_ground_truth_pmids,
    screen_papers_batch_async,
)
from metaagent.screening.profile_registry import get_profile  # noqa: E402


TRACKING_CSV = ROOT / "e2e" / "runs" / "screen_to_coding" / "e2e_pooled_mean_tracking.csv"
DEFAULT_OUT_ROOT = ROOT / "e2e" / "runs" / "screen_to_coding" / "fulltext_filter_experiments"

TIER_LABELS = {
    "s": "S",
    "strong": "S",
    "strong_candidate": "S",
    "p": "P",
    "possible": "P",
    "possible_candidate": "P",
    "u": "U",
    "unlikely": "U",
    "unlikely_candidate": "U",
    "exclude": "U",
}

TOPIC_KEYWORDS = {
    "fatality": [
        "fatality",
        "mortality",
        "death",
        "deaths",
        "cfr",
        "ifr",
        "case fatality",
        "infection fatality",
        "survival",
    ],
    "reproduction_number": [
        "reproduction number",
        "reproductive number",
        "basic reproduction",
        "effective reproduction",
        "r0",
        "rt",
        "re",
        "transmission rate",
        "serial interval",
        "generation interval",
    ],
    "serial_interval": [
        "serial interval",
        "serial intervals",
        "generation interval",
        "generation time",
        "incubation period",
        "onset",
        "symptom onset",
        "infector",
        "infectee",
        "transmission pair",
    ],
}

COMMON_KEYWORDS = [
    "estimate",
    "estimated",
    "model",
    "table",
    "figure",
    "supplement",
    "results",
    "methods",
    "confidence interval",
    "credible interval",
]


def _normalize_tier(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if not text or text.lower() == "nan":
            continue
        key = text.lower()
        if key in TIER_LABELS:
            return TIER_LABELS[key]
        upper = text.upper()
        if upper in {"S", "P", "U"}:
            return upper
    return ""


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        return None
    return f


def _clean_record(row: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in row.items():
        if value is None:
            cleaned[key] = ""
            continue
        if isinstance(value, float) and math.isnan(value):
            cleaned[key] = ""
            continue
        cleaned[key] = value
    return cleaned


def _read_gt_pmids(disease: str, topic: str, profile: str) -> set[str]:
    project_num = profile.upper().removeprefix("MP").removeprefix("P").lower()
    gt_path = ROOT / "dataset" / disease / "screening" / topic / f"p{project_num}" / "ground_truth.csv"
    return load_ground_truth_pmids(gt_path)


def _cached_markdown_path(pmid: str) -> Path | None:
    _, md_dir = _paper_pool_dirs()
    paths = [
        _markdown_cache_path(md_dir, pmid),
        md_dir / f"PMID_{pmid}" / f"PMID_{pmid}.md",
    ]
    for path in paths:
        if path.exists() and path.stat().st_size > 0:
            return path
    return None


def _read_cached_markdown(pmid: str) -> tuple[str, str]:
    path = _cached_markdown_path(pmid)
    if path is None:
        return "", ""
    text = path.read_text(encoding="utf-8", errors="ignore")
    return text, str(path)


def _split_blocks(text: str) -> list[str]:
    chunks = re.split(r"\n(?=\s*#{1,6}\s)|\n\s*\n", text)
    return [chunk.strip() for chunk in chunks if chunk and chunk.strip()]


def _condense_fulltext(text: str, topic: str, max_chars: int) -> tuple[str, str]:
    """Keep full text when possible; otherwise build deterministic evidence excerpts."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text, "full"

    keywords = [k.lower() for k in TOPIC_KEYWORDS.get(topic, []) + COMMON_KEYWORDS]
    blocks = _split_blocks(text)
    selected: list[tuple[int, int, str]] = []
    for idx, block in enumerate(blocks):
        low = block.lower()
        score = sum(low.count(keyword) for keyword in keywords)
        if score:
            selected.append((score, idx, block))

    # Always include the opening context, then high-signal blocks in source order.
    pieces: list[str] = []
    budget = max_chars
    prefix = text[: min(3000, budget)]
    pieces.append(prefix)
    budget -= len(prefix)

    keep_indices = {
        idx
        for _, idx, _ in sorted(selected, key=lambda item: (-item[0], item[1]))[:80]
    }
    for idx, block in enumerate(blocks):
        if idx not in keep_indices:
            continue
        addition = "\n\n" + block
        if len(addition) > budget:
            addition = addition[: max(0, budget)]
        if addition.strip():
            pieces.append(addition)
            budget -= len(addition)
        if budget <= 0:
            break

    condensed = "\n".join(pieces).strip()
    header = (
        "[Full-text evidence excerpts generated from cached markdown because the "
        f"original full text was {len(text)} characters; excerpt budget={max_chars}.]\n\n"
    )
    return header + condensed, "excerpted"


def _load_tracking(path: Path, profiles: list[str]) -> pd.DataFrame:
    df = pd.read_csv(path)
    if profiles:
        wanted = {p.upper() for p in profiles}
        df = df[df["profile"].astype(str).str.upper().isin(wanted)].copy()
    if df.empty:
        raise ValueError("No profiles matched the requested tracking rows.")
    return df


def _selected_records(run_dir: Path) -> pd.DataFrame:
    path = run_dir / "screening_selected_records.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path)
    if "PMID" not in df.columns:
        raise ValueError(f"{path} lacks PMID column")
    df["PMID"] = df["PMID"].astype(str).str.strip()
    df = df[df["PMID"].ne("") & df["PMID"].str.lower().ne("nan")].copy()
    return df.drop_duplicates(subset=["PMID"], keep="first")


def _profile_config(profile: str) -> tuple[dict[str, Any], str]:
    profile_obj = get_profile(profile.upper())
    if profile_obj is None:
        raise ValueError(f"Unknown profile: {profile}")
    return profile_obj.to_screening_config(), profile_obj.research_question


def _decision_row(
    *,
    profile: str,
    disease: str,
    topic: str,
    gt_pmids: set[str],
    source: dict[str, Any],
    screened: dict[str, Any] | None,
    fulltext_status: str,
    fulltext_path: str = "",
    fulltext_chars: int = 0,
    prompt_chars: int = 0,
    content_mode: str = "",
) -> dict[str, Any]:
    pmid = str(source.get("PMID") or "").strip()
    original_tier = _normalize_tier(source.get("llm_tier"), source.get("llm_suggest"))
    llm = screened or {}
    ft_tier = _normalize_tier(llm.get("llm_tier"), llm.get("llm_suggest"))
    return {
        "profile": profile,
        "disease": disease,
        "topic": topic,
        "PMID": pmid,
        "is_ground_truth": pmid in gt_pmids,
        "Title": source.get("Title", ""),
        "original_llm_suggest": source.get("llm_suggest", ""),
        "original_llm_tier": original_tier,
        "fulltext_status": fulltext_status,
        "fulltext_path": fulltext_path,
        "fulltext_chars": fulltext_chars,
        "prompt_chars": prompt_chars,
        "content_mode": content_mode,
        "ft_llm_suggest": llm.get("llm_suggest", ""),
        "ft_llm_tier": ft_tier,
        "ft_confidence": llm.get("confidence", ""),
        "ft_overall_score": llm.get("overall_score", ""),
        "ft_disease_score": llm.get("disease_score", ""),
        "ft_population_score": llm.get("population_score", ""),
        "ft_location_score": llm.get("location_score", ""),
        "ft_evidence_score": llm.get("evidence_score", ""),
        "ft_parameter_score": llm.get("parameter_score", ""),
        "ft_overall_justification": llm.get("overall_justification", ""),
        "ft_parameter_justification": llm.get("parameter_justification", ""),
        "ft_evidence_justification": llm.get("evidence_justification", ""),
        "ft_prompt_tokens": llm.get("prompt_tokens", ""),
        "ft_completion_tokens": llm.get("completion_tokens", ""),
        "ft_total_tokens": llm.get("total_tokens", ""),
        "ft_wall_time_ms": llm.get("wall_time_ms", ""),
    }


async def _screen_stage(
    papers: list[dict[str, Any]],
    *,
    research_question: str,
    llm_model: Any,
    batch_size: int,
    batch_concurrency: int,
    batch_mode: str,
    screening_config: dict[str, Any],
    screening_stage: str,
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
        screening_stage=screening_stage,
        content_label="Full-text content (Markdown; excerpted only when needed)",
        content_key="fulltext_markdown",
        content_fallback="(Full-text content unavailable.)",
        strategy="5d",
        prefer_llm_tier=True,
    )


def _load_existing_profile_decisions(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    if "PMID" not in df.columns:
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for row in df.to_dict("records"):
        pmid = str(row.get("PMID") or "").strip()
        status = str(row.get("fulltext_status") or "")
        if not pmid:
            continue
        if status in {"screened", "error"}:
            rows[pmid] = row
        elif status == "missing_markdown":
            markdown, _ = _read_cached_markdown(pmid)
            if not markdown.strip():
                rows[pmid] = row
    return rows


def _drop_predicates() -> dict[str, Callable[[dict[str, Any]], bool]]:
    def is_u(row: dict[str, Any]) -> bool:
        return str(row.get("fulltext_status") or "") == "screened" and row.get("ft_llm_tier") == "U"

    def conf_at(row: dict[str, Any], threshold: float) -> bool:
        conf = _safe_float(row.get("ft_confidence"))
        return conf is not None and conf >= threshold

    return {
        "none": lambda row: False,
        "possible_u_any_conf": lambda row: is_u(row) and row.get("original_llm_tier") != "S",
        "possible_u_conf70": lambda row: is_u(row) and row.get("original_llm_tier") != "S" and conf_at(row, 0.70),
        "possible_u_conf80": lambda row: is_u(row) and row.get("original_llm_tier") != "S" and conf_at(row, 0.80),
        "possible_u_conf90": lambda row: is_u(row) and row.get("original_llm_tier") != "S" and conf_at(row, 0.90),
        "all_u_any_conf": lambda row: is_u(row),
        "all_u_conf80": lambda row: is_u(row) and conf_at(row, 0.80),
        "guarded_u": lambda row: is_u(row)
        and (
            (row.get("original_llm_tier") != "S" and conf_at(row, 0.70))
            or (row.get("original_llm_tier") == "S" and conf_at(row, 0.95))
        ),
    }


def _profile_policy_summary(
    decisions: list[dict[str, Any]],
    *,
    selected_pmids: set[str],
    gt_pmids: set[str],
    policy_name: str,
    predicate: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    decision_by_pmid = {str(row["PMID"]): row for row in decisions}
    drop_pmids = {
        pmid
        for pmid, row in decision_by_pmid.items()
        if pmid in selected_pmids and predicate(row)
    }
    final_pmids = selected_pmids - drop_pmids
    base_tp = selected_pmids & gt_pmids
    base_fp = selected_pmids - gt_pmids
    final_tp = final_pmids & gt_pmids
    final_fp = final_pmids - gt_pmids
    screened_rows = [row for row in decisions if row.get("fulltext_status") == "screened"]
    ft_u = [row for row in screened_rows if row.get("ft_llm_tier") == "U"]
    return {
        "policy": policy_name,
        "selected_base": len(selected_pmids),
        "gt_total": len(gt_pmids),
        "tp_base": len(base_tp),
        "fp_base": len(base_fp),
        "fn_base": len(gt_pmids - selected_pmids),
        "recall_base": len(base_tp) / len(gt_pmids) if gt_pmids else None,
        "nns_base": len(selected_pmids) / len(base_tp) if base_tp else None,
        "fulltext_screened": len(screened_rows),
        "fulltext_missing_or_unscreened": len(selected_pmids) - len(screened_rows),
        "ft_u_count": len(ft_u),
        "dropped_total": len(drop_pmids),
        "dropped_tp": len(drop_pmids & gt_pmids),
        "dropped_fp": len(drop_pmids - gt_pmids),
        "selected_final": len(final_pmids),
        "tp_final": len(final_tp),
        "fp_final": len(final_fp),
        "fn_final": len(gt_pmids - final_pmids),
        "recall_final": len(final_tp) / len(gt_pmids) if gt_pmids else None,
        "nns_final": len(final_pmids) / len(final_tp) if final_tp else None,
    }


def _pooled_policy_summary(profile_rows: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(profile_rows)
    rows = []
    for policy, group in df.groupby("policy", sort=False):
        selected_base = int(group["selected_base"].sum())
        gt_total = int(group["gt_total"].sum())
        tp_base = int(group["tp_base"].sum())
        selected_final = int(group["selected_final"].sum())
        tp_final = int(group["tp_final"].sum())
        rows.append(
            {
                "policy": policy,
                "profiles": int(len(group)),
                "selected_base": selected_base,
                "gt_total": gt_total,
                "tp_base": tp_base,
                "fp_base": int(group["fp_base"].sum()),
                "fn_base": int(group["fn_base"].sum()),
                "recall_base": tp_base / gt_total if gt_total else None,
                "nns_base": selected_base / tp_base if tp_base else None,
                "fulltext_screened": int(group["fulltext_screened"].sum()),
                "fulltext_missing_or_unscreened": int(group["fulltext_missing_or_unscreened"].sum()),
                "ft_u_count": int(group["ft_u_count"].sum()),
                "dropped_total": int(group["dropped_total"].sum()),
                "dropped_tp": int(group["dropped_tp"].sum()),
                "dropped_fp": int(group["dropped_fp"].sum()),
                "selected_final": selected_final,
                "tp_final": tp_final,
                "fp_final": int(group["fp_final"].sum()),
                "fn_final": int(group["fn_final"].sum()),
                "recall_final": tp_final / gt_total if gt_total else None,
                "nns_final": selected_final / tp_final if tp_final else None,
            }
        )
    return pd.DataFrame(rows)


def _write_report(out_dir: Path, pooled: pd.DataFrame, profile: pd.DataFrame, args: argparse.Namespace) -> None:
    def render_table(df: pd.DataFrame) -> str:
        try:
            return df.to_markdown(index=False)
        except ImportError:
            return df.to_string(index=False)

    report = out_dir / "fulltext_filter_report.md"
    lines = [
        "# Coding-step full-text screening filter",
        "",
        "## Setup",
        "",
        f"- tracking: `{args.tracking_csv}`",
        f"- provider: `{args.provider or 'config default'}`",
        f"- model: `{args.model or 'config default'}`",
        f"- strong stage: `{args.strong_stage}`",
        f"- possible stage: `{args.possible_stage}`",
        f"- max full-text chars per paper: `{args.max_fulltext_chars}`",
        f"- batch mode: `{args.batch_mode}`, batch size: `{args.batch_size}`, concurrency: `{args.batch_concurrency}`",
        "",
        "## Pooled policy summary",
        "",
        render_table(pooled),
        "",
        "## Largest per-profile NNS changes under guarded_u",
        "",
    ]
    guarded = profile[profile["policy"] == "guarded_u"].copy()
    if not guarded.empty:
        guarded["nns_delta"] = guarded["nns_final"] - guarded["nns_base"]
        show_cols = [
            "profile",
            "disease",
            "topic",
            "selected_base",
            "tp_base",
            "fp_base",
            "fulltext_screened",
            "dropped_fp",
            "dropped_tp",
            "recall_final",
            "nns_base",
            "nns_final",
            "nns_delta",
        ]
        lines.append(render_table(guarded.sort_values("dropped_fp", ascending=False)[show_cols].head(20)))
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracking-csv", type=Path, default=TRACKING_CSV)
    parser.add_argument("--profiles", nargs="*", default=[])
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--provider", default="openrouter")
    parser.add_argument("--model", default="z-ai/glm-5.1")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--batch-concurrency", type=int, default=2)
    parser.add_argument("--batch-mode", choices=["single", "multi"], default="multi")
    parser.add_argument("--limit-per-profile", type=int, default=None)
    parser.add_argument("--max-fulltext-chars", type=int, default=24000)
    parser.add_argument("--strong-stage", default="strong_hard_exclusion_full_text_llm")
    parser.add_argument("--possible-stage", default="possible_full_text_llm")
    args = parser.parse_args()

    out_dir = args.out_dir
    if out_dir is None:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = DEFAULT_OUT_ROOT / f"glm51_cache_md_{run_id}"
    out_dir = out_dir.resolve()
    if args.fresh and out_dir.exists():
        shutil.rmtree(out_dir)
    profile_dir = out_dir / "profile_decisions"
    profile_dir.mkdir(parents=True, exist_ok=True)

    tracking = _load_tracking(args.tracking_csv.resolve(), args.profiles)
    llm_model = init_llm_model(
        model_override=args.model or None,
        provider_override=args.provider or None,
        temperature_override=args.temperature,
    )

    all_decisions: list[dict[str, Any]] = []
    profile_policy_rows: list[dict[str, Any]] = []
    predicates = _drop_predicates()

    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "tracking_csv": str(args.tracking_csv.resolve()),
        "profiles": tracking["profile"].astype(str).tolist(),
        "provider": args.provider,
        "model": args.model,
        "temperature": args.temperature,
        "batch_size": args.batch_size,
        "batch_concurrency": args.batch_concurrency,
        "batch_mode": args.batch_mode,
        "max_fulltext_chars": args.max_fulltext_chars,
        "strong_stage": args.strong_stage,
        "possible_stage": args.possible_stage,
    }

    for _, track_row in tracking.iterrows():
        profile = str(track_row["profile"]).upper()
        disease = str(track_row["disease"])
        topic = str(track_row["topic"])
        run_dir = Path(str(track_row["run_dir"]))
        profile_decisions_path = profile_dir / f"{profile}_fulltext_decisions.csv"
        existing = _load_existing_profile_decisions(profile_decisions_path)

        selected = _selected_records(run_dir)
        if args.limit_per_profile is not None:
            selected = selected.head(args.limit_per_profile).copy()
        selected_pmids = set(selected["PMID"].astype(str))
        gt_pmids = _read_gt_pmids(disease, topic, profile)
        screening_config, research_question = _profile_config(profile)

        decisions_by_pmid: dict[str, dict[str, Any]] = {}
        to_screen: list[dict[str, Any]] = []
        source_by_pmid: dict[str, dict[str, Any]] = {}
        meta_by_pmid: dict[str, tuple[str, int, int, str]] = {}

        for source_raw in selected.to_dict("records"):
            source = _clean_record(source_raw)
            pmid = str(source.get("PMID") or "").strip()
            if pmid in existing:
                decisions_by_pmid[pmid] = existing[pmid]
                continue

            markdown, markdown_path = _read_cached_markdown(pmid)
            if not markdown.strip():
                decisions_by_pmid[pmid] = _decision_row(
                    profile=profile,
                    disease=disease,
                    topic=topic,
                    gt_pmids=gt_pmids,
                    source=source,
                    screened=None,
                    fulltext_status="missing_markdown",
                )
                continue

            prompt_text, mode = _condense_fulltext(markdown, topic, args.max_fulltext_chars)
            paper = deepcopy(source)
            paper["fulltext_markdown"] = prompt_text
            paper["screening_stage"] = "full_text"
            source_by_pmid[pmid] = source
            meta_by_pmid[pmid] = (markdown_path, len(markdown), len(prompt_text), mode)
            to_screen.append(paper)

        if to_screen:
            strong_rows = [
                row
                for row in to_screen
                if _normalize_tier(row.get("llm_tier"), row.get("llm_suggest")) == "S"
            ]
            possible_rows = [
                row
                for row in to_screen
                if _normalize_tier(row.get("llm_tier"), row.get("llm_suggest")) != "S"
            ]
            print(
                f"\n[{profile}] selected={len(selected_pmids)} cached_markdown_to_screen={len(to_screen)} "
                f"(strong={len(strong_rows)}, possible={len(possible_rows)})"
            )
            asyncio.run(
                _screen_stage(
                    strong_rows,
                    research_question=research_question,
                    llm_model=llm_model,
                    batch_size=args.batch_size,
                    batch_concurrency=args.batch_concurrency,
                    batch_mode=args.batch_mode,
                    screening_config=screening_config,
                    screening_stage=args.strong_stage,
                )
            )
            asyncio.run(
                _screen_stage(
                    possible_rows,
                    research_question=research_question,
                    llm_model=llm_model,
                    batch_size=args.batch_size,
                    batch_concurrency=args.batch_concurrency,
                    batch_mode=args.batch_mode,
                    screening_config=screening_config,
                    screening_stage=args.possible_stage,
                )
            )
            for screened in strong_rows + possible_rows:
                pmid = str(screened.get("PMID") or "").strip()
                path, full_chars, prompt_chars, mode = meta_by_pmid[pmid]
                decisions_by_pmid[pmid] = _decision_row(
                    profile=profile,
                    disease=disease,
                    topic=topic,
                    gt_pmids=gt_pmids,
                    source=source_by_pmid[pmid],
                    screened=screened,
                    fulltext_status="screened"
                    if screened.get("llm_suggest") != "error"
                    else "error",
                    fulltext_path=path,
                    fulltext_chars=full_chars,
                    prompt_chars=prompt_chars,
                    content_mode=mode,
                )

        profile_decisions = [decisions_by_pmid[pmid] for pmid in sorted(selected_pmids)]
        pd.DataFrame(profile_decisions).to_csv(profile_decisions_path, index=False)
        all_decisions.extend(profile_decisions)

        for policy, predicate in predicates.items():
            summary = _profile_policy_summary(
                profile_decisions,
                selected_pmids=selected_pmids,
                gt_pmids=gt_pmids,
                policy_name=policy,
                predicate=predicate,
            )
            summary.update({"profile": profile, "disease": disease, "topic": topic, "run_dir": str(run_dir)})
            profile_policy_rows.append(summary)

    decisions_df = pd.DataFrame(all_decisions)
    profile_summary = pd.DataFrame(profile_policy_rows)
    pooled_summary = _pooled_policy_summary(profile_policy_rows)

    decisions_df.to_csv(out_dir / "fulltext_filter_decisions.csv", index=False)
    profile_summary.to_csv(out_dir / "fulltext_filter_policy_profile.csv", index=False)
    pooled_summary.to_csv(out_dir / "fulltext_filter_policy_pooled.csv", index=False)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_report(out_dir, pooled_summary, profile_summary, args)

    print("\nPooled policy summary:")
    print(pooled_summary.to_string(index=False))
    print(f"\n[OK] wrote {out_dir}")


if __name__ == "__main__":
    main()
