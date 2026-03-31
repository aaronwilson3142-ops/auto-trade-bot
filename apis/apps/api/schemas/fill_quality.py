"""Pydantic schemas for the Fill Quality API (Phase 52)."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from pydantic import BaseModel


class FillQualityRecordSchema(BaseModel):
    """One captured fill: expected vs actual price comparison."""

    ticker: str
    direction: str          # "BUY" | "SELL"
    action_type: str        # "open" | "close" | "trim"
    expected_price: float
    fill_price: float
    quantity: float
    slippage_usd: float
    slippage_pct: float
    filled_at: dt.datetime
    # Alpha-decay attribution (Phase 55)
    alpha_captured_pct: Optional[float] = None
    slippage_as_pct_of_move: Optional[float] = None


class FillQualitySummarySchema(BaseModel):
    """Aggregate fill quality statistics."""

    total_fills: int
    buy_fills: int
    sell_fills: int

    avg_slippage_usd: float
    median_slippage_usd: float
    worst_slippage_usd: float
    best_slippage_usd: float

    avg_slippage_pct: float
    worst_slippage_pct: float

    avg_buy_slippage_usd: Optional[float]
    avg_sell_slippage_usd: Optional[float]

    computed_at: Optional[dt.datetime]
    record_count: int
    tickers_covered: list[str]


class FillQualityResponse(BaseModel):
    """Response for GET /portfolio/fill-quality."""

    summary: FillQualitySummarySchema
    recent_fills: list[FillQualityRecordSchema]
    as_of: Optional[dt.datetime]


class FillQualityTickerResponse(BaseModel):
    """Response for GET /portfolio/fill-quality/{ticker}."""

    ticker: str
    fills: list[FillQualityRecordSchema]
    summary: Optional[FillQualitySummarySchema]
    total_fills: int


class AlphaDecaySummarySchema(BaseModel):
    """Aggregate alpha-decay attribution statistics."""

    records_with_alpha: int
    avg_alpha_captured_pct: Optional[float]
    avg_slippage_as_pct_of_move: Optional[float]
    positive_alpha_count: int
    negative_alpha_count: int
    n_days: int
    computed_at: Optional[dt.datetime]


class FillAttributionResponse(BaseModel):
    """Response for GET /portfolio/fill-quality/attribution."""

    summary: AlphaDecaySummarySchema
    enriched_fill_count: int
    total_fill_count: int
    as_of: Optional[dt.datetime]
