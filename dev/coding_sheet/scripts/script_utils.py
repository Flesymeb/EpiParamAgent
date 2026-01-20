"""
Compatibility wrapper for shared script utilities.

Note:
  The implementation now lives at:
  MetaAgent-Epi/dev/tools/paper_fetch/script_utils.py
"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_TARGET = (
    Path(__file__).resolve().parents[2]
    / "tools"
    / "paper_fetch"
    / "script_utils.py"
)

_spec = spec_from_file_location("paper_fetch_script_utils", _TARGET)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Unable to load script_utils from {_TARGET}")

_mod = module_from_spec(_spec)
_spec.loader.exec_module(_mod)

setup_logging = _mod.setup_logging
iter_pdfs = _mod.iter_pdfs
safe_slug = _mod.safe_slug
read_urls = _mod.read_urls

__all__ = ["setup_logging", "iter_pdfs", "safe_slug", "read_urls"]
