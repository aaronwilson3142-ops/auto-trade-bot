"""Response schemas for /api/v1/intelligence/* endpoints."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class MacroRegimeResponse(BaseModel):
    """Current assessed macro regime derived from active policy signals."""

    regime: str
    signal_count: int
    as_of: dt.datetime


class PolicySignalSummary(BaseModel):
    """API-serialisable summary of a single PolicySignal."""

    event_id: str
    headline: str
    event_type: str
    directional_bias: float
    confidence: float
    affected_sectors: list[str]
    affected_themes: list[str]
    implication_summary: str
    generated_at: dt.datetime | None = None


class PolicySignalsResponse(BaseModel):
    """Paginated list of active policy signals."""

    count: int
    signals: list[PolicySignalSummary]
    as_of: dt.datetime


class NewsInsightSummary(BaseModel):
    """API-serialisable summary of a single NewsInsight."""

    source_id: str
    headline: str
    sentiment: str
    sentiment_score: float
    credibility_weight: float
    affected_tickers: list[str]
    affected_themes: list[str]
    market_implication: str
    contains_rumor: bool
    processed_at: dt.datetime | None = None


class NewsInsightsResponse(BaseModel):
    """Paginated list of active news insights."""

    count: int
    insights: list[NewsInsightSummary]
    as_of: dt.datetime


class ThemeMappingSummary(BaseModel):
    """API-serialisable summary of a single ThemeMapping."""

    theme: str
    beneficiary_order: str
    thematic_score: float
    rationale: str


class ThematicExposureResponse(BaseModel):
    """Thematic exposure for a single ticker."""

    ticker: str
    primary_theme: str | None = None
    max_score: float
    mappings: list[ThemeMappingSummary]
    as_of: dt.datetime


# ---------------------------------------------------------------------------
# Operator push request / response schemas
# ---------------------------------------------------------------------------

class PushEventRequest(BaseModel):
    """Request body for POST /intelligence/events.

    External feeds submit a processed policy event with its pre-computed
    directional bias and confidence.  The event is stored directly in
    app_state.latest_policy_signals so it is reflected in the next
    feature-enrichment and signal-generation cycles.
    """

    event_id: str
    headline: str
    event_type: str          # Must match a PolicyEventType value (e.g. "rate_decision")
    source: str = "operator_push"
    body_snippet: str = ""
    affected_sectors: list[str] = []
    affected_themes: list[str] = []
    affected_tickers: list[str] = []
    directional_bias: float = 0.0   # [-1.0, +1.0]
    confidence: float = 0.5         # [0.0, 1.0]
    implication_summary: str = ""


class PushNewsItemRequest(BaseModel):
    """Request body for POST /intelligence/news.

    External feeds submit a processed news item with its pre-computed
    sentiment scores.  The item is stored directly in
    app_state.latest_news_insights so it is reflected in the next
    feature-enrichment cycle.
    """

    source_id: str
    headline: str
    body_snippet: str = ""
    sentiment_score: float = 0.0    # [-1.0, +1.0]
    credibility_weight: float = 0.5 # [0.0, 1.0]
    affected_tickers: list[str] = []
    affected_themes: list[str] = []
    market_implication: str = ""
    contains_rumor: bool = False


class PushItemResponse(BaseModel):
    """Response for successful intelligence push operations."""

    status: str           # "accepted"
    message: str
    items_in_state: int   # Total count in app_state after insertion


# ---------------------------------------------------------------------------
# Phase 36: Alternative data schemas
# ---------------------------------------------------------------------------

class AlternativeDataRecordSchema(BaseModel):
    """API-serialisable view of a single AlternativeDataRecord."""

    id: str
    ticker: str
    source: str
    sentiment_score: float
    mention_count: int
    raw_snippet: str
    captured_at: dt.datetime

    model_config = {"from_attributes": True}


class AlternativeDataResponse(BaseModel):
    """Response for GET /intelligence/alternative."""

    count: int
    records: list[AlternativeDataRecordSchema]
    as_of: dt.datetime
