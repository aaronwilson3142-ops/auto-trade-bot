"""
Worker job: portfolio VaR & CVaR refresh (Phase 43).

``run_var_refresh``
    Queries the feature store DB for recent daily close prices for all
    universe tickers, then invokes VaRService to compute 1-day historical-
    simulation VaR and CVaR for the current portfolio.  Stores the result
    in ``app_state.latest_var_result`` so that the paper trading cycle can
    gate new OPEN actions when tail risk is elevated.

Design rules
------------
- Fire-and-forget: all exceptions caught; scheduler thread never dies.
- Graceful degradation: on DB failure app_state.latest_var_result is left
  unchanged (stale-but-safe rather than cleared).
- Skips gracefully when app_state.portfolio_state is None (no paper cycle
  has run yet) — VaR is meaningless without a live portfolio.
- Runs at 06:19 ET — after fundamentals_refresh (06:18),
  before regime_detection (06:20).
- No writes to DB — pure read job.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from apps.api.state import ApiAppState
from config.logging_config import get_logger
from config.settings import Settings, get_settings

logger = get_logger(__name__)

# Trading days of bar history to load (calendar-day window used in the query).
_LOOKBACK_CALENDAR_DAYS = 400   # ~252 trading days within a 400-calendar-day window


def run_var_refresh(
    app_state: ApiAppState,
    settings: Settings | None = None,
    session_factory: Any | None = None,
) -> dict[str, Any]:
    """Load bar data and compute portfolio VaR/CVaR.

    Args:
        app_state:       Shared ApiAppState; var fields are updated on success.
        settings:        Settings instance; falls back to get_settings().
        session_factory: SQLAlchemy session factory; skips DB step when None.

    Returns:
        dict with keys: status, positions_count, lookback_days, var_95_pct,
        computed_at, error.
    """
    cfg = settings or get_settings()  # noqa: F841
    run_at = dt.datetime.now(dt.UTC)

    logger.info("var_refresh_starting")

    # ── Requires a live portfolio ──────────────────────────────────────────
    portfolio_state = getattr(app_state, "portfolio_state", None)
    if portfolio_state is None or not getattr(portfolio_state, "positions", {}):
        logger.info("var_refresh_skipped_no_portfolio")
        return {
            "status": "skipped_no_portfolio",
            "positions_count": 0,
            "lookback_days": 0,
            "var_95_pct": None,
            "computed_at": run_at.isoformat(),
            "error": "no portfolio state",
        }

    if session_factory is None:
        logger.warning("var_refresh_skipped_no_db")
        return {
            "status": "skipped_no_db",
            "positions_count": 0,
            "lookback_days": 0,
            "var_95_pct": None,
            "computed_at": run_at.isoformat(),
            "error": "no session_factory",
        }

    try:
        from services.risk_engine.var_service import VaRService  # noqa: PLC0415

        positions = portfolio_state.positions
        equity: float = float(getattr(portfolio_state, "equity", 0.0))

        if equity <= 0.0:
            logger.warning("var_refresh_skipped_zero_equity")
            return {
                "status": "skipped_zero_equity",
                "positions_count": 0,
                "lookback_days": 0,
                "var_95_pct": None,
                "computed_at": run_at.isoformat(),
                "error": "equity is zero",
            }

        tickers = list(positions.keys())
        cutoff = (run_at - dt.timedelta(days=_LOOKBACK_CALENDAR_DAYS)).date()

        price_history: dict[str, list[float]] = {}

        try:
            from infra.db.models.market_data import DailyMarketBar  # noqa: PLC0415

            with session_factory() as session:
                rows = (
                    session.query(
                        DailyMarketBar.ticker,
                        DailyMarketBar.bar_date,
                        DailyMarketBar.close_price,
                    )
                    .filter(
                        DailyMarketBar.ticker.in_(tickers),
                        DailyMarketBar.bar_date >= cutoff,
                    )
                    .order_by(DailyMarketBar.ticker, DailyMarketBar.bar_date)
                    .all()
                )

            # Group close prices by ticker in date order (oldest first)
            for ticker, _date, close in rows:
                if close is not None and ticker in tickers:
                    price_history.setdefault(ticker, []).append(float(close))

        except Exception as db_exc:  # noqa: BLE001
            logger.warning("var_refresh_db_load_failed", error=str(db_exc))
            return {
                "status": "error_db",
                "positions_count": len(positions),
                "lookback_days": 0,
                "var_95_pct": None,
                "computed_at": run_at.isoformat(),
                "error": str(db_exc),
            }

        if not price_history:
            logger.warning("var_refresh_no_bar_data")
            return {
                "status": "no_data",
                "positions_count": len(positions),
                "lookback_days": 0,
                "var_95_pct": None,
                "computed_at": run_at.isoformat(),
                "error": "no bar data found for portfolio tickers",
            }

        # ── Compute VaR ───────────────────────────────────────────────────
        var_result = VaRService.compute_var_result(
            positions=positions,
            price_history=price_history,
            equity=equity,
        )

        # ── Update app_state ──────────────────────────────────────────────
        app_state.latest_var_result = var_result
        app_state.var_computed_at = run_at

        logger.info(
            "var_refresh_complete",
            positions_count=var_result.positions_count,
            lookback_days=var_result.lookback_days,
            var_95_pct=round(var_result.portfolio_var_95_pct * 100, 3),
            cvar_95_pct=round(var_result.portfolio_cvar_95_pct * 100, 3),
            insufficient_data=var_result.insufficient_data,
        )

        return {
            "status": "ok",
            "positions_count": var_result.positions_count,
            "lookback_days": var_result.lookback_days,
            "var_95_pct": round(var_result.portfolio_var_95_pct * 100, 4),
            "computed_at": run_at.isoformat(),
            "error": None,
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("var_refresh_failed", error=str(exc))
        return {
            "status": "error",
            "positions_count": 0,
            "lookback_days": 0,
            "var_95_pct": None,
            "computed_at": run_at.isoformat(),
            "error": str(exc),
        }
