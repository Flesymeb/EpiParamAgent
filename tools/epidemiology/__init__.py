"""Epidemiology-specific modules for literature search and screening."""

# Import keyword generator components
try:
    from .keyword_generator import KeywordGeneratorAgent, KeywordSet
except ImportError:
    KeywordGeneratorAgent = None
    KeywordSet = None

# Import other modules (if they exist)
try:
    from .literature_filter import LiteratureFilter
except ImportError:
    LiteratureFilter = None

try:
    from .data_extractor import DataExtractor
except ImportError:
    DataExtractor = None

try:
    from .coding_sheet import CodingSheetGenerator
except ImportError:
    CodingSheetGenerator = None

try:
    from .config import PsychologyConfig
except ImportError:
    PsychologyConfig = None

try:
    from .search_pipeline import LiteratureSearchPipeline
except ImportError:
    LiteratureSearchPipeline = None

__all__ = [
    "KeywordGeneratorAgent",
    "KeywordSet",
    "LiteratureFilter",
    "DataExtractor",
    "CodingSheetGenerator",
    "PsychologyConfig",
    "LiteratureSearchPipeline",
]

__version__ = "0.0.1"
