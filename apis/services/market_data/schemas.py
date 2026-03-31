"""market_data Pydantic schemas for API serialization."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Optional

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
    dollar_volume: Optional[Decimal] = None


class LiquidityMetricsSchema(BaseModel):
    ticker: str
    as_of: dt.date
    avg_dollar_volume_20d: Optional[Decimal] = None
    avg_dollar_volume_60d: Optional[Decimal] = None
    avg_volume_20d: Optional[int] = None
    price_range_pct_20d: Optional[Decimal] = None
    liquidity_tier: str
    is_liquid_enough: bool


class MarketSnapshotSchema(BaseModel):
    ticker: str
    as_of: dt.datetime
    latest_price: Optional[Decimal] = None
    liquidity_tier: Optional[str] = None
    bars_count: int = Field(0, description="Number of 1-year bars loaded")
    source_key: str = "yfinance"
    reliability_tier: str = "secondary_verified"

