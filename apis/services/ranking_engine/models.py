"""
Ranking engine domain models (plain dataclasses, no ORM dependency).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


@dataclass
class RankingConfig:
    """Weighting configuration for composite score assembly."""
    # Weights for aggregating sub-scores (must sum to 1.0)
    signal_weight: float = 0.40
    confidence_weight: float = 0.20
    liquidity_weight: float = 0.20
    risk_penalty_weight: float = 0.20   # Higher risk ↓ composite score
    config_version: str = "ranking_v1"


@dataclass
class RankedResult:
    """A single ranked investment opportunity as returned by RankingEngineService.

    All Gate B requirements are embedded here:
    - thesis_summary: human-readable explanation (Gate B: outputs are explainable)
    - disconfirming_factors: contrarian considerations
    - source_reliability_tier: reliability tag on underlying data source
    - contains_rumor: True if any contributing signal was derived from unverified info
    """
    rank_position: int
    security_id: object                 # UUID
    ticker: str
    composite_score: Optional[Decimal]
    portfolio_fit_score: Optional[Decimal]
    recommended_action: str             # "buy", "watch", "avoid"
    target_horizon: str
    thesis_summary: str                 # Gate B: explainability
    disconfirming_factors: str          # Gate B: explainability
    sizing_hint_pct: Optional[Decimal]  # suggested position size as a pct of portfolio
    source_reliability_tier: str        # Gate B: source tag
    contains_rumor: bool                # Gate B: rumor separation
    as_of: dt.datetime = field(default_factory=dt.datetime.utcnow)
    contributing_signals: list[dict] = field(default_factory=list)

