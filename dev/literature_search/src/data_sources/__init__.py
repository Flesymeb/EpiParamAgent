"""Data source integrations for academic papers."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Shared data models
from .models import Paper

# Core clients for epidemiology research
from .pubmed_client import PubMedClient
from .eric_client import ERICClient

__all__ = [
    "Paper",
    "PubMedClient",
    "ERICClient",
]
