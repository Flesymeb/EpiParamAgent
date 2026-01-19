from __future__ import annotations

import re
from typing import Iterable

from .chunking import TextChunk


_DEFAULT_KEYWORDS = [
    # Statistics / effect info
    "correlation",
    "pearson",
    "spearman",
    "r=",
    "r ",
    "p=",
    "n=",
    "sample",
    "participants",
    # Time points
    "t1",
    "t2",
    "follow",
    "interval",
    "months",
    "years",
    # Measures
    "measurement",
    "test",
    "scale",
    "assessment",
    # Tables / results
    "table",
    "figure",
    "results",
    "method",
]


def select_evidence_chunk_ids(
    chunks: list[TextChunk],
    *,
    keywords: Iterable[str] | None = None,
    top_k: int = 12,
    neighbor_hops: int = 1,
) -> list[int]:
    """Select chunk ids likely to contain relevant extraction evidence.

    Priority:
    1. All table chunks (always included)
    2. Keyword-scored text chunks
    3. Neighbor expansion for context
    """

    if not chunks:
        return []

    kw = [k.lower() for k in (keywords or _DEFAULT_KEYWORDS)]

    # Separate tables from text chunks
    table_ids: list[int] = []
    text_chunks: list[TextChunk] = []

    for c in chunks:
        if c.is_table:
            table_ids.append(c.id)
        else:
            text_chunks.append(c)

    # Score text chunks by keywords
    scored: list[tuple[int, int]] = []
    for c in text_chunks:
        txt = c.text.lower()
        score = 0
        for k in kw:
            if k in txt:
                # weight by occurrences (rough)
                score += max(1, len(re.findall(re.escape(k), txt)))
        scored.append((score, c.id))

    scored.sort(reverse=True)

    # Calculate how many text chunks we can include (reserve space for tables)
    available_slots = max(1, top_k - len(table_ids))
    picked_text = [cid for score, cid in scored if score > 0][:available_slots]

    if not picked_text and not table_ids:
        # fallback: first few chunks
        picked_text = [
            c.id for c in text_chunks[: min(available_slots, len(text_chunks))]
        ]

    # Combine tables (priority) + selected text chunks
    picked = table_ids + picked_text

    # Neighbor expansion (context window) - only for text chunks
    selected: set[int] = set(table_ids)  # Always include all tables
    for cid in picked_text:
        for hop in range(-neighbor_hops, neighbor_hops + 1):
            nid = cid + hop
            if 0 <= nid < len(chunks):
                selected.add(nid)

    return sorted(selected)


def _xml_escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_chunks_as_sources_xml(chunks: list[TextChunk], chunk_ids: list[int]) -> str:
    """Format selected chunks into a citation-friendly XML wrapper.

    Tables are marked with type="table" for LLM awareness.
    """

    parts: list[str] = []
    id_set = set(chunk_ids)
    for c in chunks:
        if c.id not in id_set:
            continue

        # Mark tables explicitly
        type_attr = ' type="table"' if c.is_table else ""
        parts.append(
            f'<source id="{c.id}"{type_attr}><content>{_xml_escape(c.text)}</content></source>'
        )
    return "\n\n".join(parts)
