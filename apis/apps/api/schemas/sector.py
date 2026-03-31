"""Schemas for sector exposure endpoints (Phase 40)."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class SectorAllocationSchema(BaseModel):
    """Single sector's current portfolio allocation."""

    sector: str
    weight: float           # fraction of portfolio equity [0.0, 1.0]
    weight_pct: float       # weight * 100 for display convenience
    market_value_usd: float
    tickers: list[str]
    at_limit: bool          # weight >= max_sector_pct


class SectorExposureResponse(BaseModel):
    """Full sector breakdown of the current portfolio."""

    computed_at: dt.datetime | None
    equity_usd: float
    max_sector_pct: float
    sector_count: int
    sectors: list[SectorAllocationSchema]


class SectorDetailResponse(BaseModel):
    """Single-sector detail including per-ticker breakdown."""

    sector: str
    weight: float
    weight_pct: float
    market_value_usd: float
    tickers: list[str]
    max_sector_pct: float
    at_limit: bool
    computed_at: dt.datetime | None
