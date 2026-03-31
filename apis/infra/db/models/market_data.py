"""Market data models: daily_market_bars, security_liquidity_metrics."""
from __future__ import annotations

import uuid
import datetime as dt
from decimal import Decimal
from typing import Optional

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
    open: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(18, 6), nullable=True)
    high: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(18, 6), nullable=True)
    low: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(18, 6), nullable=True)
    close: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(18, 6), nullable=True)
    adjusted_close: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(18, 6), nullable=True)
    volume: Mapped[Optional[int]] = mapped_column(sa.BigInteger, nullable=True)
    vwap: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(18, 6), nullable=True)


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
    avg_dollar_volume_20d: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(18, 6), nullable=True)
    avg_share_volume_20d: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(18, 6), nullable=True)
    atr_14: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(18, 6), nullable=True)
    volatility_20d: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(18, 6), nullable=True)
    float_shares: Mapped[Optional[int]] = mapped_column(sa.BigInteger, nullable=True)
    market_cap: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(20, 2), nullable=True)
