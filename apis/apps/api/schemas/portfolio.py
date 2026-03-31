"""Response schemas for /api/v1/portfolio/* endpoints."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from pydantic import BaseModel


class PositionSchema(BaseModel):
    ticker: str
    quantity: float
    avg_entry_price: float
    current_price: float
    market_value: float
    cost_basis: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    opened_at: dt.datetime
    thesis_summary: str
    strategy_key: str


class PortfolioResponse(BaseModel):
    cash: float
    equity: float
    gross_exposure: float
    position_count: int
    drawdown_pct: float
    daily_pnl_pct: float
    positions: list[PositionSchema]
    as_of: dt.datetime


class PortfolioPositionsResponse(BaseModel):
    count: int
    positions: list[PositionSchema]


class PositionDetailResponse(BaseModel):
    found: bool
    position: Optional[PositionSchema]


class PortfolioSnapshotRecord(BaseModel):
    """A single DB-persisted portfolio snapshot (Priority 20)."""

    id: str
    snapshot_timestamp: dt.datetime
    mode: str
    cash_balance: Optional[float] = None
    gross_exposure: Optional[float] = None
    net_exposure: Optional[float] = None
    equity_value: Optional[float] = None
    drawdown_pct: Optional[float] = None


class PortfolioSnapshotHistoryResponse(BaseModel):
    """Paginated list of persisted portfolio snapshots."""

    count: int
    items: list[PortfolioSnapshotRecord]


# ── Phase 27: Closed trade ledger ─────────────────────────────────────────────────

class ClosedTradeRecord(BaseModel):
    """A single completed trade sourced from the in-memory closed trade ledger."""

    ticker: str
    action_type: str              # "close" or "trim"
    fill_price: float
    avg_entry_price: float
    quantity: float
    realized_pnl: float
    realized_pnl_pct: float
    is_winner: bool
    reason: str
    opened_at: dt.datetime
    closed_at: dt.datetime
    hold_duration_days: int


class ClosedTradeHistoryResponse(BaseModel):
    """Paginated closed trade history with aggregate P&L statistics."""

    count: int
    total_realized_pnl: float
    win_count: int
    loss_count: int
    win_rate: Optional[float]     # None when no trades; else win_count / total_closed
    items: list[ClosedTradeRecord]


# ── Phase 28: Trade grading + Performance summary ───────────────────────────────────

class TradeGradeRecord(BaseModel):
    """A single graded closed trade sourced from app_state.trade_grades."""

    ticker: str
    strategy_key: str
    realized_pnl: float
    realized_pnl_pct: float
    holding_days: int
    is_winner: bool
    exit_reason: str
    grade: str   # "A" | "B" | "C" | "D" | "F"


class TradeGradeHistoryResponse(BaseModel):
    """Paginated list of trade grades with distribution summary."""

    count: int
    grade_distribution: dict[str, int]   # {"A": 5, "B": 3, "C": 2, "D": 1, "F": 0}
    items: list[TradeGradeRecord]


class PerformanceSummaryResponse(BaseModel):
    """Live performance summary combining realized & unrealized P&L."""

    # Equity snapshot
    equity: float
    start_of_day_equity: float
    high_water_mark: Optional[float]
    daily_return_pct: float          # (equity - sod) / sod * 100
    drawdown_from_hwm_pct: float     # (hwm - equity) / hwm * 100, clamped ≥ 0

    # Realized (from closed trade ledger)
    total_realized_pnl: float
    realized_trade_count: int
    win_count: int
    loss_count: int
    win_rate: Optional[float]        # None when no trades

    # Unrealized (from open positions)
    total_unrealized_pnl: float
    open_position_count: int

    # Cash
    cash: float
    as_of: dt.datetime


class PositionHistoryRecord(BaseModel):
    """One P&L snapshot row for a single ticker at a single point in time."""

    id: str
    ticker: str
    snapshot_at: dt.datetime
    quantity: Optional[float]
    avg_entry_price: Optional[float]
    current_price: Optional[float]
    market_value: Optional[float]
    cost_basis: Optional[float]
    unrealized_pnl: Optional[float]
    unrealized_pnl_pct: Optional[float]


class PositionHistoryResponse(BaseModel):
    """Paginated position P&L history for one ticker (most recent first)."""

    ticker: str
    count: int
    items: list[PositionHistoryRecord]


class PositionLatestSnapshotResponse(BaseModel):
    """Most-recent P&L snapshot across all currently-tracked tickers."""

    count: int
    items: list[PositionHistoryRecord]

