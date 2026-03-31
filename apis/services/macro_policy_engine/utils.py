"""macro_policy_engine rule-based utilities.

Keyword-driven directional bias assignment and sector/theme classification
for policy and macro events.  No external dependencies.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Directional keywords  — (word, direction) where direction = +1 or -1
# ---------------------------------------------------------------------------

_POSITIVE_POLICY_WORDS: frozenset[str] = frozenset({
    "stimulus", "cut", "cuts", "easing", "ease", "relief", "deregulation",
    "deregulate", "subsidy", "subsidies", "incentive", "investment",
    "infrastructure", "approve", "approved", "approval", "lift",
    "lifted", "lower", "lowered", "remove", "removed",
})

_NEGATIVE_POLICY_WORDS: frozenset[str] = frozenset({
    "tariff", "tariffs", "sanction", "sanctions", "hike", "raise",
    "tighten", "tightening", "regulation", "regulate", "ban", "blocked",
    "restrict", "restriction", "escalation", "escalate", "war",
    "conflict", "tension", "fine", "penalty", "probe",
    "investigation", "tax", "taxes",
})

# ---------------------------------------------------------------------------
# Event-type → sector/theme mappings
# ---------------------------------------------------------------------------

from services.macro_policy_engine.models import PolicyEventType

EVENT_TYPE_SECTORS: dict[str, list[str]] = {
    PolicyEventType.TARIFF.value: [
        "consumer_discretionary", "industrials", "technology",
    ],
    PolicyEventType.SANCTION.value: [
        "energy", "financials", "technology",
    ],
    PolicyEventType.INTEREST_RATE.value: [
        "financials", "technology", "utilities", "consumer_discretionary",
    ],
    PolicyEventType.FISCAL_POLICY.value: [
        "industrials", "consumer_discretionary", "financials",
    ],
    PolicyEventType.GEOPOLITICAL.value: [
        "energy", "industrials", "technology",
    ],
    PolicyEventType.REGULATION.value: [
        "technology", "financials", "healthcare",
    ],
    PolicyEventType.ELECTION.value: [
        "healthcare", "energy", "financials",
    ],
    PolicyEventType.OTHER.value: [],
}

EVENT_TYPE_THEMES: dict[str, list[str]] = {
    PolicyEventType.TARIFF.value: ["semiconductor", "networking"],
    PolicyEventType.SANCTION.value: ["semiconductor", "defence"],
    PolicyEventType.INTEREST_RATE.value: ["fintech", "cloud_computing"],
    PolicyEventType.FISCAL_POLICY.value: ["clean_energy", "power_infrastructure"],
    PolicyEventType.GEOPOLITICAL.value: ["defence", "energy"],
    PolicyEventType.REGULATION.value: ["ai_infrastructure", "fintech"],
    PolicyEventType.ELECTION.value: ["healthcare", "clean_energy"],
    PolicyEventType.OTHER.value: [],
}

# Event-type default directional bias before keyword modifiers
EVENT_TYPE_DEFAULT_BIAS: dict[str, float] = {
    PolicyEventType.TARIFF.value: -0.4,
    PolicyEventType.SANCTION.value: -0.3,
    PolicyEventType.INTEREST_RATE.value: 0.0,    # direction set by keywords
    PolicyEventType.FISCAL_POLICY.value: 0.2,    # generally stimulative
    PolicyEventType.GEOPOLITICAL.value: -0.3,
    PolicyEventType.REGULATION.value: -0.2,
    PolicyEventType.ELECTION.value: 0.0,
    PolicyEventType.OTHER.value: 0.0,
}

# Confidence levels by event type (how reliable is the structural mapping)
EVENT_TYPE_BASE_CONFIDENCE: dict[str, float] = {
    PolicyEventType.TARIFF.value: 0.65,
    PolicyEventType.SANCTION.value: 0.6,
    PolicyEventType.INTEREST_RATE.value: 0.7,
    PolicyEventType.FISCAL_POLICY.value: 0.55,
    PolicyEventType.GEOPOLITICAL.value: 0.5,
    PolicyEventType.REGULATION.value: 0.55,
    PolicyEventType.ELECTION.value: 0.4,
    PolicyEventType.OTHER.value: 0.3,
}


def compute_directional_bias(event_type_value: str, text: str) -> float:
    """Return a directional bias in [-1.0, 1.0] for a policy event.

    Combines the event-type structural default with keyword-based modifiers
    from the headline/body text.
    """
    base = EVENT_TYPE_DEFAULT_BIAS.get(event_type_value, 0.0)
    words = re.findall(r"[a-z]+", text.lower())
    pos_boost = sum(0.1 for w in words if w in _POSITIVE_POLICY_WORDS)
    neg_boost = sum(0.1 for w in words if w in _NEGATIVE_POLICY_WORDS)
    raw = base + pos_boost - neg_boost
    return max(-1.0, min(1.0, round(raw, 4)))


def generate_implication_summary(
    event_type_value: str,
    directional_bias: float,
    headline: str,
    affected_sectors: list[str],
    affected_themes: list[str],
) -> str:
    """Produce a human-readable implication summary for a policy signal."""
    direction = "bullish" if directional_bias > 0.1 else (
        "bearish" if directional_bias < -0.1 else "neutral"
    )
    sectors_str = ", ".join(affected_sectors[:3]) or "market"
    themes_str = f" (themes: {', '.join(affected_themes[:2])})" if affected_themes else ""
    return (
        f"{direction.capitalize()} macro signal ({event_type_value}): "
        f"{headline[:80]}. Sectors: {sectors_str}{themes_str}."
    )

