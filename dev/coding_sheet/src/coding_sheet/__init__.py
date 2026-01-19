"""Coding sheet module.

Three main parts:
- Config: YAML-driven schema definition
- Template: create an empty coding sheet with headers
- Extraction: fill/codify rows from paper text via LLM
"""

from .schema import CodingSheetRecord, ExtractionBatch, ExtractionResult, Paper
from .extraction import LLMConfig, load_llm_config, extract_batch, export_coding_sheet

# Configuration-driven API
from .config_schema import (
    load_config,
    list_templates,
    list_examples,
    get_model,
    ProjectConfig,
    FieldConfig,
)
from .prompt_factory import (
    build_system_prompt,
    build_user_prompt,
    build_prompts_from_model,
)
from .template import (
    EN_XLSX_COLUMNS,
    DEFAULT_TEMPLATE,
    TemplateSpec,
    export_empty_template,
    load_template_columns_from_xlsx,
    template_from_xlsx,
)

__all__ = [
    "CodingSheetRecord",
    "ExtractionResult",
    "ExtractionBatch",
    "Paper",
    "LLMConfig",
    "load_llm_config",
    "extract_batch",
    "export_coding_sheet",
    "EN_XLSX_COLUMNS",
    "TemplateSpec",
    "DEFAULT_TEMPLATE",
    "export_empty_template",
    "load_template_columns_from_xlsx",
    "template_from_xlsx",
]
