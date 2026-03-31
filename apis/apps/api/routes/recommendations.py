"""Route handlers for /api/v1/recommendations/*.

Exposes the latest ranked opportunities produced by the ranking engine.
All endpoints are read-only (Gate G: Phase A Read APIs).
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from apps.api.deps import AppStateDep
from apps.api.schemas.recommendations import (
    RecommendationDetailResponse,
    RecommendationItem,
    RecommendationListResponse,
)

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])


def _to_item(r: object) -> RecommendationItem:
    """Convert a RankedResult dataclass to a RecommendationItem."""
    return RecommendationItem(
        rank_position=r.rank_position,
        ticker=r.ticker,
        composite_score=float(r.composite_score) if r.composite_score is not None else None,
        portfolio_fit_score=float(r.portfolio_fit_score) if r.portfolio_fit_score is not None else None,
        recommended_action=r.recommended_action,
        target_horizon=r.target_horizon,
        thesis_summary=r.thesis_summary,
        disconfirming_factors=r.disconfirming_factors,
        sizing_hint_pct=float(r.sizing_hint_pct) if r.sizing_hint_pct is not None else None,
        source_reliability_tier=r.source_reliability_tier,
        contains_rumor=r.contains_rumor,
        as_of=r.as_of,
        contributing_signals=list(r.contributing_signals),
    )


@router.get("/latest", response_model=RecommendationListResponse)
async def get_latest_recommendations(
    state: AppStateDep,
    limit: int = Query(default=20, ge=1, le=50),
    min_score: float | None = Query(default=None),
    contains_rumor: bool | None = Query(default=None),
    recommended_action: str | None = Query(default=None),
) -> RecommendationListResponse:
    """Return the latest ranked opportunities with optional filters."""
    rankings = list(state.latest_rankings)

    if min_score is not None:
        rankings = [
            r for r in rankings
            if r.composite_score is not None and float(r.composite_score) >= min_score
        ]
    if contains_rumor is not None:
        rankings = [r for r in rankings if r.contains_rumor == contains_rumor]
    if recommended_action is not None:
        rankings = [r for r in rankings if r.recommended_action == recommended_action]

    rankings = rankings[:limit]

    return RecommendationListResponse(
        count=len(rankings),
        run_id=state.ranking_run_id,
        as_of=state.ranking_as_of,
        items=[_to_item(r) for r in rankings],
    )


@router.get("/{ticker}", response_model=RecommendationDetailResponse)
async def get_recommendation_for_ticker(
    ticker: str,
    state: AppStateDep,
) -> RecommendationDetailResponse:
    """Return the latest recommendation for a single ticker."""
    ticker_upper = ticker.upper()
    match = next(
        (r for r in state.latest_rankings if r.ticker.upper() == ticker_upper),
        None,
    )
    return RecommendationDetailResponse(
        found=match is not None,
        item=_to_item(match) if match else None,
    )
