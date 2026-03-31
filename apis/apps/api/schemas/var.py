"""
VaR API response schemas (Phase 43).

GET /api/v1/portfolio/var
GET /api/v1/portfolio/var/{ticker}
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from pydantic import BaseModel


class TickerVaRSchema(BaseModel):
    """Standalone VaR contribution for a single position."""

    ticker: str
    weight_pct: float               # position weight as % of equity
    standalone_var_95_pct: float    # standalone 1-day 95% VaR as % of equity
    standalone_var_95_dollar: float # standalone 1-day 95% VaR in USD


class PortfolioVaRResponse(BaseModel):
    """Full portfolio VaR & CVaR summary.

    Returned by GET /api/v1/portfolio/var.
    """

    computed_at: Optional[dt.datetime]
    equity: float
    positions_count: int
    lookback_days: int
    insufficient_data: bool

    # Portfolio-level VaR / CVaR
    portfolio_var_95_pct: float     # 1-day 95% VaR as % of equity
    portfolio_var_99_pct: float     # 1-day 99% VaR as % of equity
    portfolio_cvar_95_pct: float    # 1-day 95% CVaR as % of equity
    portfolio_var_95_dollar: float  # 1-day 95% VaR in USD
    portfolio_var_99_dollar: float  # 1-day 99% VaR in USD
    portfolio_cvar_95_dollar: float # 1-day 95% CVaR in USD

    # Settings
    max_portfolio_var_pct: float    # configured limit (% of equity)
    var_limit_breached: bool        # True when var_95 > limit

    # Per-ticker contributions
    tickers: list[TickerVaRSchema]


class TickerVaRDetailResponse(BaseModel):
    """Single-ticker VaR detail.

    Returned by GET /api/v1/portfolio/var/{ticker}.
    A 200 with data_available=False is returned when no data exists
    for the ticker — 404 is NOT raised.
    """

    ticker: str
    data_available: bool
    computed_at: Optional[dt.datetime]

    # Position info (None when data_available=False)
    weight_pct: Optional[float] = None
    standalone_var_95_pct: Optional[float] = None
    standalone_var_95_dollar: Optional[float] = None

    # Portfolio context
    portfolio_var_95_pct: Optional[float] = None
    equity: Optional[float] = None
