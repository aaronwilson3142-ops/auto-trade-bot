"""Schemas for liquidity filter endpoints (Phase 41)."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class TickerLiquiditySchema(BaseModel):
    """Per-ticker liquidity status."""

    ticker: str
    dollar_volume_20d: float          # 20-day avg daily dollar volume (USD)
    is_liquid: bool                    # True if >= min_liquidity_dollar_volume
    adv_notional_cap_usd: float        # max position notional = max_pct_of_adv × ADV
    liquidity_tier: str                # "high" / "mid" / "low" / "micro"


class LiquidityScreenResponse(BaseModel):
    """Full universe liquidity screen — all tickers with ADV data."""

    computed_at: dt.datetime | None
    min_liquidity_dollar_volume: float
    max_position_as_pct_of_adv: float
    ticker_count: int
    liquid_count: int
    illiquid_count: int
    tickers: list[TickerLiquiditySchema]


class TickerLiquidityDetailResponse(BaseModel):
    """Single-ticker liquidity detail."""

    ticker: str
    dollar_volume_20d: float | None
    is_liquid: bool | None
    adv_notional_cap_usd: float | None
    liquidity_tier: str | None
    min_liquidity_dollar_volume: float
    max_position_as_pct_of_adv: float
    computed_at: dt.datetime | None
    data_available: bool
