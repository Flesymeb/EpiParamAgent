from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


def repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists() and (parent / "metaagent").is_dir():
            return parent
    # webapp/app/prompt_templates.py -> repo root is parents[2]
    return current.parents[2]


# Platform-owned, reusable prompt templates (decoupled from disease configs).
def templates_dir() -> Path:
    return repo_root() / "configs" / "templates" / "prompts"


def load_prompt_sections(text: str) -> dict[str, str]:
    """Parse SYSTEM / USER / OUTPUT triple-quoted blocks (same convention as
    the coding prompt files)."""
    sections: dict[str, str] = {}
    for key in ("SYSTEM", "USER", "OUTPUT"):
        match = re.search(
            rf'{key}\s*=\s*"""(.*?)"""', text, flags=re.DOTALL | re.IGNORECASE
        )
        if match:
            sections[key.lower()] = match.group(1).strip()
    return sections


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def load_query_template() -> dict[str, str]:
    """SYSTEM/USER for the query stage, from the platform template dir."""
    return load_prompt_sections(_read(templates_dir() / "query.py"))


def _resolve_codebook_prompt(
    disease: str, parameter: str, stage_key: str = "stage_a"
) -> dict[str, str]:
    root = repo_root()
    codebook = root / "configs" / disease / "codebooks" / f"{parameter}.yaml"
    if not codebook.exists():
        return {}
    try:
        data = yaml.safe_load(codebook.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    stage = data.get(stage_key) if isinstance(data.get(stage_key), dict) else {}
    prompt_file = stage.get("prompt_file")
    if not prompt_file:
        return {}
    path = Path(str(prompt_file))
    if not path.is_absolute():
        path = (codebook.parent / path).resolve()
    return load_prompt_sections(_read(path))


def _resolve_screening_prompt(strategy: str) -> dict[str, str]:
    root = repo_root()
    base = root / "metaagent" / "prompts" / (strategy or "binary")
    system = ""
    user = ""
    # Prefer title/abstract stage; fall back to any available variant.
    for name in ("screening_system_title_abstract.md", "screening_system_title_only.md"):
        text = _read(base / name)
        if text:
            system = text.strip()
            break
    for name in ("screening_user_title_abstract.md", "screening_user_title_only.md"):
        text = _read(base / name)
        if text:
            user = text.strip()
            break
    sections: dict[str, str] = {}
    if system:
        sections["system"] = system
    if user:
        sections["user"] = user
    return sections


def resolve_stage_prompt(
    stage: str,
    disease: str | None = None,
    parameter: str | None = None,
    strategy: str | None = None,
) -> dict[str, Any]:
    """Best-effort resolution of the prompt template a stage uses, for display."""
    normalized = (stage or "").lower()

    if normalized == "query":
        sections = load_query_template()
        return _envelope("query", sections, "configs/templates/prompts/query.py")

    if normalized in ("screen", "screening"):
        sections = _resolve_screening_prompt(strategy or "binary")
        src = f"metaagent/prompts/{strategy or 'binary'}/"
        return _envelope("screen", sections, src)

    if normalized in ("code", "coding"):
        sections = _resolve_codebook_prompt(
            disease or "covid19", parameter or "serial_interval", "stage_a"
        )
        src = f"configs/{disease or 'covid19'}/coding_prompts/ (stage A, via codebook)"
        return _envelope("code", sections, src)

    if normalized in ("extract", "extraction"):
        sections = _resolve_codebook_prompt(
            disease or "covid19", parameter or "serial_interval", "stage_b"
        )
        src = f"configs/{disease or 'covid19'}/coding_prompts/ (stage B, via codebook)"
        return _envelope("extract", sections, src)

    # retrieve / analyze have no LLM prompt
    return {
        "stage": normalized,
        "has_prompt": False,
        "source": None,
        "system": None,
        "user": None,
        "output": None,
    }


def _envelope(stage: str, sections: dict[str, str], source: str) -> dict[str, Any]:
    has = bool(sections.get("system") or sections.get("user") or sections.get("output"))
    return {
        "stage": stage,
        "has_prompt": has,
        "source": source if has else None,
        "system": sections.get("system"),
        "user": sections.get("user"),
        "output": sections.get("output"),
    }
