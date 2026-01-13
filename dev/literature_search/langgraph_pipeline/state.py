"""State definitions for the experimental LangGraph pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from pathlib import Path


def _default_providers():
    """Lazy load default providers from config."""
    try:
        from config import get_config

        return get_config().default_providers
    except:
        return ["pubmed"]  # Fallback


@dataclass
class SearchState:
    """Shared state passed between nodes."""

    research_question: str
    domain: str = "epidemiology"
    providers: List[str] = field(default_factory=_default_providers)
    terms: Dict[str, Any] = field(
        default_factory=dict
    )  # e.g., KeywordSet-like dict {"primary_keywords": [...]}
    queries: Dict[str, List[str]] = field(default_factory=dict)  # per-source query list
    scoping_results: List[Dict[str, Any]] = field(default_factory=list)
    scoping_context: Optional[str] = None
    raw_records: Dict[str, List[Dict[str, Any]]] = field(
        default_factory=dict
    )  # source -> records
    pubmed_records: List[Dict[str, Any]] = field(default_factory=list)
    eric_records: List[Dict[str, Any]] = field(default_factory=list)
    normalized_records: List[Dict[str, Any]] = field(default_factory=list)
    deduped_records: List[Dict[str, Any]] = field(default_factory=list)
    included: List[Dict[str, Any]] = field(default_factory=list)
    excluded: List[Dict[str, Any]] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    workdir: Optional[Path] = None  # optional cache/export root
    params: Dict[str, Any] = field(
        default_factory=dict
    )  # optional runtime params (retmax, min_year, etc.)

    # Timing fields
    timing_generate_terms: Optional[float] = None
    timing_build_queries: Optional[float] = None
    timing_retrieve_pubmed: Optional[float] = None
    timing_retrieve_eric: Optional[float] = None
    timing_normalize_and_dedupe: Optional[float] = None
    timing_autoscreen_and_export: Optional[float] = None
    timing_total: Optional[float] = None
