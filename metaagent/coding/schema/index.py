from __future__ import annotations

from pydantic import BaseModel
from typing import Optional


class IndexRecord(BaseModel):
    pmid: str
    title: Optional[str] = None
    year: Optional[int] = None
    method_raw: Optional[str] = None
    period_raw: Optional[str] = None
    region_raw: Optional[str] = None
    evidence_hint: Optional[str] = None
