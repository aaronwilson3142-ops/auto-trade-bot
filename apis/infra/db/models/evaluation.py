"""Evaluation models: evaluation_runs, evaluation_metrics, performance_attribution."""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
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
    evaluation_period_start: Mapped[dt.date | None] = mapped_column(sa.Date, nullable=True)
    evaluation_period_end: Mapped[dt.date | None] = mapped_column(sa.Date, nullable=True)
    mode: Mapped[str] = mapped_column(sa.String, nullable=False)
    status: Mapped[str] = mapped_column(sa.String, nullable=False)
    benchmark_set: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    # Deep-Dive Step 2 Rec 4 — idempotency key for fire-and-forget writers
    # (column + unique constraint added in alembic migration k1l2m3n4o5p6).
    # Format: "{run_date}:{mode}:evaluation_run".
    idempotency_key: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)


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
    metric_value: Mapped[Decimal | None] = mapped_column(sa.Numeric(20, 8), nullable=True)
    metric_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


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
    attribution_value: Mapped[Decimal | None] = mapped_column(sa.Numeric(20, 8), nullable=True)
    details_json: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
