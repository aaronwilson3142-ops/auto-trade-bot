"""
Earnings Calendar API routes (Phase 45).

GET /api/v1/portfolio/earnings-calendar
    Returns the full earnings proximity calendar for all universe tickers.
    Populated by run_earnings_refresh at 06:23 ET.

GET /api/v1/portfolio/earnings-risk/{ticker}
    Returns per-ticker earnings detail including next earnings date and
    days_to_earnings.  Returns data_available=False (not 404) when no
    calendar has run yet or ticker is not found.
"""
from __future__ import annotations

from fastapi import APIRouter

from apps.api.deps import AppStateDep, SettingsDep
from apps.api.schemas.earnings import (
    EarningsCalendarResponse,
    EarningsEntrySchema,
    EarningsTickerResponse,
)

earnings_router = APIRouter(prefix="/portfolio", tags=["Earnings Calendar"])


@earnings_router.get(
    "/earnings-calendar",
    response_model=EarningsCalendarResponse,
    summary="Earnings proximity calendar for universe tickers",
    description=(
        "Returns the latest earnings calendar showing which tickers have "
        "upcoming earnings within the proximity window "
        "(max_earnings_proximity_days).  Tickers in at_risk_tickers will "
        "have new OPEN actions blocked by the paper cycle earnings gate.  "
        "Data is populated by run_earnings_refresh at 06:23 ET.  "
        "Returns an empty response when no earnings refresh has run yet."
    ),
)
def get_earnings_calendar(
    state: AppStateDep,
    settings: SettingsDep,
) -> EarningsCalendarResponse:
    """Return full earnings calendar from in-memory app_state."""
    cal = getattr(state, "latest_earnings_calendar", None)
    max_days: int = int(getattr(settings, "max_earnings_proximity_days", 2))
    filtered_count: int = int(getattr(state, "earnings_filtered_count", 0))

    if cal is None:
        return EarningsCalendarResponse(
            computed_at=None,
            reference_date=None,
            max_earnings_proximity_days=max_days,
            tickers_checked=0,
            at_risk_count=0,
            at_risk_tickers=[],
            earnings_gate_active=False,
            earnings_filtered_count=filtered_count,
            no_calendar=True,
            entries=[],
        )

    entry_schemas = [
        EarningsEntrySchema(
            ticker=e.ticker,
            earnings_date=e.earnings_date,
            days_to_earnings=e.days_to_earnings,
            earnings_within_window=e.earnings_within_window,
            max_earnings_proximity_days=e.max_earnings_proximity_days,
        )
        for e in cal.entries.values()
    ]

    gate_active = (
        max_days > 0
        and not cal.no_calendar
        and len(cal.at_risk_tickers) > 0
    )

    return EarningsCalendarResponse(
        computed_at=cal.computed_at,
        reference_date=cal.reference_date,
        max_earnings_proximity_days=max_days,
        tickers_checked=len(cal.entries),
        at_risk_count=len(cal.at_risk_tickers),
        at_risk_tickers=sorted(cal.at_risk_tickers),
        earnings_gate_active=gate_active,
        earnings_filtered_count=filtered_count,
        no_calendar=cal.no_calendar,
        entries=entry_schemas,
    )


@earnings_router.get(
    "/earnings-risk/{ticker}",
    response_model=EarningsTickerResponse,
    summary="Per-ticker earnings proximity detail",
    description=(
        "Returns earnings date and proximity data for a single ticker.  "
        "earnings_within_window=True means this ticker's OPEN actions are "
        "currently blocked by the earnings proximity gate.  "
        "Returns data_available=False (200, not 404) when no earnings "
        "calendar has been populated yet or the ticker is not found."
    ),
)
def get_earnings_risk_ticker(
    ticker: str,
    state: AppStateDep,
    settings: SettingsDep,
) -> EarningsTickerResponse:
    """Return earnings proximity detail for a single ticker."""
    ticker = ticker.upper()
    max_days: int = int(getattr(settings, "max_earnings_proximity_days", 2))
    cal = getattr(state, "latest_earnings_calendar", None)

    if cal is None:
        return EarningsTickerResponse(
            ticker=ticker,
            data_available=False,
            max_earnings_proximity_days=max_days,
        )

    entry = cal.entries.get(ticker)
    if entry is None:
        return EarningsTickerResponse(
            ticker=ticker,
            data_available=False,
            computed_at=cal.computed_at,
            max_earnings_proximity_days=max_days,
        )

    return EarningsTickerResponse(
        ticker=ticker,
        data_available=True,
        computed_at=cal.computed_at,
        earnings_date=entry.earnings_date,
        days_to_earnings=entry.days_to_earnings,
        earnings_within_window=entry.earnings_within_window,
        max_earnings_proximity_days=max_days,
    )
