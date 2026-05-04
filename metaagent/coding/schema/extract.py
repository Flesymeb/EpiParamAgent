from __future__ import annotations

from pydantic import BaseModel
from typing import Optional


class ExtractRecord(BaseModel):
    pmid: str
    study: Optional[str] = None
    method: Optional[str] = None
    period: Optional[str] = None
    region: Optional[str] = None
    k_value: Optional[float] = None
    k_ci_low: Optional[float] = None
    k_ci_high: Optional[float] = None
    notes: Optional[str] = None
