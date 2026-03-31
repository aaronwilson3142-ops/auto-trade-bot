"""Signal and ranking models: strategies, signal_runs, security_signals,
ranking_runs, ranked_opportunities."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class Strategy(Base, TimestampMixin):
    """Registry of strategy families and configurations."""

    __tablename__ = "strategies"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    strategy_key: Mapped[str] = mapped_column(sa.String, unique=True, nullable=False)
    strategy_name: Mapped[str] = mapped_column(sa.String, nullable=False)
    strategy_family: Mapped[str] = mapped_column(sa.String, nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    config_version: Mapped[Optional[str]] = mapped_column(sa.String, nullable=True)


class SignalRun(Base, TimestampMixin):
    """Top-level record of a signal-generation run."""

    __tablename__ = "signal_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_timestamp: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False)
    run_mode: Mapped[str] = mapped_column(sa.String, nullable=False)
    universe_name: Mapped[Optional[str]] = mapped_column(sa.String, nullable=True)
    config_version: Mapped[Optional[str]] = mapped_column(sa.String, nullable=True)
    status: Mapped[str] = mapped_column(sa.String, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)


class SecuritySignal(Base, TimestampMixin):
    """Signal output per security for a given signal run and strategy."""

    __tablename__ = "security_signals"
    __table_args__ = (
        sa.Index("ix_signal_run_security", "signal_run_id", "security_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    signal_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("signal_runs.id"), nullable=False
    )
    security_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("securities.id"), nullable=False
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("strategies.id"), nullable=False
    )
    signal_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    signal_score: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(12, 6), nullable=True)
    confidence_score: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(12, 6), nullable=True)
    risk_score: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(12, 6), nullable=True)
    catalyst_score: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(12, 6), nullable=True)
    liquidity_score: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(12, 6), nullable=True)
    horizon_classification: Mapped[Optional[str]] = mapped_column(sa.String, nullable=True)
    explanation_json: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)


class RankingRun(Base, TimestampMixin):
    """Top-level record for a final portfolio ranking pass."""

    __tablename__ = "ranking_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    signal_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("signal_runs.id"), nullable=False
    )
    run_timestamp: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False)
    config_version: Mapped[Optional[str]] = mapped_column(sa.String, nullable=True)
    status: Mapped[str] = mapped_column(sa.String, nullable=False)


class RankedOpportunity(Base, TimestampMixin):
    """Final ranked and annotated investment opportunity."""

    __tablename__ = "ranked_opportunities"
    __table_args__ = (
        sa.Index("ix_ranked_opp_run_rank", "ranking_run_id", "rank_position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ranking_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("ranking_runs.id"), nullable=False
    )
    security_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("securities.id"), nullable=False
    )
    rank_position: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    composite_score: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(12, 6), nullable=True)
    portfolio_fit_score: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(12, 6), nullable=True)
    recommended_action: Mapped[str] = mapped_column(sa.String, nullable=False)
    target_horizon: Mapped[Optional[str]] = mapped_column(sa.String, nullable=True)
    thesis_summary: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    disconfirming_factors: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    sizing_hint_pct: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(8, 4), nullable=True)
