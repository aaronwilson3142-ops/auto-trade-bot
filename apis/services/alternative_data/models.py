"""Alternative data domain models.

An AlternativeDataRecord captures a single data point from a non-traditional
source (social media, satellite, web-scraping, etc.) for a specific ticker.

Phase 36 — Alternative Data Integration
"""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from enum import Enum


class AlternativeDataSource(str, Enum):
    """Supported alternative data source types."""
    SOCIAL_MENTION   = "social_mention"    # Reddit / Twitter / StockTwits
    WEB_SEARCH_TREND = "web_search_trend"  # Google Trends proxy
    EMPLOYEE_REVIEW  = "employee_review"   # Glassdoor / Indeed proxy
    SATELLITE        = "satellite"         # satellite imagery stub
    CUSTOM           = "custom"            # operator-supplied


@dataclass
class AlternativeDataRecord:
    """One alternative data observation for a ticker.

    sentiment_score: [-1.0, 1.0]  (negative = bearish, positive = bullish)
    mention_count:   raw count of mentions / signals captured in this batch
    raw_snippet:     optional short text excerpt for operator audit
    """
    ticker: str
    source: AlternativeDataSource
    sentiment_score: float                 # clamped to [-1.0, 1.0]
    mention_count: int = 0
    raw_snippet: str = ""
    captured_at: dt.datetime = field(
        default_factory=lambda: dt.datetime.now(dt.UTC)
    )
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        # Clamp sentiment to valid range
        self.sentiment_score = round(
            max(-1.0, min(1.0, self.sentiment_score)), 4
        )

    @property
    def is_bullish(self) -> bool:
        return self.sentiment_score > 0.1

    @property
    def is_bearish(self) -> bool:
        return self.sentiment_score < -0.1
