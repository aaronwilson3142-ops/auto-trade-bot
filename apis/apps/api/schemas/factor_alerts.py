"""Pydantic schemas for the Factor Tilt Alert API (Phase 54)."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from pydantic import BaseModel


class FactorTiltEventSchema(BaseModel):
    """One factor tilt detection event."""

    event_time: dt.datetime
    previous_factor: Optional[str]
    new_factor: str
    previous_weight: Optional[float]
    new_weight: float
    tilt_type: str          # "factor_change" | "weight_shift"
    delta_weight: float


class FactorTiltHistoryResponse(BaseModel):
    """Response for GET /portfolio/factor-tilt-history."""

    events: list[FactorTiltEventSchema]
    total_events: int
    last_dominant_factor: Optional[str]
    as_of: Optional[dt.datetime]
