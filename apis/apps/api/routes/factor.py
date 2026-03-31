"""Phase 50 — Factor Exposure Monitoring routes.

Endpoints
---------
GET /portfolio/factor-exposure
    Portfolio-level factor weights + per-ticker scores from the most recent
    paper cycle computation.  Returns 200 + empty response when no data yet.

GET /portfolio/factor-exposure/{factor}
    Detail view for one factor (MOMENTUM | VALUE | GROWTH | QUALITY | LOW_VOL):
    portfolio weight, top-5 and bottom-5 tickers by score.
    Returns 404 for unknown factor names.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from apps.api.deps import AppStateDep
from apps.api.schemas.factor import (
    FactorDetailResponse,
    FactorExposureResponse,
    FactorTopBottomEntry,
    TickerFactorScoresSchema,
)
from services.risk_engine.factor_exposure import FACTORS

factor_router = APIRouter(tags=["Portfolio"])

_VALID_FACTORS = set(FACTORS)


@factor_router.get(
    "/portfolio/factor-exposure",
    response_model=FactorExposureResponse,
    summary="Portfolio factor exposure summary",
)
async def get_factor_exposure(state: AppStateDep) -> FactorExposureResponse:
    """Return the most recent portfolio factor exposure summary.

    Factor scores are computed each paper trading cycle from:
    - composite_score from ranking engine   → MOMENTUM
    - pe_ratio from fundamentals            → VALUE
    - eps_growth from fundamentals          → GROWTH
    - dollar_volume_20d from liquidity data → QUALITY
    - volatility_20d from feature store     → LOW_VOL

    Each factor score is in [0.0, 1.0] (higher = more exposed to that style).
    Returns HTTP 200 with neutral 0.5 defaults when no data is yet available.
    """
    result = getattr(state, "latest_factor_exposure", None)
    computed_at_raw = getattr(state, "factor_exposure_computed_at", None)
    computed_at_str = computed_at_raw.isoformat() if computed_at_raw else None

    if result is None:
        return FactorExposureResponse(
            computed_at=computed_at_str,
            position_count=0,
            total_market_value=0.0,
            dominant_factor="UNKNOWN",
            momentum=0.5,
            value=0.5,
            growth=0.5,
            quality=0.5,
            low_vol=0.5,
            ticker_scores=[],
        )

    fw = result.portfolio_factor_weights
    ticker_schemas = [
        TickerFactorScoresSchema(
            ticker=t.ticker,
            momentum=t.scores.get("MOMENTUM", 0.5),
            value=t.scores.get("VALUE", 0.5),
            growth=t.scores.get("GROWTH", 0.5),
            quality=t.scores.get("QUALITY", 0.5),
            low_vol=t.scores.get("LOW_VOL", 0.5),
            market_value=t.market_value,
            dominant_factor=t.dominant_factor,
        )
        for t in result.ticker_scores
    ]

    return FactorExposureResponse(
        computed_at=computed_at_str or result.computed_at.isoformat(),
        position_count=result.position_count,
        total_market_value=result.total_market_value,
        dominant_factor=result.dominant_factor,
        momentum=fw.get("MOMENTUM", 0.5),
        value=fw.get("VALUE", 0.5),
        growth=fw.get("GROWTH", 0.5),
        quality=fw.get("QUALITY", 0.5),
        low_vol=fw.get("LOW_VOL", 0.5),
        ticker_scores=ticker_schemas,
    )


@factor_router.get(
    "/portfolio/factor-exposure/{factor}",
    response_model=FactorDetailResponse,
    summary="Detail view for a single factor",
)
async def get_factor_detail(factor: str, state: AppStateDep) -> FactorDetailResponse:
    """Return portfolio weight and top/bottom tickers for a specific factor.

    Path parameter *factor* must be one of:
        MOMENTUM, VALUE, GROWTH, QUALITY, LOW_VOL  (case-insensitive).

    Returns HTTP 404 for unknown factor names.
    Returns HTTP 200 with empty lists when no factor data has been computed yet.
    """
    factor_upper = factor.upper()
    if factor_upper not in _VALID_FACTORS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown factor '{factor}'. Valid factors: {sorted(_VALID_FACTORS)}",
        )

    result = getattr(state, "latest_factor_exposure", None)
    computed_at_raw = getattr(state, "factor_exposure_computed_at", None)
    computed_at_str = computed_at_raw.isoformat() if computed_at_raw else None

    if result is None:
        return FactorDetailResponse(
            factor=factor_upper,
            portfolio_weight=0.5,
            top_tickers=[],
            bottom_tickers=[],
            computed_at=computed_at_str,
        )

    portfolio_weight = result.portfolio_factor_weights.get(factor_upper, 0.5)
    top = result.top_tickers_by_factor(factor_upper, n=5)
    bottom = result.bottom_tickers_by_factor(factor_upper, n=5)

    return FactorDetailResponse(
        factor=factor_upper,
        portfolio_weight=portfolio_weight,
        top_tickers=[
            FactorTopBottomEntry(
                ticker=t.ticker,
                score=t.scores.get(factor_upper, 0.5),
                market_value=t.market_value,
            )
            for t in top
        ],
        bottom_tickers=[
            FactorTopBottomEntry(
                ticker=t.ticker,
                score=t.scores.get(factor_upper, 0.5),
                market_value=t.market_value,
            )
            for t in bottom
        ],
        computed_at=computed_at_str or result.computed_at.isoformat(),
    )
