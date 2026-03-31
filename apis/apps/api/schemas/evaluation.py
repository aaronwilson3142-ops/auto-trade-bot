"""Response schemas for /api/v1/evaluation/* endpoints."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from pydantic import BaseModel


class DailyScorecardResponse(BaseModel):
    scorecard_date: dt.date
    equity: float
    cash: float
    gross_exposure: float
    position_count: int
    net_pnl: float
    realized_pnl: float
    unrealized_pnl: float
    daily_return_pct: float
    hit_rate: float
    closed_trade_count: int
    avg_winner_pct: float
    avg_loser_pct: float
    current_drawdown_pct: float
    max_drawdown_pct: float
    mode: str
    benchmark_returns: dict[str, float]       # benchmark ticker → daily return
    benchmark_differentials: dict[str, float] # portfolio - benchmark
    run_id: Optional[str] = None


class EvaluationLatestResponse(BaseModel):
    found: bool
    scorecard: Optional[DailyScorecardResponse]
    run_id: Optional[str]


class EvaluationHistoryResponse(BaseModel):
    count: int
    items: list[DailyScorecardResponse]


class EvaluationRunRecord(BaseModel):
    """A single DB-persisted evaluation run entry (Priority 20)."""

    id: str
    run_timestamp: dt.datetime
    mode: str
    status: str
    evaluation_period_start: Optional[dt.date] = None
    evaluation_period_end: Optional[dt.date] = None
    metrics: dict[str, Optional[float]]


class EvaluationRunHistoryResponse(BaseModel):
    """Paginated list of persisted evaluation runs."""

    count: int
    items: list[EvaluationRunRecord]
