"""Pydantic schemas for the Factor Tilt Alert API (Phase 54)."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class FactorTiltEventSchema(BaseModel):
    """One factor tilt detection event."""

    event_time: dt.datetime
    previous_factor: str | None
    new_factor: str
    previous_weight: float | None
    new_weight: float
    tilt_type: str          # "factor_change" | "weight_shift"
    delta_weight: float


class FactorTiltHistoryResponse(BaseModel):
    """Response for GET /portfolio/factor-tilt-history."""

    events: list[FactorTiltEventSchema]
    total_events: int
    last_dominant_factor: str | None
    as_of: dt.datetime | None
