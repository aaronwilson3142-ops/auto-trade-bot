"""macro_policy_engine domain models."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum


class PolicyEventType(str, Enum):
    TARIFF = "tariff"
    SANCTION = "sanction"
    REGULATION = "regulation"
    INTEREST_RATE = "interest_rate"
    FISCAL_POLICY = "fiscal_policy"
    GEOPOLITICAL = "geopolitical"
    ELECTION = "election"
    OTHER = "other"


class MacroRegime(str, Enum):
    RISK_ON = "risk_on"
    RISK_OFF = "risk_off"
    NEUTRAL = "neutral"
    STAGFLATION = "stagflation"
    REFLATION = "reflation"


@dataclass
class PolicyEvent:
    """A single macro/policy development."""
    event_id: str
    headline: str
    event_type: PolicyEventType
    published_at: dt.datetime
    source: str = ""
    body_snippet: str = ""


@dataclass
class PolicySignal:
    """Structured implication of a PolicyEvent for a sector or theme."""
    event: PolicyEvent
    affected_sectors: list[str] = field(default_factory=list)
    affected_themes: list[str] = field(default_factory=list)
    affected_tickers: list[str] = field(default_factory=list)
    directional_bias: float = 0.0         # [-1.0 bearish, 1.0 bullish]
    confidence: float = 0.5               # [0.0, 1.0]
    implication_summary: str = ""
    generated_at: dt.datetime | None = None


@dataclass
class MacroRegimeIndicator:
    """Current assessed macro regime and supporting detail."""
    regime: MacroRegime = MacroRegime.NEUTRAL
    confidence: float = 0.5
    supporting_factors: list[str] = field(default_factory=list)
    assessed_at: dt.datetime | None = None
