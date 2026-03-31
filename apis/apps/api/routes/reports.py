"""Route handlers for /api/v1/reports/*.

Exposes daily operational reports produced by ReportingService.
All endpoints are read-only (Gate G: Phase A Read APIs).
"""
from __future__ import annotations

from fastapi import APIRouter

from apps.api.deps import AppStateDep
from apps.api.schemas.reports import (
    DailyReportLatestResponse,
    DailyReportResponse,
    ReportHistoryResponse,
)

router = APIRouter(prefix="/reports", tags=["Reports"])


def _to_report_response(r: object) -> DailyReportResponse:
    """Convert a DailyOperationalReport dataclass to the API response schema."""
    benchmarks: dict[str, float] = {}
    if r.benchmark_differentials:
        benchmarks = {k: float(v) for k, v in r.benchmark_differentials.items()}

    recon = r.reconciliation
    avg_slip = float(recon.avg_slippage_bps) if recon is not None else 0.0
    max_slip = float(recon.max_slippage_bps) if recon is not None else 0.0

    return DailyReportResponse(
        report_date=r.report_date,
        equity=float(r.equity),
        cash=float(r.cash),
        gross_exposure=float(r.gross_exposure),
        daily_return_pct=float(r.daily_return_pct),
        orders_submitted=r.orders_submitted,
        orders_filled=r.orders_filled,
        orders_cancelled=r.orders_cancelled,
        orders_rejected=r.orders_rejected,
        reconciliation_clean=r.reconciliation_clean,
        avg_slippage_bps=avg_slip,
        max_slippage_bps=max_slip,
        scorecard_grade=r.scorecard_grade,
        narrative=r.narrative,
        benchmark_differentials=benchmarks,
        improvement_proposals_generated=r.improvement_proposals_generated,
        improvement_proposals_promoted=r.improvement_proposals_promoted,
    )


@router.get("/daily/latest", response_model=DailyReportLatestResponse)
async def get_latest_daily_report(state: AppStateDep) -> DailyReportLatestResponse:
    """Return the most recent daily operational report."""
    rep = state.latest_daily_report
    if rep is None:
        return DailyReportLatestResponse(found=False, report=None)
    return DailyReportLatestResponse(found=True, report=_to_report_response(rep))


@router.get("/daily/history", response_model=ReportHistoryResponse)
async def get_daily_report_history(state: AppStateDep) -> ReportHistoryResponse:
    """Return historical daily reports (most recent first)."""
    items = [_to_report_response(r) for r in state.report_history]
    return ReportHistoryResponse(count=len(items), items=items)
