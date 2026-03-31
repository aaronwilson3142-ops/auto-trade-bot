"""Pydantic schemas for the market regime detection API.

Phase 38 — Market Regime Detection + Regime-Adaptive Weight Profiles
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel


class RegimeCurrentResponse(BaseModel):
    """Current market regime state returned by GET /signals/regime."""

    regime: str                         # MarketRegime value
    confidence: float                   # [0.0, 1.0]
    detection_basis: dict[str, Any]     # signals / thresholds that drove the result
    is_manual_override: bool
    override_reason: str | None
    detected_at: dt.datetime | None
    regime_weights: dict[str, float]    # regime-adaptive strategy weights


class RegimeOverrideRequest(BaseModel):
    """Body for POST /signals/regime/override."""

    regime: str   # must be a valid MarketRegime value
    reason: str


class RegimeOverrideResponse(BaseModel):
    """Response after setting or clearing a manual override."""

    status: str                         # "override_set" | "override_cleared"
    regime: str | None
    is_manual_override: bool
    regime_weights: dict[str, float]


class RegimeSnapshotSchema(BaseModel):
    """One historical regime detection record."""

    id: str
    regime: str
    confidence: float
    is_manual_override: bool
    override_reason: str | None
    detected_at: dt.datetime | None

    class Config:
        from_attributes = True


class RegimeHistoryResponse(BaseModel):
    """Paginated list of regime snapshot records."""

    snapshots: list[RegimeSnapshotSchema]
    count: int
