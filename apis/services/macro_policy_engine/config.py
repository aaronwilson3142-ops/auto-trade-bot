"""macro_policy_engine configuration."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MacroPolicyConfig:
    """Tunable parameters for the macro/policy interpretation pipeline."""
    # Minimum confidence threshold for a PolicySignal to propagate downstream
    min_signal_confidence: float = 0.3
    # Maximum age (hours) of a policy event to be considered active
    max_event_age_hours: int = 72
    # Sectors actively tracked for policy impact
    tracked_sectors: list[str] = field(default_factory=lambda: [
        "technology", "energy", "financials", "industrials",
        "consumer_discretionary", "healthcare", "utilities",
    ])
    # Maximum number of policy signals retained per cycle
    max_signals_per_cycle: int = 20
