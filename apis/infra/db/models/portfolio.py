"""Portfolio and execution models: portfolio_snapshots, positions, orders,
fills, risk_events."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class PortfolioSnapshot(Base, TimestampMixin):
    """Periodic snapshot of full portfolio state (cash, exposure, equity)."""

    __tablename__ = "portfolio_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    snapshot_timestamp: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False)
    mode: Mapped[str] = mapped_column(sa.String, nullable=False)
    cash_balance: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(20, 4), nullable=True)
    gross_exposure: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(20, 4), nullable=True)
    net_exposure: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(20, 4), nullable=True)
    equity_value: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(20, 4), nullable=True)
    drawdown_pct: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(12, 6), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)


class Position(Base, TimestampMixin):
    """Current and historical position records including thesis snapshots."""

    __tablename__ = "positions"
    __table_args__ = (
        sa.Index("ix_position_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    security_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("securities.id"), nullable=False
    )
    opened_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime, nullable=True)
    status: Mapped[str] = mapped_column(sa.String, nullable=False)
    entry_price: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(18, 6), nullable=True)
    exit_price: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(18, 6), nullable=True)
    quantity: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(20, 6), nullable=True)
    cost_basis: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(20, 4), nullable=True)
    market_value: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(20, 4), nullable=True)
    unrealized_pnl: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(20, 4), nullable=True)
    realized_pnl: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(20, 4), nullable=True)
    strategy_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("strategies.id"), nullable=True
    )
    thesis_snapshot_json: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)


class Order(Base, TimestampMixin):
    """Order intent, submission, and lifecycle tracking."""

    __tablename__ = "orders"
    __table_args__ = (
        sa.Index("ix_order_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    broker_order_ref: Mapped[Optional[str]] = mapped_column(sa.String, nullable=True)
    security_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("securities.id"), nullable=False
    )
    position_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("positions.id"), nullable=True
    )
    order_timestamp: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False)
    order_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    side: Mapped[str] = mapped_column(sa.String, nullable=False)
    quantity: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(20, 6), nullable=True)
    notional_amount: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(20, 4), nullable=True)
    limit_price: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(18, 6), nullable=True)
    stop_price: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(18, 6), nullable=True)
    status: Mapped[str] = mapped_column(sa.String, nullable=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(sa.String, nullable=True)
    decision_snapshot_json: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)


class Fill(Base, TimestampMixin):
    """Trade execution fill details and reconciliation data."""

    __tablename__ = "fills"
    __table_args__ = (
        sa.Index("ix_fill_timestamp", "fill_timestamp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=False
    )
    fill_timestamp: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False)
    fill_quantity: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(20, 6), nullable=True)
    fill_price: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(18, 6), nullable=True)
    fees: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(20, 4), nullable=True)
    liquidity_flag: Mapped[Optional[str]] = mapped_column(sa.String, nullable=True)


class PositionHistory(Base, TimestampMixin):
    """Per-position P&L snapshot recorded after each paper trading cycle."""

    __tablename__ = "position_history"
    __table_args__ = (
        sa.Index("ix_pos_hist_ticker_snapshot", "ticker", "snapshot_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticker: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False)
    quantity: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(20, 6), nullable=True)
    avg_entry_price: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(18, 6), nullable=True)
    current_price: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(18, 6), nullable=True)
    market_value: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(20, 4), nullable=True)
    cost_basis: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(20, 4), nullable=True)
    unrealized_pnl: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(20, 4), nullable=True)
    unrealized_pnl_pct: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(12, 6), nullable=True)


class RiskEvent(Base, TimestampMixin):
    """Captured risk breaches, warnings, and kill-switch activations."""

    __tablename__ = "risk_events"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_timestamp: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False)
    event_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    severity: Mapped[str] = mapped_column(sa.String, nullable=False)
    security_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("securities.id"), nullable=True
    )
    position_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("positions.id"), nullable=True
    )
    details_json: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime, nullable=True)
