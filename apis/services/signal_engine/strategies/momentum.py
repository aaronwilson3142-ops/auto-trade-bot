"""
MomentumStrategy — signal family: momentum/trend.

Computes a directional momentum signal from the baseline feature set.
All sub-scores are explained so the ranking engine can render a human-readable
thesis.

Gate B compliance:
  - explanation_dict["rationale"] is always populated
  - source_reliability_tier is always tagged
  - contains_rumor is always False for this strategy (OHLCV only)
"""
from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal, InvalidOperation
from typing import Optional

from services.feature_store.models import FeatureSet
from services.signal_engine.models import (
    HorizonClassification,
    SignalOutput,
    SignalType,
)

logger = logging.getLogger(__name__)

STRATEGY_KEY = "momentum_v1"
STRATEGY_FAMILY = "momentum"
CONFIG_VERSION = "1.0"

# Feature weights for composite momentum score
_WEIGHTS: dict[str, float] = {
    "return_1m": 0.30,
    "return_3m": 0.35,
    "return_6m": 0.20,
    "sma_cross_signal": 0.15,
}

# Reasonable normalisation ranges for each momentum feature
_NORM_RANGES: dict[str, tuple[float, float]] = {
    "return_1m": (-0.20, 0.20),    # -20% to +20% → 0-1
    "return_3m": (-0.30, 0.30),
    "return_6m": (-0.50, 0.50),
    "sma_cross_signal": (-1.0, 1.0),
}


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _normalise(value: float, lo: float, hi: float) -> float:
    """Map value from [lo, hi] to [0, 1]."""
    if hi == lo:
        return 0.5
    return _clamp((value - lo) / (hi - lo))


def _d(x: Optional[float]) -> Optional[Decimal]:
    if x is None:
        return None
    try:
        return Decimal(str(round(x, 6)))
    except InvalidOperation:
        return None


class MomentumStrategy:
    """Generates momentum/trend signals from pre-computed feature sets.

    Accepts a FeatureSet and returns a SignalOutput with all score dimensions
    populated and an explanation_dict containing the feature breakdown.
    """

    STRATEGY_KEY: str = STRATEGY_KEY
    STRATEGY_FAMILY: str = STRATEGY_FAMILY
    CONFIG_VERSION: str = CONFIG_VERSION

    def score(self, feature_set: FeatureSet) -> SignalOutput:
        """Compute a momentum signal for the security described by *feature_set*.

        Returns a fully populated SignalOutput.  All scores are in [0.0, 1.0].
        A score of 0.5 means neutral momentum; >0.5 is bullish, <0.5 bearish.
        """
        driver_features: dict[str, Optional[float]] = {}
        weighted_sum = 0.0
        total_weight = 0.0

        for feat_key, weight in _WEIGHTS.items():
            val = feature_set.get(feat_key)
            if val is None:
                driver_features[feat_key] = None
                continue
            raw = float(val)
            driver_features[feat_key] = raw
            lo, hi = _NORM_RANGES[feat_key]
            norm = _normalise(raw, lo, hi)
            weighted_sum += norm * weight
            total_weight += weight

        if total_weight == 0:
            signal_score = 0.5  # neutral — no data
            confidence = 0.0
        else:
            signal_score = weighted_sum / total_weight
            # Confidence scales with how many features were available
            confidence = total_weight / sum(_WEIGHTS.values())

        # ── Risk sub-score ──────────────────────────────────────────────────
        # High volatility ↑ risk_score; low ATR ↓ risk_score
        risk_score = self._compute_risk(feature_set)

        # ── Liquidity sub-score ─────────────────────────────────────────────
        liquidity_score = self._compute_liquidity(feature_set)

        # ── Horizon classification ──────────────────────────────────────────
        horizon = self._classify_horizon(feature_set)

        # ── Rationale ──────────────────────────────────────────────────────
        rationale = self._build_rationale(feature_set, signal_score, driver_features)

        explanation: dict[str, object] = {
            "signal_type": SignalType.MOMENTUM.value,
            "strategy_key": STRATEGY_KEY,
            "config_version": CONFIG_VERSION,
            "driver_features": driver_features,
            "raw_signal_score": round(signal_score, 4),
            "confidence_basis": f"{round(confidence * 100, 1)}% features available",
            "rationale": rationale,
            "source_reliability": "secondary_verified (yfinance EOD)",
            "contains_rumor": False,
        }

        return SignalOutput(
            security_id=feature_set.security_id,
            ticker=feature_set.ticker,
            strategy_key=STRATEGY_KEY,
            signal_type=SignalType.MOMENTUM.value,
            signal_score=_d(signal_score),
            confidence_score=_d(confidence),
            risk_score=_d(risk_score),
            catalyst_score=None,        # Momentum strategy has no catalyst model
            liquidity_score=_d(liquidity_score),
            horizon_classification=horizon,
            explanation_dict=explanation,
            source_reliability_tier="secondary_verified",
            contains_rumor=False,
            as_of=feature_set.as_of_timestamp,
        )

    # ------------------------------------------------------------------
    # Private sub-score helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_risk(fs: FeatureSet) -> float:
        """Derive risk score from volatility and ATR (0=low risk, 1=high risk)."""
        vol = fs.get("volatility_20d")
        if vol is None:
            return 0.5
        # Normalise: 0–100% annualised vol → 0–1
        return _clamp(float(vol) / 1.0)

    @staticmethod
    def _compute_liquidity(fs: FeatureSet) -> float:
        """Derive liquidity score from avg dollar volume (0=illiquid, 1=liquid).

        Scale: $1M ADV → ~0.0, $100M ADV → 0.5, $10B ADV → 1.0.
        Uses (log10(ADV) - 6) / 4 mapped on [1M, 10B] = [10^6, 10^10].
        """
        dv = fs.get("dollar_volume_20d")
        if dv is None:
            return 0.5
        import math
        raw = max(float(dv), 1e6)   # floor at $1M
        scaled = (math.log10(raw) - 6.0) / 4.0
        return _clamp(scaled)

    @staticmethod
    def _classify_horizon(fs: FeatureSet) -> str:
        """Classify expected holding horizon based on momentum profile."""
        r1m = fs.get("return_1m")
        r3m = fs.get("return_3m")
        sma_cross = fs.get("sma_cross_signal")

        if sma_cross and float(sma_cross) != 0.0:
            return HorizonClassification.POSITIONAL.value
        if r1m is not None and abs(float(r1m)) > 0.10:
            return HorizonClassification.SWING.value
        if r3m is not None and abs(float(r3m)) > 0.15:
            return HorizonClassification.POSITIONAL.value
        return HorizonClassification.POSITIONAL.value

    @staticmethod
    def _build_rationale(
        fs: FeatureSet,
        signal_score: float,
        driver_features: dict[str, Optional[float]],
    ) -> str:
        """Generate a one-sentence natural language rationale."""
        direction = "bullish" if signal_score > 0.55 else ("bearish" if signal_score < 0.45 else "neutral")
        r1m = driver_features.get("return_1m")
        r3m = driver_features.get("return_3m")
        parts = []
        if r1m is not None:
            parts.append(f"1m return {r1m:+.1%}")
        if r3m is not None:
            parts.append(f"3m return {r3m:+.1%}")
        feature_str = ", ".join(parts) if parts else "limited data"
        return (
            f"{fs.ticker} shows {direction} momentum (score={signal_score:.2f}) "
            f"driven by {feature_str}."
        )
