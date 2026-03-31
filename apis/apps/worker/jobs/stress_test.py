"""
Worker job: portfolio stress-test refresh (Phase 44).

``run_stress_test``
    Applies four built-in historical shock scenarios (2008 crisis, COVID 2020,
    rate shock 2022, dotcom bust 2001) to the current portfolio using
    sector-level return shocks.  Stores the result in
    ``app_state.latest_stress_result`` so that the paper trading cycle can
    gate new OPEN actions when worst-case stressed loss is elevated.

Design rules
------------
- Fire-and-forget: all exceptions caught; scheduler thread never dies.
- Graceful degradation: on error app_state.latest_stress_result is left
  unchanged (stale-but-safe rather than cleared).
- Skips gracefully when app_state.portfolio_state is None (no paper cycle
  has run yet) — stress testing is meaningless without a live portfolio.
- Runs at 06:21 ET — after var_refresh (06:19) and regime_detection (06:20),
  before feature_enrichment (06:22).
- Pure computation job — no DB reads or writes.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from apps.api.state import ApiAppState
from config.logging_config import get_logger
from config.settings import Settings, get_settings

logger = get_logger(__name__)


def run_stress_test(
    app_state: ApiAppState,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    """Compute portfolio stress-test result and store in app_state.

    Args:
        app_state: Shared ApiAppState; stress fields are updated on success.
        settings:  Settings instance; falls back to get_settings().

    Returns:
        dict with keys: status, positions_count, worst_case_scenario,
        worst_case_loss_pct, computed_at, error.
    """
    cfg = settings or get_settings()  # noqa: F841
    run_at = dt.datetime.now(dt.timezone.utc)

    logger.info("stress_test_refresh_starting")

    # ── Requires a live portfolio ──────────────────────────────────────────
    portfolio_state = getattr(app_state, "portfolio_state", None)
    if portfolio_state is None or not getattr(portfolio_state, "positions", {}):
        logger.info("stress_test_refresh_skipped_no_portfolio")
        return {
            "status": "skipped_no_portfolio",
            "positions_count": 0,
            "worst_case_scenario": None,
            "worst_case_loss_pct": None,
            "computed_at": run_at.isoformat(),
            "error": "no portfolio state",
        }

    try:
        from services.risk_engine.stress_test import StressTestService  # noqa: PLC0415

        positions = portfolio_state.positions
        equity: float = float(getattr(portfolio_state, "equity", 0.0))

        if equity <= 0.0:
            logger.warning("stress_test_refresh_skipped_zero_equity")
            return {
                "status": "skipped_zero_equity",
                "positions_count": 0,
                "worst_case_scenario": None,
                "worst_case_loss_pct": None,
                "computed_at": run_at.isoformat(),
                "error": "equity is zero",
            }

        stress_result = StressTestService.run_all_scenarios(
            positions=positions,
            equity=equity,
        )

        # ── Update app_state ──────────────────────────────────────────────
        app_state.latest_stress_result = stress_result
        app_state.stress_computed_at = run_at

        logger.info(
            "stress_test_refresh_complete",
            positions_count=stress_result.positions_count,
            worst_case_scenario=stress_result.worst_case_scenario,
            worst_case_loss_pct=round(stress_result.worst_case_loss_pct * 100, 2),
            no_positions=stress_result.no_positions,
        )

        return {
            "status": "ok",
            "positions_count": stress_result.positions_count,
            "worst_case_scenario": stress_result.worst_case_scenario,
            "worst_case_loss_pct": round(stress_result.worst_case_loss_pct * 100, 4),
            "computed_at": run_at.isoformat(),
            "error": None,
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("stress_test_refresh_failed", error=str(exc))
        return {
            "status": "error",
            "positions_count": 0,
            "worst_case_scenario": None,
            "worst_case_loss_pct": None,
            "computed_at": run_at.isoformat(),
            "error": str(exc),
        }
