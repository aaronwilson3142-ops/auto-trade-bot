"""news_intelligence configuration."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NewsIntelligenceConfig:
    """Tunable parameters for the news intelligence pipeline."""
    # Credibility weights applied to sentiment scores by tier
    credibility_weights: dict[str, float] = field(default_factory=lambda: {
        "primary_verified": 1.0,
        "secondary_verified": 0.8,
        "unverified": 0.4,
        "rumor": 0.2,
    })
    # Maximum age of a news item to be considered actionable (hours)
    max_item_age_hours: int = 48
    # Minimum credibility weight to include insight in ranking pipeline
    min_credibility_weight: float = 0.3
    # Maximum insights returned per ticker per cycle
    max_insights_per_ticker: int = 5
