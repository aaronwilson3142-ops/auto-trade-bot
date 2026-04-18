"""Shadow Portfolio service package (Deep-Dive Plan Step 7, Rec 11 + DEC-034).

Exports the public API — ``ShadowPortfolioService`` plus named-shadow constants.
"""
from __future__ import annotations

from infra.db.models.shadow_portfolio import SHADOW_NAMES

from .service import (
    REBALANCE_SHADOWS,
    REJECTION_SHADOWS,
    ShadowOrderResult,
    ShadowPnL,
    ShadowPortfolioService,
)

__all__ = [
    "REBALANCE_SHADOWS",
    "REJECTION_SHADOWS",
    "SHADOW_NAMES",
    "ShadowOrderResult",
    "ShadowPnL",
    "ShadowPortfolioService",
]
