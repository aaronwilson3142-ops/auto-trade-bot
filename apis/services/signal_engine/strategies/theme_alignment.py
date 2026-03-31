"""
ThemeAlignmentStrategy — signal family: theme / sector exposure.

Computes a directional signal by measuring a security's thematic alignment
against the AI/tech growth themes in the APIS universe.  Scores come from
the pre-populated ``FeatureSet.theme_scores`` overlay field (a dict of
theme_name → float in [0, 1] sourced from the ThemeEngineService).

Design rules
------------
- signal_score = mean of all non-zero theme scores (already in [0, 1]).
  A ticker with strong AI/semiconductor alignment (e.g. NVDA, AMD) scores
  near 1.0; a ticker with no theme exposure scores 0.5 (neutral).
- confidence scales with coverage: min(1.0, n_themes_with_exposure / 3).
  One strong theme = moderate confidence; ≥3 themes = full confidence.
- risk_score and liquidity_score are passed through from the baseline
  OHLCV features (same helpers as MomentumStrategy).
- Horizon: POSITIONAL — thematic tailwinds are medium-term structural.
- contains_rumor is always False (curated static registry, no chatter).
- When theme_scores is empty, returns a neutral signal (score=0.5,
  confidence=0.0) so callers can always use the output safely.

Gate B compliance:
  - explanation_dict["rationale"] is always populated
  - source_reliability_tier = "secondary_verified" (curated registry)
  - contains_rumor = False
"""
from __future__ import annotations

import logging
import math
from decimal import Decimal, InvalidOperation
from typing import Optional

from services.feature_store.models import FeatureSet
from services.signal_engine.models import (
    HorizonClassification,
    SignalOutput,
    SignalType,
)

logger = logging.getLogger(__name__)

STRATEGY_KEY = "theme_alignment_v1"
STRATEGY_FAMILY = "theme_alignment"
CONFIG_VERSION = "1.0"

# Minimum theme score considered "non-zero" for coverage calculation
_MIN_THEME_SCORE = 0.05


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _d(x: Optional[float]) -> Optional[Decimal]:
    if x is None:
        return None
    try:
        return Decimal(str(round(x, 6)))
    except InvalidOperation:
        return None


class ThemeAlignmentStrategy:
    """Generates theme-alignment signals from FeatureSet.theme_scores.

    The strategy rewards tickers with high structural exposure to AI,
    semiconductors, data-centre infrastructure, and other APIS growth themes.
    """

    STRATEGY_KEY: str = STRATEGY_KEY
    STRATEGY_FAMILY: str = STRATEGY_FAMILY
    CONFIG_VERSION: str = CONFIG_VERSION

    def score(self, feature_set: FeatureSet) -> SignalOutput:
        """Compute a theme-alignment signal for the security in *feature_set*.

        Returns a fully populated SignalOutput.  Scores are in [0.0, 1.0].
        A score of 0.5 is neutral (no theme data or no theme exposure).
        """
        theme_scores: dict = feature_set.theme_scores or {}

        # Identify themes with meaningful exposure
        active_themes = {
            k: v for k, v in theme_scores.items()
            if isinstance(v, (int, float)) and v >= _MIN_THEME_SCORE
        }

        if not active_themes:
            signal_score = 0.5
            confidence = 0.0
            rationale = (
                f"{feature_set.ticker}: No theme-exposure data available. "
                "Signal is neutral until overlay pipeline provides theme scores."
            )
        else:
            mean_score = sum(active_themes.values()) / len(active_themes)
            signal_score = _clamp(mean_score)
            # Confidence: 1 strong theme → ~0.33, 3 themes → 1.0
            confidence = _clamp(len(active_themes) / 3.0)
            top_theme = max(active_themes, key=active_themes.get)  # type: ignore[arg-type]
            top_score = active_themes[top_theme]
            rationale = (
                f"{feature_set.ticker}: Thematic alignment score {signal_score:.2f} "
                f"across {len(active_themes)} theme(s). "
                f"Strongest theme: {top_theme.replace('_', ' ')} ({top_score:.2f}). "
                f"{'Bullish structural tailwind.' if signal_score > 0.5 else 'Limited thematic overlap.'}"
            )

        risk_score = self._compute_risk(feature_set)
        liquidity_score = self._compute_liquidity(feature_set)

        explanation: dict = {
            "signal_type": SignalType.THEME_ALIGNMENT.value,
            "strategy_key": STRATEGY_KEY,
            "config_version": CONFIG_VERSION,
            "active_themes": dict(list(active_themes.items())[:5]),  # top-5 for readability
            "theme_count": len(active_themes),
            "mean_theme_score": round(signal_score, 4),
            "raw_signal_score": round(signal_score, 4),
            "confidence_basis": (
                f"{len(active_themes)} theme(s) with score ≥ {_MIN_THEME_SCORE}"
                if active_themes else "no theme data"
            ),
            "rationale": rationale,
            "source_reliability": "secondary_verified (curated static registry)",
            "contains_rumor": False,
        }

        return SignalOutput(
            security_id=feature_set.security_id,
            ticker=feature_set.ticker,
            strategy_key=STRATEGY_KEY,
            signal_type=SignalType.THEME_ALIGNMENT.value,
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
    # Private helpers (mirrors MomentumStrategy helpers)
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_risk(fs: FeatureSet) -> float:
        """Derive risk score from volatility_20d."""
        vol = fs.get("volatility_20d")
        if vol is None:
            return 0.5
        return _clamp(float(vol) / 1.0)

    @staticmethod
    def _compute_liquidity(fs: FeatureSet) -> float:
        """Derive liquidity score from avg dollar volume."""
        dv = fs.get("dollar_volume_20d")
        if dv is None:
            return 0.5
        raw = max(float(dv), 1e6)
        scaled = (math.log10(raw) - 6.0) / 4.0
        return _clamp(scaled)
