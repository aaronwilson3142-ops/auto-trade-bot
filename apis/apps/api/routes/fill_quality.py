"""Routes for Order Fill Quality API (Phase 52).

GET /portfolio/fill-quality           — aggregate summary + recent fills
GET /portfolio/fill-quality/{ticker}  — per-ticker fill detail
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from apps.api.deps import AppStateDep
from apps.api.schemas.fill_quality import (
    AlphaDecaySummarySchema,
    FillAttributionResponse,
    FillQualityRecordSchema,
    FillQualityResponse,
    FillQualitySummarySchema,
    FillQualityTickerResponse,
)

fill_quality_router = APIRouter(prefix="/portfolio", tags=["Fill Quality"])


def _record_to_schema(r: object) -> FillQualityRecordSchema:
    return FillQualityRecordSchema(
        ticker=r.ticker,
        direction=r.direction,
        action_type=r.action_type,
        expected_price=float(r.expected_price),
        fill_price=float(r.fill_price),
        quantity=float(r.quantity),
        slippage_usd=float(r.slippage_usd),
        slippage_pct=float(r.slippage_pct),
        filled_at=r.filled_at,
    )


def _summary_to_schema(s: object) -> FillQualitySummarySchema:
    return FillQualitySummarySchema(
        total_fills=s.total_fills,
        buy_fills=s.buy_fills,
        sell_fills=s.sell_fills,
        avg_slippage_usd=float(s.avg_slippage_usd),
        median_slippage_usd=float(s.median_slippage_usd),
        worst_slippage_usd=float(s.worst_slippage_usd),
        best_slippage_usd=float(s.best_slippage_usd),
        avg_slippage_pct=float(s.avg_slippage_pct),
        worst_slippage_pct=float(s.worst_slippage_pct),
        avg_buy_slippage_usd=float(s.avg_buy_slippage_usd) if s.avg_buy_slippage_usd is not None else None,
        avg_sell_slippage_usd=float(s.avg_sell_slippage_usd) if s.avg_sell_slippage_usd is not None else None,
        computed_at=s.computed_at,
        record_count=s.record_count,
        tickers_covered=list(s.tickers_covered),
    )


@fill_quality_router.get("/fill-quality", response_model=FillQualityResponse)
async def get_fill_quality(state: AppStateDep) -> FillQualityResponse:
    """Return aggregate fill quality statistics and the 20 most recent fills.

    Returns an empty summary (all zeros) when no fills have been captured yet.
    """
    records = list(getattr(state, "fill_quality_records", []))
    summary = getattr(state, "fill_quality_summary", None)
    as_of = getattr(state, "fill_quality_updated_at", None)

    if summary is None:
        # Build a live on-demand summary (no evening job has run yet)
        from services.fill_quality.service import FillQualityService
        summary = FillQualityService.compute_fill_summary(records)

    recent = records[-20:]  # newest last → return as-is (time-ordered insertion)

    return FillQualityResponse(
        summary=_summary_to_schema(summary),
        recent_fills=[_record_to_schema(r) for r in recent],
        as_of=as_of,
    )


@fill_quality_router.get(
    "/fill-quality/attribution",
    response_model=FillAttributionResponse,
    summary="Fill quality alpha-decay attribution summary",
)
async def get_fill_quality_attribution(state: AppStateDep) -> FillAttributionResponse:
    """Return aggregate alpha-decay attribution statistics for all enriched fills.

    Alpha-decay attribution compares the actual fill price to the N-day subsequent
    market price to estimate how much slippage cost relative to the realised price move.

    Returns HTTP 200 with zero-count summary when no attribution data is yet
    available (run_fill_quality_attribution job runs at 18:32 ET weekdays).
    """
    from services.fill_quality.models import AlphaDecaySummary  # noqa: PLC0415

    summary = getattr(state, "fill_quality_attribution_summary", None)
    as_of = getattr(state, "fill_quality_attribution_updated_at", None)
    records = list(getattr(state, "fill_quality_records", []))

    if summary is None:
        summary = AlphaDecaySummary()

    enriched_count = sum(
        1 for r in records if getattr(r, "alpha_captured_pct", None) is not None
    )

    return FillAttributionResponse(
        summary=AlphaDecaySummarySchema(
            records_with_alpha=summary.records_with_alpha,
            avg_alpha_captured_pct=summary.avg_alpha_captured_pct,
            avg_slippage_as_pct_of_move=summary.avg_slippage_as_pct_of_move,
            positive_alpha_count=summary.positive_alpha_count,
            negative_alpha_count=summary.negative_alpha_count,
            n_days=summary.n_days,
            computed_at=summary.computed_at,
        ),
        enriched_fill_count=enriched_count,
        total_fill_count=len(records),
        as_of=as_of,
    )


@fill_quality_router.get("/fill-quality/{ticker}", response_model=FillQualityTickerResponse)
async def get_fill_quality_ticker(ticker: str, state: AppStateDep) -> FillQualityTickerResponse:
    """Return fill quality detail for a specific ticker.

    Returns HTTP 404 when no fills have been recorded for the ticker.
    """
    from services.fill_quality.service import FillQualityService

    all_records = list(getattr(state, "fill_quality_records", []))
    ticker_records = FillQualityService.filter_by_ticker(all_records, ticker)

    if not ticker_records:
        raise HTTPException(
            status_code=404,
            detail=f"No fill quality records found for ticker '{ticker.upper()}'.",
        )

    ticker_summary = FillQualityService.compute_fill_summary(ticker_records)

    return FillQualityTickerResponse(
        ticker=ticker.upper(),
        fills=[_record_to_schema(r) for r in ticker_records],
        summary=_summary_to_schema(ticker_summary),
        total_fills=len(ticker_records),
    )
