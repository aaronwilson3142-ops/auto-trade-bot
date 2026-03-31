"""
Stress Test API response schemas (Phase 44).

GET /api/v1/portfolio/stress-test
GET /api/v1/portfolio/stress-test/{scenario}
"""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class ScenarioResultSchema(BaseModel):
    """P&L impact of a single historical-shock scenario."""

    scenario_name: str                  # machine key, e.g. "financial_crisis_2008"
    scenario_label: str                 # human-readable name
    portfolio_shocked_pnl: float        # total portfolio P&L in USD (negative = loss)
    portfolio_shocked_pnl_pct: float    # portfolio P&L as % of equity (negative = loss)
    positions_count: int
    ticker_shocked_pnl: dict            # ticker → USD P&L
    ticker_shocked_pnl_pct: dict        # ticker → % of equity P&L


class StressTestSummaryResponse(BaseModel):
    """Full stress-test result across all four scenarios.

    Returned by GET /api/v1/portfolio/stress-test.
    """

    computed_at: dt.datetime | None
    equity: float
    positions_count: int
    no_positions: bool

    # Worst-case summary
    worst_case_scenario: str
    worst_case_scenario_label: str
    worst_case_loss_pct: float          # positive %; magnitude of worst loss
    worst_case_loss_dollar: float       # positive USD; magnitude of worst loss

    # Gate info
    max_stress_loss_pct: float          # configured threshold (%)
    stress_limit_breached: bool         # True when worst_case > limit

    scenarios: list[ScenarioResultSchema]


class StressScenarioDetailResponse(BaseModel):
    """Detail for a single scenario.

    Returned by GET /api/v1/portfolio/stress-test/{scenario}.
    A 200 with data_available=False is returned when no stress data exists
    for the named scenario — 404 is NOT raised.
    """

    scenario_name: str
    data_available: bool
    computed_at: dt.datetime | None

    scenario_label: str | None = None
    portfolio_shocked_pnl: float | None = None
    portfolio_shocked_pnl_pct: float | None = None
    equity: float | None = None
    positions_count: int | None = None
    ticker_shocked_pnl: dict | None = None
    worst_case_scenario: str | None = None
