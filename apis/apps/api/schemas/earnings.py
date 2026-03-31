"""
Pydantic schemas for Phase 45 — Earnings Calendar endpoints.

GET /api/v1/portfolio/earnings-calendar
    Returns the full earnings calendar for the universe with proximity flags.

GET /api/v1/portfolio/earnings-risk/{ticker}
    Returns per-ticker earnings detail including days_to_earnings.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from pydantic import BaseModel


class EarningsEntrySchema(BaseModel):
    """Earnings data for a single ticker."""

    ticker: str
    earnings_date: Optional[dt.date]
    days_to_earnings: Optional[int]
    earnings_within_window: bool
    max_earnings_proximity_days: int


class EarningsCalendarResponse(BaseModel):
    """Full earnings calendar response for the universe.

    at_risk_tickers: tickers with earnings within the proximity window.
    earnings_gate_active: True when at least one ticker is at-risk and
        the gate is enabled (max_earnings_proximity_days > 0).
    """

    computed_at: Optional[dt.datetime]
    reference_date: Optional[dt.date]
    max_earnings_proximity_days: int
    tickers_checked: int
    at_risk_count: int
    at_risk_tickers: list[str]
    earnings_gate_active: bool
    earnings_filtered_count: int
    no_calendar: bool
    entries: list[EarningsEntrySchema]


class EarningsTickerResponse(BaseModel):
    """Per-ticker earnings detail.

    data_available: False when no calendar data exists yet or ticker not found.
    """

    ticker: str
    data_available: bool
    computed_at: Optional[dt.datetime] = None
    earnings_date: Optional[dt.date] = None
    days_to_earnings: Optional[int] = None
    earnings_within_window: bool = False
    max_earnings_proximity_days: int = 0
