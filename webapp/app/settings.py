from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from metaagent.config import get_project_root, load_llm_config, load_runtime_env

router = APIRouter(prefix="/settings", tags=["settings"])

LLMModule = Literal["screening", "coding"]
VerifySslValue = Literal["default", "true", "false"]

MODULE_PREFIXES: dict[LLMModule, str] = {
    "screening": "SCREENING",
    "coding": "CODING",
}

PROFILE_FIELDS = {
    "provider": "LLM_PROVIDER",
    "model": "LLM_MODEL",
    "api_base": "LLM_API_BASE",
    "api_key": "LLM_API_KEY",
    "temperature": "LLM_TEMPERATURE",
    "max_tokens": "LLM_MAX_TOKENS",
    "timeout_s": "LLM_TIMEOUT_S",
    "verify_ssl": "LLM_VERIFY_SSL",
}

ENV_ASSIGNMENT_RE = re.compile(
    r"^(?P<prefix>\s*(?:export\s+)?)"
    r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)"
    r"\s*="
)


class LLMProfileRead(BaseModel):
    provider: str = ""
    model: str = ""
    api_base: str = ""
    temperature: str = ""
    max_tokens: str = ""
    timeout_s: str = ""
    verify_ssl: VerifySslValue = "default"
    has_api_key: bool = False
    has_module_api_key: bool = False
    api_key_hint: str = ""
    resolved_provider: str = ""
    resolved_model: str = ""
    resolved_api_base: str = ""


class LLMSettingsRead(BaseModel):
    profiles: dict[LLMModule, LLMProfileRead]


class LLMProfileUpdate(BaseModel):
    provider: str | None = None
    model: str | None = None
    api_base: str | None = None
    api_key: str | None = None
    clear_api_key: bool = False
    temperature: str | None = None
    max_tokens: str | None = None
    timeout_s: str | None = None
    verify_ssl: VerifySslValue | None = None


class LLMSettingsUpdate(BaseModel):
    profiles: dict[LLMModule, LLMProfileUpdate] = Field(default_factory=dict)


@router.get("/llm", response_model=LLMSettingsRead)
def read_llm_settings() -> LLMSettingsRead:
    load_runtime_env()
    return LLMSettingsRead(
        profiles={
            module: _read_profile(module)
            for module in MODULE_PREFIXES
        }
    )


@router.put("/llm", response_model=LLMSettingsRead)
def update_llm_settings(body: LLMSettingsUpdate) -> LLMSettingsRead:
    updates = _collect_updates(body)
    if updates:
        env_path = _env_local_path()
        lines = _read_env_lines(env_path)
        next_lines = _apply_env_updates(lines, updates)
        env_path.write_text("".join(next_lines), encoding="utf-8")
        _apply_process_env(updates)
    return read_llm_settings()


def _read_profile(module: LLMModule) -> LLMProfileRead:
    module_api_key = _env_value(module, "api_key")
    resolved = load_llm_config(module_hint=module)
    resolved_api_key = resolved.api_key or ""
    return LLMProfileRead(
        provider=_env_value(module, "provider"),
        model=_env_value(module, "model"),
        api_base=_env_value(module, "api_base"),
        temperature=_env_value(module, "temperature"),
        max_tokens=_env_value(module, "max_tokens"),
        timeout_s=_env_value(module, "timeout_s"),
        verify_ssl=_read_verify_ssl(module),
        has_api_key=bool(resolved_api_key),
        has_module_api_key=bool(module_api_key),
        api_key_hint=_api_key_hint(resolved_api_key),
        resolved_provider=resolved.provider or "",
        resolved_model=resolved.model or "",
        resolved_api_base=resolved.api_base or "",
    )


def _read_verify_ssl(module: LLMModule) -> VerifySslValue:
    value = _env_value(module, "verify_ssl").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return "true"
    if value in {"0", "false", "no", "off"}:
        return "false"
    return "default"


def _api_key_hint(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "configured"
    return f"••••{value[-4:]}"


def _collect_updates(body: LLMSettingsUpdate) -> dict[str, str | None]:
    updates: dict[str, str | None] = {}
    for module, profile in body.profiles.items():
        for field, suffix in PROFILE_FIELDS.items():
            env_name = _env_name(module, suffix)
            if field == "api_key":
                if profile.clear_api_key:
                    updates[env_name] = None
                elif profile.api_key is not None and profile.api_key.strip():
                    updates[env_name] = profile.api_key.strip()
                continue

            value = getattr(profile, field)
            if value is None:
                continue
            if field == "verify_ssl" and value == "default":
                updates[env_name] = None
                continue
            text = str(value).strip()
            updates[env_name] = text or None
    return updates


def _env_value(module: LLMModule, field: str) -> str:
    return (os.getenv(_env_name(module, PROFILE_FIELDS[field])) or "").strip()


def _env_name(module: LLMModule, suffix: str) -> str:
    return f"{MODULE_PREFIXES[module]}_{suffix}"


def _env_local_path() -> Path:
    return get_project_root() / ".env.local"


def _read_env_lines(env_path: Path) -> list[str]:
    if not env_path.exists():
        return []
    return env_path.read_text(encoding="utf-8").splitlines(keepends=True)


def _apply_env_updates(
    lines: list[str],
    updates: dict[str, str | None],
) -> list[str]:
    next_lines: list[str] = []
    handled: set[str] = set()

    for line in lines:
        match = ENV_ASSIGNMENT_RE.match(line)
        key = match.group("key") if match else None
        if key not in updates:
            next_lines.append(line)
            continue
        if key in handled:
            continue
        handled.add(key)
        value = updates[key]
        if value is not None:
            next_lines.append(_format_env_assignment(key, value))

    missing_assignments = [
        _format_env_assignment(key, value)
        for key, value in updates.items()
        if key not in handled and value is not None
    ]
    if missing_assignments:
        if next_lines and not next_lines[-1].endswith("\n"):
            next_lines[-1] += "\n"
        if next_lines and next_lines[-1].strip():
            next_lines.append("\n")
        next_lines.append("# Webapp LLM settings\n")
        next_lines.extend(missing_assignments)

    return next_lines


def _format_env_assignment(key: str, value: str) -> str:
    return f"{key}={json.dumps(value, ensure_ascii=False)}\n"


def _apply_process_env(updates: dict[str, str | None]) -> None:
    for key, value in updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
