"""
Feature-store domain models (plain dataclasses, no ORM dependency).

These are the internal transport objects produced by the pipeline and consumed
by the signal engine.  They are version-tagged so the signal engine can trace
which pipeline version produced each feature.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


# ---------------------------------------------------------------------------
# Feature registry constants
# Each key must match the feature_key column in the `features` ORM table.
# ---------------------------------------------------------------------------
FEATURE_KEYS: list[str] = [
    "return_1m",
    "return_3m",
    "return_6m",
    "volatility_20d",
    "atr_14",
    "dollar_volume_20d",
    "sma_20",
    "sma_50",
    "sma_cross_signal",  # 1.0 = golden cross, -1.0 = death cross, 0.0 = neutral
    "price_vs_sma20",    # (close - sma20) / sma20
    "price_vs_sma50",    # (close - sma50) / sma50
]

FEATURE_GROUP_MAP: dict[str, str] = {
    "return_1m": "momentum",
    "return_3m": "momentum",
    "return_6m": "momentum",
    "volatility_20d": "risk",
    "atr_14": "risk",
    "dollar_volume_20d": "liquidity",
    "sma_20": "trend",
    "sma_50": "trend",
    "sma_cross_signal": "trend",
    "price_vs_sma20": "trend",
    "price_vs_sma50": "trend",
}


@dataclass
class ComputedFeature:
    """A single computed feature value for one security at one point in time."""
    feature_key: str
    feature_group: str
    value: Optional[Decimal]
    as_of_timestamp: dt.datetime
    source_version: str = "baseline_v1"


@dataclass
class FeatureSet:
    """All features computed for a single security as of one timestamp."""
    security_id: object          # UUID from the ORM Security row
    ticker: str
    as_of_timestamp: dt.datetime
    features: list[ComputedFeature] = field(default_factory=list)
    source_version: str = "baseline_v1"

    # ── Optional overlay inputs populated by enrichment pipeline (not baseline) ──
    # Set before passing to multi-strategy signal generation when additional
    # context is available (theme engine, macro policy engine, news intelligence).
    theme_scores: dict = field(default_factory=dict)  # theme_name → score in [0, 1]
    macro_bias: float = 0.0                            # directional bias: -1 (bearish) to +1 (bullish)
    macro_regime: str = "NEUTRAL"                      # RISK_ON / RISK_OFF / STAGFLATION / NEUTRAL
    sentiment_score: float = 0.0                       # news sentiment: -1 (negative) to +1 (positive)
    sentiment_confidence: float = 0.0                  # news confidence in [0, 1]

    # ── Fundamentals overlay fields (populated by FundamentalsService) ────────
    # All None by default so callers can detect "no data" vs a genuine 0 value.
    pe_ratio: Optional[float] = None              # trailing 12-month P/E ratio
    forward_pe: Optional[float] = None            # forward P/E (consensus estimate)
    peg_ratio: Optional[float] = None             # price/earnings-to-growth ratio
    price_to_sales: Optional[float] = None        # trailing 12-month price/sales
    eps_growth: Optional[float] = None            # YoY EPS growth (0.15 = +15%)
    revenue_growth: Optional[float] = None        # YoY revenue growth (0.10 = +10%)
    earnings_surprise_pct: Optional[float] = None # latest quarterly EPS surprise %

    def get(self, feature_key: str) -> Optional[Decimal]:
        """Return the value for *feature_key*, or None if absent."""
        for f in self.features:
            if f.feature_key == feature_key:
                return f.value
        return None

