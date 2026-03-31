"""Schemas for the exit-levels REST endpoint (Phase 42)."""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class PositionExitLevelSchema(BaseModel):
    ticker: str
    current_price: float
    avg_entry_price: float
    unrealized_pnl_pct: float          # e.g. 0.12 = 12%
    peak_price: Optional[float]        # highest price seen since entry
    # Computed levels (None when feature is disabled)
    stop_loss_level: Optional[float]   # entry * (1 - stop_loss_pct)
    trailing_stop_level: Optional[float]  # peak * (1 - trailing_stop_pct)
    take_profit_level: Optional[float] # entry * (1 + take_profit_pct)
    # Status flags
    trailing_stop_activated: bool      # True when gain >= activation_pct
    stop_loss_pct: float
    trailing_stop_pct: float
    take_profit_pct: float


class ExitLevelsResponse(BaseModel):
    positions: list[PositionExitLevelSchema]
    trailing_stop_pct: float
    trailing_stop_activation_pct: float
    take_profit_pct: float
    computed_at: str
