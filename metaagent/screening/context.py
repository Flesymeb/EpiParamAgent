"""Source-only bibliographic context shared by standalone and workflow screening."""

from __future__ import annotations
from metaagent.screening.metadata_completion import FIELDS, get_field


def metadata_text(value):
    """Render known bibliographic containers without serializing arbitrary payloads."""
    if value is None:
        return ""
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    if isinstance(value, list):
        return "; ".join(filter(None, (metadata_text(v) for v in value)))
    if isinstance(value, dict):
        # Europe PMC / NCBI keyword and controlled-vocabulary containers.
        keys = (
            "keyword",
            "keywords",
            "meshHeading",
            "meshHeadingList",
            "descriptorName",
            "DescriptorName",
            "qualifierName",
            "QualifierName",
            "qualifierNameList",
            "name",
            "term",
            "text",
            "value",
            "pubType",
            "language",
        )
        return "; ".join(
            filter(None, (metadata_text(value[k]) for k in keys if k in value))
        )
    return ""


def bibliographic_context(paper):
    return {field: metadata_text(get_field(paper, field)) for field in FIELDS}


def normalize_bibliographic_aliases(paper):
    """Add established legacy aliases while preserving every existing nonblank value."""
    destinations = {
        "title": "Title",
        "abstract": "Abstract",
        "keywords": "Keywords",
        "year": "Publication Year",
        "journal": "Journal/Book",
        "authors": "Authors",
    }
    for canonical, destination in destinations.items():
        if not paper.get(destination):
            value = get_field(paper, canonical)
            if value is not None:
                paper[destination] = value
    if not paper.get("PMID") and paper.get("pmid"):
        paper["PMID"] = paper["pmid"]
    return paper
