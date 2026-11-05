"""Bounded lexical navigation over immutable supplied sources, with exact offsets.

Search is navigation, never a declaration that an unreturned field is absent.
"""
from __future__ import annotations

import hashlib
import heapq
import re


def search_evidence(sources, terms, *, limit=20, max_excerpt_chars=1600, expected_hashes=None):
    """Search literal terms and return bounded exact excerpts from every source.

    Offsets are Unicode character offsets into the identified source text. Hashes
    bind the UTF-8 bytes. A result cap bounds returned excerpts, not search scope.
    """
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("evidence search limit must be between 1 and 100")
    if type(max_excerpt_chars) is not int or not 80 <= max_excerpt_chars <= 8000:
        raise ValueError("max_excerpt_chars must be between 80 and 8000")
    if not isinstance(terms, list) or not terms or len(terms) > 64 or any(
        not isinstance(term, str) or not term.strip() or len(term) > 256 for term in terms
    ):
        raise ValueError("Provide 1-64 nonempty literal search terms of at most 256 characters")
    terms = list(dict.fromkeys(term.strip() for term in terms))
    if not isinstance(sources, list):
        raise ValueError("sources must be a list")
    expected_hashes = expected_hashes or {}
    results, searched, seen = [], [], set()
    total_hits = 0
    total_windows = 0
    for source in sources:
        source_id, text = source.get("source_id"), source.get("text")
        if not isinstance(source_id, str) or not source_id or source_id in seen or not isinstance(text, str):
            raise ValueError("Sources require unique source_id and original text")
        seen.add(source_id)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if source_id in expected_hashes and expected_hashes[source_id] != digest:
            raise ValueError("Evidence source changed: " + source_id)
        def matches(term):
            return ((match.start(), match.end(), term) for match in re.finditer(re.escape(term), text, re.IGNORECASE))
        hits = heapq.merge(*(matches(term) for term in terms))
        source_hits = 0
        # Hits are ordered; paragraph/local windows are monotone. Retain only
        # the previous window instead of materializing every occurrence.
        previous_window = None
        for start, end, term in hits:
            source_hits += 1
            # Prefer whole paragraphs/Markdown table blocks, falling back to a
            # bounded local slice when the paragraph itself exceeds the budget.
            left = text.rfind("\n\n", 0, start) + 2
            if left == 1:
                left = 0
            right = text.find("\n\n", end)
            if right == -1:
                right = len(text)
            if right - left > max_excerpt_chars:
                left = max(left, start - max_excerpt_chars // 3)
                right = min(right, left + max_excerpt_chars)
            window = (left, right)
            if window == previous_window:
                continue
            previous_window = window
            total_windows += 1
            if len(results) >= limit:
                continue
            results.append({"source_id": source_id, "source_sha256": digest,
                            "source_start": left, "source_end": right,
                            "text": text[left:right], "matched_term": term,
                            "match_start": start, "match_end": end})
        total_hits += source_hits
        searched.append({"source_id": source_id, "source_sha256": digest,
                         "characters_searched": len(text), "literal_hits": source_hits})
    unknown = set(expected_hashes) - seen
    if unknown:
        raise ValueError("Expected evidence sources are missing: " + ", ".join(sorted(unknown)))
    return {"schema_version": "1", "matches": results, "searched_sources": searched,
            "literal_hits": total_hits, "returned_excerpts": len(results),
            "results_limited": len(results) < total_windows,
            "search_scope": "all_supplied_source_text", "no_match_is_absence": False}
