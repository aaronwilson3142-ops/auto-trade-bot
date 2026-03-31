"""Worker job: dynamic universe refresh (Phase 48).

``run_universe_refresh``
    Loads active operator overrides from DB, applies optional signal-quality
    pruning, and writes the resulting active_universe list to ApiAppState.

    Runs at 06:25 ET (after earnings_refresh, before signal_generation) so that
    run_signal_generation and run_ranking_generation always use an up-to-date
    universe.

Design rules
------------
- Fire-and-forget: exceptions are caught; scheduler thread never dies.
- Falls back to UNIVERSE_TICKERS when DB is unavailable.
- No override = active_universe == UNIVERSE_TICKERS (behaviour unchanged).
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from config.logging_config import get_logger
from config.settings import Settings, get_settings

logger = get_logger(__name__)


def run_universe_refresh(
    app_state: Any,
    settings: Settings | None = None,
    session_factory: Any = None,
) -> dict:
    """Compute and persist the active universe to app_state.

    Args:
        app_state: ApiAppState singleton.
        settings: Settings object (defaults to get_settings()).
        session_factory: SQLAlchemy session factory (None = skip DB).

    Returns:
        Dict with status, active_count, override_count.
    """
    cfg = settings or get_settings()
    run_at = dt.datetime.now(dt.UTC)

    try:
        from config.universe import UNIVERSE_TICKERS
        from services.universe_management.service import UniverseManagementService

        min_quality: float = float(
            getattr(cfg, "min_universe_signal_quality_score", 0.0)
        )

        # Load active overrides from DB (empty list if DB unavailable)
        overrides = UniverseManagementService.load_active_overrides(
            session_factory=session_factory,
            reference_dt=run_at,
        )

        # Build per-ticker quality score dict from latest signal quality report
        quality_scores: dict[str, float] | None = None
        latest_quality = getattr(app_state, "latest_signal_quality", None)
        if latest_quality is not None and min_quality > 0.0:
            # SignalQualityReport.strategy_quality is dict[str, StrategyQualityStats]
            # Aggregate: for each ticker across strategies, use best win_rate seen
            # (conservative: don't remove a ticker that any strategy finds valuable)
            per_ticker: dict[str, list[float]] = {}
            sq = getattr(latest_quality, "strategy_quality", {})
            for _strat, stats in sq.items():
                wr = getattr(stats, "win_rate", None)
                # stats doesn't have per-ticker scores; use strategy-level win_rate
                # as proxy applied equally to all tickers scored by that strategy
                if wr is not None:
                    for ticker in UNIVERSE_TICKERS:
                        per_ticker.setdefault(ticker, []).append(float(wr))
            if per_ticker:
                quality_scores = {
                    t: sum(scores) / len(scores) for t, scores in per_ticker.items()
                }

        # Compute active universe
        active = UniverseManagementService.get_active_universe(
            base_tickers=list(UNIVERSE_TICKERS),
            overrides=overrides,
            signal_quality_scores=quality_scores,
            min_quality_score=min_quality,
            reference_dt=run_at,
        )

        # Persist to app_state
        app_state.active_universe = active
        app_state.universe_computed_at = run_at
        app_state.universe_override_count = len(overrides)

        logger.info(
            "universe_refresh_complete",
            active_count=len(active),
            base_count=len(UNIVERSE_TICKERS),
            override_count=len(overrides),
            quality_pruning_enabled=min_quality > 0.0,
        )

        return {
            "status": "ok",
            "run_at": run_at.isoformat(),
            "active_count": len(active),
            "base_count": len(UNIVERSE_TICKERS),
            "override_count": len(overrides),
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("universe_refresh_failed", error=str(exc))
        return {
            "status": "error",
            "run_at": run_at.isoformat(),
            "error": str(exc),
        }
