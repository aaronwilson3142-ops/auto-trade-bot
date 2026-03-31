"""market_data Pydantic schemas for API serialization."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, Field


class NormalizedBarSchema(BaseModel):
    ticker: str
    trade_date: dt.date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adjusted_close: Decimal
    volume: int
    dollar_volume: Decimal | None = None


class LiquidityMetricsSchema(BaseModel):
    ticker: str
    as_of: dt.date
    avg_dollar_volume_20d: Decimal | None = None
    avg_dollar_volume_60d: Decimal | None = None
    avg_volume_20d: int | None = None
    price_range_pct_20d: Decimal | None = None
    liquidity_tier: str
    is_liquid_enough: bool


class MarketSnapshotSchema(BaseModel):
    ticker: str
    as_of: dt.datetime
    latest_price: Decimal | None = None
    liquidity_tier: str | None = None
    bars_count: int = Field(0, description="Number of 1-year bars loaded")
    source_key: str = "yfinance"
    reliability_tier: str = "secondary_verified"

