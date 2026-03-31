"""Pydantic schemas for Dynamic Universe Management API (Phase 48)."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from pydantic import BaseModel, Field


class UniverseTickerStatusSchema(BaseModel):
    """Per-ticker universe status."""
    ticker: str
    in_base_universe: bool
    in_active_universe: bool
    override_action: Optional[str] = None     # "ADD", "REMOVE", or None
    override_reason: Optional[str] = None
    quality_removed: bool = False
    signal_quality_score: Optional[float] = None


class UniverseListResponse(BaseModel):
    """Response for GET /universe/tickers."""
    computed_at: Optional[dt.datetime]
    base_count: int
    active_count: int
    added_count: int
    removed_count: int
    override_count: int
    min_quality_score: float
    active_tickers: list[str]
    added_tickers: list[str]
    removed_tickers: list[str]
    quality_removed_tickers: list[str]
    ticker_statuses: list[UniverseTickerStatusSchema]
    no_data: bool = False


class UniverseTickerDetailResponse(BaseModel):
    """Response for GET /universe/tickers/{ticker}."""
    ticker: str
    data_available: bool
    computed_at: Optional[dt.datetime] = None
    in_base_universe: Optional[bool] = None
    in_active_universe: Optional[bool] = None
    override_action: Optional[str] = None
    override_reason: Optional[str] = None
    quality_removed: Optional[bool] = None
    signal_quality_score: Optional[float] = None


class UniverseOverrideRequest(BaseModel):
    """Request body for POST /universe/tickers/{ticker}/override."""
    action: str = Field(..., description="'ADD' or 'REMOVE'")
    reason: Optional[str] = Field(None, description="Human-readable reason for override")
    operator_id: Optional[str] = Field(None, description="Operator identifier")
    expires_at: Optional[dt.datetime] = Field(
        None, description="Optional UTC expiry; null = no expiry"
    )


class UniverseOverrideResponse(BaseModel):
    """Response for POST /universe/tickers/{ticker}/override."""
    status: str
    ticker: str
    action: str
    override_id: str
    reason: Optional[str] = None
    expires_at: Optional[dt.datetime] = None


class UniverseOverrideDeleteResponse(BaseModel):
    """Response for DELETE /universe/tickers/{ticker}/override."""
    status: str
    ticker: str
    deactivated_count: int
