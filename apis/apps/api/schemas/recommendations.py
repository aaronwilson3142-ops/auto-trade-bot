"""Response schemas for /api/v1/recommendations/* endpoints."""
from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel


class RecommendationItem(BaseModel):
    rank_position: int
    ticker: str
    composite_score: float | None
    portfolio_fit_score: float | None
    recommended_action: str
    target_horizon: str
    thesis_summary: str
    disconfirming_factors: str
    sizing_hint_pct: float | None
    source_reliability_tier: str
    contains_rumor: bool
    as_of: dt.datetime
    contributing_signals: list[dict[str, Any]]


class RecommendationListResponse(BaseModel):
    count: int
    run_id: str | None
    as_of: dt.datetime | None
    items: list[RecommendationItem]


class RecommendationDetailResponse(BaseModel):
    found: bool
    item: RecommendationItem | None
