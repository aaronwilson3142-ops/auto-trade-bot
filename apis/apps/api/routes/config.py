"""Route handlers for /api/v1/config/* and /api/v1/risk/*.

Config-visibility and risk-status endpoints.
All endpoints are read-only (Gate G: Phase D Admin Visibility).
"""
from __future__ import annotations

from fastapi import APIRouter

from apps.api.deps import AppStateDep, SettingsDep
from apps.api.schemas.system import ActiveConfigResponse, RiskStatusResponse

router = APIRouter(tags=["Config & Risk"])


@router.get("/config/active", response_model=ActiveConfigResponse)
async def get_active_config(
    state: AppStateDep,
    settings: SettingsDep,
) -> ActiveConfigResponse:
    """Return active non-secret configuration identifiers and version labels."""
    return ActiveConfigResponse(
        env=settings.env.value,
        operating_mode=settings.operating_mode.value,
        ranking_config_version="ranking_v1",
        feature_version_label="baseline_v1",
        max_positions=settings.max_positions,
        daily_loss_limit_pct=settings.daily_loss_limit_pct,
        weekly_drawdown_limit_pct=settings.weekly_drawdown_limit_pct,
        max_single_name_pct=settings.max_single_name_pct,
        max_sector_pct=settings.max_sector_pct,
        max_thematic_pct=settings.max_thematic_pct,
        kill_switch=getattr(state, "kill_switch_active", False) or settings.kill_switch,
        promoted_versions=dict(state.promoted_versions),
    )


@router.get("/risk/status", response_model=RiskStatusResponse)
async def get_risk_status(
    state: AppStateDep,
    settings: SettingsDep,
) -> RiskStatusResponse:
    """Return current risk posture including kill switch, limits, and warnings."""
    ps = state.portfolio_state
    current_positions = ps.position_count if ps is not None else 0

    loss_limit_status = "ok"
    drawdown_status = "ok"

    if ps is not None:
        daily_loss = abs(float(ps.daily_pnl_pct))
        if daily_loss >= settings.daily_loss_limit_pct:
            loss_limit_status = "tripped"
        elif daily_loss >= settings.daily_loss_limit_pct * 0.8:
            loss_limit_status = "warning"

        drawdown = float(ps.drawdown_pct)
        if drawdown >= settings.weekly_drawdown_limit_pct:
            drawdown_status = "tripped"
        elif drawdown >= settings.weekly_drawdown_limit_pct * 0.8:
            drawdown_status = "warning"

    effective_kill = getattr(state, "kill_switch_active", False) or settings.kill_switch
    return RiskStatusResponse(
        kill_switch_active=effective_kill,
        operating_mode=settings.operating_mode.value,
        max_positions=settings.max_positions,
        current_positions=current_positions,
        loss_limit_status=loss_limit_status,
        drawdown_status=drawdown_status,
        active_warnings=list(state.active_warnings),
        blocked_action_count=state.blocked_action_count,
    )
