"""Resolve screening configs and filesystem inputs for CLI workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def resolve_screening_config(
    config_name: str | None,
) -> tuple[dict[str, Any] | None, str]:
    """Resolve a screening config dict and its research question."""
    screening_config = None
    research_question = (
        "What are the reproduction numbers of different SARS-CoV-2 variants?"
    )
    if not config_name:
        return screening_config, research_question

    try:
        from screening_configs import (
            CONFIG_COVID_VARIANTS,
            CONFIG_EBOLA_TRANSMISSION,
            CONFIG_GENERIC_INFECTIOUS_DISEASE,
            CONFIG_INFLUENZA_TRANSMISSION,
            CONFIG_MEASLES_TRANSMISSION,
            CONFIG_OUTBREAK_INVESTIGATION,
            CONFIG_SERIAL_INTERVAL,
            CONFIG_SUPERSPREADING,
            CONFIG_TB_TRANSMISSION,
        )

        config_map = {
            "SERIAL_INTERVAL": CONFIG_SERIAL_INTERVAL,
            "CONFIG_SERIAL_INTERVAL": CONFIG_SERIAL_INTERVAL,
            "V1": CONFIG_SERIAL_INTERVAL,
            "COVID_VARIANTS": CONFIG_COVID_VARIANTS,
            "CONFIG_COVID_VARIANTS": CONFIG_COVID_VARIANTS,
            "V2": CONFIG_COVID_VARIANTS,
            "VARIANTS": CONFIG_COVID_VARIANTS,
            "SUPERSPREADING": CONFIG_SUPERSPREADING,
            "CONFIG_SUPERSPREADING": CONFIG_SUPERSPREADING,
            "V3": CONFIG_SUPERSPREADING,
            "INFLUENZA": CONFIG_INFLUENZA_TRANSMISSION,
            "CONFIG_INFLUENZA_TRANSMISSION": CONFIG_INFLUENZA_TRANSMISSION,
            "MEASLES": CONFIG_MEASLES_TRANSMISSION,
            "CONFIG_MEASLES_TRANSMISSION": CONFIG_MEASLES_TRANSMISSION,
            "EBOLA": CONFIG_EBOLA_TRANSMISSION,
            "CONFIG_EBOLA_TRANSMISSION": CONFIG_EBOLA_TRANSMISSION,
            "TB": CONFIG_TB_TRANSMISSION,
            "CONFIG_TB_TRANSMISSION": CONFIG_TB_TRANSMISSION,
            "GENERIC": CONFIG_GENERIC_INFECTIOUS_DISEASE,
            "CONFIG_GENERIC_INFECTIOUS_DISEASE": CONFIG_GENERIC_INFECTIOUS_DISEASE,
            "OUTBREAK": CONFIG_OUTBREAK_INVESTIGATION,
            "CONFIG_OUTBREAK_INVESTIGATION": CONFIG_OUTBREAK_INVESTIGATION,
        }
        try:
            import screening_configs_2 as configs_v2

            for name, cfg in vars(configs_v2).items():
                if name.upper().startswith("P") and isinstance(cfg, dict):
                    config_map[name.upper()] = cfg
        except Exception:
            pass

        screening_config = config_map.get(config_name.upper())
        if screening_config:
            research_question = screening_config.get(
                "research_question", research_question
            )
            print(f"✓ 使用配置: {config_name}")
            print(f"  Research question: {research_question}")
            print(f"  Disease focus: {screening_config['disease_focus'][:80]}...")
            print(
                f"  Transmission focus: {screening_config['transmission_focus'][:80]}...\n"
            )
        else:
            print(f"⚠ 未找到配置 '{config_name}'，使用默认配置（COVID-19 variants）\n")
    except ImportError as exc:
        print(f"⚠ 无法加载配置文件: {exc}")
        print("使用默认配置（COVID-19 variants）\n")

    return screening_config, research_question


def resolve_cli_paths(
    *,
    base_dir: Path,
    input_raw: str,
    output_raw: str,
    ground_truth_raw: str,
) -> tuple[Path, Path, Path]:
    """Resolve CLI path arguments relative to the literature_search root."""

    def resolve_arg(raw: str) -> Path:
        path = Path(str(raw).strip().strip("\"'").strip()).expanduser()
        return path if path.is_absolute() else (base_dir / path).resolve()

    return (
        resolve_arg(input_raw),
        resolve_arg(output_raw),
        resolve_arg(ground_truth_raw),
    )
