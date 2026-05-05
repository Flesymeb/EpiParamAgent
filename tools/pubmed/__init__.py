"""Data source integrations for academic papers (PubMed, Embase, ERIC, Google Scholar)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

from .data_source_models import Paper
from .client import PubMedClient
from .eric_client import ERICClient

__all__ = [
    "Paper",
    "PubMedClient",
    "ERICClient",
]
