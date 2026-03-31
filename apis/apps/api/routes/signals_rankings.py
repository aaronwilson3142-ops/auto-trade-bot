"""Route handlers for /api/v1/signals/* and /api/v1/rankings/*.

Exposes DB-backed history of signal runs and ranking runs (Phase 30).
All endpoints are read-only.
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Query

from apps.api.deps import AppStateDep
from apps.api.schemas.signals import (
    RankedOpportunityRecord,
    RankingRunDetailResponse,
    RankingRunHistoryResponse,
    RankingRunRecord,
    SignalRunHistoryResponse,
    SignalRunRecord,
)

signals_router = APIRouter(prefix="/signals", tags=["Signals"])
rankings_router = APIRouter(prefix="/rankings", tags=["Rankings"])


# ---------------------------------------------------------------------------
# Signal run history
# ---------------------------------------------------------------------------

@signals_router.get("/runs", response_model=SignalRunHistoryResponse)
async def list_signal_runs(
    state: AppStateDep,
    limit: int = Query(default=20, ge=1, le=200),
) -> SignalRunHistoryResponse:
    """Return recent signal generation runs ordered newest-first.

    Requires a live DB session factory on the app state.  Returns an empty
    list when the DB is unavailable (graceful degradation).
    """
    session_factory = getattr(state, "_session_factory", None)
    if session_factory is None:
        return SignalRunHistoryResponse(count=0, runs=[])

    try:
        from infra.db.models import SecuritySignal, SignalRun

        with session_factory() as session:
            runs = (
                session.execute(
                    sa.select(SignalRun)
                    .order_by(SignalRun.run_timestamp.desc())
                    .limit(limit)
                )
                .scalars()
                .all()
            )

            records: list[SignalRunRecord] = []
            for run in runs:
                # Count signals and distinct strategies for this run
                signal_count = session.execute(
                    sa.select(sa.func.count()).where(
                        SecuritySignal.signal_run_id == run.id
                    )
                ).scalar_one()
                strategy_count = session.execute(
                    sa.select(sa.func.count(SecuritySignal.strategy_id.distinct())).where(
                        SecuritySignal.signal_run_id == run.id
                    )
                ).scalar_one()

                records.append(
                    SignalRunRecord(
                        run_id=str(run.id),
                        run_timestamp=run.run_timestamp,
                        run_mode=run.run_mode,
                        universe_name=run.universe_name,
                        status=run.status,
                        signal_count=signal_count,
                        strategy_count=strategy_count,
                    )
                )

        return SignalRunHistoryResponse(count=len(records), runs=records)

    except Exception:  # noqa: BLE001
        return SignalRunHistoryResponse(count=0, runs=[])


# ---------------------------------------------------------------------------
# Ranking run history
# ---------------------------------------------------------------------------

@rankings_router.get("/runs", response_model=RankingRunHistoryResponse)
async def list_ranking_runs(
    state: AppStateDep,
    limit: int = Query(default=20, ge=1, le=200),
) -> RankingRunHistoryResponse:
    """Return recent ranking runs ordered newest-first."""
    session_factory = getattr(state, "_session_factory", None)
    if session_factory is None:
        return RankingRunHistoryResponse(count=0, runs=[])

    try:
        from infra.db.models import RankedOpportunity, RankingRun

        with session_factory() as session:
            runs = (
                session.execute(
                    sa.select(RankingRun)
                    .order_by(RankingRun.run_timestamp.desc())
                    .limit(limit)
                )
                .scalars()
                .all()
            )

            records: list[RankingRunRecord] = []
            for run in runs:
                ranked_count = session.execute(
                    sa.select(sa.func.count()).where(
                        RankedOpportunity.ranking_run_id == run.id
                    )
                ).scalar_one()

                records.append(
                    RankingRunRecord(
                        run_id=str(run.id),
                        signal_run_id=str(run.signal_run_id),
                        run_timestamp=run.run_timestamp,
                        status=run.status,
                        ranked_count=ranked_count,
                    )
                )

        return RankingRunHistoryResponse(count=len(records), runs=records)

    except Exception:  # noqa: BLE001
        return RankingRunHistoryResponse(count=0, runs=[])


@rankings_router.get("/latest", response_model=RankingRunDetailResponse)
async def get_latest_ranking_run(state: AppStateDep) -> RankingRunDetailResponse:
    """Return the most recent ranking run with full opportunity detail."""
    session_factory = getattr(state, "_session_factory", None)
    if session_factory is None:
        raise HTTPException(status_code=503, detail="DB session unavailable")

    try:
        from infra.db.models import RankedOpportunity, RankingRun, Security

        with session_factory() as session:
            run = session.execute(
                sa.select(RankingRun)
                .order_by(RankingRun.run_timestamp.desc())
                .limit(1)
            ).scalar_one_or_none()

            if run is None:
                raise HTTPException(status_code=404, detail="No ranking runs found")

            opps_rows = (
                session.execute(
                    sa.select(RankedOpportunity, Security.ticker)
                    .join(Security, Security.id == RankedOpportunity.security_id, isouter=True)
                    .where(RankedOpportunity.ranking_run_id == run.id)
                    .order_by(RankedOpportunity.rank_position)
                )
                .all()
            )

            opportunities = [
                RankedOpportunityRecord(
                    rank_position=opp.rank_position,
                    ticker=ticker,
                    composite_score=float(opp.composite_score) if opp.composite_score else None,
                    portfolio_fit_score=float(opp.portfolio_fit_score) if opp.portfolio_fit_score else None,
                    recommended_action=opp.recommended_action,
                    target_horizon=opp.target_horizon,
                    thesis_summary=opp.thesis_summary,
                    disconfirming_factors=opp.disconfirming_factors,
                    sizing_hint_pct=float(opp.sizing_hint_pct) if opp.sizing_hint_pct else None,
                )
                for opp, ticker in opps_rows
            ]

        return RankingRunDetailResponse(
            run_id=str(run.id),
            signal_run_id=str(run.signal_run_id),
            run_timestamp=run.run_timestamp,
            status=run.status,
            opportunities=opportunities,
        )

    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="DB error retrieving ranking run")


@rankings_router.get("/runs/{run_id}", response_model=RankingRunDetailResponse)
async def get_ranking_run_detail(
    run_id: str,
    state: AppStateDep,
) -> RankingRunDetailResponse:
    """Return full detail for a specific ranking run by ID."""
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid run_id format")

    session_factory = getattr(state, "_session_factory", None)
    if session_factory is None:
        raise HTTPException(status_code=503, detail="DB session unavailable")

    try:
        from infra.db.models import RankedOpportunity, RankingRun, Security

        with session_factory() as session:
            run = session.get(RankingRun, run_uuid)
            if run is None:
                raise HTTPException(status_code=404, detail="Ranking run not found")

            opps_rows = (
                session.execute(
                    sa.select(RankedOpportunity, Security.ticker)
                    .join(Security, Security.id == RankedOpportunity.security_id, isouter=True)
                    .where(RankedOpportunity.ranking_run_id == run.id)
                    .order_by(RankedOpportunity.rank_position)
                )
                .all()
            )

            opportunities = [
                RankedOpportunityRecord(
                    rank_position=opp.rank_position,
                    ticker=ticker,
                    composite_score=float(opp.composite_score) if opp.composite_score else None,
                    portfolio_fit_score=float(opp.portfolio_fit_score) if opp.portfolio_fit_score else None,
                    recommended_action=opp.recommended_action,
                    target_horizon=opp.target_horizon,
                    thesis_summary=opp.thesis_summary,
                    disconfirming_factors=opp.disconfirming_factors,
                    sizing_hint_pct=float(opp.sizing_hint_pct) if opp.sizing_hint_pct else None,
                )
                for opp, ticker in opps_rows
            ]

        return RankingRunDetailResponse(
            run_id=str(run.id),
            signal_run_id=str(run.signal_run_id),
            run_timestamp=run.run_timestamp,
            status=run.status,
            opportunities=opportunities,
        )

    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="DB error retrieving ranking run")
