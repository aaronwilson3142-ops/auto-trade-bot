"""news_intelligence domain models."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CredibilityTier(str, Enum):
    """Source credibility classification."""
    PRIMARY_VERIFIED = "primary_verified"       # official filings, press releases
    SECONDARY_VERIFIED = "secondary_verified"   # established financial media
    UNVERIFIED = "unverified"                   # blogs, social, aggregators
    RUMOR = "rumor"                             # explicitly unconfirmed chatter


class SentimentLabel(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"


@dataclass
class NewsItem:
    """Raw normalised news event from any source."""
    source_id: str                        # unique identifier from the data source
    headline: str
    published_at: dt.datetime
    source_url: str = ""
    body_snippet: str = ""               # first ~500 chars of article body
    credibility_tier: CredibilityTier = CredibilityTier.UNVERIFIED
    tickers_mentioned: list[str] = field(default_factory=list)


@dataclass
class NewsInsight:
    """Structured interpretation of a NewsItem produced by NLP pipeline."""
    news_item: NewsItem
    sentiment: SentimentLabel = SentimentLabel.NEUTRAL
    sentiment_score: float = 0.0          # [-1.0, 1.0]
    credibility_weight: float = 1.0       # discount applied to sentiment_score
    affected_tickers: list[str] = field(default_factory=list)
    affected_themes: list[str] = field(default_factory=list)
    market_implication: str = ""          # human-readable one-liner
    contains_rumor: bool = False
    processed_at: Optional[dt.datetime] = None

    @property
    def weighted_sentiment(self) -> float:
        """Credibility-discounted sentiment score."""
        return self.sentiment_score * self.credibility_weight
