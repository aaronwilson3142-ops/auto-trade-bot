"""
ValuationStrategy — signal family: fundamentals / valuation.

Scores a security based on its fundamental valuation metrics:
  - Forward P/E ratio (lower is cheaper; priced-for-perfection = poor)
  - PEG ratio (< 1.0 = growth at a reasonable price; > 3.0 = overpriced)
  - EPS growth (higher is better; loss-deepening is penalised)
  - Earnings surprise % (positive surprise = analyst under-estimates)

All sub-scores are weighted and combined into a composite signal in [0, 1]:
  - 0.50 = neutral / no data
  - > 0.50 = valuation attractive relative to typical APIS universe
  - < 0.50 = valuation stretched or fundamentals deteriorating

When no fundamentals are present (all None), returns a neutral signal with
confidence=0.0 so the ranking engine can down-weight this strategy family.

Gate B compliance:
  - explanation_dict["rationale"] is always populated
  - source_reliability_tier = "secondary_verified" (yfinance consensus data)
  - contains_rumor = False (structured reported data only)

Spec references
---------------
- APIS_MASTER_SPEC.md § 8 (Signal and Scoring Framework — valuation family)
- APIS_MASTER_SPEC.md § 7.2 (Fundamentals data domain)
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from services.feature_store.models import FeatureSet
from services.signal_engine.models import (
    HorizonClassification,
    SignalOutput,
    SignalType,
)

logger = logging.getLogger(__name__)

STRATEGY_KEY = "valuation_v1"
STRATEGY_FAMILY = "valuation"
CONFIG_VERSION = "1.0"

# Sub-score weights (must sum to 1.0)
_WEIGHTS: dict[str, float] = {
    "forward_pe":          0.30,
    "peg_ratio":           0.25,
    "eps_growth":          0.30,
    "earnings_surprise":   0.15,
}

# Normalisation ranges: (best_value, worst_value) → maps to score 1.0, 0.0
_PE_BEST   = 5.0   # very cheap
_PE_WORST  = 50.0  # priced for perfection

_PEG_BEST  = 0.5   # GARP sweet spot
_PEG_WORST = 3.0   # overpriced relative to growth

_EPS_BEST  = 0.50  # +50% EPS growth → excellent
_EPS_WORST = -0.50 # -50% EPS growth → deteriorating

_SURP_BEST  = 0.10  # +10% beat → strong
_SURP_WORST = -0.10 # -10% miss → weak


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _normalise(value: float, best: float, worst: float) -> float:
    """Map value from [worst, best] to [0.0, 1.0].

    *best* → 1.0, *worst* → 0.0.  Values outside the range are clamped.
    """
    span = best - worst
    if span == 0:
        return 0.5
    return _clamp((value - worst) / span)


def _d(x: float | None) -> Decimal | None:
    if x is None:
        return None
    try:
        return Decimal(str(round(x, 6)))
    except InvalidOperation:
        return None


class ValuationStrategy:
    """Generates fundamental valuation signals from FeatureSet overlay fields.

    Reads ``pe_ratio``, ``forward_pe``, ``peg_ratio``, ``price_to_sales``,
    ``eps_growth``, ``revenue_growth``, and ``earnings_surprise_pct`` from
    the FeatureSet — all of which are populated by FundamentalsService before
    strategy scoring.

    When all fields are None the strategy returns a neutral signal (score=0.5,
    confidence=0.0) so it doesn't inadvertently bias the ranking engine.
    """

    STRATEGY_KEY: str = STRATEGY_KEY
    STRATEGY_FAMILY: str = STRATEGY_FAMILY
    CONFIG_VERSION: str = CONFIG_VERSION

    def score(self, feature_set: FeatureSet) -> SignalOutput:
        """Compute a valuation signal for the security in *feature_set*.

        Returns a fully populated SignalOutput.  Scores are in [0.0, 1.0].
        A score of 0.5 is neutral (no fundamentals data available).
        """
        ticker = feature_set.ticker

        # ── Sub-scores ────────────────────────────────────────────────────────
        sub_scores: dict[str, float | None] = {}

        # 1. Forward P/E
        fpe = feature_set.forward_pe
        if fpe is not None and fpe > 0:
            sub_scores["forward_pe"] = _normalise(fpe, best=_PE_BEST, worst=_PE_WORST)

        # 2. PEG ratio
        peg = feature_set.peg_ratio
        if peg is not None and peg > 0:
            sub_scores["peg_ratio"] = _normalise(peg, best=_PEG_BEST, worst=_PEG_WORST)

        # 3. EPS growth
        eps_g = feature_set.eps_growth
        if eps_g is not None:
            sub_scores["eps_growth"] = _normalise(eps_g, best=_EPS_BEST, worst=_EPS_WORST)

        # 4. Earnings surprise
        surp = feature_set.earnings_surprise_pct
        if surp is not None:
            sub_scores["earnings_surprise"] = _normalise(
                surp, best=_SURP_BEST, worst=_SURP_WORST
            )

        # ── Composite score ───────────────────────────────────────────────────
        available = {k: v for k, v in sub_scores.items() if v is not None}
        n_available = len(available)

        if n_available == 0:
            composite = 0.5
            confidence = 0.0
        else:
            # Weighted average over the sub-scores that are available;
            # re-normalise weights so they sum to 1.0 over available signals.
            total_weight = sum(_WEIGHTS[k] for k in available)
            composite = sum(
                _WEIGHTS[k] * v for k, v in available.items()
            ) / total_weight
            # Confidence scales with data coverage: all 4 signals → full confidence
            confidence = _clamp(n_available / len(_WEIGHTS))

        # ── Risk / liquidity pass-through from OHLCV features ─────────────────
        vol = feature_set.get("volatility_20d")
        risk_score = (
            _clamp(1.0 - float(vol) * 5)
            if vol is not None else 0.5
        )

        dv = feature_set.get("dollar_volume_20d")
        liquidity_score = (
            _clamp(float(dv) / 1e8)
            if dv is not None else 0.5
        )

        # ── Explanation ───────────────────────────────────────────────────────
        rationale_parts: list[str] = []
        if "forward_pe" in available:
            pe_score = available["forward_pe"]
            rationale_parts.append(
                f"fwd P/E={feature_set.forward_pe:.1f} "
                f"({'cheap' if pe_score > 0.6 else 'fair' if pe_score > 0.4 else 'expensive'})"
            )
        if "peg_ratio" in available:
            peg_score = available["peg_ratio"]
            rationale_parts.append(
                f"PEG={feature_set.peg_ratio:.2f} "
                f"({'attractive' if peg_score > 0.6 else 'rich' if peg_score < 0.4 else 'fair'})"
            )
        if "eps_growth" in available:
            g = feature_set.eps_growth
            rationale_parts.append(
                f"EPS growth={g:+.1%}" if g is not None else ""
            )
        if "earnings_surprise" in available:
            s = feature_set.earnings_surprise_pct
            rationale_parts.append(
                f"EPS surprise={s:+.1%}" if s is not None else ""
            )

        if not rationale_parts:
            rationale = f"{ticker}: no fundamentals data — neutral valuation signal"
        else:
            summary = "attractive" if composite > 0.6 else (
                "expensive" if composite < 0.4 else "fairly valued"
            )
            rationale = f"{ticker} appears {summary}. " + "; ".join(
                p for p in rationale_parts if p
            )

        explanation_dict = {
            "signal_type": STRATEGY_FAMILY,
            "driver_features": {
                "forward_pe":        feature_set.forward_pe,
                "peg_ratio":         feature_set.peg_ratio,
                "eps_growth":        feature_set.eps_growth,
                "earnings_surprise": feature_set.earnings_surprise_pct,
                "price_to_sales":    feature_set.price_to_sales,
            },
            "sub_scores": {k: round(v, 4) for k, v in available.items()},
            "n_available": n_available,
            "rationale": rationale,
        }

        return SignalOutput(
            security_id=feature_set.security_id,
            ticker=ticker,
            strategy_key=STRATEGY_KEY,
            signal_type=SignalType.VALUATION.value,
            signal_score=_d(composite),
            confidence_score=_d(confidence),
            risk_score=_d(risk_score),
            liquidity_score=_d(liquidity_score),
            catalyst_score=_d(0.5),
            horizon_classification=HorizonClassification.POSITIONAL.value,
            explanation_dict=explanation_dict,
            source_reliability_tier="secondary_verified",
            contains_rumor=False,
            as_of=feature_set.as_of_timestamp,
        )
