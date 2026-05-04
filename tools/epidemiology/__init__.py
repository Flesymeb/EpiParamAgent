"""Epidemiological utility tools."""

try:
    from tools.epidemiology.keyword_generator import KeywordGeneratorAgent
except ImportError:
    KeywordGeneratorAgent = None  # type: ignore[assignment]

__all__ = ["KeywordGeneratorAgent"]
