"""Route handlers for /api/v1/backtest/*.

Phase 34 — Strategy Backtesting Comparison API.

Endpoints
---------
POST /api/v1/backtest/compare
    Run a multi-strategy comparison and persist results.
    Body: BacktestCompareRequest (tickers, start_date, end_date, initial_cash)
    Returns: BacktestComparisonResponse (6 runs: 5 individual + 1 combined)

GET /api/v1/backtest/runs?limit=10
    List recent comparison groups (newest first).
    Returns: BacktestRunListResponse

GET /api/v1/backtest/runs/{comparison_id}
    Return all run rows for a specific comparison group.
    Returns: BacktestRunDetailResponse

Design
------
- POST /compare is synchronous — runs inline; acceptable for a paper system.
- All list/detail endpoints gracefully return empty results when DB unavailable.
- DB session_factory is read from app_state._session_factory (same pattern
  as signals_rankings.py).
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import List, Optional

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Query

from apps.api.deps import AppStateDep
from apps.api.schemas.backtest import (
    BacktestCompareRequest,
    BacktestComparisonResponse,
    BacktestComparisonSummary,
    BacktestRunDetailResponse,
    BacktestRunListResponse,
    BacktestRunRecord,
)

backtest_router = APIRouter(prefix="/backtest", tags=["Backtest"])


# ---------------------------------------------------------------------------
# POST /compare — run comparison
# ---------------------------------------------------------------------------

@backtest_router.post("/compare", response_model=BacktestComparisonResponse)
async def run_backtest_comparison(
    body: BacktestCompareRequest,
    state: AppStateDep,
) -> BacktestComparisonResponse:
    """Run a per-strategy + combined backtest comparison over a date range.

    Runs 6 backtests (5 individual strategies + 1 combined) and persists
    results to the DB when a session_factory is available.  Always returns
    the full comparison result regardless of DB availability.
    """
    from services.backtest.comparison import BacktestComparisonService

    session_factory = getattr(state, "_session_factory", None)
    svc = BacktestComparisonService(session_factory=session_factory)

    try:
        comparison_id, run_results = svc.run_comparison(
            tickers=body.tickers,
            start_date=body.start_date,
            end_date=body.end_date,
            initial_cash=Decimal(str(body.initial_cash)),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Backtest comparison failed: {exc}") from exc

    records: list[BacktestRunRecord] = []
    for rr in run_results:
        tickers_list = body.tickers if rr.error is None else None
        records.append(
            BacktestRunRecord(
                run_id=rr.run_id,
                comparison_id=comparison_id,
                strategy_name=rr.strategy_name,
                start_date=body.start_date,
                end_date=body.end_date,
                ticker_count=len(body.tickers),
                tickers=tickers_list,
                total_return_pct=rr.result.total_return_pct if rr.error is None else None,
                sharpe_ratio=rr.result.sharpe_ratio if rr.error is None else None,
                max_drawdown_pct=rr.result.max_drawdown_pct if rr.error is None else None,
                win_rate=rr.result.win_rate if rr.error is None else None,
                total_trades=rr.result.total_trades if rr.error is None else 0,
                days_simulated=rr.result.days_simulated if rr.error is None else 0,
                final_portfolio_value=(
                    float(rr.result.final_portfolio_value) if rr.error is None else None
                ),
                initial_cash=float(rr.result.initial_cash),
                status="error" if rr.error else "completed",
                error=rr.error,
            )
        )

    return BacktestComparisonResponse(
        comparison_id=comparison_id,
        run_count=len(records),
        runs=records,
    )


# ---------------------------------------------------------------------------
# GET /runs — list comparison groups
# ---------------------------------------------------------------------------

@backtest_router.get("/runs", response_model=BacktestRunListResponse)
async def list_backtest_runs(
    state: AppStateDep,
    limit: int = Query(default=10, ge=1, le=100),
) -> BacktestRunListResponse:
    """Return recent comparison groups ordered newest first.

    Each entry is a summary of one comparison_id group (best strategy by
    total return, number of runs, etc.).  Returns empty list on DB failure.
    """
    session_factory = getattr(state, "_session_factory", None)
    if session_factory is None:
        return BacktestRunListResponse(count=0, comparisons=[])

    try:
        from infra.db.models.backtest import BacktestRun

        with session_factory() as session:
            # Distinct comparison_ids ordered by newest created_at within group
            subq = (
                sa.select(
                    BacktestRun.comparison_id,
                    sa.func.max(BacktestRun.created_at).label("max_created_at"),
                )
                .group_by(BacktestRun.comparison_id)
                .order_by(sa.func.max(BacktestRun.created_at).desc())
                .limit(limit)
                .subquery()
            )
            rows = session.execute(
                sa.select(BacktestRun).where(
                    BacktestRun.comparison_id.in_(
                        sa.select(subq.c.comparison_id)
                    )
                )
            ).scalars().all()

            # Group by comparison_id
            groups: dict[str, list] = {}
            for row in rows:
                groups.setdefault(row.comparison_id, []).append(row)

            # Sort groups by newest created_at desc
            sorted_cids = sorted(
                groups.keys(),
                key=lambda cid: max(
                    (r.created_at for r in groups[cid] if r.created_at),
                    default=None,
                ) or "",
                reverse=True,
            )

            summaries: list[BacktestComparisonSummary] = []
            for cid in sorted_cids:
                group = groups[cid]
                best = max(
                    (r for r in group if r.total_return_pct is not None),
                    key=lambda r: r.total_return_pct,
                    default=None,
                )
                representative = group[0]
                created_at = max(
                    (r.created_at for r in group if r.created_at), default=None
                )
                summaries.append(
                    BacktestComparisonSummary(
                        comparison_id=cid,
                        run_count=len(group),
                        created_at=created_at,
                        start_date=representative.start_date,
                        end_date=representative.end_date,
                        ticker_count=representative.ticker_count,
                        best_strategy=best.strategy_name if best else None,
                        best_total_return_pct=best.total_return_pct if best else None,
                    )
                )

            return BacktestRunListResponse(count=len(summaries), comparisons=summaries)

    except Exception:  # noqa: BLE001
        return BacktestRunListResponse(count=0, comparisons=[])


# ---------------------------------------------------------------------------
# GET /runs/{comparison_id} — detail for one comparison group
# ---------------------------------------------------------------------------

@backtest_router.get("/runs/{comparison_id}", response_model=BacktestRunDetailResponse)
async def get_backtest_comparison(
    comparison_id: str,
    state: AppStateDep,
) -> BacktestRunDetailResponse:
    """Return all run rows for a specific comparison_id.

    Returns HTTP 404 when the comparison_id is not found.
    Returns HTTP 503 when the DB is unavailable.
    """
    session_factory = getattr(state, "_session_factory", None)
    if session_factory is None:
        raise HTTPException(status_code=503, detail="DB unavailable")

    try:
        from infra.db.models.backtest import BacktestRun

        with session_factory() as session:
            rows = session.execute(
                sa.select(BacktestRun)
                .where(BacktestRun.comparison_id == comparison_id)
                .order_by(BacktestRun.created_at.asc())
            ).scalars().all()

        if not rows:
            raise HTTPException(status_code=404, detail="Comparison not found")

        records: list[BacktestRunRecord] = []
        for row in rows:
            tickers: Optional[List[str]] = None
            if row.tickers_json:
                try:
                    tickers = json.loads(row.tickers_json)
                except Exception:  # noqa: BLE001
                    pass
            records.append(
                BacktestRunRecord(
                    run_id=str(row.id),
                    comparison_id=row.comparison_id,
                    strategy_name=row.strategy_name,
                    start_date=row.start_date,
                    end_date=row.end_date,
                    ticker_count=row.ticker_count or 0,
                    tickers=tickers,
                    total_return_pct=row.total_return_pct,
                    sharpe_ratio=row.sharpe_ratio,
                    max_drawdown_pct=row.max_drawdown_pct,
                    win_rate=row.win_rate,
                    total_trades=row.total_trades or 0,
                    days_simulated=row.days_simulated or 0,
                    final_portfolio_value=row.final_portfolio_value,
                    initial_cash=row.initial_cash,
                    status=row.status or "completed",
                    created_at=row.created_at,
                )
            )

        return BacktestRunDetailResponse(
            comparison_id=comparison_id,
            run_count=len(records),
            runs=records,
        )

    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"DB error: {exc}") from exc
