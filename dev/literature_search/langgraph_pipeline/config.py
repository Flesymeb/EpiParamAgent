"""LangGraph config shim.

The LangGraph pipeline now delegates runtime env loading to
``dev/tools/common/config.py`` so literature_search does not maintain a second
runtime config implementation.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from common.config import LLMConfig, load_llm_config as _load_llm_config  # type: ignore


def load_llm_config(params: Dict[str, Any]) -> LLMConfig:
    return _load_llm_config(params, module_hint="literature_search")
