"""
Signal engine domain models (plain dataclasses, no ORM dependency).

SignalOutput encapsulates every score dimension required by the ranking engine.
The explanation_dict field must be populated with a human-readable breakdown so
that Gate B's "outputs are explainable" criterion is met.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any


class HorizonClassification(str, Enum):
    """Expected holding horizon for this signal."""
    INTRADAY = "intraday"
    SWING = "swing"          # 1–10 days
    POSITIONAL = "positional"  # 10–60 days
    LONG_TERM = "long_term"  # 60+ days
    UNKNOWN = "unknown"


class SignalType(str, Enum):
    """Strategy family that produced this signal."""
    MOMENTUM = "momentum"
    VALUATION = "valuation"
    QUALITY = "quality"
    SENTIMENT = "sentiment"
    MACRO = "macro"
    COMPOSITE = "composite"
    THEME_ALIGNMENT = "theme_alignment"
    MACRO_TAILWIND = "macro_tailwind"
    INSIDER_FLOW = "insider_flow"  # Phase 57 — congressional / whale / unusual-options flow


@dataclass
class SignalOutput:
    """Full signal output for one security from one strategy run.

    All numeric scores are in [0.0, 1.0] unless documented otherwise.
    The explanation_dict must contain at minimum:
        - "signal_type": str
        - "driver_features": dict[str, float|None]  — features that drove the score
        - "rationale": str  — one-sentence English explanation
    """
    security_id: object             # UUID
    ticker: str
    strategy_key: str
    signal_type: str
    signal_score: Decimal | None       # directional strength 0–1
    confidence_score: Decimal | None   # confidence in signal quality 0–1
    risk_score: Decimal | None         # downside risk intensity 0–1
    catalyst_score: Decimal | None     # presence of near-term catalyst 0–1
    liquidity_score: Decimal | None    # liquidity quality 0–1
    horizon_classification: str = HorizonClassification.UNKNOWN.value
    explanation_dict: dict[str, Any] = field(default_factory=dict)
    source_reliability_tier: str = "secondary_verified"   # Gate B: source tagged
    contains_rumor: bool = False                          # Gate B: rumor flag
    as_of: dt.datetime = field(default_factory=dt.datetime.utcnow)

