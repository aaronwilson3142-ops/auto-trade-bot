"""Shadow Portfolio models — Deep-Dive Plan Step 7 Rec 11 + DEC-034.

Virtual paper portfolios that mirror the live portfolio's risk gates but take
the ideas the live portfolio *rejected* or *didn't take*, plus parallel
alternative-rebalance-weighting shadows (equal / score / score_invvol) per
**DEC-034**.

Six named shadows are maintained in ``shadow_portfolios``:

    * ``rejected_actions``         — composite-filter or risk-gate rejections
    * ``watch_tier``               — ranked opportunities with composite ∈ [0.55, 0.65]
    * ``stopped_out_continued``    — positions stopped-out continuing virtually
    * ``rebalance_equal``          — parallel A/B shadow for equal weighting
    * ``rebalance_score``          — parallel A/B shadow for score weighting
    * ``rebalance_score_invvol``   — parallel A/B shadow for score/inv-vol

All writes are flag-gated at the call site (``settings.shadow_portfolio_enabled``).
The tables exist even when the flag is OFF so the migration stays reversible
on its own.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


# Reserved shadow names — these are the six DEC-034 buckets.  Free-form
# names are still permitted by the schema (no CHECK), but these are the
# canonical set recognised by ``ShadowPortfolioService``.
SHADOW_NAMES = (
    "rejected_actions",
    "watch_tier",
    "stopped_out_continued",
    "rebalance_equal",
    "rebalance_score",
    "rebalance_score_invvol",
)


class ShadowPortfolio(Base, TimestampMixin):
    """A named virtual portfolio with its own cash balance."""

    __tablename__ = "shadow_portfolios"
    __table_args__ = (
        sa.UniqueConstraint("name", name="uq_shadow_portfolios_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    starting_cash: Mapped[Decimal] = mapped_column(
        sa.Numeric(14, 2),
        nullable=False,
        server_default=sa.text("100000"),
    )


class ShadowPosition(Base, TimestampMixin):
    """One virtual open position inside a shadow portfolio.

    There is at most one row per (shadow_portfolio_id, ticker) — virtual closes
    delete the row; virtual adds-to-position upsert into shares/avg_cost.
    """

    __tablename__ = "shadow_positions"
    __table_args__ = (
        sa.UniqueConstraint(
            "shadow_portfolio_id",
            "ticker",
            name="uq_shadow_positions_portfolio_ticker",
        ),
        sa.Index("ix_shadow_positions_portfolio", "shadow_portfolio_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    shadow_portfolio_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("shadow_portfolios.id"),
        nullable=False,
    )
    ticker: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    shares: Mapped[Decimal] = mapped_column(sa.Numeric(14, 4), nullable=False)
    avg_cost: Mapped[Decimal] = mapped_column(sa.Numeric(14, 4), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    opened_source: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    # rejection reason, watch composite bucket, or weighting_mode that birthed
    # the position — free-form text, surfaced on dashboards.


class ShadowTrade(Base, TimestampMixin):
    """Immutable ledger of every virtual order placed against a shadow."""

    __tablename__ = "shadow_trades"
    __table_args__ = (
        sa.Index(
            "ix_shadow_trades_portfolio_exec",
            "shadow_portfolio_id",
            "executed_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    shadow_portfolio_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("shadow_portfolios.id"),
        nullable=False,
    )
    ticker: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    action: Mapped[str] = mapped_column(sa.String(10), nullable=False)
    # BUY | SELL
    shares: Mapped[Decimal] = mapped_column(sa.Numeric(14, 4), nullable=False)
    price: Mapped[Decimal] = mapped_column(sa.Numeric(14, 4), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    realized_pnl: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(14, 2), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    # Populated for ``rejected_actions`` and ``watch_tier``; NULL otherwise.
    weighting_mode: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    # Populated for ``rebalance_*`` shadows; NULL otherwise.
