"""Universe override persistence model.

Each row records an operator-directed add or remove override for a specific
ticker.  Active overrides (active=True, not expired) are consumed by
UniverseManagementService to produce the active_universe list.

Phase 48 — Dynamic Universe Management
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class UniverseOverride(Base, TimestampMixin):
    """One operator-directed universe override record.

    action values:
        "ADD"    — include this ticker even if not in UNIVERSE_TICKERS
        "REMOVE" — exclude this ticker from the active universe

    active=False means the override has been manually deactivated.
    expires_at=None means the override never expires automatically.
    """

    __tablename__ = "universe_overrides"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, nullable=False)

    ticker: Mapped[str] = mapped_column(sa.String(16), nullable=False)

    # "ADD" or "REMOVE"
    action: Mapped[str] = mapped_column(sa.String(8), nullable=False)

    reason: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)

    # Optional: the operator identity who created the override
    operator_id: Mapped[Optional[str]] = mapped_column(sa.String(128), nullable=True)

    # When True the override is currently active
    active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)

    # Optional expiry — NULL = no expiry
    expires_at: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        sa.CheckConstraint("action IN ('ADD', 'REMOVE')", name="ck_universe_override_action"),
        sa.Index("ix_universe_override_ticker",  "ticker"),
        sa.Index("ix_universe_override_active",  "active"),
        sa.Index("ix_universe_override_action",  "action"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<UniverseOverride ticker={self.ticker!r} action={self.action!r} "
            f"active={self.active} expires_at={self.expires_at}>"
        )
