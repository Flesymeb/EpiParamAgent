from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class TextChunk:
    id: int
    text: str
    is_table: bool = False  # Mark if this chunk is a table


def chunk_text(
    text: str,
    *,
    max_chars: int = 1200,
    overlap_chars: int = 150,
) -> list[TextChunk]:
    """Split text into numbered chunks with table-aware logic.

    - Extracts tables as complete chunks (no splitting)
    - Splits remaining text on blank lines
    - Packs paragraphs into chunks up to `max_chars`
    - Adds overlap between non-table chunks

    Tables are identified by:
    - Markdown table syntax (lines with |)
    - Multiple consecutive rows with common structure
    """

    text = (text or "").strip()
    if not text:
        return []

    # Extract tables first
    tables, non_table_text = _extract_tables(text)

    # Process non-table text as before
    # Split by paragraphs but also detect section headers
    paragraphs = [p.strip() for p in non_table_text.split("\n\n") if p.strip()]

    def is_section_header(text: str) -> bool:
        """Check if text looks like a section header (short, starts with # or all caps)."""
        if not text:
            return False
        lines = text.split("\n")
        first_line = lines[0].strip()
        # Markdown headers
        if first_line.startswith("#"):
            return True
        # Short uppercase lines (< 80 chars, mostly uppercase)
        if len(first_line) < 80 and first_line.isupper():
            return True
        # Short lines ending with colon (likely subsection)
        if len(first_line) < 60 and first_line.endswith(":"):
            return True
        return False

    packed: list[str] = []
    buf = ""
    for p in paragraphs:
        # Force chunk break at section headers (unless buffer is empty)
        if buf and is_section_header(p):
            packed.append(buf)
            buf = p
            continue

        candidate = (buf + "\n\n" + p).strip() if buf else p
        if len(candidate) <= max_chars:
            buf = candidate
            continue
        if buf:
            packed.append(buf)
        # If a single paragraph is huge, try to split at sentence boundaries
        if len(p) > max_chars:
            # Try to split at sentence boundaries (. ! ?)
            sentences = []
            current = ""
            for sent in (
                p.replace(". ", ".\n")
                .replace("! ", "!\n")
                .replace("? ", "?\n")
                .split("\n")
            ):
                if len(current) + len(sent) <= max_chars:
                    current = (current + " " + sent).strip()
                else:
                    if current:
                        sentences.append(current)
                    current = sent
            if current:
                sentences.append(current)
            # If still too large, hard split
            final_chunks = []
            for sent in sentences:
                if len(sent) <= max_chars:
                    final_chunks.append(sent)
                else:
                    start = 0
                    while start < len(sent):
                        final_chunks.append(sent[start : start + max_chars])
                        start += (
                            max_chars - overlap_chars
                            if overlap_chars > 0
                            else max_chars
                        )
            packed.extend(final_chunks)
            buf = ""
        else:
            buf = p

    if buf:
        packed.append(buf)

    # Add overlap between packed chunks
    if overlap_chars > 0 and len(packed) > 1:
        overlapped: list[str] = []
        prev_tail = ""
        for i, c in enumerate(packed):
            if i == 0:
                overlapped.append(c)
                prev_tail = c[-overlap_chars:]
                continue
            merged = (prev_tail + "\n" + c).strip()
            overlapped.append(merged)
            prev_tail = c[-overlap_chars:]
        packed = overlapped

    # Combine tables and text chunks
    all_chunks: list[TextChunk] = []
    chunk_id = 0

    # Add tables first (prioritize tables in chunk order)
    for table_text in tables:
        all_chunks.append(TextChunk(id=chunk_id, text=table_text, is_table=True))
        chunk_id += 1

    # Add text chunks
    for text_chunk in packed:
        all_chunks.append(TextChunk(id=chunk_id, text=text_chunk, is_table=False))
        chunk_id += 1

    return all_chunks


def _extract_tables(text: str) -> tuple[list[str], str]:
    """Extract tables from text and return (tables, remaining_text).

    Identifies tables by:
    - Markdown table syntax (multiple lines with |)
    - Consecutive rows with similar structure
    """
    lines = text.split("\n")
    tables: list[str] = []
    table_buffer: list[str] = []
    non_table_lines: list[str] = []
    in_table = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Check if line looks like a table row
        is_table_row = _is_table_row(stripped)

        if is_table_row:
            if not in_table:
                # Start new table
                in_table = True
                # Include previous line if it looks like a caption
                if table_buffer and len(table_buffer[-1].strip()) < 100:
                    # Likely a table caption
                    pass
                else:
                    table_buffer = []
            table_buffer.append(line)
        else:
            if in_table:
                # Check if this is just a blank line within table
                if (
                    not stripped
                    and i + 1 < len(lines)
                    and _is_table_row(lines[i + 1].strip())
                ):
                    table_buffer.append(line)
                    continue
                # End of table
                if len(table_buffer) >= 3:  # At least 3 rows to be considered a table
                    tables.append("\n".join(table_buffer))
                else:
                    non_table_lines.extend(table_buffer)
                table_buffer = []
                in_table = False
            non_table_lines.append(line)

    # Handle remaining table buffer
    if table_buffer and len(table_buffer) >= 3:
        tables.append("\n".join(table_buffer))
    else:
        non_table_lines.extend(table_buffer)

    remaining_text = "\n".join(non_table_lines)
    return tables, remaining_text


def _is_table_row(line: str) -> bool:
    """Check if a line looks like a table row."""
    if not line:
        return False

    # Markdown table (has | separators)
    if "|" in line and line.count("|") >= 2:
        return True

    # Table separator line (------|-----)
    if re.match(r"^[\s\-|:]+$", line) and "-" in line:
        return True

    # Check for aligned columns (multiple spaces or tabs)
    # Common in MinerU table output: "Variable    Mean    SD    r"
    if re.search(r"\s{3,}|\t", line):
        # Has multiple spaces/tabs suggesting columns
        parts = re.split(r"\s{2,}|\t", line.strip())
        if len(parts) >= 3:  # At least 3 columns
            return True

    return False
