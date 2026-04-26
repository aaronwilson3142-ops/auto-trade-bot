"""
Worker job: signal quality update (Phase 46).

``run_signal_quality_update``
    For each closed trade in app_state.closed_trades, matches the trade
    against SecuritySignal rows in the DB for the same ticker on the day
    the position was opened, creates SignalOutcome rows (one per strategy
    that had a signal for that ticker on that date), then recomputes the
    full SignalQualityReport from all persisted SignalOutcome rows and
    stores it in app_state.latest_signal_quality.

Design rules
------------
- Fire-and-forget: all exceptions caught; scheduler thread never dies.
- Graceful degradation: on DB error, app_state.latest_signal_quality is
  left unchanged (stale-but-safe rather than cleared).
- Skips gracefully when closed_trades is empty.
- Runs at 17:20 ET — after attribution_analysis (17:15), before
  generate_daily_report (17:30).
- DB writes use ON CONFLICT DO NOTHING (uq_signal_outcome_trade) so
  re-runs are idempotent.
- When no matching SecuritySignal row is found for a trade, the outcome
  is still recorded for all DEFAULT_STRATEGIES with signal_score=NULL,
  ensuring win/return statistics are complete even without signal scores.

Strategy name resolution
------------------------
The job tries to look up strategy names from the SecuritySignal +
Strategy tables in the DB.  If no signal rows are found for a ticker/date
(e.g. the signal_runs table is sparsely populated in test/paper mode),
it falls back to DEFAULT_STRATEGIES and records NULL signal scores.
This ensures outcomes are always recorded regardless of signal DB state.
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from apps.api.state import ApiAppState
from config.logging_config import get_logger
from config.settings import Settings, get_settings

logger = get_logger(__name__)

# Strategy names recorded when no DB signal rows are found for a trade
DEFAULT_STRATEGIES = [
    "momentum",
    "theme_alignment",
    "macro_tailwind",
    "sentiment",
    "valuation",
]


def run_signal_quality_update(
    app_state: ApiAppState,
    settings: Settings | None = None,
    session_factory: Any | None = None,
) -> dict[str, Any]:
    """Match closed trades to strategy signals, persist outcomes, compute report.

    Args:
        app_state:       Shared ApiAppState; signal_quality fields updated on success.
        settings:        Settings instance; falls back to get_settings().
        session_factory: SQLAlchemy session factory; DB steps skipped if None.

    Returns:
        dict with keys: status, trades_processed, outcomes_inserted,
        outcomes_total, computed_at, error.
    """
    cfg = settings or get_settings()  # noqa: F841
    run_at = dt.datetime.now(dt.UTC)

    logger.info("signal_quality_update_starting")

    closed_trades = getattr(app_state, "closed_trades", [])

    if not closed_trades:
        logger.info("signal_quality_update_skipped_no_trades")
        return {
            "status": "skipped_no_trades",
            "trades_processed": 0,
            "outcomes_inserted": 0,
            "outcomes_total": 0,
            "computed_at": run_at.isoformat(),
            "error": None,
        }

    # ── DB path ─────────────────────────────────────────────────────────────
    if session_factory is not None:
        try:
            return _run_with_db(
                app_state=app_state,
                closed_trades=closed_trades,
                session_factory=session_factory,
                run_at=run_at,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("signal_quality_update_db_failed", error=str(exc))
            return {
                "status": "error",
                "trades_processed": 0,
                "outcomes_inserted": 0,
                "outcomes_total": 0,
                "computed_at": run_at.isoformat(),
                "error": str(exc),
            }

    # ── No-DB path: compute report purely from closed_trades in memory ──────
    return _run_no_db(
        app_state=app_state,
        closed_trades=closed_trades,
        run_at=run_at,
    )


# ---------------------------------------------------------------------------
# DB-backed path
# ---------------------------------------------------------------------------

def _run_with_db(
    app_state: ApiAppState,
    closed_trades: list,
    session_factory: Any,
    run_at: dt.datetime,
) -> dict[str, Any]:
    """Persist SignalOutcome rows and compute quality report from DB."""
    from infra.db.models.signal_quality import SignalOutcome  # noqa: PLC0415
    from services.signal_engine.signal_quality import SignalQualityService  # noqa: PLC0415

    outcomes_inserted = 0
    trades_processed = 0

    with session_factory() as session:
        # ── For each closed trade, find matching strategy signals ────────────
        # Build all outcome rows first, then bulk-insert with ON CONFLICT DO
        # NOTHING to avoid UniqueViolation when the same trade appears in
        # multiple cycles (e.g. from churn) or re-runs.
        pending_rows: list[dict] = []
        for trade in closed_trades:
            trades_processed += 1
            ticker = trade.ticker
            opened_at = trade.opened_at
            closed_at = trade.closed_at
            outcome_return_pct = float(trade.realized_pnl_pct)
            hold_days = int(trade.hold_duration_days)
            was_profitable = bool(trade.is_winner)

            # Try DB signal lookup
            strategy_scores = _fetch_strategy_scores(
                session=session,
                ticker=ticker,
                signal_date=opened_at.date() if hasattr(opened_at, "date") else opened_at,
            )

            # If no signals found, fall back to default strategies with NULL scores
            if not strategy_scores:
                strategy_scores = dict.fromkeys(DEFAULT_STRATEGIES)

            for strategy_name, signal_score in strategy_scores.items():
                pending_rows.append({
                    "id": str(uuid.uuid4()),
                    "ticker": ticker,
                    "strategy_name": strategy_name,
                    "signal_score": signal_score,
                    "trade_opened_at": opened_at,
                    "trade_closed_at": closed_at,
                    "outcome_return_pct": outcome_return_pct,
                    "hold_days": hold_days,
                    "was_profitable": was_profitable,
                })

        # Bulk upsert with ON CONFLICT DO NOTHING (matches docstring contract)
        if pending_rows:
            from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: PLC0415

            stmt = pg_insert(SignalOutcome.__table__).values(pending_rows)
            stmt = stmt.on_conflict_do_nothing(
                constraint="uq_signal_outcome_trade",
            )
            result = session.execute(stmt)
            outcomes_inserted = result.rowcount if result.rowcount else 0

        session.commit()

        # ── Load all outcomes for report computation ─────────────────────────
        all_rows = session.query(SignalOutcome).all()
        outcomes_total = len(all_rows)

        outcome_dicts = [
            SignalQualityService.build_outcome_dict(
                ticker=r.ticker,
                strategy_name=r.strategy_name,
                trade_opened_at=r.trade_opened_at,
                trade_closed_at=r.trade_closed_at,
                outcome_return_pct=float(r.outcome_return_pct),
                hold_days=int(r.hold_days),
                was_profitable=bool(r.was_profitable),
                signal_score=float(r.signal_score) if r.signal_score is not None else None,
            )
            for r in all_rows
        ]

    report = SignalQualityService.compute_quality_report(
        outcomes=outcome_dicts,
        computed_at=run_at,
    )

    app_state.latest_signal_quality = report
    app_state.signal_quality_computed_at = run_at

    logger.info(
        "signal_quality_update_complete",
        trades_processed=trades_processed,
        outcomes_inserted=outcomes_inserted,
        outcomes_total=outcomes_total,
        strategies=report.strategies_with_data,
    )

    return {
        "status": "ok",
        "trades_processed": trades_processed,
        "outcomes_inserted": outcomes_inserted,
        "outcomes_total": outcomes_total,
        "computed_at": run_at.isoformat(),
        "error": None,
    }


def _fetch_strategy_scores(
    session: Any,
    ticker: str,
    signal_date: dt.date,
) -> dict[str, float | None]:
    """Return {strategy_name: signal_score} for ticker on signal_date.

    Queries SecuritySignal + SignalRun + Strategy + Security.
    Returns empty dict when no matching rows are found or any query fails.
    """
    try:
        from infra.db.models.reference import Security  # noqa: PLC0415
        from infra.db.models.signal import SecuritySignal, SignalRun, Strategy  # noqa: PLC0415

        # Resolve security_id from ticker
        security = (
            session.query(Security)
            .filter(Security.ticker == ticker)
            .first()
        )
        if security is None:
            return {}

        # Find signal_runs for the given date
        day_start = dt.datetime.combine(signal_date, dt.time.min)
        day_end = dt.datetime.combine(signal_date, dt.time.max)

        signal_runs = (
            session.query(SignalRun)
            .filter(
                SignalRun.run_timestamp >= day_start,
                SignalRun.run_timestamp <= day_end,
            )
            .all()
        )
        if not signal_runs:
            return {}

        run_ids = [r.id for r in signal_runs]

        # Fetch SecuritySignal rows for this security across those runs
        sig_rows = (
            session.query(SecuritySignal, Strategy)
            .join(Strategy, SecuritySignal.strategy_id == Strategy.id)
            .filter(
                SecuritySignal.security_id == security.id,
                SecuritySignal.signal_run_id.in_(run_ids),
            )
            .all()
        )

        result: dict[str, float | None] = {}
        for sig, strat in sig_rows:
            score = float(sig.signal_score) if sig.signal_score is not None else None
            result[strat.strategy_name] = score

        return result

    except Exception as exc:  # noqa: BLE001
        logger.debug("fetch_strategy_scores_failed", ticker=ticker, error=str(exc))
        return {}


# ---------------------------------------------------------------------------
# No-DB path (fallback when session_factory is None)
# ---------------------------------------------------------------------------

def _run_no_db(
    app_state: ApiAppState,
    closed_trades: list,
    run_at: dt.datetime,
) -> dict[str, Any]:
    """Compute quality report purely from in-memory closed_trades.

    Records one outcome per DEFAULT_STRATEGY per closed trade (no DB
    signal matching).  Used when session_factory is not provided.
    """
    from services.signal_engine.signal_quality import SignalQualityService  # noqa: PLC0415

    outcomes: list[dict] = []
    for trade in closed_trades:
        for strategy_name in DEFAULT_STRATEGIES:
            outcomes.append(
                SignalQualityService.build_outcome_dict(
                    ticker=trade.ticker,
                    strategy_name=strategy_name,
                    trade_opened_at=trade.opened_at,
                    trade_closed_at=trade.closed_at,
                    outcome_return_pct=float(trade.realized_pnl_pct),
                    hold_days=int(trade.hold_duration_days),
                    was_profitable=bool(trade.is_winner),
                    signal_score=None,
                )
            )

    report = SignalQualityService.compute_quality_report(
        outcomes=outcomes,
        computed_at=run_at,
    )

    app_state.latest_signal_quality = report
    app_state.signal_quality_computed_at = run_at

    logger.info(
        "signal_quality_update_no_db_complete",
        trades_processed=len(closed_trades),
        outcomes_computed=len(outcomes),
    )

    return {
        "status": "ok_no_db",
        "trades_processed": len(closed_trades),
        "outcomes_inserted": 0,
        "outcomes_total": len(outcomes),
        "computed_at": run_at.isoformat(),
        "error": None,
    }
