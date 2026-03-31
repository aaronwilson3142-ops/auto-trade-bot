"""
Signal Quality API routes (Phase 46).

GET /api/v1/signals/quality
    Returns the full signal quality report across all tracked strategies.
    Populated by run_signal_quality_update at 17:20 ET.

GET /api/v1/signals/quality/{strategy_name}
    Returns per-strategy quality detail for a single strategy.
    Returns data_available=False (200, not 404) when no outcomes exist.
"""
from __future__ import annotations

from fastapi import APIRouter

from apps.api.deps import AppStateDep, SettingsDep
from apps.api.schemas.signal_quality import (
    SignalQualityReportResponse,
    StrategyQualityDetailResponse,
    StrategyQualitySchema,
)

signal_quality_router = APIRouter(prefix="/signals", tags=["Signal Quality"])


@signal_quality_router.get(
    "/quality",
    response_model=SignalQualityReportResponse,
    summary="Per-strategy signal quality report",
    description=(
        "Returns signal prediction quality statistics for each strategy: "
        "win rate, average return, best/worst return, average hold days, "
        "and an annualised Sharpe estimate.  "
        "Populated by run_signal_quality_update at 17:20 ET.  "
        "Returns data_available=False when no update has run yet."
    ),
)
def get_signal_quality(
    state: AppStateDep,
    settings: SettingsDep,  # noqa: ARG001
) -> SignalQualityReportResponse:
    """Return full signal quality report from in-memory app_state."""
    report = getattr(state, "latest_signal_quality", None)

    if report is None:
        return SignalQualityReportResponse(
            computed_at=None,
            total_outcomes_recorded=0,
            strategies_with_data=[],
            strategy_count=0,
            strategy_results=[],
            data_available=False,
        )

    strategy_schemas = [
        StrategyQualitySchema(
            strategy_name=r.strategy_name,
            prediction_count=r.prediction_count,
            win_count=r.win_count,
            win_rate=r.win_rate,
            avg_return_pct=r.avg_return_pct,
            best_return_pct=r.best_return_pct,
            worst_return_pct=r.worst_return_pct,
            avg_hold_days=r.avg_hold_days,
            sharpe_estimate=r.sharpe_estimate,
        )
        for r in report.strategy_results
    ]

    return SignalQualityReportResponse(
        computed_at=report.computed_at,
        total_outcomes_recorded=report.total_outcomes_recorded,
        strategies_with_data=report.strategies_with_data,
        strategy_count=len(report.strategy_results),
        strategy_results=strategy_schemas,
        data_available=True,
    )


@signal_quality_router.get(
    "/quality/{strategy_name}",
    response_model=StrategyQualityDetailResponse,
    summary="Per-strategy signal quality detail",
    description=(
        "Returns signal quality statistics for a single strategy by name.  "
        "strategy_name is case-insensitive (normalised to lowercase).  "
        "Returns data_available=False (200, not 404) when no signal quality "
        "report has been computed yet or the strategy has no outcome records."
    ),
)
def get_signal_quality_strategy(
    strategy_name: str,
    state: AppStateDep,
    settings: SettingsDep,  # noqa: ARG001
) -> StrategyQualityDetailResponse:
    """Return signal quality detail for a single strategy."""
    strategy_name = strategy_name.lower()
    report = getattr(state, "latest_signal_quality", None)

    if report is None:
        return StrategyQualityDetailResponse(
            strategy_name=strategy_name,
            data_available=False,
        )

    # Find matching strategy result (case-insensitive)
    match = next(
        (r for r in report.strategy_results if r.strategy_name.lower() == strategy_name),
        None,
    )

    if match is None:
        return StrategyQualityDetailResponse(
            strategy_name=strategy_name,
            data_available=False,
            computed_at=report.computed_at,
        )

    return StrategyQualityDetailResponse(
        strategy_name=match.strategy_name,
        data_available=True,
        computed_at=report.computed_at,
        prediction_count=match.prediction_count,
        win_count=match.win_count,
        win_rate=match.win_rate,
        avg_return_pct=match.avg_return_pct,
        best_return_pct=match.best_return_pct,
        worst_return_pct=match.worst_return_pct,
        avg_hold_days=match.avg_hold_days,
        sharpe_estimate=match.sharpe_estimate,
    )
