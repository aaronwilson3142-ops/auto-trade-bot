"""Phase 49 — Portfolio Rebalancing Engine routes.

Endpoints
---------
GET /portfolio/rebalance-status
    Returns current target weights, per-ticker drift, and action suggestions.
    Reads from app_state.rebalance_targets + portfolio_state for live drift.
    Returns 200 + empty drift list when no data is available yet.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter

from apps.api.deps import AppStateDep, SettingsDep
from apps.api.schemas.rebalancing import DriftEntrySchema, RebalanceStatusResponse

rebalance_router = APIRouter(tags=["Portfolio"])


@rebalance_router.get(
    "/portfolio/rebalance-status",
    response_model=RebalanceStatusResponse,
    summary="Portfolio rebalance status and drift",
)
async def get_rebalance_status(
    state: AppStateDep,
    cfg: SettingsDep,
) -> RebalanceStatusResponse:
    """Return current rebalancing targets, per-ticker drift, and action suggestions.

    Computes live drift on each request using the most recent target_weights
    (set by run_rebalance_check at 06:26 ET) and the current portfolio_state.

    Returns an empty drift list with HTTP 200 when rebalancing has not yet run
    or portfolio state is unavailable (graceful degradation).
    """
    from services.risk_engine.rebalancing import RebalancingService

    enabled: bool = bool(getattr(cfg, "enable_rebalancing", True))
    threshold_pct: float = float(getattr(cfg, "rebalance_threshold_pct", 0.05))
    min_trade_usd: float = float(getattr(cfg, "rebalance_min_trade_usd", 500.0))
    max_positions: int = int(getattr(cfg, "max_positions", 10))

    target_weights: dict = getattr(state, "rebalance_targets", {}) or {}
    computed_at_raw = getattr(state, "rebalance_computed_at", None)
    computed_at_str: str | None = (
        computed_at_raw.isoformat() if computed_at_raw else None
    )

    portfolio_state = getattr(state, "portfolio_state", None)
    positions = getattr(portfolio_state, "positions", {}) if portfolio_state else {}
    equity = float(getattr(portfolio_state, "equity", 0) or 0) if portfolio_state else 0.0

    drift_entries: list[DriftEntrySchema] = []
    trim_count = open_count = hold_count = 0

    if enabled and target_weights and equity > 0:
        raw_entries = RebalancingService.compute_drift(
            positions=positions,
            target_weights=target_weights,
            equity=equity,
            threshold_pct=threshold_pct,
            min_trade_usd=min_trade_usd,
        )
        for e in raw_entries:
            drift_entries.append(DriftEntrySchema(
                ticker=e.ticker,
                current_weight=e.current_weight,
                target_weight=e.target_weight,
                drift_pct=e.drift_pct,
                drift_usd=e.drift_usd,
                action_suggested=e.action_suggested,
            ))
        trim_count = sum(1 for e in raw_entries if e.action_suggested == "TRIM")
        open_count = sum(1 for e in raw_entries if e.action_suggested == "OPEN")
        hold_count = sum(1 for e in raw_entries if e.action_suggested == "HOLD")

    return RebalanceStatusResponse(
        rebalance_enabled=enabled,
        computed_at=computed_at_str,
        target_n_positions=max_positions,
        total_equity=equity,
        drift_entries=drift_entries,
        trim_count=trim_count,
        open_count=open_count,
        hold_count=hold_count,
        threshold_pct=threshold_pct,
        min_trade_usd=min_trade_usd,
    )
