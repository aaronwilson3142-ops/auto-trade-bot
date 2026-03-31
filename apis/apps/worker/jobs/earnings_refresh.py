"""
Worker job: earnings calendar refresh (Phase 45).

``run_earnings_refresh``
    Fetches the next earnings date for every ticker in the configured universe
    using yfinance, identifies tickers with earnings within the proximity
    window (max_earnings_proximity_days), and stores the result in
    app_state.latest_earnings_calendar so the paper trading cycle can gate
    new OPEN actions.

Design rules
------------
- Fire-and-forget: all exceptions caught; scheduler thread never dies.
- Graceful degradation: on error app_state.latest_earnings_calendar is left
  unchanged (stale-but-safe rather than cleared).
- Skips gracefully when the universe is empty.
- Runs at 06:23 ET — after stress_test (06:21) and feature_enrichment (06:22),
  before signal_generation (06:30).
- Pure computation job — no DB reads or writes.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from apps.api.state import ApiAppState
from config.logging_config import get_logger
from config.settings import Settings, get_settings

logger = get_logger(__name__)


def run_earnings_refresh(
    app_state: ApiAppState,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    """Fetch upcoming earnings dates and store result in app_state.

    Args:
        app_state: Shared ApiAppState; earnings fields are updated on success.
        settings:  Settings instance; falls back to get_settings().

    Returns:
        dict with keys: status, tickers_checked, at_risk_count,
        at_risk_tickers, computed_at, error.
    """
    cfg = settings or get_settings()
    run_at = dt.datetime.now(dt.timezone.utc)

    logger.info("earnings_refresh_starting")

    try:
        from config.universe import UNIVERSE_TICKERS  # noqa: PLC0415
        from services.risk_engine.earnings_calendar import EarningsCalendarService  # noqa: PLC0415

        max_days: int = int(getattr(cfg, "max_earnings_proximity_days", 2))
        tickers: list[str] = list(UNIVERSE_TICKERS)

        if not tickers:
            logger.info("earnings_refresh_skipped_empty_universe")
            return {
                "status": "skipped_empty_universe",
                "tickers_checked": 0,
                "at_risk_count": 0,
                "at_risk_tickers": [],
                "computed_at": run_at.isoformat(),
                "error": "universe is empty",
            }

        calendar_result = EarningsCalendarService.build_calendar(
            tickers=tickers,
            max_earnings_proximity_days=max_days,
            reference_date=run_at.date(),
        )

        # ── Update app_state ─────────────────────────────────────────────
        app_state.latest_earnings_calendar = calendar_result
        app_state.earnings_computed_at = run_at
        app_state.earnings_filtered_count = 0  # reset; updated during paper cycle

        logger.info(
            "earnings_refresh_complete",
            tickers_checked=len(calendar_result.entries),
            at_risk_count=len(calendar_result.at_risk_tickers),
            at_risk_tickers=calendar_result.at_risk_tickers,
        )

        return {
            "status": "ok",
            "tickers_checked": len(calendar_result.entries),
            "at_risk_count": len(calendar_result.at_risk_tickers),
            "at_risk_tickers": calendar_result.at_risk_tickers,
            "computed_at": run_at.isoformat(),
            "error": None,
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("earnings_refresh_failed", error=str(exc))
        return {
            "status": "error",
            "tickers_checked": 0,
            "at_risk_count": 0,
            "at_risk_tickers": [],
            "computed_at": run_at.isoformat(),
            "error": str(exc),
        }
