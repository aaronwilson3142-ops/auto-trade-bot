"""
SentimentStrategy — signal family: news / sentiment.

Computes a directional signal from pre-scored news sentiment attached to
the security.  Scores come from the pre-populated
``FeatureSet.sentiment_score`` and ``FeatureSet.sentiment_confidence``
overlay fields (populated by the NewsIntelligenceService).

Design rules
------------
- base_score = clamp((sentiment_score + 1) / 2) maps the raw sentiment
  from [-1, +1] to [0, 1].  A score of +1 (all positive headlines) → 1.0;
  -1 (all negative) → 0.0; no news → 0.5 neutral.
- confidence_score = sentiment_confidence (already in [0, 1]).
  When confidence = 0 the signal is neutral regardless of sentiment_score,
  preventing random noise from driving trades.
- contains_rumor flag is determined by confidence < 0.3 AND non-zero
  sentiment:  low-confidence sentiment signals are treated as rumour-class
  until a verified news article corroborates them.
- risk_score and liquidity_score pass through baseline OHLCV features.
- Horizon: SWING — news-driven moves typically resolve in 1–10 days.

Gate B compliance:
  - explanation_dict["rationale"] is always populated
  - source_reliability_tier dynamically set ("primary_verified" when
    confidence ≥ 0.7, "secondary_verified" when ≥ 0.3, "unverified" below)
  - contains_rumor = True when confidence < 0.3 AND non-zero sentiment
"""
from __future__ import annotations

import logging
import math
from decimal import Decimal, InvalidOperation

from services.feature_store.models import FeatureSet
from services.signal_engine.models import (
    HorizonClassification,
    SignalOutput,
    SignalType,
)

logger = logging.getLogger(__name__)

STRATEGY_KEY = "sentiment_v1"
STRATEGY_FAMILY = "sentiment"
CONFIG_VERSION = "1.0"

# Confidence thresholds for reliability tier
_CONFIDENCE_HIGH = 0.70    # primary_verified
_CONFIDENCE_MED = 0.30     # secondary_verified
# Below _CONFIDENCE_MED → unverified / rumour-class


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _d(x: float | None) -> Decimal | None:
    if x is None:
        return None
    try:
        return Decimal(str(round(x, 6)))
    except InvalidOperation:
        return None


def _reliability_tier(confidence: float) -> str:
    if confidence >= _CONFIDENCE_HIGH:
        return "primary_verified"
    if confidence >= _CONFIDENCE_MED:
        return "secondary_verified"
    return "unverified"


class SentimentStrategy:
    """Generates sentiment signals from FeatureSet.sentiment_score/confidence.

    The strategy converts news-derived sentiment into a [0, 1] directional
    score, with confidence and reliability tier informed by the underlying
    news source quality.
    """

    STRATEGY_KEY: str = STRATEGY_KEY
    STRATEGY_FAMILY: str = STRATEGY_FAMILY
    CONFIG_VERSION: str = CONFIG_VERSION

    def score(self, feature_set: FeatureSet) -> SignalOutput:
        """Compute a sentiment signal for the security in *feature_set*.

        Returns a fully populated SignalOutput.  Scores are in [0.0, 1.0].
        A score of 0.5 is neutral (no news or zero-confidence sentiment).
        """
        raw_sentiment: float = getattr(feature_set, "sentiment_score", 0.0) or 0.0
        confidence: float = getattr(feature_set, "sentiment_confidence", 0.0) or 0.0

        # Map [-1, +1] sentiment → [0, 1] signal
        base_score = _clamp((raw_sentiment + 1.0) / 2.0)

        # No-news / zero-confidence → neutral
        if confidence == 0.0:
            signal_score = 0.5
            rationale = (
                f"{feature_set.ticker}: No news sentiment available or confidence is zero. "
                "Signal is neutral until news overlay provides a scored headline."
            )
        else:
            # Weight the score towards neutral when confidence is low
            # (linear interpolation between 0.5 and base_score by confidence)
            signal_score = _clamp(0.5 + (base_score - 0.5) * confidence)
            direction = (
                "positive" if raw_sentiment > 0.05
                else "negative" if raw_sentiment < -0.05
                else "neutral"
            )
            rationale = (
                f"{feature_set.ticker}: News sentiment is {direction} "
                f"(raw={raw_sentiment:+.2f}, confidence={confidence:.2f}). "
                f"Adjusted sentiment signal: {signal_score:.2f}."
            )

        # Determine reliability and rumour flag
        reliability = _reliability_tier(confidence)
        contains_rumor = bool(confidence < _CONFIDENCE_MED and abs(raw_sentiment) > 0.05)

        risk_score = self._compute_risk(feature_set)
        liquidity_score = self._compute_liquidity(feature_set)

        explanation: dict = {
            "signal_type": SignalType.SENTIMENT.value,
            "strategy_key": STRATEGY_KEY,
            "config_version": CONFIG_VERSION,
            "raw_sentiment_score": round(raw_sentiment, 4),
            "sentiment_confidence": round(confidence, 4),
            "base_score": round(base_score, 4),
            "raw_signal_score": round(signal_score, 4),
            "reliability_tier": reliability,
            "contains_rumor": contains_rumor,
            "confidence_basis": (
                f"news confidence={confidence:.2f}" if confidence > 0 else "no news data"
            ),
            "rationale": rationale,
            "source_reliability": f"{reliability} (news intelligence overlay)",
        }

        return SignalOutput(
            security_id=feature_set.security_id,
            ticker=feature_set.ticker,
            strategy_key=STRATEGY_KEY,
            signal_type=SignalType.SENTIMENT.value,
            signal_score=_d(signal_score),
            confidence_score=_d(confidence),
            risk_score=_d(risk_score),
            catalyst_score=None,
            liquidity_score=_d(liquidity_score),
            horizon_classification=HorizonClassification.SWING.value,
            explanation_dict=explanation,
            source_reliability_tier=reliability,
            contains_rumor=contains_rumor,
            as_of=feature_set.as_of_timestamp,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_risk(fs: FeatureSet) -> float:
        """Derive risk score from volatility_20d (0=low risk, 1=high risk)."""
        vol = fs.get("volatility_20d")
        if vol is None:
            return 0.5
        # Normalise: 0% vol → 0.0, 40%+ vol → 1.0 (annualised decimal)
        return _clamp(float(vol) * 2.5)

    @staticmethod
    def _compute_liquidity(fs: FeatureSet) -> float:
        """Derive liquidity score from avg dollar volume."""
        dv = fs.get("dollar_volume_20d")
        if dv is None:
            return 0.5
        raw = max(float(dv), 1e6)
        scaled = (math.log10(raw) - 6.0) / 4.0
        return _clamp(scaled)
