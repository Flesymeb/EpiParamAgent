"""Extract and mark tables from MinerU Markdown output.

MinerU outputs tables as HTML <table> tags. This module identifies them,
extracts captions, and adds markers for LLM reference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class TableInfo:
    """Information about an extracted table."""

    id: str  # "t1", "t2", etc.
    caption: str  # Table caption if found
    content: str  # Original HTML content
    start_pos: int  # Start position in document
    end_pos: int  # End position in document


# Pattern to match HTML tables (including nested content)
_TABLE_PATTERN = re.compile(
    r"<table[^>]*>.*?</table>",
    re.DOTALL | re.IGNORECASE,
)

# Pattern to find table caption before the table
# Matches lines like "Table 1 Descriptive Statistics..." or "Table 1. Results..."
_CAPTION_PATTERN = re.compile(
    r"^(?:Table|TABLE)\s*(\d+)[\s.:]*(.*)$",
    re.MULTILINE,
)


def _find_caption_near_table(
    text: str, table_start: int, table_end: int, max_distance: int = 300
) -> str:
    """Find table caption in text near the table (before or after).

    MinerU typically places captions AFTER the table HTML, like:
        <table>...</table>
        Table 1. Caption text here.

    But some papers have captions before. This function checks both.

    Args:
        text: Full document text
        table_start: Start position of the table
        table_end: End position of the table
        max_distance: Maximum characters to search

    Returns:
        Caption string if found, empty string otherwise
    """
    # First check AFTER the table (more common in MinerU output)
    after_start = table_end
    after_end = min(len(text), table_end + max_distance)
    after_text = text[after_start:after_end]

    # Check first few lines after table
    after_lines = after_text.strip().split("\n")[:5]
    for line in after_lines:
        line = line.strip()
        match = _CAPTION_PATTERN.match(line)
        if match:
            table_num = match.group(1)
            caption_text = match.group(2).strip()
            if caption_text:
                return f"Table {table_num}: {caption_text}"
            return f"Table {table_num}"

    # Then check BEFORE the table (fallback)
    before_start = max(0, table_start - max_distance)
    before_text = text[before_start:table_start]

    before_lines = before_text.strip().split("\n")
    for line in reversed(before_lines[-5:]):
        line = line.strip()
        match = _CAPTION_PATTERN.match(line)
        if match:
            table_num = match.group(1)
            caption_text = match.group(2).strip()
            if caption_text:
                return f"Table {table_num}: {caption_text}"
            return f"Table {table_num}"

    return ""


def extract_tables(markdown: str) -> Tuple[str, List[TableInfo]]:
    """Extract tables from markdown and add markers.

    Identifies HTML <table> tags, extracts captions from preceding text,
    and adds comment markers for LLM reference.

    Args:
        markdown: MinerU markdown content

    Returns:
        Tuple of (marked_markdown, list of TableInfo)
    """
    tables: List[TableInfo] = []
    result_parts: List[str] = []
    last_end = 0
    table_count = 0

    for match in _TABLE_PATTERN.finditer(markdown):
        table_count += 1
        table_id = f"t{table_count}"
        start_pos = match.start()
        end_pos = match.end()
        table_html = match.group(0)

        # Find caption (checks after table first, then before)
        caption = _find_caption_near_table(markdown, start_pos, end_pos)

        # Store table info
        tables.append(
            TableInfo(
                id=table_id,
                caption=caption,
                content=table_html,
                start_pos=start_pos,
                end_pos=end_pos,
            )
        )

        # Add text before table
        result_parts.append(markdown[last_end:start_pos])

        # Add marked table
        caption_attr = f', caption="{caption}"' if caption else ""
        result_parts.append(f"<!-- table: {table_id}{caption_attr} -->\n")
        result_parts.append(table_html)
        result_parts.append(f"\n<!-- /table: {table_id} -->")

        last_end = end_pos

    # Add remaining text after last table
    result_parts.append(markdown[last_end:])

    marked_markdown = "".join(result_parts)
    return marked_markdown, tables


def get_tables_summary(tables: List[TableInfo]) -> str:
    """Generate a summary of tables for the prompt.

    Args:
        tables: List of TableInfo objects

    Returns:
        Formatted string summarizing all tables
    """
    if not tables:
        return "No tables found in document."

    lines = ["## Tables in Document", ""]
    for table in tables:
        caption_text = table.caption if table.caption else "(no caption)"
        lines.append(f"- **{table.id}**: {caption_text} (position: ~{table.start_pos})")

    return "\n".join(lines)
