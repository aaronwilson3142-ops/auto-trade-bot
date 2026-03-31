"""Market data models: daily_market_bars, security_liquidity_metrics."""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class DailyMarketBar(Base, TimestampMixin):
    """Daily OHLCV bar data per security."""

    __tablename__ = "daily_market_bars"
    __table_args__ = (
        sa.UniqueConstraint("security_id", "trade_date", name="uq_daily_bar_security_date"),
        sa.Index("ix_daily_bar_security_date", "security_id", "trade_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    security_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("securities.id"), nullable=False
    )
    trade_date: Mapped[dt.date] = mapped_column(sa.Date, nullable=False)
    open: Mapped[Decimal | None] = mapped_column(sa.Numeric(18, 6), nullable=True)
    high: Mapped[Decimal | None] = mapped_column(sa.Numeric(18, 6), nullable=True)
    low: Mapped[Decimal | None] = mapped_column(sa.Numeric(18, 6), nullable=True)
    close: Mapped[Decimal | None] = mapped_column(sa.Numeric(18, 6), nullable=True)
    adjusted_close: Mapped[Decimal | None] = mapped_column(sa.Numeric(18, 6), nullable=True)
    volume: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    vwap: Mapped[Decimal | None] = mapped_column(sa.Numeric(18, 6), nullable=True)


class SecurityLiquidityMetric(Base, TimestampMixin):
    """Derived daily liquidity statistics per security."""

    __tablename__ = "security_liquidity_metrics"
    __table_args__ = (
        sa.UniqueConstraint("security_id", "metric_date", name="uq_liquidity_security_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    security_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("securities.id"), nullable=False
    )
    metric_date: Mapped[dt.date] = mapped_column(sa.Date, nullable=False)
    avg_dollar_volume_20d: Mapped[Decimal | None] = mapped_column(sa.Numeric(18, 6), nullable=True)
    avg_share_volume_20d: Mapped[Decimal | None] = mapped_column(sa.Numeric(18, 6), nullable=True)
    atr_14: Mapped[Decimal | None] = mapped_column(sa.Numeric(18, 6), nullable=True)
    volatility_20d: Mapped[Decimal | None] = mapped_column(sa.Numeric(18, 6), nullable=True)
    float_shares: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    market_cap: Mapped[Decimal | None] = mapped_column(sa.Numeric(20, 2), nullable=True)
