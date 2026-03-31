"""
Sector Exposure API routes (Phase 40).

GET /api/v1/portfolio/sector-exposure
    Returns the current sector allocation breakdown derived from live
    portfolio positions in app_state.  No DB access — pure in-memory.

GET /api/v1/portfolio/sector-exposure/{sector}
    Returns a single sector's detail: weight, market value, constituent
    tickers, and whether the sector is at or near its limit.

Both endpoints return empty/zero responses when no portfolio positions exist.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter

from apps.api.deps import AppStateDep, SettingsDep
from apps.api.schemas.sector import (
    SectorAllocationSchema,
    SectorDetailResponse,
    SectorExposureResponse,
)
from services.risk_engine.sector_exposure import SectorExposureService

sector_router = APIRouter(prefix="/portfolio", tags=["Sector Exposure"])


def _build_sector_allocation(
    sector: str,
    tickers: list[str],
    market_value_usd: float,
    equity_usd: float,
    max_sector_pct: float,
) -> SectorAllocationSchema:
    weight = (market_value_usd / equity_usd) if equity_usd > 0 else 0.0
    return SectorAllocationSchema(
        sector=sector,
        weight=round(weight, 6),
        weight_pct=round(weight * 100, 4),
        market_value_usd=round(market_value_usd, 2),
        tickers=sorted(tickers),
        at_limit=weight >= max_sector_pct,
    )


@sector_router.get(
    "/sector-exposure",
    response_model=SectorExposureResponse,
    summary="Current sector allocation breakdown",
    description=(
        "Returns the portfolio's sector allocation computed from live positions "
        "in app_state.  Sectors are derived from the static universe TICKER_SECTOR "
        "registry.  Returns an empty response when no positions are open."
    ),
)
def get_sector_exposure(state: AppStateDep, settings: SettingsDep) -> SectorExposureResponse:
    """Return current sector breakdown from live portfolio positions."""
    ps = getattr(state, "portfolio_state", None)
    max_pct: float = float(getattr(settings, "max_sector_pct", 0.40))
    computed_at = dt.datetime.now(dt.timezone.utc)

    if ps is None or not getattr(ps, "positions", {}):
        return SectorExposureResponse(
            computed_at=computed_at,
            equity_usd=0.0,
            max_sector_pct=max_pct,
            sector_count=0,
            sectors=[],
        )

    equity: Decimal = getattr(ps, "equity", Decimal("0"))
    positions: dict = ps.positions
    equity_usd = float(equity)

    # Aggregate tickers and market values per sector
    sector_tickers: dict[str, list[str]] = {}
    sector_mv: dict[str, float] = {}

    for ticker, pos in positions.items():
        sector = SectorExposureService.get_sector(ticker)
        mv = float(getattr(pos, "market_value", Decimal("0")))
        sector_tickers.setdefault(sector, []).append(ticker)
        sector_mv[sector] = sector_mv.get(sector, 0.0) + mv

    sectors = [
        _build_sector_allocation(
            sector=s,
            tickers=sector_tickers[s],
            market_value_usd=sector_mv[s],
            equity_usd=equity_usd,
            max_sector_pct=max_pct,
        )
        for s in sorted(sector_mv.keys())
    ]

    return SectorExposureResponse(
        computed_at=computed_at,
        equity_usd=round(equity_usd, 2),
        max_sector_pct=max_pct,
        sector_count=len(sectors),
        sectors=sectors,
    )


@sector_router.get(
    "/sector-exposure/{sector}",
    response_model=SectorDetailResponse,
    summary="Single sector detail",
    description=(
        "Returns a single sector's current allocation detail.  "
        "A 200 response with weight=0.0 is returned when the sector has no "
        "open positions — 404 is NOT raised."
    ),
)
def get_sector_detail(
    sector: str,
    state: AppStateDep,
    settings: SettingsDep,
) -> SectorDetailResponse:
    """Return detailed breakdown for a single sector."""
    sector = sector.lower()
    max_pct: float = float(getattr(settings, "max_sector_pct", 0.40))
    computed_at = dt.datetime.now(dt.timezone.utc)

    ps = getattr(state, "portfolio_state", None)
    if ps is None or not getattr(ps, "positions", {}):
        return SectorDetailResponse(
            sector=sector,
            weight=0.0,
            weight_pct=0.0,
            market_value_usd=0.0,
            tickers=[],
            max_sector_pct=max_pct,
            at_limit=False,
            computed_at=computed_at,
        )

    equity: Decimal = getattr(ps, "equity", Decimal("0"))
    positions: dict = ps.positions
    equity_usd = float(equity)

    tickers_in_sector = [
        t for t, pos in positions.items()
        if SectorExposureService.get_sector(t) == sector
    ]
    mv_usd = sum(
        float(getattr(positions[t], "market_value", Decimal("0")))
        for t in tickers_in_sector
    )
    weight = (mv_usd / equity_usd) if equity_usd > 0 else 0.0

    return SectorDetailResponse(
        sector=sector,
        weight=round(weight, 6),
        weight_pct=round(weight * 100, 4),
        market_value_usd=round(mv_usd, 2),
        tickers=sorted(tickers_in_sector),
        max_sector_pct=max_pct,
        at_limit=weight >= max_pct,
        computed_at=computed_at,
    )
