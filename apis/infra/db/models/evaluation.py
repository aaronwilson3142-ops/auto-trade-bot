"""Evaluation models: evaluation_runs, evaluation_metrics, performance_attribution."""
from __future__ import annotations

import uuid
import datetime as dt
from decimal import Decimal
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class EvaluationRun(Base, TimestampMixin):
    """Top-level daily or periodic grading record."""

    __tablename__ = "evaluation_runs"
    __table_args__ = (
        sa.Index("ix_eval_run_timestamp", "run_timestamp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_timestamp: Mapped[dt.datetime] = mapped_column(sa.DateTime, nullable=False)
    evaluation_period_start: Mapped[Optional[dt.date]] = mapped_column(sa.Date, nullable=True)
    evaluation_period_end: Mapped[Optional[dt.date]] = mapped_column(sa.Date, nullable=True)
    mode: Mapped[str] = mapped_column(sa.String, nullable=False)
    status: Mapped[str] = mapped_column(sa.String, nullable=False)
    benchmark_set: Mapped[Optional[str]] = mapped_column(sa.String, nullable=True)


class EvaluationMetric(Base, TimestampMixin):
    """Individual metric value stored for an evaluation run."""

    __tablename__ = "evaluation_metrics"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    evaluation_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("evaluation_runs.id"), nullable=False
    )
    metric_key: Mapped[str] = mapped_column(sa.String, nullable=False)
    metric_value: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(20, 8), nullable=True)
    metric_text: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)


class PerformanceAttribution(Base, TimestampMixin):
    """Attribution slice for a given evaluation run (sector, theme, strategy, etc.)."""

    __tablename__ = "performance_attribution"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    evaluation_run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("evaluation_runs.id"), nullable=False
    )
    attribution_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    attribution_key: Mapped[str] = mapped_column(sa.String, nullable=False)
    attribution_value: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(20, 8), nullable=True)
    details_json: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
