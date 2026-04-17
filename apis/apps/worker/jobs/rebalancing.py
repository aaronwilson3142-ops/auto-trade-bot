"""Worker job: portfolio rebalancing refresh (Phase 49).

``run_rebalance_check``
    Reads the latest ranking list from app_state, computes target weights
    (equal-weight over max_positions top-ranked tickers), measures per-ticker
    drift vs. held positions, and writes the result to app_state.

    Runs at 06:26 ET (after universe_refresh, before signal_generation) so
    that the paper trading cycle can use fresh rebalance targets.

Design rules
------------
- Fire-and-forget: exceptions are caught; scheduler thread never dies.
- Falls back to UNIVERSE_TICKERS when no rankings are available.
- No DB writes — purely in-memory state update.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from config.logging_config import get_logger
from config.settings import Settings, get_settings

logger = get_logger(__name__)


def run_rebalance_check(
    app_state: Any,
    settings: Settings | None = None,
) -> dict:
    """Compute rebalance targets and drift; persist to app_state.

    Args:
        app_state: ApiAppState singleton.
        settings: Settings object (defaults to get_settings()).

    Returns:
        Dict with status, drift_count, trim_count, open_count.
    """
    cfg = settings or get_settings()
    run_at = dt.datetime.now(dt.UTC)

    try:
        if not getattr(cfg, "enable_rebalancing", True):
            logger.info("rebalance_check_disabled")
            return {"status": "disabled", "run_at": run_at.isoformat()}

        from services.risk_engine.rebalancing import RebalancingService

        max_positions: int = int(getattr(cfg, "max_positions", 10))

        # Pull ranked tickers from latest_rankings; fall back to active_universe
        rankings = getattr(app_state, "latest_rankings", [])
        if rankings:
            ranked_tickers = [
                getattr(r, "ticker", None) or r.get("ticker", "") if isinstance(r, dict) else getattr(r, "ticker", "")
                for r in rankings
            ]
            ranked_tickers = [t for t in ranked_tickers if t]
        else:
            ranked_tickers = list(getattr(app_state, "active_universe", []))
            if not ranked_tickers:
                from config.universe import UNIVERSE_TICKERS
                ranked_tickers = list(UNIVERSE_TICKERS)

        # -- Deep-Dive Plan Step 4 (Rec 6) -- score-weighted rebalance --------
        # Default method="equal" + enabled=False preserves legacy 1/N behaviour
        # byte-for-byte. Operator must flip APIS_SCORE_WEIGHTED_REBALANCE_ENABLED
        # AND set APIS_REBALANCE_WEIGHTING_METHOD to "score" or "score_invvol"
        # to activate the new paths.
        _method = str(getattr(cfg, "rebalance_weighting_method", "equal"))
        _method_on = bool(getattr(cfg, "score_weighted_rebalance_enabled", False))
        if _method_on and _method in ("score", "score_invvol"):
            from services.rebalancing_engine import compute_weights as _compute_weights  # noqa: PLC0415

            _scores: dict[str, float] = {}
            for _r in rankings or []:
                _t = getattr(_r, "ticker", None) or (
                    _r.get("ticker", "") if isinstance(_r, dict) else ""
                )
                if isinstance(_r, dict):
                    _cs = _r.get("composite_score", None)
                else:
                    _cs = getattr(_r, "composite_score", None)
                if _t and _cs is not None:
                    try:
                        _scores[_t] = float(_cs)
                    except (TypeError, ValueError):
                        continue
            _vols = getattr(app_state, "latest_volatility_20d", {}) or {}
            _alloc = _compute_weights(
                ranked_tickers=ranked_tickers,
                n_positions=max_positions,
                method=_method,
                enabled=True,
                scores=_scores,
                volatilities=_vols,
                min_floor_fraction=float(
                    getattr(cfg, "rebalance_min_weight_floor_fraction", 0.10)
                ),
                max_single_weight=float(
                    getattr(cfg, "rebalance_max_single_weight", 0.20)
                ),
            )
            target_weights = _alloc.weights
            logger.info(
                "rebalance_weighted_allocation",
                method=_alloc.method_used,
                tickers=_alloc.tickers_considered,
                floor_applied=_alloc.floor_applied_count,
                cap_applied=_alloc.cap_applied_count,
                fell_back=_alloc.fell_back_to_equal,
                reason=_alloc.reason,
            )
        else:
            target_weights = RebalancingService.compute_target_weights(
                ranked_tickers=ranked_tickers,
                n_positions=max_positions,
            )

        # Measure drift against current positions (if portfolio state available)
        portfolio_state = getattr(app_state, "portfolio_state", None)
        positions = getattr(portfolio_state, "positions", {}) if portfolio_state else {}
        equity = float(getattr(portfolio_state, "equity", 0) or 0) if portfolio_state else 0.0

        threshold_pct: float = float(getattr(cfg, "rebalance_threshold_pct", 0.05))
        min_trade_usd: float = float(getattr(cfg, "rebalance_min_trade_usd", 500.0))

        drift_entries = RebalancingService.compute_drift(
            positions=positions,
            target_weights=target_weights,
            equity=equity,
            threshold_pct=threshold_pct,
            min_trade_usd=min_trade_usd,
        )

        drift_count = len([e for e in drift_entries if e.action_suggested != "HOLD"])
        trim_count = len([e for e in drift_entries if e.action_suggested == "TRIM"])
        open_count = len([e for e in drift_entries if e.action_suggested == "OPEN"])

        # Write to app_state
        app_state.rebalance_targets = target_weights
        app_state.rebalance_computed_at = run_at
        app_state.rebalance_drift_count = drift_count

        logger.info(
            "rebalance_check_complete",
            target_count=len(target_weights),
            drift_count=drift_count,
            trim_count=trim_count,
            open_count=open_count,
        )

        return {
            "status": "ok",
            "run_at": run_at.isoformat(),
            "target_count": len(target_weights),
            "drift_count": drift_count,
            "trim_count": trim_count,
            "open_count": open_count,
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("rebalance_check_failed", error=str(exc))
        return {
            "status": "error",
            "run_at": run_at.isoformat(),
            "error": str(exc),
        }
