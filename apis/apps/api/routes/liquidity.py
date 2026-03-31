"""
Liquidity Filter API routes (Phase 41).

GET /api/v1/portfolio/liquidity
    Returns the full universe liquidity screen — every ticker for which
    dollar_volume_20d data exists, sorted by ADV descending.

GET /api/v1/portfolio/liquidity/{ticker}
    Returns single-ticker liquidity detail: ADV, gate status, notional cap.

Both endpoints return from in-memory app_state (no DB access on the request
path).  Data is populated by the run_liquidity_refresh job at 06:17 ET.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter

from apps.api.deps import AppStateDep, SettingsDep
from apps.api.schemas.liquidity import (
    LiquidityScreenResponse,
    TickerLiquidityDetailResponse,
    TickerLiquiditySchema,
)
from services.risk_engine.liquidity import LiquidityService

liquidity_router = APIRouter(prefix="/portfolio", tags=["Liquidity"])


@liquidity_router.get(
    "/liquidity",
    response_model=LiquidityScreenResponse,
    summary="Full universe liquidity screen",
    description=(
        "Returns dollar_volume_20d, liquidity gate status, and ADV notional cap "
        "for every ticker in the latest liquidity dataset.  "
        "Tickers are sorted by ADV descending.  Returns an empty response when "
        "the run_liquidity_refresh job has not yet run."
    ),
)
def get_liquidity_screen(
    state: AppStateDep,
    settings: SettingsDep,
) -> LiquidityScreenResponse:
    """Return full liquidity screen from in-memory app_state."""
    dollar_volumes: dict = getattr(state, "latest_dollar_volumes", {})
    computed_at = getattr(state, "liquidity_computed_at", None)
    min_dv: float = float(getattr(settings, "min_liquidity_dollar_volume", 1_000_000.0))
    max_pct: float = float(getattr(settings, "max_position_as_pct_of_adv", 0.10))

    if not dollar_volumes:
        return LiquidityScreenResponse(
            computed_at=computed_at,
            min_liquidity_dollar_volume=min_dv,
            max_position_as_pct_of_adv=max_pct,
            ticker_count=0,
            liquid_count=0,
            illiquid_count=0,
            tickers=[],
        )

    summaries = LiquidityService.liquidity_summary(dollar_volumes, settings)

    tickers_out = [
        TickerLiquiditySchema(
            ticker=row["ticker"],
            dollar_volume_20d=row["dollar_volume_20d"],
            is_liquid=row["is_liquid"],
            adv_notional_cap_usd=row["adv_notional_cap_usd"],
            liquidity_tier=row["liquidity_tier"],
        )
        for row in summaries
    ]

    liquid_count = sum(1 for t in tickers_out if t.is_liquid)

    return LiquidityScreenResponse(
        computed_at=computed_at,
        min_liquidity_dollar_volume=min_dv,
        max_position_as_pct_of_adv=max_pct,
        ticker_count=len(tickers_out),
        liquid_count=liquid_count,
        illiquid_count=len(tickers_out) - liquid_count,
        tickers=tickers_out,
    )


@liquidity_router.get(
    "/liquidity/{ticker}",
    response_model=TickerLiquidityDetailResponse,
    summary="Single-ticker liquidity detail",
    description=(
        "Returns dollar_volume_20d, gate status, and ADV notional cap for a "
        "single ticker.  A 200 response with data_available=False is returned "
        "when no data exists for the ticker — 404 is NOT raised."
    ),
)
def get_ticker_liquidity(
    ticker: str,
    state: AppStateDep,
    settings: SettingsDep,
) -> TickerLiquidityDetailResponse:
    """Return liquidity detail for a single ticker."""
    ticker = ticker.upper()
    dollar_volumes: dict = getattr(state, "latest_dollar_volumes", {})
    computed_at = getattr(state, "liquidity_computed_at", None)
    min_dv: float = float(getattr(settings, "min_liquidity_dollar_volume", 1_000_000.0))
    max_pct: float = float(getattr(settings, "max_position_as_pct_of_adv", 0.10))

    dv = dollar_volumes.get(ticker)

    if dv is None:
        return TickerLiquidityDetailResponse(
            ticker=ticker,
            dollar_volume_20d=None,
            is_liquid=None,
            adv_notional_cap_usd=None,
            liquidity_tier=None,
            min_liquidity_dollar_volume=min_dv,
            max_position_as_pct_of_adv=max_pct,
            computed_at=computed_at,
            data_available=False,
        )

    liquid = LiquidityService.is_liquid(dv, settings)
    cap_usd = round(dv * max_pct, 2)

    if dv >= 100_000_000:
        tier = "high"
    elif dv >= 10_000_000:
        tier = "mid"
    elif dv >= 1_000_000:
        tier = "low"
    else:
        tier = "micro"

    return TickerLiquidityDetailResponse(
        ticker=ticker,
        dollar_volume_20d=dv,
        is_liquid=liquid,
        adv_notional_cap_usd=cap_usd,
        liquidity_tier=tier,
        min_liquidity_dollar_volume=min_dv,
        max_position_as_pct_of_adv=max_pct,
        computed_at=computed_at,
        data_available=True,
    )
