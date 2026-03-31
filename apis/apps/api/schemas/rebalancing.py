"""Phase 49 — Portfolio Rebalancing Engine schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class DriftEntrySchema(BaseModel):
    """Per-ticker drift between current and target allocation."""

    ticker: str
    current_weight: float = Field(description="Current allocation as fraction of equity")
    target_weight: float = Field(description="Target allocation as fraction of equity")
    drift_pct: float = Field(description="current_weight - target_weight (signed)")
    drift_usd: float = Field(description="drift_pct × equity in USD (signed)")
    action_suggested: str = Field(description="One of: TRIM, OPEN, HOLD")


class RebalanceStatusResponse(BaseModel):
    """Response for GET /portfolio/rebalance-status."""

    rebalance_enabled: bool
    computed_at: str | None = None
    target_n_positions: int
    total_equity: float
    drift_entries: list[DriftEntrySchema]
    trim_count: int
    open_count: int
    hold_count: int
    threshold_pct: float = Field(description="Drift threshold to trigger action")
    min_trade_usd: float = Field(description="Minimum trade size in USD")
