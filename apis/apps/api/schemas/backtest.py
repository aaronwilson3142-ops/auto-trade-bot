"""Pydantic schemas for backtest comparison endpoints."""
from __future__ import annotations

import datetime as dt
from typing import List, Optional

from pydantic import BaseModel, Field


class BacktestCompareRequest(BaseModel):
    """Request body for POST /api/v1/backtest/compare."""

    tickers: List[str] = Field(
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

    run_id: Optional[str] = None
    comparison_id: str
    strategy_name: str
    start_date: dt.date
    end_date: dt.date
    ticker_count: int
    tickers: Optional[List[str]] = None
    total_return_pct: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    win_rate: Optional[float] = None
    total_trades: Optional[int] = 0
    days_simulated: Optional[int] = 0
    final_portfolio_value: Optional[float] = None
    initial_cash: Optional[float] = None
    status: str = "completed"
    error: Optional[str] = None
    created_at: Optional[dt.datetime] = None


class BacktestComparisonResponse(BaseModel):
    """Response from POST /api/v1/backtest/compare."""

    comparison_id: str
    run_count: int
    runs: List[BacktestRunRecord]


class BacktestComparisonSummary(BaseModel):
    """Summary of one comparison group (latest created_at, number of runs)."""

    comparison_id: str
    run_count: int
    created_at: Optional[dt.datetime] = None
    start_date: Optional[dt.date] = None
    end_date: Optional[dt.date] = None
    ticker_count: Optional[int] = None
    best_strategy: Optional[str] = None
    best_total_return_pct: Optional[float] = None


class BacktestRunListResponse(BaseModel):
    """Response from GET /api/v1/backtest/runs."""

    count: int
    comparisons: List[BacktestComparisonSummary]


class BacktestRunDetailResponse(BaseModel):
    """Response from GET /api/v1/backtest/runs/{comparison_id}."""

    comparison_id: str
    run_count: int
    runs: List[BacktestRunRecord]
