"""Full-text processor for extraction mode.

Processes MinerU Markdown output for full-context extraction:
- Marks tables with identifiers
- Handles context length limits via truncation
- Prepares document for LLM input
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from .table_extractor import TableInfo, extract_tables, get_tables_summary

logger = logging.getLogger(__name__)


@dataclass
class ProcessedDocument:
    """Result of processing a full-text document."""

    content: str  # Processed markdown with table markers
    tables: List[TableInfo] = field(default_factory=list)  # Extracted table info
    total_chars: int = 0  # Original document length
    was_truncated: bool = False  # Whether truncation occurred
    truncated_chars: int = 0  # Number of chars truncated

    @property
    def tables_summary(self) -> str:
        """Get formatted summary of tables."""
        return get_tables_summary(self.tables)


def process_fulltext(
    markdown: str,
    max_chars: int = 500000,
    truncation_marker: str = "\n\n[... document truncated, {chars} chars omitted ...]",
) -> ProcessedDocument:
    """Process full-text markdown for LLM extraction.

    1. Extract and mark tables with identifiers
    2. Check length against limit
    3. Truncate from end if necessary (preserves beginning which usually has abstract/methods)

    Args:
        markdown: Raw MinerU markdown content
        max_chars: Maximum characters to keep (default ~125k tokens)
        truncation_marker: Text to insert at truncation point, {chars} will be replaced

    Returns:
        ProcessedDocument with processed content and metadata
    """
    if not markdown:
        return ProcessedDocument(
            content="",
            tables=[],
            total_chars=0,
            was_truncated=False,
            truncated_chars=0,
        )

    original_len = len(markdown)

    # Step 1: Extract and mark tables
    marked_content, tables = extract_tables(markdown)
    marked_len = len(marked_content)

    # Step 2: Check if truncation needed
    if marked_len <= max_chars:
        # No truncation needed
        return ProcessedDocument(
            content=marked_content,
            tables=tables,
            total_chars=original_len,
            was_truncated=False,
            truncated_chars=0,
        )

    # Step 3: Truncate from end
    logger.warning(
        f"Document exceeds max_chars ({marked_len} > {max_chars}), truncating..."
    )

    # Calculate truncation point
    # Reserve space for truncation marker
    marker_len = len(truncation_marker.format(chars="999999"))
    truncate_at = max_chars - marker_len

    # Try to truncate at a paragraph boundary (double newline)
    truncated = marked_content[:truncate_at]

    # Find last paragraph break for cleaner cut
    last_para = truncated.rfind("\n\n")
    if last_para > truncate_at * 0.8:  # Only use if not too far back
        truncated = truncated[:last_para]

    # Add truncation marker
    chars_omitted = marked_len - len(truncated)
    truncated += truncation_marker.format(chars=chars_omitted)

    # Filter tables to only include those still in truncated content
    remaining_tables = [t for t in tables if t.end_pos <= len(truncated)]

    return ProcessedDocument(
        content=truncated,
        tables=remaining_tables,
        total_chars=original_len,
        was_truncated=True,
        truncated_chars=chars_omitted,
    )


def estimate_tokens(text: str, chars_per_token: float = 4.0) -> int:
    """Estimate token count from character count.

    Uses simple character-based estimation.
    - OpenAI: ~4 chars/token for English
    - Anthropic: similar ratio

    Args:
        text: Input text
        chars_per_token: Average characters per token

    Returns:
        Estimated token count
    """
    if not text:
        return 0
    return int(len(text) / chars_per_token)
