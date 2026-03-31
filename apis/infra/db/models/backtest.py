"""Backtest run persistence model.

Each row represents one strategy backtest run produced by
BacktestComparisonService.  A comparison stores one row per strategy
(including "all_strategies" for the combined run).
"""
from __future__ import annotations

import uuid
from datetime import date

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class BacktestRun(Base, TimestampMixin):
    """One backtest simulation run (single strategy or combined)."""

    __tablename__ = "backtest_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Groups all rows from a single comparison request
    comparison_id: Mapped[str] = mapped_column(sa.String(36), nullable=False, index=True)
    strategy_name: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    start_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    end_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    ticker_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    tickers_json: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # Key performance metrics
    total_return_pct: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    sharpe_ratio: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    max_drawdown_pct: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    win_rate: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    total_trades: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    days_simulated: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    final_portfolio_value: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    initial_cash: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="completed")
    run_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
