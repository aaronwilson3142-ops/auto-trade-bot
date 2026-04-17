"""
InsiderFlowStrategy — signal family: insider / smart-money flow.

Computes a directional signal from aggregated congressional disclosure
filings, 13F holdings changes, and unusual options flow attached to the
security.  Scores come from the pre-populated
``FeatureSet.insider_flow_score``, ``insider_flow_confidence``, and
``insider_flow_age_days`` overlay fields populated by the
InsiderFlowAdapter / enrichment pipeline.

This strategy is deliberately conservative:

- Congressional filings are lagged up to 45 days under the STOCK Act, so
  the signal MUST decay with age.  Default half-life is 14 days; any
  filing older than 60 days contributes zero signal.
- The raw score is in [-1, +1] (net buy/sell bias).  This is mapped to
  a [0, 1] directional signal with 0.5 = neutral.
- The reliability tier is always at most ``secondary_verified`` because
  insiders may trade for liquidity / tax reasons unrelated to alpha.
- The strategy never sets ``contains_rumor=True`` — SEC filings are
  verified public records, not rumour.  Unusual options flow, however,
  downgrades confidence.
- Horizon is POSITIONAL (10–60 days): congressional trades disclose slow
  and resolve over weeks, not intraday.

Phase 57 scaffold: the overlay fields default to 0.0 / 0.0 / None, so
without an InsiderFlowAdapter populating them the strategy always emits
a neutral 0.5 signal with zero confidence.  This is intentional —
nothing ships to ranking until the adapter is wired AND a walk-forward
backtest validates the edge.
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

STRATEGY_KEY = "insider_flow_v1"
STRATEGY_FAMILY = "insider_flow"
CONFIG_VERSION = "1.0"

# Decay parameters (half-life in days)
_HALF_LIFE_DAYS = 14.0
# Any filing older than this contributes zero signal regardless of raw score
_MAX_AGE_DAYS = 60.0
# Reliability tier thresholds
_CONFIDENCE_MED = 0.30  # below this → unverified tier


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _d(x: float | None) -> Decimal | None:
    if x is None:
        return None
    try:
        return Decimal(str(round(x, 6)))
    except InvalidOperation:
        return None


def _age_decay(age_days: float | None) -> float:
    """Exponential decay factor in [0, 1] given an age in days.

    age_days = None → 0.0 (no data → no signal)
    age_days >= _MAX_AGE_DAYS → 0.0 (too stale)
    age_days = 0  → 1.0 (fresh)
    Half-life = _HALF_LIFE_DAYS.
    """
    if age_days is None or age_days < 0 or age_days >= _MAX_AGE_DAYS:
        return 0.0
    return float(math.exp(-math.log(2.0) * age_days / _HALF_LIFE_DAYS))


class InsiderFlowStrategy:
    """Generates insider-flow signals from FeatureSet overlay fields.

    This is the Phase 57 scaffold: read-only over FeatureSet fields,
    stateless, no external calls, pure function.  Emits a neutral 0.5
    signal with zero confidence when no overlay data is present, so it
    is a no-op in production until the adapter + enrichment pipeline
    wire real data into the FeatureSet.
    """

    STRATEGY_KEY: str = STRATEGY_KEY
    STRATEGY_FAMILY: str = STRATEGY_FAMILY
    CONFIG_VERSION: str = CONFIG_VERSION

    def score(self, feature_set: FeatureSet) -> SignalOutput:
        """Compute an insider-flow signal for the security in *feature_set*."""
        raw_flow: float = getattr(feature_set, "insider_flow_score", 0.0) or 0.0
        raw_conf: float = getattr(feature_set, "insider_flow_confidence", 0.0) or 0.0
        age_days = getattr(feature_set, "insider_flow_age_days", None)

        decay = _age_decay(age_days)
        # Effective confidence is the product of raw confidence and age decay
        effective_conf = _clamp(raw_conf * decay)

        # Map [-1, +1] net flow to [0, 1] directional signal
        base_score = _clamp((raw_flow + 1.0) / 2.0)

        if effective_conf == 0.0:
            signal_score = 0.5
            rationale = (
                f"{feature_set.ticker}: No insider-flow data available "
                "(adapter not populated or signal fully decayed). Neutral."
            )
        else:
            # Blend towards neutral by effective confidence
            signal_score = _clamp(0.5 + (base_score - 0.5) * effective_conf)
            direction = (
                "net buying" if raw_flow > 0.05
                else "net selling" if raw_flow < -0.05
                else "balanced"
            )
            rationale = (
                f"{feature_set.ticker}: Smart-money flow is {direction} "
                f"(raw={raw_flow:+.2f}, raw_conf={raw_conf:.2f}, "
                f"age={age_days}d, decay={decay:.2f}). "
                f"Adjusted insider-flow signal: {signal_score:.2f}."
            )

        # Reliability tier: ALWAYS at most secondary_verified.  SEC filings
        # are public record but lagged, and insider motives are not always
        # alpha-driven, so we deliberately do not ship primary_verified.
        reliability = (
            "secondary_verified"
            if effective_conf >= _CONFIDENCE_MED
            else "unverified"
        )

        explanation: dict = {
            "signal_type": SignalType.INSIDER_FLOW.value,
            "strategy_key": STRATEGY_KEY,
            "config_version": CONFIG_VERSION,
            "raw_flow_score": round(raw_flow, 4),
            "raw_confidence": round(raw_conf, 4),
            "age_days": age_days,
            "age_decay_factor": round(decay, 4),
            "effective_confidence": round(effective_conf, 4),
            "base_score": round(base_score, 4),
            "raw_signal_score": round(signal_score, 4),
            "reliability_tier": reliability,
            "contains_rumor": False,  # filings are public record, not rumour
            "half_life_days": _HALF_LIFE_DAYS,
            "max_age_days": _MAX_AGE_DAYS,
            "rationale": rationale,
            "source_reliability": f"{reliability} (insider-flow overlay)",
        }

        return SignalOutput(
            security_id=feature_set.security_id,
            ticker=feature_set.ticker,
            strategy_key=STRATEGY_KEY,
            signal_type=SignalType.INSIDER_FLOW.value,
            signal_score=_d(signal_score),
            confidence_score=_d(effective_conf),
            risk_score=_d(self._compute_risk(feature_set)),
            catalyst_score=_d(effective_conf) if effective_conf > 0 else None,
            liquidity_score=_d(self._compute_liquidity(feature_set)),
            horizon_classification=HorizonClassification.POSITIONAL.value,
            explanation_dict=explanation,
            source_reliability_tier=reliability,
            contains_rumor=False,
            as_of=feature_set.as_of_timestamp,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_risk(fs: FeatureSet) -> float:
        vol = fs.get("volatility_20d")
        if vol is None:
            return 0.5
        # Normalise: 0% vol → 0.0, 40%+ vol → 1.0 (annualised decimal)
        return _clamp(float(vol) * 2.5)

    @staticmethod
    def _compute_liquidity(fs: FeatureSet) -> float:
        dv = fs.get("dollar_volume_20d")
        if dv is None:
            return 0.5
        raw = max(float(dv), 1e6)
        scaled = (math.log10(raw) - 6.0) / 4.0
        return _clamp(scaled)
