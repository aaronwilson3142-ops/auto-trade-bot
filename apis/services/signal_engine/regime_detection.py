"""
Market Regime Detection Service — signal_engine.regime_detection.

Classifies the current market environment into one of four regimes:
    BULL_TREND  — broad momentum positive; most signals scoring bullish
    BEAR_TREND  — broad momentum negative; most signals scoring bearish
    SIDEWAYS    — no clear directional bias; mixed signals
    HIGH_VOL    — extreme divergence in signal scores; high implied volatility

Detection Algorithm
-------------------
Inputs: a list of ranked-signal objects with a ``composite_score`` attribute
in [0.0, 1.0] (RankedResult or any duck-type with .composite_score).

1. Compute median composite score across the universe (momentum proxy).
2. Compute population standard deviation of composite scores (volatility proxy).
3. Priority order:
   a. HIGH_VOL  : std_dev  > HIGH_VOL_THRESHOLD (0.18)
   b. BULL_TREND: median   > BULL_THRESHOLD      (0.60)
   c. BEAR_TREND: median   < BEAR_THRESHOLD      (0.40)
   d. SIDEWAYS  : fallback

Regime-Adaptive Weights
-----------------------
Each regime has a predefined strategy weight vector that favours strategies
most likely to outperform in that environment:
    BULL_TREND  — momentum-heavy  (0.35 momentum, 0.20 theme, 0.20 sentiment)
    BEAR_TREND  — defensive       (0.35 macro_tailwind, 0.30 valuation)
    SIDEWAYS    — fundamentals    (0.35 valuation, 0.20 macro_tailwind)
    HIGH_VOL    — sentiment-led   (0.30 sentiment, 0.30 macro_tailwind)

The job (run_regime_detection at 06:20 ET) writes the adaptive weights to
``app_state.active_weight_profile`` so the 06:45 ranking cycle picks them up.
WeightOptimizerService (06:52) may further refine the profile from backtest data.

Manual Override
---------------
Operators can override the detected regime via POST /api/v1/signals/regime/override.
The override is stored in ``app_state.current_regime_result`` with
``is_manual_override=True`` and takes priority over automated detection until
cleared via DELETE /api/v1/signals/regime/override.

DB Persistence
--------------
Each detection (automated or override) is persisted to the ``regime_snapshots``
table as a fire-and-forget write.  Exceptions are caught and logged; this
method never raises so the detection result is always returned to callers.
"""
from __future__ import annotations

import datetime as dt
import statistics
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Regime enum
# ---------------------------------------------------------------------------

class MarketRegime(str, Enum):
    """Four mutually-exclusive market environment classifications."""

    BULL_TREND = "BULL_TREND"
    BEAR_TREND = "BEAR_TREND"
    SIDEWAYS   = "SIDEWAYS"
    HIGH_VOL   = "HIGH_VOL"


# ---------------------------------------------------------------------------
# Regime-adaptive default strategy weights
# ---------------------------------------------------------------------------

REGIME_DEFAULT_WEIGHTS: dict[MarketRegime, dict[str, float]] = {
    MarketRegime.BULL_TREND: {
        "momentum_v1":        0.35,
        "theme_alignment_v1": 0.20,
        "macro_tailwind_v1":  0.15,
        "sentiment_v1":       0.20,
        "valuation_v1":       0.10,
    },
    MarketRegime.BEAR_TREND: {
        "momentum_v1":        0.10,
        "theme_alignment_v1": 0.10,
        "macro_tailwind_v1":  0.35,
        "sentiment_v1":       0.15,
        "valuation_v1":       0.30,
    },
    MarketRegime.SIDEWAYS: {
        "momentum_v1":        0.15,
        "theme_alignment_v1": 0.15,
        "macro_tailwind_v1":  0.20,
        "sentiment_v1":       0.15,
        "valuation_v1":       0.35,
    },
    MarketRegime.HIGH_VOL: {
        "momentum_v1":        0.10,
        "theme_alignment_v1": 0.10,
        "macro_tailwind_v1":  0.30,
        "sentiment_v1":       0.30,
        "valuation_v1":       0.20,
    },
}


# ---------------------------------------------------------------------------
# RegimeResult dataclass
# ---------------------------------------------------------------------------

@dataclass
class RegimeResult:
    """Output of a single regime detection run."""

    regime: MarketRegime
    confidence: float           # [0.0, 1.0]
    detection_basis: dict       # signals / thresholds that drove the decision
    is_manual_override: bool = False
    override_reason: str | None = None
    detected_at: dt.datetime = field(
        default_factory=lambda: dt.datetime.now(dt.UTC)
    )


# ---------------------------------------------------------------------------
# RegimeDetectionService
# ---------------------------------------------------------------------------

class RegimeDetectionService:
    """Classifies the current market regime from universe ranking signals.

    Core method: ``detect_from_signals(signals)`` where each element exposes
    a ``composite_score`` float attribute in [0.0, 1.0].  A manual override
    held in-memory takes priority over all automated detection until cleared.

    Detection thresholds
    --------------------
    HIGH_VOL_THRESHOLD = 0.18  — population std-dev of composite scores
    BULL_THRESHOLD     = 0.60  — median composite score
    BEAR_THRESHOLD     = 0.40  — median composite score

    DB persistence (``persist_snapshot``) is fire-and-forget; exceptions are
    caught and logged so detection results are always returned to callers.
    """

    HIGH_VOL_THRESHOLD: float = 0.18
    BULL_THRESHOLD:     float = 0.60
    BEAR_THRESHOLD:     float = 0.40

    def __init__(self, session_factory: Callable | None = None) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # Core detection
    # ------------------------------------------------------------------

    def detect_from_signals(self, signals: list[Any]) -> RegimeResult:
        """Classify market regime from ranked-signal objects.

        Args:
            signals: Objects with a ``composite_score`` float attribute.
                     Empty list → SIDEWAYS with 0.0 confidence.

        Returns:
            RegimeResult with regime, confidence, and detection_basis.
        """
        scores: list[float] = []
        for s in signals:
            try:
                v = getattr(s, "composite_score", None)
                if v is not None:
                    scores.append(float(v))
            except (TypeError, ValueError):
                pass

        if not scores:
            return RegimeResult(
                regime=MarketRegime.SIDEWAYS,
                confidence=0.0,
                detection_basis={
                    "reason": "no signal data available",
                    "universe_size": 0,
                },
            )

        median_score = statistics.median(scores)
        std_dev      = statistics.pstdev(scores) if len(scores) > 1 else 0.0

        basis: dict[str, Any] = {
            "universe_size":           len(scores),
            "median_composite_score":  round(median_score, 4),
            "std_dev_composite_score": round(std_dev, 4),
            "high_vol_threshold":      self.HIGH_VOL_THRESHOLD,
            "bull_threshold":          self.BULL_THRESHOLD,
            "bear_threshold":          self.BEAR_THRESHOLD,
        }

        # Detection hierarchy: HIGH_VOL → BULL_TREND → BEAR_TREND → SIDEWAYS
        if std_dev > self.HIGH_VOL_THRESHOLD:
            confidence = min(
                1.0,
                (std_dev - self.HIGH_VOL_THRESHOLD) / self.HIGH_VOL_THRESHOLD,
            )
            return RegimeResult(
                regime=MarketRegime.HIGH_VOL,
                confidence=round(confidence, 4),
                detection_basis={**basis, "trigger": "std_dev > high_vol_threshold"},
            )

        if median_score > self.BULL_THRESHOLD:
            confidence = min(1.0, (median_score - self.BULL_THRESHOLD) / 0.20)
            return RegimeResult(
                regime=MarketRegime.BULL_TREND,
                confidence=round(confidence, 4),
                detection_basis={**basis, "trigger": "median_composite > bull_threshold"},
            )

        if median_score < self.BEAR_THRESHOLD:
            confidence = min(1.0, (self.BEAR_THRESHOLD - median_score) / 0.20)
            return RegimeResult(
                regime=MarketRegime.BEAR_TREND,
                confidence=round(confidence, 4),
                detection_basis={**basis, "trigger": "median_composite < bear_threshold"},
            )

        # SIDEWAYS fallback — signals in neutral band
        return RegimeResult(
            regime=MarketRegime.SIDEWAYS,
            confidence=0.5,
            detection_basis={**basis, "trigger": "median_composite in neutral band"},
        )

    # ------------------------------------------------------------------
    # Regime-adaptive weight profile helper
    # ------------------------------------------------------------------

    def get_regime_weights(self, regime: MarketRegime) -> dict[str, float]:
        """Return a copy of the default strategy weights for *regime*."""
        return dict(REGIME_DEFAULT_WEIGHTS[regime])

    # ------------------------------------------------------------------
    # Manual override
    # ------------------------------------------------------------------

    def set_manual_override(self, regime: MarketRegime, reason: str) -> RegimeResult:
        """Produce a manual-override RegimeResult (does not mutate service state).

        The caller must store the returned result in ``app_state.current_regime_result``
        so it is visible to subsequent cycles.
        """
        result = RegimeResult(
            regime=regime,
            confidence=1.0,
            detection_basis={"trigger": "manual_override", "reason": reason},
            is_manual_override=True,
            override_reason=reason,
        )
        logger.info("regime_manual_override_set", regime=regime.value, reason=reason)
        return result

    # ------------------------------------------------------------------
    # DB persistence (fire-and-forget)
    # ------------------------------------------------------------------

    def persist_snapshot(
        self,
        result: RegimeResult,
        session_factory: Callable | None = None,
    ) -> None:
        """Persist *result* to the ``regime_snapshots`` table.

        Fire-and-forget: all exceptions are caught and logged; this method
        never raises so callers are never blocked.
        """
        sf = session_factory or self._session_factory
        if sf is None:
            return
        try:
            import json

            from infra.db.models.regime_detection import RegimeSnapshot

            with sf() as session:
                snapshot = RegimeSnapshot(
                    id=str(uuid.uuid4()),
                    regime=result.regime.value,
                    confidence=result.confidence,
                    detection_basis_json=json.dumps(result.detection_basis),
                    is_manual_override=result.is_manual_override,
                    override_reason=result.override_reason,
                )
                session.add(snapshot)
                session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("regime_snapshot_persist_failed", error=str(exc))
