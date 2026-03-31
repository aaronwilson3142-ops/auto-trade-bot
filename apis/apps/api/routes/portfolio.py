"""Route handlers for /api/v1/portfolio/*.

Exposes current portfolio state, positions, per-ticker detail, snapshot
history, and closed trade ledger.
All endpoints are read-only.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Query

from apps.api.deps import AppStateDep, SettingsDep
from apps.api.schemas.portfolio import (
    ClosedTradeHistoryResponse,
    ClosedTradeRecord,
    PerformanceSummaryResponse,
    PortfolioPositionsResponse,
    PortfolioResponse,
    PortfolioSnapshotHistoryResponse,
    PortfolioSnapshotRecord,
    PositionDetailResponse,
    PositionHistoryRecord,
    PositionHistoryResponse,
    PositionLatestSnapshotResponse,
    PositionSchema,
    TradeGradeHistoryResponse,
    TradeGradeRecord,
)

router = APIRouter(prefix="/portfolio", tags=["Portfolio"])


def _to_position_schema(pos: object) -> PositionSchema:
    """Convert a PortfolioPosition dataclass to PositionSchema."""
    return PositionSchema(
        ticker=pos.ticker,
        quantity=float(pos.quantity),
        avg_entry_price=float(pos.avg_entry_price),
        current_price=float(pos.current_price),
        market_value=float(pos.market_value),
        cost_basis=float(pos.cost_basis),
        unrealized_pnl=float(pos.unrealized_pnl),
        unrealized_pnl_pct=float(pos.unrealized_pnl_pct),
        opened_at=pos.opened_at,
        thesis_summary=pos.thesis_summary,
        strategy_key=pos.strategy_key,
    )


@router.get("", response_model=PortfolioResponse)
async def get_portfolio(state: AppStateDep) -> PortfolioResponse:
    """Return current portfolio state."""
    ps = state.portfolio_state
    if ps is None:
        return PortfolioResponse(
            cash=0.0,
            equity=0.0,
            gross_exposure=0.0,
            position_count=0,
            drawdown_pct=0.0,
            daily_pnl_pct=0.0,
            positions=[],
            as_of=dt.datetime.now(tz=dt.timezone.utc),
        )

    positions = [_to_position_schema(p) for p in ps.positions.values()]
    return PortfolioResponse(
        cash=float(ps.cash),
        equity=float(ps.equity),
        gross_exposure=float(ps.gross_exposure),
        position_count=ps.position_count,
        drawdown_pct=float(ps.drawdown_pct),
        daily_pnl_pct=float(ps.daily_pnl_pct),
        positions=positions,
        as_of=dt.datetime.now(tz=dt.timezone.utc),
    )


@router.get("/positions", response_model=PortfolioPositionsResponse)
async def get_positions(state: AppStateDep) -> PortfolioPositionsResponse:
    """Return all current positions."""
    ps = state.portfolio_state
    if ps is None:
        return PortfolioPositionsResponse(count=0, positions=[])

    positions = [_to_position_schema(p) for p in ps.positions.values()]
    return PortfolioPositionsResponse(count=len(positions), positions=positions)


@router.get("/positions/{ticker}", response_model=PositionDetailResponse)
async def get_position_detail(
    ticker: str,
    state: AppStateDep,
) -> PositionDetailResponse:
    """Return detailed position data for a single ticker."""
    ticker_upper = ticker.upper()
    ps = state.portfolio_state
    if ps is None or ticker_upper not in ps.positions:
        return PositionDetailResponse(found=False, position=None)

    return PositionDetailResponse(
        found=True,
        position=_to_position_schema(ps.positions[ticker_upper]),
    )


@router.get("/performance", response_model=PerformanceSummaryResponse)
async def get_performance_summary(state: AppStateDep) -> PerformanceSummaryResponse:
    """Return a live performance summary combining realized and unrealized P&L.

    Equity, daily return, drawdown, realized P&L from the closed trade ledger,
    and unrealized P&L from current open positions are all computed in-memory.
    """
    ps = state.portfolio_state
    now = dt.datetime.now(tz=dt.timezone.utc)

    if ps is None:
        return PerformanceSummaryResponse(
            equity=0.0,
            start_of_day_equity=0.0,
            high_water_mark=None,
            daily_return_pct=0.0,
            drawdown_from_hwm_pct=0.0,
            total_realized_pnl=0.0,
            realized_trade_count=0,
            win_count=0,
            loss_count=0,
            win_rate=None,
            total_unrealized_pnl=0.0,
            open_position_count=0,
            cash=0.0,
            as_of=now,
        )

    equity = float(ps.equity)
    sod = float(ps.start_of_day_equity) if ps.start_of_day_equity else equity
    hwm_raw = ps.high_water_mark
    hwm = float(hwm_raw) if hwm_raw is not None else None

    daily_return_pct = round(((equity - sod) / sod * 100) if sod > 0 else 0.0, 4)
    drawdown_from_hwm_pct = round(
        max(0.0, ((hwm - equity) / hwm * 100)) if hwm and hwm > 0 else 0.0, 4
    )

    closed = list(getattr(state, "closed_trades", []))
    total_realized_pnl = round(sum(float(t.realized_pnl) for t in closed), 2)
    win_count = sum(1 for t in closed if t.is_winner)
    loss_count = len(closed) - win_count
    win_rate = round(win_count / len(closed), 4) if closed else None

    total_unrealized_pnl = round(
        sum(float(p.unrealized_pnl) for p in ps.positions.values()), 2
    )

    return PerformanceSummaryResponse(
        equity=equity,
        start_of_day_equity=sod,
        high_water_mark=hwm,
        daily_return_pct=daily_return_pct,
        drawdown_from_hwm_pct=drawdown_from_hwm_pct,
        total_realized_pnl=total_realized_pnl,
        realized_trade_count=len(closed),
        win_count=win_count,
        loss_count=loss_count,
        win_rate=win_rate,
        total_unrealized_pnl=total_unrealized_pnl,
        open_position_count=ps.position_count,
        cash=float(ps.cash),
        as_of=now,
    )


@router.get("/grades", response_model=TradeGradeHistoryResponse)
async def get_trade_grades(
    limit: int = Query(50, ge=1, le=500),
    ticker: Optional[str] = Query(None, description="Filter by ticker symbol (case-insensitive)."),
    state: AppStateDep = None,
) -> TradeGradeHistoryResponse:
    """Return trade grade history from the in-memory grade ledger, most recent first.

    Grades are assigned by EvaluationEngineService after each CLOSE/TRIM fill.
    Letter grades: A (≥10%), B (≥5%), C (≥0%), D (≥-3%), F (<-3%).
    """
    grades = list(reversed(list(getattr(state, "trade_grades", []))))

    if ticker:
        ticker_upper = ticker.upper()
        grades = [g for g in grades if g.ticker.upper() == ticker_upper]

    grades = grades[:limit]

    distribution: dict[str, int] = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
    for g in grades:
        if g.grade in distribution:
            distribution[g.grade] += 1

    items = [
        TradeGradeRecord(
            ticker=g.ticker,
            strategy_key=g.strategy_key,
            realized_pnl=float(g.realized_pnl),
            realized_pnl_pct=float(g.realized_pnl_pct),
            holding_days=g.holding_days,
            is_winner=g.is_winner,
            exit_reason=g.exit_reason,
            grade=g.grade,
        )
        for g in grades
    ]

    return TradeGradeHistoryResponse(
        count=len(items),
        grade_distribution=distribution,
        items=items,
    )


@router.get("/trades", response_model=ClosedTradeHistoryResponse)
async def get_trade_history(
    limit: int = Query(50, ge=1, le=500),
    ticker: Optional[str] = Query(None, description="Filter by ticker symbol (case-insensitive)."),
    state: AppStateDep = None,
) -> ClosedTradeHistoryResponse:
    """Return closed trade history from the in-memory ledger, most recent first.

    Args:
        limit:  Maximum number of records to return (1–500, default 50).
        ticker: Optional ticker filter; case-insensitive.
    """
    all_trades = list(getattr(state, "closed_trades", []))

    if ticker:
        ticker_upper = ticker.upper()
        all_trades = [t for t in all_trades if t.ticker == ticker_upper]

    # Most recent first, then cap at limit
    all_trades.sort(key=lambda t: t.closed_at, reverse=True)
    paged = all_trades[:limit]

    win_count = sum(1 for t in paged if t.is_winner)
    loss_count = len(paged) - win_count
    total_pnl = sum(float(t.realized_pnl) for t in paged)
    win_rate = win_count / len(paged) if paged else None

    items = [
        ClosedTradeRecord(
            ticker=t.ticker,
            action_type=t.action_type.value,
            fill_price=float(t.fill_price),
            avg_entry_price=float(t.avg_entry_price),
            quantity=float(t.quantity),
            realized_pnl=float(t.realized_pnl),
            realized_pnl_pct=float(t.realized_pnl_pct),
            is_winner=t.is_winner,
            reason=t.reason,
            opened_at=t.opened_at,
            closed_at=t.closed_at,
            hold_duration_days=t.hold_duration_days,
        )
        for t in paged
    ]

    return ClosedTradeHistoryResponse(
        count=len(items),
        total_realized_pnl=total_pnl,
        win_count=win_count,
        loss_count=loss_count,
        win_rate=win_rate,
        items=items,
    )


@router.get("/positions/{ticker}/history", response_model=PositionHistoryResponse)
async def get_position_history(
    ticker: str,
    limit: int = Query(30, ge=1, le=200),
) -> PositionHistoryResponse:
    """Return P&L history for a single ticker (most recent first).

    Falls back to an empty list when the DB is unavailable.

    Args:
        ticker: Ticker symbol (case-insensitive).
        limit:  Maximum number of records to return (1–200, default 30).
    """
    ticker_upper = ticker.upper()
    try:
        from infra.db.models.portfolio import PositionHistory as _PosHist
        from infra.db.session import db_session as _db_session

        with _db_session() as db:
            rows = (
                db.query(_PosHist)
                .filter(_PosHist.ticker == ticker_upper)
                .order_by(_PosHist.snapshot_at.desc())
                .limit(limit)
                .all()
            )
            items = [_pos_hist_row_to_record(row) for row in rows]
        return PositionHistoryResponse(ticker=ticker_upper, count=len(items), items=items)
    except Exception:  # noqa: BLE001
        return PositionHistoryResponse(ticker=ticker_upper, count=0, items=[])


@router.get("/position-snapshots", response_model=PositionLatestSnapshotResponse)
async def get_positions_latest_history() -> PositionLatestSnapshotResponse:
    """Return the most-recent P&L snapshot for every tracked ticker.

    One row per ticker, ordered by snapshot_at descending.
    Falls back to an empty list when the DB is unavailable.

    Path is ``/position-snapshots`` (not ``/positions/history``) to avoid
    conflicting with the parameterised ``/positions/{ticker}`` route.
    """
    try:
        from infra.db.models.portfolio import PositionHistory as _PosHist
        from infra.db.session import db_session as _db_session
        import sqlalchemy as _sa

        with _db_session() as db:
            # Subquery: max snapshot_at per ticker
            sub = (
                db.query(
                    _PosHist.ticker,
                    _sa.func.max(_PosHist.snapshot_at).label("max_snap"),
                )
                .group_by(_PosHist.ticker)
                .subquery()
            )
            rows = (
                db.query(_PosHist)
                .join(
                    sub,
                    (_PosHist.ticker == sub.c.ticker)
                    & (_PosHist.snapshot_at == sub.c.max_snap),
                )
                .order_by(_PosHist.snapshot_at.desc())
                .all()
            )
            items = [_pos_hist_row_to_record(row) for row in rows]
        return PositionLatestSnapshotResponse(count=len(items), items=items)
    except Exception:  # noqa: BLE001
        return PositionLatestSnapshotResponse(count=0, items=[])


def _pos_hist_row_to_record(row: object) -> PositionHistoryRecord:
    """Convert a PositionHistory ORM row to PositionHistoryRecord schema."""
    return PositionHistoryRecord(
        id=str(row.id),
        ticker=row.ticker,
        snapshot_at=row.snapshot_at,
        quantity=float(row.quantity) if row.quantity is not None else None,
        avg_entry_price=float(row.avg_entry_price) if row.avg_entry_price is not None else None,
        current_price=float(row.current_price) if row.current_price is not None else None,
        market_value=float(row.market_value) if row.market_value is not None else None,
        cost_basis=float(row.cost_basis) if row.cost_basis is not None else None,
        unrealized_pnl=float(row.unrealized_pnl) if row.unrealized_pnl is not None else None,
        unrealized_pnl_pct=float(row.unrealized_pnl_pct) if row.unrealized_pnl_pct is not None else None,
    )


@router.get("/snapshots", response_model=PortfolioSnapshotHistoryResponse)
async def get_portfolio_snapshots(
    limit: int = Query(20, ge=1, le=100),
) -> PortfolioSnapshotHistoryResponse:
    """Return recent portfolio snapshots persisted to DB (most recent first).

    Falls back to an empty list when the DB is unavailable.

    Args:
        limit: Maximum number of records to return (1–100, default 20).
    """
    try:
        from infra.db.models.portfolio import PortfolioSnapshot as _DBSnap
        from infra.db.session import db_session as _db_session

        with _db_session() as db:
            rows = (
                db.query(_DBSnap)
                .order_by(_DBSnap.snapshot_timestamp.desc())
                .limit(limit)
                .all()
            )
            items = [
                PortfolioSnapshotRecord(
                    id=str(row.id),
                    snapshot_timestamp=row.snapshot_timestamp,
                    mode=row.mode,
                    cash_balance=float(row.cash_balance) if row.cash_balance is not None else None,
                    gross_exposure=float(row.gross_exposure) if row.gross_exposure is not None else None,
                    net_exposure=float(row.net_exposure) if row.net_exposure is not None else None,
                    equity_value=float(row.equity_value) if row.equity_value is not None else None,
                    drawdown_pct=float(row.drawdown_pct) if row.drawdown_pct is not None else None,
                )
                for row in rows
            ]
        return PortfolioSnapshotHistoryResponse(count=len(items), items=items)
    except Exception:  # noqa: BLE001
        return PortfolioSnapshotHistoryResponse(count=0, items=[])


@router.get("/drawdown-state")
async def get_drawdown_state(app_state: AppStateDep, settings: SettingsDep):
    """Current drawdown recovery state."""
    from services.risk_engine.drawdown_recovery import DrawdownRecoveryService
    from apps.api.schemas.drawdown import DrawdownStateResponse

    ps = app_state.portfolio_state
    if ps is not None:
        current_equity = float(ps.equity)
        hwm = float(ps.high_water_mark) if ps.high_water_mark is not None else current_equity
    else:
        current_equity = 0.0
        hwm = 0.0

    result = DrawdownRecoveryService.evaluate_state(
        current_equity=current_equity,
        high_water_mark=hwm,
        caution_threshold_pct=settings.drawdown_caution_pct,
        recovery_threshold_pct=settings.drawdown_recovery_pct,
        recovery_mode_size_multiplier=settings.recovery_mode_size_multiplier,
    )
    return DrawdownStateResponse(
        state=result.state.value,
        current_drawdown_pct=result.current_drawdown_pct,
        high_water_mark=result.high_water_mark,
        current_equity=result.current_equity,
        caution_threshold_pct=result.caution_threshold_pct,
        recovery_threshold_pct=result.recovery_threshold_pct,
        size_multiplier=result.size_multiplier,
        block_new_positions=settings.recovery_mode_block_new_positions,
        state_changed_at=app_state.drawdown_state_changed_at,
    )
