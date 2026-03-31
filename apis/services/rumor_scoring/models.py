"""rumor_scoring domain models."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RumorSource(str, Enum):
    SOCIAL_MEDIA = "social_media"
    ANONYMOUS_TIP = "anonymous_tip"
    UNATTRIBUTED_ARTICLE = "unattributed_article"
    CHAT_FORUM = "chat_forum"
    OTHER = "other"


@dataclass
class RumorEvent:
    """A low-confidence unverified chatter event."""
    rumor_id: str
    ticker: str
    headline: str
    source: RumorSource
    received_at: dt.datetime
    raw_text: str = ""


@dataclass
class RumorScore:
    """Credibility-discounted influence score for a RumorEvent."""
    rumor: RumorEvent
    raw_confidence: float = 0.0           # initial confidence [0.0, 1.0]
    credibility_penalty: float = 0.0      # discount applied based on source type
    decay_factor: float = 1.0             # time-based decay [0.0, 1.0]
    influence_score: float = 0.0          # raw_confidence * (1-penalty) * decay
    scored_at: Optional[dt.datetime] = None

    @property
    def is_actionable(self) -> bool:
        """True if influence_score exceeds a minimum threshold (0.1)."""
        return self.influence_score >= 0.1
