"""Response schemas for /api/v1/config/* and /api/v1/risk/* endpoints."""
from __future__ import annotations

from pydantic import BaseModel


class ActiveConfigResponse(BaseModel):
    env: str
    operating_mode: str
    ranking_config_version: str
    feature_version_label: str
    max_positions: int
    daily_loss_limit_pct: float
    weekly_drawdown_limit_pct: float
    max_single_name_pct: float
    max_sector_pct: float
    max_thematic_pct: float
    kill_switch: bool
    promoted_versions: dict[str, str]   # component → version label


class RiskStatusResponse(BaseModel):
    kill_switch_active: bool
    operating_mode: str
    max_positions: int
    current_positions: int
    loss_limit_status: str      # "ok" | "warning" | "tripped"
    drawdown_status: str        # "ok" | "warning" | "tripped"
    active_warnings: list[str]
    blocked_action_count: int
