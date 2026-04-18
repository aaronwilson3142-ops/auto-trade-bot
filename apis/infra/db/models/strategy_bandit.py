"""Thompson Strategy Bandit state — Deep-Dive Plan Step 8 Rec 12.

One row per ``strategy_family`` maintains the ``Beta(alpha, beta)`` posterior
that the bandit samples from to propose per-cycle ranking weights.  Updates
are driven by live closed-trade outcomes **regardless of the runtime flag**
(plan §8.6) — only the *application* of the sampled weights in the ranking
engine is gated by ``settings.strategy_bandit_enabled``.

Updating the posterior from live trades even when the flag is OFF means that
when the operator eventually flips the flag ON, the bandit already has 2–4
weeks of accumulated priors and can skip a cold-start discovery phase.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class StrategyBanditState(Base, TimestampMixin):
    """Per-strategy Beta posterior + rolling counters.

    ``alpha`` / ``beta`` parameterise a Beta(α, β) distribution; Thompson
    sampling draws ``w ~ Beta(α, β)`` on each ranking cycle and feeds the
    renormalised vector to the ranking engine as ``strategy_weights``.

    ``n_wins`` and ``n_losses`` are human-readable counters tracking how
    the posterior was accumulated; they duplicate the ``(alpha, beta)``
    pair up to the prior because ``alpha = prior_alpha + n_wins`` and
    ``beta = prior_beta + n_losses``.  Keeping them explicit means the
    dashboard and ops scripts can inspect sample sizes without having
    to back them out of the Beta parameters.

    ``last_sampled_weight`` caches the most recent Thompson draw so the
    service can reuse it between resampling windows (plan §8.4 — resample
    every ``strategy_bandit_resample_every_n_cycles`` cycles).
    """

    __tablename__ = "strategy_bandit_state"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    strategy_family: Mapped[str] = mapped_column(
        sa.String(64), nullable=False, unique=True, index=True
    )
    # Beta(alpha, beta) — posterior parameters.  Stored as Numeric for the
    # same reason the portfolio book is: floats wobble on replay.
    alpha: Mapped[Decimal] = mapped_column(
        sa.Numeric(14, 4),
        nullable=False,
        server_default=sa.text("1.0"),
    )
    beta: Mapped[Decimal] = mapped_column(
        sa.Numeric(14, 4),
        nullable=False,
        server_default=sa.text("1.0"),
    )
    n_wins: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    n_losses: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    # Most recent sampled weight (raw draw, before smoothing+floor/ceiling).
    # Nullable because freshly-inserted priors have never been sampled yet.
    last_sampled_weight: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(18, 16), nullable=True
    )
    last_sampled_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    # Cycle counter — the service increments this each time weights are
    # returned (whether sampled fresh or served from cache) so that the
    # "resample every N cycles" logic has a durable counter.
    cycles_since_resample: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<StrategyBanditState family={self.strategy_family!r} "
            f"alpha={self.alpha} beta={self.beta} "
            f"wins={self.n_wins} losses={self.n_losses}>"
        )
