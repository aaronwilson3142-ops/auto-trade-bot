"""
Worker job: daily evaluation and attribution analysis.

Functions
---------
run_daily_evaluation      — generate DailyScorecard from current portfolio state
run_attribution_analysis  — run attribution on today's closed trades (standalone)

Design rules
------------
- Both jobs read from ApiAppState and write back to it.
- No DB session required: evaluation is purely in-memory.
- When portfolio_state is None, the job builds a minimal "empty portfolio"
  scorecard so the pipeline still runs cleanly.
- Exceptions are caught; jobs must never crash the scheduler thread.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from apps.api.state import ApiAppState
from config.logging_config import get_logger
from config.settings import Settings, get_settings


def _persist_evaluation_run(scorecard: Any, mode: str) -> None:
    """Fire-and-forget: write EvaluationRun + EvaluationMetric rows to DB.

    Never raises — DB failures are logged at WARNING level only.
    Called at the end of every successful run_daily_evaluation.
    """
    try:
        from decimal import Decimal as _Decimal

        from infra.db.models.evaluation import EvaluationMetric as _DBMetric
        from infra.db.models.evaluation import EvaluationRun as _DBRun
        from infra.db.session import db_session as _db_session

        with _db_session() as db:
            run = _DBRun(
                run_timestamp=dt.datetime.now(dt.UTC),
                evaluation_period_start=scorecard.scorecard_date,
                evaluation_period_end=scorecard.scorecard_date,
                mode=mode,
                status="complete",
            )
            db.add(run)
            db.flush()  # populate run.id before referencing it

            metric_fields: dict[str, Any] = {
                "equity": scorecard.equity,
                "daily_return_pct": scorecard.daily_return_pct,
                "net_pnl": scorecard.net_pnl,
                "hit_rate": scorecard.hit_rate,
                "current_drawdown_pct": scorecard.current_drawdown_pct,
                "max_drawdown_pct": scorecard.max_drawdown_pct,
                "position_count": scorecard.position_count,
                "closed_trade_count": scorecard.closed_trade_count,
            }
            for key, val in metric_fields.items():
                db.add(
                    _DBMetric(
                        evaluation_run_id=run.id,
                        metric_key=key,
                        metric_value=(
                            _Decimal(str(val)) if val is not None else None
                        ),
                    )
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("persist_evaluation_run_failed %s", exc)

logger = get_logger(__name__)

# Default benchmark returns used when no live data is available
_DEFAULT_BENCHMARKS: dict[str, Decimal] = {
    "SPY": Decimal("0"),
    "QQQ": Decimal("0"),
    "IWM": Decimal("0"),
}


def _make_empty_snapshot(mode: str = "research") -> Any:
    """Build a minimal PortfolioSnapshot with all-zero values."""
    from services.portfolio_engine.models import PortfolioSnapshot

    return PortfolioSnapshot(
        snapshot_at=dt.datetime.now(dt.UTC),
        cash=Decimal("0"),
        equity=Decimal("0"),
        gross_exposure=Decimal("0"),
        position_count=0,
        drawdown_pct=Decimal("0"),
        daily_pnl_pct=Decimal("0"),
        positions=[],
        mode=mode,
    )


def _snapshot_from_state(portfolio_state: Any, mode: str = "research") -> Any:
    """Convert a live PortfolioState into a PortfolioSnapshot."""
    from services.portfolio_engine.models import PortfolioSnapshot

    return PortfolioSnapshot(
        snapshot_at=dt.datetime.now(dt.UTC),
        cash=portfolio_state.cash,
        equity=portfolio_state.equity,
        gross_exposure=portfolio_state.gross_exposure,
        position_count=portfolio_state.position_count,
        drawdown_pct=portfolio_state.drawdown_pct,
        daily_pnl_pct=portfolio_state.daily_pnl_pct,
        positions=list(portfolio_state.positions.values()),
        mode=mode,
    )


# ---------------------------------------------------------------------------
# run_daily_evaluation
# ---------------------------------------------------------------------------

def run_daily_evaluation(
    app_state: ApiAppState,
    settings: Settings | None = None,
    closed_today: list[Any] | None = None,
    benchmark_returns: dict[str, Decimal] | None = None,
    equity_curve: list[Decimal] | None = None,
    evaluation_service: Any | None = None,
    max_history: int = 90,
) -> dict[str, Any]:
    """Generate a DailyScorecard and write it into app_state.

    Args:
        app_state:          Shared ApiAppState.  latest_scorecard and
                            evaluation_history are written here.
        settings:           Settings instance.
        closed_today:       List of TradeRecord objects closed today.
                            Defaults to empty list.
        benchmark_returns:  Fractional daily returns by benchmark ticker.
                            Defaults to zero for all benchmarks.
        equity_curve:       Chronological equity values for drawdown math.
                            Defaults to [current equity].
        evaluation_service: EvaluationEngineService for injection/testing.
        max_history:        Maximum evaluation_history entries to retain.

    Returns:
        dict with keys: status, scorecard_date, daily_return_pct, run_at.
    """
    from services.evaluation_engine.service import EvaluationEngineService

    cfg = settings or get_settings()
    run_at = dt.datetime.now(dt.UTC)
    svc = evaluation_service or EvaluationEngineService()

    logger.info("daily_evaluation_job_starting", run_at=run_at.isoformat())

    try:
        # Build snapshot from live portfolio state (or an empty one)
        if app_state.portfolio_state is not None:
            snapshot = _snapshot_from_state(
                app_state.portfolio_state, mode=cfg.operating_mode.value
            )
        else:
            snapshot = _make_empty_snapshot(mode=cfg.operating_mode.value)

        trades = closed_today or []
        benchmarks = benchmark_returns or _DEFAULT_BENCHMARKS

        # Use current equity as the single-element curve when none is supplied
        curve = equity_curve or [snapshot.equity]

        scorecard = svc.generate_daily_scorecard(
            snapshot=snapshot,
            closed_today=trades,
            benchmark_returns=benchmarks,
            equity_curve=curve,
        )

        # Write to shared state
        app_state.latest_scorecard = scorecard
        app_state.evaluation_run_id = str(dt.date.today())

        app_state.evaluation_history.append(scorecard)
        if len(app_state.evaluation_history) > max_history:
            app_state.evaluation_history = app_state.evaluation_history[-max_history:]

        # Persist evaluation results to DB (fire-and-forget, Priority 20)
        _persist_evaluation_run(scorecard, cfg.operating_mode.value)

        # ── Phase 31: Daily evaluation alert ────────────────────────────────
        _alert_svc = getattr(app_state, "alert_service", None)
        if _alert_svc and getattr(cfg, "alert_on_daily_evaluation", True):
            from services.alerting.models import AlertEvent, AlertEventType, AlertSeverity
            _return_pct = float(scorecard.daily_return_pct or 0)
            _severity = (
                AlertSeverity.WARNING.value if _return_pct < -1.0
                else AlertSeverity.INFO.value
            )
            _alert_svc.send_alert(AlertEvent(
                event_type=AlertEventType.DAILY_EVALUATION.value,
                severity=_severity,
                title=f"APIS Daily Evaluation: {scorecard.scorecard_date} | return={_return_pct:.2f}%",
                payload={
                    "scorecard_date": str(scorecard.scorecard_date),
                    "daily_return_pct": str(scorecard.daily_return_pct),
                    "equity": str(scorecard.equity),
                    "position_count": scorecard.position_count,
                    "closed_trade_count": scorecard.closed_trade_count,
                    "hit_rate": str(scorecard.hit_rate),
                    "current_drawdown_pct": str(scorecard.current_drawdown_pct),
                },
            ))

        logger.info(
            "daily_evaluation_job_complete",
            scorecard_date=str(scorecard.scorecard_date),
            daily_return_pct=str(scorecard.daily_return_pct),
            position_count=scorecard.position_count,
        )
        return {
            "status": "ok",
            "scorecard_date": str(scorecard.scorecard_date),
            "daily_return_pct": str(scorecard.daily_return_pct),
            "run_at": run_at.isoformat(),
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("daily_evaluation_job_failed", error=str(exc))
        return {
            "status": "error",
            "scorecard_date": None,
            "daily_return_pct": None,
            "run_at": run_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# run_attribution_analysis
# ---------------------------------------------------------------------------

def run_attribution_analysis(
    app_state: ApiAppState,
    settings: Settings | None = None,
    closed_trades: list[Any] | None = None,
    evaluation_service: Any | None = None,
) -> dict[str, Any]:
    """Run attribution analysis on closed trades and log the result.

    This is a lightweight companion to run_daily_evaluation, suitable for
    being scheduled independently or called on-demand.  It does NOT update
    app_state — attribution is already embedded in the scorecard via
    generate_daily_scorecard.  This job is useful for surfacing attribution
    data in logs.

    Args:
        app_state:          Shared ApiAppState (read-only here).
        settings:           Settings instance.
        closed_trades:      List of TradeRecord objects.  Defaults to empty.
        evaluation_service: EvaluationEngineService for injection/testing.

    Returns:
        dict with keys: status, by_ticker_count, by_strategy_count,
        by_theme_count, run_at.
    """
    from services.evaluation_engine.service import EvaluationEngineService

    cfg = settings or get_settings()
    run_at = dt.datetime.now(dt.UTC)
    svc = evaluation_service or EvaluationEngineService()

    logger.info("attribution_analysis_job_starting", run_at=run_at.isoformat())

    try:
        trades = closed_trades or []
        attribution = svc.compute_attribution(trades)

        logger.info(
            "attribution_analysis_job_complete",
            by_ticker=len(attribution.by_ticker),
            by_strategy=len(attribution.by_strategy),
            by_theme=len(attribution.by_theme),
        )
        return {
            "status": "ok",
            "by_ticker_count": len(attribution.by_ticker),
            "by_strategy_count": len(attribution.by_strategy),
            "by_theme_count": len(attribution.by_theme),
            "run_at": run_at.isoformat(),
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("attribution_analysis_job_failed", error=str(exc))
        return {
            "status": "error",
            "by_ticker_count": 0,
            "by_strategy_count": 0,
            "by_theme_count": 0,
            "run_at": run_at.isoformat(),
        }
