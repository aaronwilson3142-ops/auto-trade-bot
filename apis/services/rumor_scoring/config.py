"""rumor_scoring configuration."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RumorScoringConfig:
    """Tunable parameters for the rumor scoring pipeline."""
    # Credibility penalties by source type [0.0 = no penalty, 1.0 = full discount]
    source_penalties: dict[str, float] = field(default_factory=lambda: {
        "social_media": 0.7,
        "anonymous_tip": 0.9,
        "unattributed_article": 0.6,
        "chat_forum": 0.8,
        "other": 0.7,
    })
    # Half-life for exponential time decay (hours)
    decay_half_life_hours: float = 24.0
    # Minimum influence_score to flag a rumor as actionable
    min_actionable_score: float = 0.1
    # Maximum rumors retained per ticker per cycle
    max_rumors_per_ticker: int = 3
