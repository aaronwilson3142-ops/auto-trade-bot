"""
Worker job: generate daily operational report and publish operator summary.

Functions
---------
run_generate_daily_report    — assemble DailyOperationalReport from state
run_publish_operator_summary — log/print a human-readable operator summary

Design rules
------------
- Reads from ApiAppState (portfolio_state, latest_scorecard, improvement_proposals).
- Writes latest_daily_report and appends to report_history in ApiAppState.
- No DB session required: all data flows in-memory.
- Exceptions are caught; jobs must never crash the scheduler thread.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from apps.api.state import ApiAppState
from config.logging_config import get_logger
from config.settings import Settings, get_settings

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# run_generate_daily_report
# ---------------------------------------------------------------------------

def run_generate_daily_report(
    app_state: ApiAppState,
    settings: Settings | None = None,
    orders: list[Any] | None = None,
    reconciliation: Any | None = None,
    reporting_service: Any | None = None,
    max_history: int = 90,
) -> dict[str, Any]:
    """Assemble and store the daily operational report.

    Reads portfolio state and evaluation scorecard from app_state to build a
    DailyOperationalReport.  Writes to app_state.latest_daily_report and
    appends to app_state.report_history.

    Args:
        app_state:          Shared ApiAppState (read + write).
        settings:           Settings instance.
        orders:             List of Order objects submitted today.  Defaults to [].
        reconciliation:     FillReconciliationSummary from the broker layer.
                            Defaults to an empty summary.
        reporting_service:  ReportingService for injection/testing.
        max_history:        Maximum report_history entries to retain.

    Returns:
        dict with keys: status, report_date, daily_return_pct, run_at.
    """
    from services.reporting.models import FillReconciliationSummary
    from services.reporting.service import ReportingService

    cfg = settings or get_settings()
    run_at = dt.datetime.now(dt.UTC)
    today = run_at.date()
    svc = reporting_service or ReportingService()

    logger.info("reporting_job_starting", run_at=run_at.isoformat())

    try:
        # ── Derive figures from portfolio state ───────────────────────────────
        ps = app_state.portfolio_state
        if ps is not None:
            equity = ps.equity
            cash = ps.cash
            gross_exposure = ps.gross_exposure
            position_count = ps.position_count
            unrealized_pnl = sum(
                (p.unrealized_pnl for p in ps.positions.values()), Decimal("0")
            )
            start_of_day_equity = ps.start_of_day_equity or equity
        else:
            equity = Decimal("0")
            cash = Decimal("0")
            gross_exposure = Decimal("0")
            position_count = 0
            unrealized_pnl = Decimal("0")
            start_of_day_equity = Decimal("0")

        realized_pnl = Decimal("0")  # would come from closed trades in full pipeline

        # ── Scorecard grade and benchmark differentials ───────────────────────
        scorecard_grade: str | None = None
        benchmark_differentials: dict[str, Decimal] = {}

        sc = app_state.latest_scorecard
        if sc is not None:
            scorecard_grade = _derive_grade(sc)
            if hasattr(sc, "benchmark_comparison") and sc.benchmark_comparison:
                benchmark_differentials = dict(
                    sc.benchmark_comparison.differentials or {}
                )
            realized_pnl = getattr(sc, "realized_pnl", Decimal("0"))

        # ── Self-improvement counts ───────────────────────────────────────────
        proposals_generated = len(app_state.improvement_proposals)
        proposals_promoted = sum(
            1
            for p in app_state.improvement_proposals
            if getattr(p, "status", None) == "promoted"
        )

        # ── Reconciliation ────────────────────────────────────────────────────
        recon = reconciliation or FillReconciliationSummary(records=[])

        # ── Assemble report ───────────────────────────────────────────────────
        report = svc.generate_daily_report(
            report_date=today,
            equity=equity,
            cash=cash,
            gross_exposure=gross_exposure,
            position_count=position_count,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            start_of_day_equity=start_of_day_equity,
            orders=orders or [],
            reconciliation=recon,
            scorecard_grade=scorecard_grade,
            benchmark_differentials=benchmark_differentials,
            improvement_proposals_generated=proposals_generated,
            improvement_proposals_promoted=proposals_promoted,
        )

        # ── Write back ────────────────────────────────────────────────────────
        app_state.latest_daily_report = report
        app_state.report_history.append(report)
        if len(app_state.report_history) > max_history:
            app_state.report_history = app_state.report_history[-max_history:]

        logger.info(
            "reporting_job_complete",
            report_date=str(today),
            grade=scorecard_grade,
            proposals=proposals_generated,
        )
        return {
            "status": "ok",
            "report_date": str(today),
            "daily_return_pct": str(
                ((equity - start_of_day_equity) / start_of_day_equity).quantize(
                    Decimal("0.0001")
                )
                if start_of_day_equity and start_of_day_equity != Decimal("0")
                else Decimal("0")
            ),
            "run_at": run_at.isoformat(),
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("reporting_job_failed", error=str(exc))
        return {
            "status": "error",
            "report_date": str(today),
            "daily_return_pct": None,
            "run_at": run_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# run_publish_operator_summary
# ---------------------------------------------------------------------------

def run_publish_operator_summary(
    app_state: ApiAppState,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Log a structured operator summary of the current system state.

    Reads latest_daily_report and latest_scorecard from app_state.
    Emits a single structured log event suitable for operator monitoring.

    Args:
        app_state: Shared ApiAppState (read-only).
        settings:  Settings instance.

    Returns:
        dict with keys: status, lines_emitted, run_at.
    """
    cfg = settings or get_settings()
    run_at = dt.datetime.now(dt.UTC)

    logger.info("publish_operator_summary_starting", run_at=run_at.isoformat())

    try:
        report = app_state.latest_daily_report
        scorecard = app_state.latest_scorecard
        rankings_count = len(app_state.latest_rankings)

        summary: dict[str, Any] = {
            "mode": cfg.operating_mode.value,
            "rankings_available": rankings_count,
            "portfolio_positions": (
                app_state.portfolio_state.position_count
                if app_state.portfolio_state
                else 0
            ),
            "scorecard_grade": _derive_grade(scorecard) if scorecard else "N/A",
            "proposals_generated": len(app_state.improvement_proposals),
            "kill_switch": cfg.is_kill_switch_active,
        }

        if report is not None:
            summary["report_date"] = str(report.report_date)
            summary["daily_return_pct"] = str(report.daily_return_pct)
            summary["reconciliation_clean"] = report.reconciliation_clean
            summary["narrative"] = report.narrative

        logger.info("operator_summary", **summary)

        return {
            "status": "ok",
            "lines_emitted": 1,
            "run_at": run_at.isoformat(),
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("publish_operator_summary_failed", error=str(exc))
        return {
            "status": "error",
            "lines_emitted": 0,
            "run_at": run_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _derive_grade(scorecard: Any) -> str | None:
    """Extract a letter grade from a DailyScorecard."""
    # DailyScorecard does not have a direct letter_grade field;
    # derive from daily_return_pct using standard evaluation thresholds.
    if scorecard is None:
        return None
    # If the scorecard already carries a grade attribute, prefer it.
    if hasattr(scorecard, "grade"):
        return scorecard.grade
    # Fall back: positive return = B, zero/unknown = C
    ret = getattr(scorecard, "daily_return_pct", None)
    if ret is None:
        return "C"
    return "A" if ret >= Decimal("0.05") else "B" if ret > Decimal("0") else "D"
