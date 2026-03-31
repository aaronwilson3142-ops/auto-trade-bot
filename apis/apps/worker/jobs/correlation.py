"""
Worker job: correlation matrix refresh (Phase 39).

``run_correlation_refresh``
    Loads recent DailyMarketBar close prices for universe tickers from the DB,
    computes daily return series, and invokes CorrelationService to build the
    pairwise Pearson correlation matrix.  Stores the result in ApiAppState so
    that the paper trading cycle can apply correlation-aware position sizing
    without blocking on a DB query mid-cycle.

Design rules
------------
- Fire-and-forget: all exceptions are caught; scheduler thread never dies.
- Graceful degradation: on DB failure app_state.correlation_matrix is left
  unchanged (stale-but-safe rather than empty).
- Runs at 06:16 ET (after feature_refresh at 06:15, before fundamentals at 06:18).
- Uses get_settings() fallback so the job remains testable with injection.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from apps.api.state import ApiAppState
from config.logging_config import get_logger
from config.settings import Settings, get_settings

logger = get_logger(__name__)


def run_correlation_refresh(
    app_state: ApiAppState,
    settings: Settings | None = None,
    session_factory: Any | None = None,
) -> dict[str, Any]:
    """Load bar data and compute the pairwise correlation matrix.

    Args:
        app_state:       Shared ApiAppState; correlation fields are updated.
        settings:        Settings instance; falls back to get_settings().
        session_factory: SQLAlchemy session factory; skips DB step when None.

    Returns:
        dict with keys: status, ticker_count, pair_count, computed_at, error.
    """
    cfg = settings or get_settings()
    run_at = dt.datetime.now(dt.UTC)

    logger.info("correlation_refresh_starting", lookback_days=cfg.correlation_lookback_days)

    if session_factory is None:
        logger.warning("correlation_refresh_skipped_no_db")
        return {
            "status": "skipped_no_db",
            "ticker_count": 0,
            "pair_count": 0,
            "computed_at": run_at.isoformat(),
            "error": "no session_factory",
        }

    try:
        from services.risk_engine.correlation import CorrelationService  # noqa: PLC0415

        lookback = cfg.correlation_lookback_days
        cutoff = (run_at - dt.timedelta(days=lookback)).date()

        bars_by_ticker: dict[str, list[float]] = {}

        try:
            from infra.db.models.market_data import DailyMarketBar  # noqa: PLC0415
            from infra.db.models.reference import Security  # noqa: PLC0415

            with session_factory() as session:
                # Pull close prices for all tickers within the lookback window.
                # DailyMarketBar normalises through security_id FK; join Security
                # to resolve the ticker symbol.  Correct column names:
                #   bar_date  -> trade_date
                #   close_price -> close
                rows = (
                    session.query(
                        Security.ticker,
                        DailyMarketBar.trade_date,
                        DailyMarketBar.close,
                    )
                    .join(Security, Security.id == DailyMarketBar.security_id)
                    .filter(DailyMarketBar.trade_date >= cutoff)
                    .order_by(Security.ticker, DailyMarketBar.trade_date)
                    .all()
                )

            # Group close prices by ticker in date order
            prices_by_ticker: dict[str, list[float]] = {}
            for ticker, _date, close in rows:
                if close is not None:
                    prices_by_ticker.setdefault(ticker, []).append(float(close))

            # Convert prices to daily returns: (p[t] - p[t-1]) / p[t-1]
            for ticker, prices in prices_by_ticker.items():
                if len(prices) < 2:
                    continue
                returns = [
                    (prices[i] - prices[i - 1]) / prices[i - 1]
                    for i in range(1, len(prices))
                    if prices[i - 1] != 0.0
                ]
                if returns:
                    bars_by_ticker[ticker] = returns

        except Exception as db_exc:  # noqa: BLE001
            logger.warning("correlation_refresh_db_load_failed", error=str(db_exc))
            return {
                "status": "error_db",
                "ticker_count": 0,
                "pair_count": 0,
                "computed_at": run_at.isoformat(),
                "error": str(db_exc),
            }

        if not bars_by_ticker:
            logger.warning("correlation_refresh_no_bar_data")
            return {
                "status": "no_data",
                "ticker_count": 0,
                "pair_count": 0,
                "computed_at": run_at.isoformat(),
                "error": "no bar data found",
            }

        matrix = CorrelationService.compute_correlation_matrix(bars_by_ticker)

        # Update app_state (in-memory; no DB write needed)
        app_state.correlation_matrix = matrix
        app_state.correlation_tickers = list(bars_by_ticker.keys())
        app_state.correlation_computed_at = run_at

        # Each pair is stored twice (a,b) and (b,a); report unique count
        pair_count = len(matrix) // 2

        logger.info(
            "correlation_refresh_complete",
            ticker_count=len(bars_by_ticker),
            pair_count=pair_count,
        )

        return {
            "status": "ok",
            "ticker_count": len(bars_by_ticker),
            "pair_count": pair_count,
            "computed_at": run_at.isoformat(),
            "error": None,
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("correlation_refresh_failed", error=str(exc))
        return {
            "status": "error",
            "ticker_count": 0,
            "pair_count": 0,
            "computed_at": run_at.isoformat(),
            "error": str(exc),
        }
