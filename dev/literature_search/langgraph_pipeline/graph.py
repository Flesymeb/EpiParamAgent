"""LangGraph wiring for the experimental pipeline.

Guarded import: if langgraph is missing, raise a clear error.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional
from typing_extensions import TypedDict, NotRequired
from pathlib import Path

from .state import SearchState
from . import nodes
from config import get_config

try:
    from langgraph.graph import StateGraph, END
except Exception as e:  # pragma: no cover - optional dependency
    StateGraph = None
    END = None
    _import_error = e
else:
    _import_error = None

logger = logging.getLogger(__name__)


class InputSchema(TypedDict):
    """Minimal input exposed to Studio/UI - epidemiology literature search."""

    research_question: str
    """Research question for the systematic review (e.g., 'What is the association between air pollution and cardiovascular disease?')"""

    domain: NotRequired[str]
    """Epidemiology subdomain: infectious_disease, chronic_disease, environmental_epi, etc. Default: epidemiology"""

    params: NotRequired[dict]
    """Optional runtime params (scoping, query limits, year filters, etc.)"""


def _require_langgraph():
    if StateGraph is None:
        raise ImportError(
            "langgraph is not installed. Install with `pip install langgraph`.\n"
            f"Original import error: {_import_error}"
        )


def build_graph() -> "StateGraph":
    """Build a simple linear graph: scoping -> terms -> queries -> retrieval -> normalize -> screen."""
    _require_langgraph()
    graph = StateGraph(SearchState, input=InputSchema)

    # Search and screening nodes
    graph.add_node("scoping_search", _wrap("scoping_search", nodes.scoping_search))
    graph.add_node("generate_terms", _wrap("generate_terms", nodes.generate_terms))
    graph.add_node("build_queries", _wrap("build_queries", nodes.build_queries))
    graph.add_node("retrieve_pubmed", _wrap("retrieve_pubmed", nodes.retrieve_pubmed))
    graph.add_node(
        "normalize_and_dedupe",
        _wrap("normalize_and_dedupe", nodes.normalize_and_dedupe),
    )
    graph.add_node(
        "autoscreen_and_export",
        _wrap("autoscreen_and_export", nodes.autoscreen_and_export),
    )

    # Build graph edges
    graph.set_entry_point("scoping_search")
    graph.add_edge("scoping_search", "generate_terms")
    graph.add_edge("generate_terms", "build_queries")

    # Primary retrieval: PubMed only (ERIC removed for epidemiology focus)
    graph.add_edge("build_queries", "retrieve_pubmed")
    graph.add_edge("retrieve_pubmed", "normalize_and_dedupe")
    graph.add_edge("normalize_and_dedupe", "autoscreen_and_export")
    graph.add_edge("autoscreen_and_export", END)

    return graph


def run_once(
    graph: "StateGraph",
    research_question: str,
    *,
    domain: str = "epidemiology",
    providers: Optional[list[str]] = None,
    workdir: str | None = None,
    params: Optional[dict] = None,
) -> SearchState:
    """Run the graph once with a fresh state."""
    config = get_config()

    initial = SearchState(
        research_question=research_question,
        domain=domain,
        providers=providers or config.default_providers,
        workdir=Path(workdir) if workdir else None,
        params=params or {},
    )
    result = graph.invoke(initial)
    return result


def _wrap(name: str, fn: Callable):
    """Wrap node functions so LangGraph can pass kwargs and capture timings."""

    def _inner(state: SearchState, **kwargs):
        start = time.perf_counter()
        if name == "generate_terms" and getattr(state, "_pipeline_start", None) is None:
            setattr(state, "_pipeline_start", start)
        result = fn(state, **kwargs)
        elapsed = time.perf_counter() - start

        if isinstance(result, dict):
            result[f"timing_{name}"] = elapsed
            if name == "autoscreen_and_export":
                pipeline_start = getattr(state, "_pipeline_start", None)
                if pipeline_start is not None:
                    result["timing_total"] = time.perf_counter() - pipeline_start
            return result

        setattr(result, f"timing_{name}", elapsed)
        if name == "autoscreen_and_export":
            pipeline_start = getattr(result, "_pipeline_start", None)
            if pipeline_start is not None:
                result.timing_total = time.perf_counter() - pipeline_start
        return result

    return _inner
