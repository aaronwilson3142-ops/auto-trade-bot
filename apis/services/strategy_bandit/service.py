"""Thompson Strategy Bandit service — Deep-Dive Plan Step 8 Rec 12.

The bandit keeps one Beta(α, β) posterior per ``strategy_family`` and uses
Thompson sampling to propose per-cycle ranking weights.  Every closed trade
updates the posterior — **always** — so that when the operator eventually
flips ``settings.strategy_bandit_enabled`` ON, the bandit already has a
warm start (plan §8.6).

Only the *application* of the sampled weights in the ranking engine is
flag-gated.  See ``apps/worker/jobs/paper_trading.py`` for the closed-trade
hook and ``services/ranking_engine/service.py`` for the (future) weight
source wiring.

The flow on a ranking cycle, when the flag is ON, is:

    1. Sample ``w_raw ~ Beta(α, β)`` for each known family (or reuse the
       cached draw if we are inside the resampling window).
    2. Smooth: ``w = λ · w_raw + (1 − λ) · equal_weight``.
    3. Clamp each weight into ``[min_weight, max_weight]``.
    4. Renormalise so the vector sums to 1.0.
    5. Return the map ``{ family: weight }``.

If the DB has no rows for any family the service upserts ``Beta(1, 1)``
priors on first sample — matching the migration's ``server_default``.
"""
from __future__ import annotations

import datetime as dt
import random
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from infra.db.models.strategy_bandit import StrategyBanditState

_log = structlog.get_logger(__name__)


# Canonical families the bandit starts with.  Any family seen in a closed
# trade that's not in this tuple is still tracked (upserted on update) —
# this is just the "operator's default universe" used when the ranking
# engine asks for weights before any closed trades have been recorded.
DEFAULT_STRATEGY_FAMILIES: tuple[str, ...] = (
    "momentum",
    "theme_alignment",
    "sentiment",
    "valuation",
    "insider_flow",
    "macro_tailwind",
)


@dataclass(frozen=True)
class BanditUpdateResult:
    """Return value of ``update_from_trade`` — useful for tests and logs."""

    strategy_family: str
    outcome: str  # "win" or "loss"
    new_alpha: float
    new_beta: float
    n_wins: int
    n_losses: int


@dataclass(frozen=True)
class BanditWeights:
    """A single map-like snapshot of sampled weights."""

    weights: dict[str, float]
    sampled_fresh: bool  # True if this call resampled, False if cached


class StrategyBanditService:
    """Manage Beta posteriors + Thompson sampling for strategy weights.

    A single instance is cheap: it holds a session reference plus runtime
    configuration (smoothing lambda, floor/ceiling, resample cadence).  In
    production the ranking engine will build one per cycle on the paper
    session; tests build one against an in-memory session stub.
    """

    # -- construction ---------------------------------------------------
    def __init__(
        self,
        db: Session,
        *,
        smoothing_lambda: float = 0.3,
        min_weight: float = 0.05,
        max_weight: float = 0.40,
        resample_every_n_cycles: int = 10,
        rng: random.Random | None = None,
    ) -> None:
        if not (0.0 <= smoothing_lambda <= 1.0):
            raise ValueError("smoothing_lambda must be in [0, 1]")
        if not (0.0 <= min_weight <= 1.0):
            raise ValueError("min_weight must be in [0, 1]")
        if not (0.0 <= max_weight <= 1.0):
            raise ValueError("max_weight must be in [0, 1]")
        if min_weight > max_weight:
            raise ValueError("min_weight cannot exceed max_weight")
        if resample_every_n_cycles < 1:
            raise ValueError("resample_every_n_cycles must be >= 1")
        self._db = db
        self._smoothing = float(smoothing_lambda)
        self._min = float(min_weight)
        self._max = float(max_weight)
        self._resample_n = int(resample_every_n_cycles)
        self._rng = rng or random.Random()

    # -- private helpers -----------------------------------------------
    def _get_or_create(self, family: str) -> StrategyBanditState:
        """Upsert idempotently.  Fresh rows get Beta(1, 1) priors."""
        row = self._db.execute(
            select(StrategyBanditState).where(
                StrategyBanditState.strategy_family == family
            )
        ).scalar_one_or_none()
        if row is None:
            row = StrategyBanditState(
                id=uuid.uuid4(),
                strategy_family=family,
                alpha=Decimal("1.0"),
                beta=Decimal("1.0"),
                n_wins=0,
                n_losses=0,
                cycles_since_resample=0,
            )
            self._db.add(row)
            self._db.flush()
            _log.info("strategy_bandit.create", family=family)
        return row

    # -- public API ----------------------------------------------------
    def update_from_trade(
        self,
        strategy_family: str,
        realized_pnl: float | Decimal,
        *,
        now: dt.datetime | None = None,
    ) -> BanditUpdateResult:
        """Update the posterior from one closed-trade outcome.

        Called from the paper-trading worker AFTER the trade is graded.
        Runs unconditionally — not gated on ``settings.strategy_bandit_enabled``
        per plan §8.6 — so flipping the flag ON later gets a warm start.

        A ``realized_pnl > 0`` closed trade is a "win" (α += 1); anything
        else (<=0 or zero) is a "loss" (β += 1).  The zero-PnL boundary is
        classified as loss so breakeven trades don't artificially boost
        the bandit's confidence in a strategy.
        """
        if not strategy_family:
            raise ValueError("strategy_family required")
        try:
            pnl = float(realized_pnl)
        except (TypeError, ValueError) as exc:  # noqa: BLE001
            raise ValueError(f"realized_pnl must be numeric, got {realized_pnl!r}") from exc

        row = self._get_or_create(strategy_family)
        if pnl > 0:
            row.alpha = (Decimal(str(row.alpha)) + Decimal("1.0"))
            row.n_wins = int(row.n_wins) + 1
            outcome = "win"
        else:
            row.beta = (Decimal(str(row.beta)) + Decimal("1.0"))
            row.n_losses = int(row.n_losses) + 1
            outcome = "loss"
        row.updated_at = now or dt.datetime.now(dt.UTC)
        self._db.flush()

        result = BanditUpdateResult(
            strategy_family=strategy_family,
            outcome=outcome,
            new_alpha=float(row.alpha),
            new_beta=float(row.beta),
            n_wins=int(row.n_wins),
            n_losses=int(row.n_losses),
        )
        _log.info(
            "strategy_bandit.update",
            family=strategy_family,
            outcome=outcome,
            pnl=pnl,
            alpha=result.new_alpha,
            beta=result.new_beta,
        )
        return result

    def sample_weights(
        self,
        families: Iterable[str] | None = None,
        *,
        force_resample: bool = False,
        now: dt.datetime | None = None,
    ) -> BanditWeights:
        """Return per-family weights summing to 1.0.

        When ``force_resample=False`` (the default) and every family still
        has at least one cached draw within the resampling window, the
        cached draws are reused.  The per-row ``cycles_since_resample``
        counter is incremented regardless.
        """
        now = now or dt.datetime.now(dt.UTC)
        # Distinguish None (use defaults) from [] (caller explicitly asked
        # for an empty weight map — honour that rather than silently falling
        # back to the default family list).
        if families is None:
            fams: tuple[str, ...] = DEFAULT_STRATEGY_FAMILIES
        else:
            fams = tuple(families)
        if not fams:
            return BanditWeights(weights={}, sampled_fresh=False)

        # Pull or create a row per family.
        rows = [self._get_or_create(f) for f in fams]

        # Decide whether to resample.  Resample if forced, if any row has
        # never been sampled, or if any row's counter says this call is the
        # N-th cycle since the last fresh draw.  The counter is incremented
        # AFTER a cached call, so the cached value here is the count of
        # cached reuses so far; resample triggers when reusing one more time
        # would exceed the window (counter + 1 >= N  ⇔  counter >= N - 1).
        any_fresh_needed = force_resample or any(
            r.last_sampled_weight is None
            or int(r.cycles_since_resample) >= self._resample_n - 1
            for r in rows
        )

        raw: dict[str, float] = {}
        if any_fresh_needed:
            for r in rows:
                w = self._rng.betavariate(float(r.alpha), float(r.beta))
                # Numerical safety: ``betavariate`` can return 0 or 1 at
                # extreme parameter values; clamp to open interval so we
                # never persist exactly 0 or 1 (which would divide badly).
                w = min(max(w, 1e-6), 1.0 - 1e-6)
                # Persist with enough decimal places to round-trip a float64
                # — the DB column is Numeric(18, 16) so reading back and
                # casting to float gives bit-for-bit identical weights.
                r.last_sampled_weight = Decimal(f"{w:.16f}")
                r.last_sampled_at = now
                r.cycles_since_resample = 0
                raw[r.strategy_family] = w
        else:
            for r in rows:
                raw[r.strategy_family] = float(r.last_sampled_weight or 0.5)
                r.cycles_since_resample = int(r.cycles_since_resample) + 1
        self._db.flush()

        # Smooth: w = λ · raw + (1 − λ) · equal_weight.
        n = len(rows)
        equal = 1.0 / n
        smoothed = {
            f: self._smoothing * w + (1.0 - self._smoothing) * equal
            for f, w in raw.items()
        }
        # Clamp each to [min, max].
        clamped = {
            f: min(max(w, self._min), self._max)
            for f, w in smoothed.items()
        }
        # Renormalise so the vector sums to 1.0.
        total = sum(clamped.values()) or 1.0
        final = {f: w / total for f, w in clamped.items()}

        return BanditWeights(weights=final, sampled_fresh=any_fresh_needed)

    def get_state(self, strategy_family: str) -> StrategyBanditState | None:
        """Read-only helper — returns the row if it exists, else None."""
        return self._db.execute(
            select(StrategyBanditState).where(
                StrategyBanditState.strategy_family == strategy_family
            )
        ).scalar_one_or_none()

    def list_all(self) -> list[StrategyBanditState]:
        return list(
            self._db.execute(
                select(StrategyBanditState).order_by(
                    StrategyBanditState.strategy_family
                )
            )
            .scalars()
            .all()
        )
