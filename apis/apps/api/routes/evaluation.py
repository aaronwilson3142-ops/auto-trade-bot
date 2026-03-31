"""Route handlers for /api/v1/evaluation/*.

Exposes daily scorecard summaries and evaluation history.
All endpoints are read-only (Gate G: Phase A Read APIs).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from apps.api.deps import AppStateDep
from apps.api.schemas.evaluation import (
    DailyScorecardResponse,
    EvaluationHistoryResponse,
    EvaluationLatestResponse,
    EvaluationRunHistoryResponse,
    EvaluationRunRecord,
)

router = APIRouter(prefix="/evaluation", tags=["Evaluation"])


def _to_scorecard_response(
    sc: object, run_id: Optional[str] = None
) -> DailyScorecardResponse:
    """Convert a DailyScorecard dataclass to the API response schema."""
    benchmark_returns: dict[str, float] = {}
    benchmark_differentials: dict[str, float] = {}
    if sc.benchmark_comparison is not None:
        benchmark_returns = {
            k: float(v) for k, v in sc.benchmark_comparison.benchmark_returns.items()
        }
        benchmark_differentials = {
            k: float(v) for k, v in sc.benchmark_comparison.differentials.items()
        }

    return DailyScorecardResponse(
        scorecard_date=sc.scorecard_date,
        equity=float(sc.equity),
        cash=float(sc.cash),
        gross_exposure=float(sc.gross_exposure),
        position_count=sc.position_count,
        net_pnl=float(sc.net_pnl),
        realized_pnl=float(sc.realized_pnl),
        unrealized_pnl=float(sc.unrealized_pnl),
        daily_return_pct=float(sc.daily_return_pct),
        hit_rate=float(sc.hit_rate),
        closed_trade_count=sc.closed_trade_count,
        avg_winner_pct=float(sc.avg_winner_pct),
        avg_loser_pct=float(sc.avg_loser_pct),
        current_drawdown_pct=float(sc.current_drawdown_pct),
        max_drawdown_pct=float(sc.max_drawdown_pct),
        mode=sc.mode,
        benchmark_returns=benchmark_returns,
        benchmark_differentials=benchmark_differentials,
        run_id=run_id,
    )


@router.get("/latest", response_model=EvaluationLatestResponse)
async def get_latest_evaluation(state: AppStateDep) -> EvaluationLatestResponse:
    """Return the most recent daily scorecard."""
    sc = state.latest_scorecard
    if sc is None:
        return EvaluationLatestResponse(found=False, scorecard=None, run_id=None)

    return EvaluationLatestResponse(
        found=True,
        scorecard=_to_scorecard_response(sc, run_id=state.evaluation_run_id),
        run_id=state.evaluation_run_id,
    )


@router.get("/history", response_model=EvaluationHistoryResponse)
async def get_evaluation_history(state: AppStateDep) -> EvaluationHistoryResponse:
    """Return historical daily scorecards (most recent first)."""
    items = [_to_scorecard_response(sc) for sc in state.evaluation_history]
    return EvaluationHistoryResponse(count=len(items), items=items)


@router.get("/runs", response_model=EvaluationRunHistoryResponse)
async def get_evaluation_runs(
    limit: int = Query(20, ge=1, le=100),
) -> EvaluationRunHistoryResponse:
    """Return recent evaluation runs persisted to DB (most recent first).

    Falls back to an empty list when the DB is unavailable.

    Args:
        limit: Maximum number of records to return (1–100, default 20).
    """
    try:
        from infra.db.models.evaluation import EvaluationMetric as _DBMetric
        from infra.db.models.evaluation import EvaluationRun as _DBRun
        from infra.db.session import db_session as _db_session

        with _db_session() as db:
            rows = (
                db.query(_DBRun)
                .order_by(_DBRun.run_timestamp.desc())
                .limit(limit)
                .all()
            )
            items: list[EvaluationRunRecord] = []
            for row in rows:
                metric_rows = (
                    db.query(_DBMetric)
                    .filter_by(evaluation_run_id=row.id)
                    .all()
                )
                metrics: dict[str, Optional[float]] = {
                    m.metric_key: (
                        float(m.metric_value) if m.metric_value is not None else None
                    )
                    for m in metric_rows
                }
                items.append(
                    EvaluationRunRecord(
                        id=str(row.id),
                        run_timestamp=row.run_timestamp,
                        mode=row.mode,
                        status=row.status,
                        evaluation_period_start=row.evaluation_period_start,
                        evaluation_period_end=row.evaluation_period_end,
                        metrics=metrics,
                    )
                )
        return EvaluationRunHistoryResponse(count=len(items), items=items)
    except Exception:  # noqa: BLE001
        return EvaluationRunHistoryResponse(count=0, items=[])
