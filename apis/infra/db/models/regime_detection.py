"""Market regime snapshot persistence model.

Each row records one regime classification event — either automated (from
universe signal analysis) or a manual operator override.  The most recent
row by ``created_at`` represents the current active regime.

Phase 38 — Market Regime Detection + Regime-Adaptive Weight Profiles
"""
from __future__ import annotations

from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class RegimeSnapshot(Base, TimestampMixin):
    """One market-regime classification event."""

    __tablename__ = "regime_snapshots"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    # MarketRegime value: BULL_TREND | BEAR_TREND | SIDEWAYS | HIGH_VOL
    regime: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(sa.Float, nullable=False)
    # JSON: universe metrics and thresholds that drove the classification
    detection_basis_json: Mapped[str] = mapped_column(
        sa.Text, nullable=False, default="{}", server_default="{}"
    )
    is_manual_override: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    override_reason: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)

    __table_args__ = (
        sa.Index("ix_regime_snapshot_regime",     "regime"),
        sa.Index("ix_regime_snapshot_created_at", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<RegimeSnapshot id={self.id} regime={self.regime!r} "
            f"confidence={self.confidence:.3f} override={self.is_manual_override}>"
        )
