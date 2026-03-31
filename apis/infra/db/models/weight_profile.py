"""Strategy weight profile persistence model.

Each row stores a complete set of per-strategy weights derived either
from a backtest-comparison optimisation run or entered manually by the
operator.  At most one row has ``is_active=True`` at any time; the
ranking engine reads the active profile to blend strategy signal scores.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class WeightProfile(Base, TimestampMixin):
    """One set of per-strategy signal weights."""

    __tablename__ = "weight_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    profile_name: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    # "optimized" | "manual"
    source: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default="optimized", server_default="optimized"
    )
    # JSON: {"momentum_v1": 0.35, "theme_alignment_v1": 0.20, ...}
    weights_json: Mapped[str] = mapped_column(
        sa.Text, nullable=False, default="{}", server_default="{}"
    )
    # JSON: per-strategy Sharpe ratios used for optimisation (empty for manual)
    sharpe_metrics_json: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    # True for the single active profile (NULL-safe: default False)
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    # FK reference to backtest_runs.comparison_id (informational, no FK constraint)
    optimization_run_id: Mapped[Optional[str]] = mapped_column(sa.String(36), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)

    __table_args__ = (
        sa.Index("ix_weight_profile_is_active", "is_active"),
        sa.Index("ix_weight_profile_created_at", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<WeightProfile id={self.id} name={self.profile_name!r} "
            f"source={self.source!r} active={self.is_active}>"
        )
