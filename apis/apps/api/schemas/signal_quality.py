"""
Signal quality API schemas (Phase 46).

Three response models:
  StrategyQualitySchema        — per-strategy statistics row
  SignalQualityReportResponse  — full report (all strategies)
  StrategyQualityDetailResponse — single-strategy detail (used by /{strategy_name})
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class StrategyQualitySchema(BaseModel):
    """Signal quality statistics for one strategy."""

    strategy_name: str
    prediction_count: int
    win_count: int
    win_rate: float
    avg_return_pct: float
    best_return_pct: float
    worst_return_pct: float
    avg_hold_days: float
    sharpe_estimate: float


class SignalQualityReportResponse(BaseModel):
    """Full signal quality report across all tracked strategies.

    Returned by GET /signals/quality.
    """

    computed_at: Optional[datetime]
    total_outcomes_recorded: int
    strategies_with_data: List[str]
    strategy_count: int
    strategy_results: List[StrategyQualitySchema]
    data_available: bool


class StrategyQualityDetailResponse(BaseModel):
    """Single-strategy detail response.

    Returned by GET /signals/quality/{strategy_name}.
    data_available=False when no outcomes exist for the requested strategy.
    """

    strategy_name: str
    data_available: bool
    computed_at: Optional[datetime] = None
    prediction_count: int = 0
    win_count: int = 0
    win_rate: float = 0.0
    avg_return_pct: float = 0.0
    best_return_pct: float = 0.0
    worst_return_pct: float = 0.0
    avg_hold_days: float = 0.0
    sharpe_estimate: float = 0.0
