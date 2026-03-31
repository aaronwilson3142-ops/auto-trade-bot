"""Pydantic schemas for price streaming endpoints.

Phase 36 — Real-time Price Streaming / WebSocket Feed
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from pydantic import BaseModel


class PriceTickSchema(BaseModel):
    """Single price tick for one portfolio position."""

    ticker: str
    current_price: float
    avg_entry_price: float
    unrealized_pnl_pct: float    # (current - entry) / entry
    market_value: float
    quantity: float


class PriceSnapshotResponse(BaseModel):
    """Response for GET /prices/snapshot — REST fallback for WebSocket feed."""

    ticks: list[PriceTickSchema]
    position_count: int
    as_of: dt.datetime
    note: Optional[str] = None
