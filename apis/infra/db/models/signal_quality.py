"""Signal quality outcome persistence model.

Each row records the outcome of one strategy signal prediction for a
closed trade — whether the predicted direction was correct and what
return was realised.  Aggregated by SignalQualityService to produce
per-strategy win-rate, average-return, and Sharpe-estimate statistics.

Phase 46 — Signal Quality Tracking + Per-Strategy Attribution
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class SignalOutcome(Base, TimestampMixin):
    """One strategy-signal → closed-trade outcome record.

    ticker + strategy_name + trade_opened_at forms the natural key: the
    same ticker may be traded multiple times, but a given (ticker,
    strategy, open-date) tuple identifies a unique prediction event.

    signal_score is nullable — it is only populated when a matching
    SecuritySignal row can be found in the DB for that ticker/date.
    When no signal row is found (e.g. signal_runs table is empty for
    that date) the outcome is still recorded with signal_score=NULL
    so the trade-level win/return statistics remain accurate.
    """

    __tablename__ = "signal_outcomes"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, nullable=False)

    # Trade identification
    ticker: Mapped[str] = mapped_column(sa.String(16), nullable=False)

    # Strategy that generated the signal (denormalized for query simplicity)
    strategy_name: Mapped[str] = mapped_column(sa.String(64), nullable=False)

    # Signal score from SecuritySignal on the day the position was opened
    signal_score: Mapped[Optional[Decimal]] = mapped_column(
        sa.Numeric(12, 6), nullable=True
    )

    # Timestamps from the closed trade
    trade_opened_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    trade_closed_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )

    # Outcome metrics
    outcome_return_pct: Mapped[Decimal] = mapped_column(
        sa.Numeric(12, 6), nullable=False
    )
    hold_days: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    was_profitable: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)

    __table_args__ = (
        # Prevent duplicate outcome rows for the same trade
        sa.UniqueConstraint(
            "ticker",
            "strategy_name",
            "trade_opened_at",
            name="uq_signal_outcome_trade",
        ),
        sa.Index("ix_signal_outcome_strategy", "strategy_name"),
        sa.Index("ix_signal_outcome_ticker",   "ticker"),
        sa.Index("ix_signal_outcome_opened_at", "trade_opened_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<SignalOutcome ticker={self.ticker!r} strategy={self.strategy_name!r} "
            f"return={self.outcome_return_pct} profitable={self.was_profitable}>"
        )
