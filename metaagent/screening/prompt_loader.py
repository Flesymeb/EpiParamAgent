"""Prompt template loading for screening strategies."""

from __future__ import annotations

from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"

PROMPT_FILES = {
    "title_abstract": (
        PROMPT_DIR / "5d" / "screening_system_title_abstract.md",
        PROMPT_DIR / "5d" / "screening_user_title_abstract.md",
    ),
    "title_only": (
        PROMPT_DIR / "5d" / "screening_system_title_only.md",
        PROMPT_DIR / "5d" / "screening_user_title_only.md",
    ),
    "full_text": (
        PROMPT_DIR / "5d" / "screening_system_full_text.md",
        PROMPT_DIR / "5d" / "screening_user_full_text.md",
    ),
    "matched_full_text": (
        PROMPT_DIR / "5d" / "screening_system_matched_full_text.md",
        PROMPT_DIR / "5d" / "screening_user_title_abstract.md",
    ),
    "possible_full_text": (
        PROMPT_DIR / "5d" / "screening_system_possible_full_text.md",
        PROMPT_DIR / "5d" / "screening_user_possible_full_text.md",
    ),
    "strong_full_text": (
        PROMPT_DIR / "5d" / "screening_system_strong_full_text.md",
        PROMPT_DIR / "5d" / "screening_user_strong_full_text.md",
    ),
    "possible_full_text_llm": (
        PROMPT_DIR / "5d" / "screening_system_possible_full_text_llm.md",
        PROMPT_DIR / "5d" / "screening_user_possible_full_text_llm.md",
    ),
    "strong_full_text_llm": (
        PROMPT_DIR / "5d" / "screening_system_strong_full_text_llm.md",
        PROMPT_DIR / "5d" / "screening_user_strong_full_text_llm.md",
    ),
    "strong_source_scope_full_text_llm": (
        PROMPT_DIR / "5d" / "screening_system_strong_source_scope_full_text_llm.md",
        PROMPT_DIR / "5d" / "screening_user_strong_source_scope_full_text_llm.md",
    ),
    "strong_hard_exclusion_full_text_llm": (
        PROMPT_DIR / "5d" / "screening_system_strong_hard_exclusion_full_text_llm.md",
        PROMPT_DIR / "5d" / "screening_user_strong_hard_exclusion_full_text_llm.md",
    ),
    "rescue_full_text_llm": (
        PROMPT_DIR / "5d" / "screening_system_rescue_full_text_llm.md",
        PROMPT_DIR / "5d" / "screening_user_rescue_full_text_llm.md",
    ),
    "rescue_full_text_conservative_llm": (
        PROMPT_DIR / "5d" / "screening_system_rescue_full_text_conservative_llm.md",
        PROMPT_DIR / "5d" / "screening_user_rescue_full_text_conservative_llm.md",
    ),
    "coding_fulltext_recall_guard_llm": (
        PROMPT_DIR / "5d" / "screening_system_coding_fulltext_recall_guard_llm.md",
        PROMPT_DIR / "5d" / "screening_user_coding_fulltext_recall_guard_llm.md",
    ),
    "binary_title_abstract": (
        PROMPT_DIR / "binary" / "screening_system_title_abstract.md",
        PROMPT_DIR / "binary" / "screening_user_title_abstract.md",
    ),
    "binary_title_only": (
        PROMPT_DIR / "binary" / "screening_system_title_only.md",
        PROMPT_DIR / "binary" / "screening_user_title_only.md",
    ),
    "binary_noguidance_title_abstract": (
        PROMPT_DIR / "binary_noguidance" / "screening_system_title_abstract.md",
        PROMPT_DIR / "binary_noguidance" / "screening_user_title_abstract.md",
    ),
    "binary_noguidance_title_only": (
        PROMPT_DIR / "binary_noguidance" / "screening_system_title_only.md",
        PROMPT_DIR / "binary_noguidance" / "screening_user_title_only.md",
    ),
    "binary_baseline_title_abstract": (
        PROMPT_DIR / "binary_baseline" / "screening_system_title_abstract.md",
        PROMPT_DIR / "binary_baseline" / "screening_user_title_abstract.md",
    ),
    "binary_baseline_title_only": (
        PROMPT_DIR / "binary_baseline" / "screening_system_title_only.md",
        PROMPT_DIR / "binary_baseline" / "screening_user_title_only.md",
    ),
    "peco_title_abstract": (
        PROMPT_DIR / "peco" / "screening_system_title_abstract.md",
        PROMPT_DIR / "peco" / "screening_user_title_abstract.md",
    ),
    "peco_title_only": (
        PROMPT_DIR / "peco" / "screening_system_title_only.md",
        PROMPT_DIR / "peco" / "screening_user_title_only.md",
    ),
}


def load_prompt_templates(screening_stage: str) -> tuple[str, str]:
    """Load stage-aware screening system/user prompts from prompt files."""
    prompt_pair = PROMPT_FILES.get(screening_stage)
    if prompt_pair is None:
        raise KeyError(f"Unknown screening prompt stage: {screening_stage}")
    system_path, user_path = prompt_pair
    return system_path.read_text(encoding="utf-8"), user_path.read_text(encoding="utf-8")


def load_parameter_guides(config: dict | None, research_question: str = "") -> str:
    """Load terminology relevant to the task, never extra eligibility criteria."""
    import re
    config = config or {}
    patterns = {
        "fatality": r"fatality|mortality|\b(?:CFR|IFR)\b|病死|死亡风险|死亡比例",
        "reproduction_number": r"reproduction[_ -]?(?:number|ratio)|reproductive[_ -]?(?:number|ratio)|\bR[_ ]?0\b|(?-i:\bR[_ ]?[tTeE]\b)|再生数|再生系数",
        "intervals": r"serial[_ -]?interval|(?:incubation|latent)[_ -]?period|generation[_ -]?(?:time|interval)|潜伏期|序列间隔|代际间隔",
    }
    task = " ".join([*(str(config.get(k) or "") for k in ("topic", "parameter_focus")), research_question])
    selected = [name for name, pattern in patterns.items() if re.search(pattern, task, re.I)]
    if str(config.get("topic", "")).strip().lower() == "intervals" and "intervals" not in selected:
        selected.append("intervals")
    if not selected:
        return ""
    blocks = ["Parameter interpretation notes: terminology only, not additional inclusion rules. "
              "The complete research question and declared eligibility criteria take precedence. "
              "Do not narrow whole-review eligibility to a downstream pooled-analysis target."]
    for name in selected:
        text = (PROMPT_DIR / "screening" / "guides" / f"{name}.md").read_text(encoding="utf-8")
        blocks.append(f"[Parameter guide: {name}]\n{text.strip()}")
    return "\n\n".join(blocks)
