"""Pydantic schemas for backtest comparison endpoints."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field


class BacktestCompareRequest(BaseModel):
    """Request body for POST /api/v1/backtest/compare."""

    tickers: list[str] = Field(
        default=["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"],
        description="List of ticker symbols to include in the backtest.",
    )
    start_date: dt.date = Field(
        description="Backtest start date (inclusive).",
    )
    end_date: dt.date = Field(
        description="Backtest end date (inclusive).",
    )
    initial_cash: float = Field(
        default=100_000.0,
        ge=1.0,
        description="Starting portfolio cash in USD.",
    )


class BacktestRunRecord(BaseModel):
    """Single strategy run within a comparison group."""

    run_id: str | None = None
    comparison_id: str
    strategy_name: str
    start_date: dt.date
    end_date: dt.date
    ticker_count: int
    tickers: list[str] | None = None
    total_return_pct: float | None = None
    sharpe_ratio: float | None = None
    max_drawdown_pct: float | None = None
    win_rate: float | None = None
    total_trades: int | None = 0
    days_simulated: int | None = 0
    final_portfolio_value: float | None = None
    initial_cash: float | None = None
    status: str = "completed"
    error: str | None = None
    created_at: dt.datetime | None = None


class BacktestComparisonResponse(BaseModel):
    """Response from POST /api/v1/backtest/compare."""

    comparison_id: str
    run_count: int
    runs: list[BacktestRunRecord]


class BacktestComparisonSummary(BaseModel):
    """Summary of one comparison group (latest created_at, number of runs)."""

    comparison_id: str
    run_count: int
    created_at: dt.datetime | None = None
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    ticker_count: int | None = None
    best_strategy: str | None = None
    best_total_return_pct: float | None = None


class BacktestRunListResponse(BaseModel):
    """Response from GET /api/v1/backtest/runs."""

    count: int
    comparisons: list[BacktestComparisonSummary]


class BacktestRunDetailResponse(BaseModel):
    """Response from GET /api/v1/backtest/runs/{comparison_id}."""

    comparison_id: str
    run_count: int
    runs: list[BacktestRunRecord]
