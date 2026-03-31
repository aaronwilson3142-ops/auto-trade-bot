"""Response schemas for /api/v1/recommendations/* endpoints."""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from pydantic import BaseModel


class RecommendationItem(BaseModel):
    rank_position: int
    ticker: str
    composite_score: Optional[float]
    portfolio_fit_score: Optional[float]
    recommended_action: str
    target_horizon: str
    thesis_summary: str
    disconfirming_factors: str
    sizing_hint_pct: Optional[float]
    source_reliability_tier: str
    contains_rumor: bool
    as_of: dt.datetime
    contributing_signals: list[dict[str, Any]]


class RecommendationListResponse(BaseModel):
    count: int
    run_id: Optional[str]
    as_of: Optional[dt.datetime]
    items: list[RecommendationItem]


class RecommendationDetailResponse(BaseModel):
    found: bool
    item: Optional[RecommendationItem]
