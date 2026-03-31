"""Pydantic schemas for strategy weight profile endpoints."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WeightProfileSchema(BaseModel):
    """Serialised representation of one weight profile."""

    id: str
    profile_name: str
    source: str                         # "optimized" | "manual"
    weights: dict[str, float]           # strategy_key → weight (sums to ~1.0)
    sharpe_metrics: dict[str, float]    # strategy_key → Sharpe used (empty for manual)
    is_active: bool
    optimization_run_id: str | None = None
    notes: str | None = None
    created_at: Any | None = None


class WeightProfileListResponse(BaseModel):
    """Response for GET /signals/weights/history."""

    profiles: list[WeightProfileSchema] = Field(default_factory=list)
    count: int = 0


class OptimizeWeightsResponse(BaseModel):
    """Response for POST /signals/weights/optimize."""

    profile: WeightProfileSchema
    message: str = "Weight profile optimized and activated."


class SetActiveWeightResponse(BaseModel):
    """Response for PUT /signals/weights/active/{profile_id}."""

    profile_id: str
    message: str = "Weight profile activated."


class CreateManualWeightRequest(BaseModel):
    """Request body for POST /signals/weights/manual."""

    profile_name: str
    weights: dict[str, float]           # strategy_key → raw weight (will be normalised)
    notes: str | None = None
    set_active: bool = True
