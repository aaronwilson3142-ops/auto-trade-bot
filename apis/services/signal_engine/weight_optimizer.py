"""
WeightOptimizerService — derives per-strategy signal weights from backtest
comparison results and persists the result as a WeightProfile.

Algorithm
---------
For each individual strategy run in a backtest comparison (rows where
strategy_name != "all_strategies"):

  raw_weight = max(sharpe_ratio, 0.01)   # floor prevents zero/negative Sharpe
                                          # from dropping a strategy entirely

Weights are then normalised to sum to 1.0.

If fewer than 2 strategies have valid backtest rows, equal weights are
returned (safe fallback that never changes trading behaviour).

DB writes are fire-and-forget: exceptions are caught and logged; the
optimised weight dict is always returned so callers are never blocked.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from config.logging_config import get_logger

logger = get_logger(__name__)

# The 5 individual strategy keys recognised by the system.
# "all_strategies" is excluded from per-strategy weight derivation.
_INDIVIDUAL_STRATEGY_KEYS = {
    "momentum_v1",
    "theme_alignment_v1",
    "macro_tailwind_v1",
    "sentiment_v1",
    "valuation_v1",
}

_ALL_STRATEGIES_KEY = "all_strategies"


@dataclass
class WeightProfileRecord:
    """In-memory representation of a weight profile (ORM-free)."""

    id: str                         # UUID string
    profile_name: str
    source: str                     # "optimized" | "manual"
    weights: dict[str, float]       # strategy_key → normalised weight
    sharpe_metrics: dict[str, float]  # strategy_key → sharpe used
    is_active: bool
    optimization_run_id: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[Any] = None


class WeightOptimizerService:
    """Derives optimal strategy weights from BacktestRun rows.

    Args:
        session_factory: Callable returning a SQLAlchemy Session, or None
            when operating without a database (weights returned but not
            persisted).
    """

    def __init__(self, session_factory: Optional[Callable] = None) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimize_from_backtest(
        self,
        backtest_runs: list[Any],
        comparison_id: Optional[str] = None,
        profile_name: Optional[str] = None,
        set_active: bool = True,
    ) -> WeightProfileRecord:
        """Compute Sharpe-proportional weights from a list of BacktestRun objects.

        Args:
            backtest_runs:   BacktestRun ORM rows (or duck-typed objects with
                             strategy_name and sharpe_ratio attributes).
            comparison_id:   Backtest comparison_id used as provenance link.
            profile_name:    Human-readable name; defaults to auto-generated.
            set_active:      If True, deactivates all other profiles and marks
                             this one active in the DB.

        Returns:
            WeightProfileRecord with the computed weights.
        """
        weights, sharpe_metrics = self._compute_weights(backtest_runs)
        name = profile_name or self._auto_name(comparison_id)

        profile = WeightProfileRecord(
            id=str(uuid.uuid4()),
            profile_name=name,
            source="optimized",
            weights=weights,
            sharpe_metrics=sharpe_metrics,
            is_active=set_active,
            optimization_run_id=comparison_id,
        )

        self._persist_profile(profile, set_active=set_active)
        return profile

    def create_manual_profile(
        self,
        weights: dict[str, float],
        profile_name: str,
        set_active: bool = True,
        notes: Optional[str] = None,
    ) -> WeightProfileRecord:
        """Create a manually specified weight profile.

        Weights are normalised to sum to 1.0 before persisting.

        Args:
            weights:      Dict of strategy_key → weight (raw, un-normalised).
            profile_name: Human-readable name.
            set_active:   Mark this profile as active.
            notes:        Optional operator notes.

        Returns:
            WeightProfileRecord with normalised weights.
        """
        normalised = self._normalise(weights)
        profile = WeightProfileRecord(
            id=str(uuid.uuid4()),
            profile_name=profile_name,
            source="manual",
            weights=normalised,
            sharpe_metrics={},
            is_active=set_active,
            notes=notes,
        )
        self._persist_profile(profile, set_active=set_active)
        return profile

    def get_active_profile(self) -> Optional[WeightProfileRecord]:
        """Return the currently active WeightProfile from DB, or None."""
        if not self._session_factory:
            return None
        try:
            from infra.db.models import WeightProfile

            with self._session_factory() as session:
                row = (
                    session.query(WeightProfile)
                    .filter(WeightProfile.is_active.is_(True))
                    .order_by(WeightProfile.created_at.desc())
                    .first()
                )
                if row is None:
                    return None
                return self._row_to_record(row)
        except Exception as exc:  # noqa: BLE001
            logger.warning("weight_optimizer_get_active_failed", error=str(exc))
            return None

    def list_profiles(self, limit: int = 20) -> list[WeightProfileRecord]:
        """Return all weight profiles, newest first."""
        if not self._session_factory:
            return []
        try:
            from infra.db.models import WeightProfile

            with self._session_factory() as session:
                rows = (
                    session.query(WeightProfile)
                    .order_by(WeightProfile.created_at.desc())
                    .limit(limit)
                    .all()
                )
                return [self._row_to_record(r) for r in rows]
        except Exception as exc:  # noqa: BLE001
            logger.warning("weight_optimizer_list_failed", error=str(exc))
            return []

    def set_active_profile(self, profile_id: str) -> Optional[WeightProfileRecord]:
        """Set a specific profile as active, deactivating all others.

        Returns:
            The newly activated WeightProfileRecord, or None if not found.
        """
        if not self._session_factory:
            return None
        try:
            from infra.db.models import WeightProfile
            import sqlalchemy as sa

            with self._session_factory() as session:
                # Deactivate all
                session.execute(
                    sa.update(WeightProfile).values(is_active=False)
                )
                # Activate the target
                row = session.get(WeightProfile, uuid.UUID(profile_id))
                if row is None:
                    session.rollback()
                    return None
                row.is_active = True
                session.commit()
                session.refresh(row)
                return self._row_to_record(row)
        except Exception as exc:  # noqa: BLE001
            logger.warning("weight_optimizer_set_active_failed", error=str(exc))
            return None

    # ------------------------------------------------------------------
    # Class-level helpers (also usable without an instance)
    # ------------------------------------------------------------------

    @classmethod
    def equal_weights(cls) -> dict[str, float]:
        """Return equal weights across all 5 individual strategies."""
        w = 1.0 / len(_INDIVIDUAL_STRATEGY_KEYS)
        return {k: round(w, 6) for k in sorted(_INDIVIDUAL_STRATEGY_KEYS)}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_weights(
        self,
        backtest_runs: list[Any],
    ) -> tuple[dict[str, float], dict[str, float]]:
        """Extract Sharpe-proportional weights from backtest run objects.

        Returns:
            (weights dict, sharpe_metrics dict)  — both keyed by strategy_key.
        """
        sharpe_map: dict[str, float] = {}
        for run in backtest_runs:
            name = getattr(run, "strategy_name", None) or ""
            if name == _ALL_STRATEGIES_KEY or name not in _INDIVIDUAL_STRATEGY_KEYS:
                continue
            sharpe = getattr(run, "sharpe_ratio", None)
            if sharpe is not None:
                # Keep the best (most recent) run if duplicates exist
                sharpe_map[name] = float(sharpe)

        if len(sharpe_map) < 2:
            # Not enough data — fall back to equal weights
            logger.info(
                "weight_optimizer_insufficient_data",
                strategies_found=len(sharpe_map),
                fallback="equal_weights",
            )
            return self.equal_weights(), {}

        # Floor at 0.01 so negative/zero Sharpe strategies still contribute
        raw = {k: max(v, 0.01) for k, v in sharpe_map.items()}

        # Strategies in the system but missing from backtest data get floor weight
        for key in _INDIVIDUAL_STRATEGY_KEYS:
            raw.setdefault(key, 0.01)

        weights = self._normalise(raw)
        return weights, {k: round(sharpe_map.get(k, 0.0), 4) for k in weights}

    @staticmethod
    def _normalise(raw: dict[str, float]) -> dict[str, float]:
        """Normalise a dict of positive floats so values sum to 1.0."""
        total = sum(raw.values())
        if total <= 0:
            n = len(raw)
            return {k: round(1.0 / n, 6) for k in raw}
        return {k: round(v / total, 6) for k, v in raw.items()}

    def _persist_profile(
        self,
        profile: WeightProfileRecord,
        set_active: bool,
    ) -> None:
        """Fire-and-forget: write WeightProfile to DB.  Never raises."""
        if not self._session_factory:
            return
        try:
            from infra.db.models import WeightProfile
            import sqlalchemy as sa

            with self._session_factory() as session:
                if set_active:
                    # Deactivate existing active profiles
                    session.execute(
                        sa.update(WeightProfile).values(is_active=False)
                    )
                row = WeightProfile(
                    id=uuid.UUID(profile.id),
                    profile_name=profile.profile_name,
                    source=profile.source,
                    weights_json=json.dumps(profile.weights),
                    sharpe_metrics_json=json.dumps(profile.sharpe_metrics) if profile.sharpe_metrics else None,
                    is_active=profile.is_active,
                    optimization_run_id=profile.optimization_run_id,
                    notes=profile.notes,
                )
                session.add(row)
                session.commit()
                logger.info(
                    "weight_profile_persisted",
                    profile_id=profile.id,
                    name=profile.profile_name,
                    active=profile.is_active,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("weight_profile_persist_failed", error=str(exc))

    @staticmethod
    def _row_to_record(row: Any) -> WeightProfileRecord:
        """Convert a WeightProfile ORM row to a WeightProfileRecord."""
        try:
            weights = json.loads(row.weights_json or "{}")
        except (ValueError, TypeError):
            weights = {}
        try:
            sharpe = json.loads(row.sharpe_metrics_json or "{}")
        except (ValueError, TypeError):
            sharpe = {}
        return WeightProfileRecord(
            id=str(row.id),
            profile_name=row.profile_name,
            source=row.source,
            weights=weights,
            sharpe_metrics=sharpe,
            is_active=row.is_active,
            optimization_run_id=row.optimization_run_id,
            notes=row.notes,
            created_at=row.created_at,
        )

    @staticmethod
    def _auto_name(comparison_id: Optional[str]) -> str:
        """Generate a human-readable profile name."""
        suffix = f"run-{comparison_id[:8]}" if comparison_id else "auto"
        return f"Optimized weights ({suffix})"
