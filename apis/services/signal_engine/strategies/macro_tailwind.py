"""
MacroTailwindStrategy — signal family: macro / policy sensitivity.

Computes a directional signal by measuring whether the current macro regime
is a tailwind or headwind for the security.  Scores come from the
pre-populated ``FeatureSet.macro_bias`` and ``FeatureSet.macro_regime``
overlay fields (populated by the MacroPolicyEngineService).

Design rules
------------
- base_score = clamp((macro_bias + 1) / 2) maps the directional bias
  from [-1, +1] to [0, 1].  A bias of +1.0 (fully bullish policy
  environment) → score 1.0; -1.0 → score 0.0; neutral → 0.5.
- Regime adjustment:
    RISK_ON    → +0.05 additive boost (risk assets benefit)
    RISK_OFF   → -0.05 penalty (risk assets de-rate)
    STAGFLATION→ -0.03 penalty (macro uncertainty)
    NEUTRAL    →  0.00 (no adjustment)
- confidence_score = abs(macro_bias) so a strong directional biasproduces
  high confidence.  A zero bias produces confidence = 0.0.
- When macro_bias = 0 and regime = "NEUTRAL", returns a neutral zero-
  confidence signal (score=0.5, confidence=0.0).
- risk_score and liquidity_score pass through baseline OHLCV features.
- Horizon: POSITIONAL — macro regimes typically last weeks to months.
- contains_rumor is always False (structured policy data, not chatter).

Gate B compliance:
  - explanation_dict["rationale"] is always populated
  - source_reliability_tier = "secondary_verified" (structured policy signals)
  - contains_rumor = False
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

STRATEGY_KEY = "macro_tailwind_v1"
STRATEGY_FAMILY = "macro_tailwind"
CONFIG_VERSION = "1.0"

# Regime → score adjustment
_REGIME_ADJUSTMENTS: dict[str, float] = {
    "RISK_ON": +0.05,
    "RISK_OFF": -0.05,
    "STAGFLATION": -0.03,
    "NEUTRAL": 0.00,
}


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _d(x: float | None) -> Decimal | None:
    if x is None:
        return None
    try:
        return Decimal(str(round(x, 6)))
    except InvalidOperation:
        return None


class MacroTailwindStrategy:
    """Generates macro-tailwind signals from FeatureSet.macro_bias/regime.

    The strategy converts the macro policy engine's directional bias into
    a [0, 1] signal score and adjusts for the prevailing macro regime.
    """

    STRATEGY_KEY: str = STRATEGY_KEY
    STRATEGY_FAMILY: str = STRATEGY_FAMILY
    CONFIG_VERSION: str = CONFIG_VERSION

    def score(self, feature_set: FeatureSet) -> SignalOutput:
        """Compute a macro-tailwind signal for the security in *feature_set*.

        Returns a fully populated SignalOutput.  Scores are in [0.0, 1.0].
        A score of 0.5 is neutral (no macro view or zero-bias neutral regime).
        """
        macro_bias: float = getattr(feature_set, "macro_bias", 0.0) or 0.0
        macro_regime: str = getattr(feature_set, "macro_regime", "NEUTRAL") or "NEUTRAL"

        # Base score: map [-1, +1] bias → [0, 1]
        base_score = _clamp((macro_bias + 1.0) / 2.0)

        # Regime adjustment
        adj = _REGIME_ADJUSTMENTS.get(macro_regime.upper(), 0.0)
        signal_score = _clamp(base_score + adj)

        # Confidence proportional to bias magnitude
        confidence = _clamp(abs(macro_bias))

        # When completely neutral → return neutral (no view)
        is_neutral = (macro_bias == 0.0 and macro_regime.upper() in {"NEUTRAL", ""})

        if is_neutral:
            rationale = (
                f"{feature_set.ticker}: Macro regime is NEUTRAL with zero directional bias. "
                "No macro tailwind or headwind currently identified."
            )
        else:
            direction = "bullish" if macro_bias > 0 else "bearish"
            rationale = (
                f"{feature_set.ticker}: Macro regime is {macro_regime} "
                f"with {direction} policy bias ({macro_bias:+.2f}). "
                f"Adjusted signal score: {signal_score:.2f}."
            )

        risk_score = self._compute_risk(feature_set)
        liquidity_score = self._compute_liquidity(feature_set)

        explanation: dict = {
            "signal_type": SignalType.MACRO_TAILWIND.value,
            "strategy_key": STRATEGY_KEY,
            "config_version": CONFIG_VERSION,
            "macro_bias_raw": round(macro_bias, 4),
            "macro_regime": macro_regime,
            "base_score": round(base_score, 4),
            "regime_adjustment": adj,
            "raw_signal_score": round(signal_score, 4),
            "confidence_basis": (
                f"abs(macro_bias)={abs(macro_bias):.2f}"
                if not is_neutral else "no macro view"
            ),
            "rationale": rationale,
            "source_reliability": "secondary_verified (structured policy signals)",
            "contains_rumor": False,
        }

        return SignalOutput(
            security_id=feature_set.security_id,
            ticker=feature_set.ticker,
            strategy_key=STRATEGY_KEY,
            signal_type=SignalType.MACRO_TAILWIND.value,
            signal_score=_d(signal_score),
            confidence_score=_d(confidence),
            risk_score=_d(risk_score),
            catalyst_score=None,
            liquidity_score=_d(liquidity_score),
            horizon_classification=HorizonClassification.POSITIONAL.value,
            explanation_dict=explanation,
            source_reliability_tier="secondary_verified",
            contains_rumor=False,
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
