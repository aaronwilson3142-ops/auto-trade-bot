"""
Worker job: Automated Live-Mode Readiness Report (Phase 53).

``run_readiness_report_update``
    Evening job that generates a pre-computed readiness snapshot by
    running all live-gate checks and caching the result in app_state.

    Runs at 18:45 ET — after all other evening jobs have completed
    (fill_quality_update at 18:30 is the previous last job), so the
    report reflects the latest signal quality, fill quality, evaluation
    history, and drawdown state for the day.

    Never raises — errors are logged at WARNING level only.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from apps.api.state import ApiAppState
from config.logging_config import get_logger
from config.settings import Settings, get_settings

logger = get_logger(__name__)


def run_readiness_report_update(
    app_state: ApiAppState,
    settings: Settings | None = None,
    session_factory: Any = None,
) -> dict[str, Any]:
    """Generate and cache the live-mode readiness report.

    Args:
        app_state:       Shared ApiAppState; writes latest_readiness_report
                         and readiness_report_computed_at on success.
        settings:        Settings instance; falls back to get_settings().
        session_factory: DB session factory for fire-and-forget snapshot persist.
                         When None, snapshot persistence is skipped.

    Returns:
        dict with keys: status, overall_status, gate_count, computed_at, error.
    """
    cfg = settings or get_settings()
    run_at = dt.datetime.now(dt.UTC)

    try:
        from services.readiness.service import ReadinessReportService

        svc = ReadinessReportService()
        report = svc.generate_report(app_state=app_state, settings=cfg)

        app_state.latest_readiness_report = report
        app_state.readiness_report_computed_at = run_at

        # Phase 56: Fire-and-forget snapshot persist for history tracking
        svc.persist_snapshot(report=report, session_factory=session_factory)

        logger.info(
            "readiness_report_update_complete",
            overall_status=report.overall_status,
            gate_count=report.gate_count,
            pass_count=report.pass_count,
            warn_count=report.warn_count,
            fail_count=report.fail_count,
            current_mode=report.current_mode,
            target_mode=report.target_mode,
        )

        return {
            "status": "ok",
            "overall_status": report.overall_status,
            "gate_count": report.gate_count,
            "computed_at": run_at.isoformat(),
            "error": None,
        }

    except Exception as exc:  # noqa: BLE001
        logger.warning("readiness_report_update_failed", error=str(exc))
        return {
            "status": "error",
            "overall_status": None,
            "gate_count": 0,
            "computed_at": run_at.isoformat(),
            "error": str(exc),
        }
