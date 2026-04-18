"""Thompson Strategy Bandit service (Deep-Dive Plan Step 8, Rec 12).

Public API:

    * ``StrategyBanditService`` — the Beta(α, β) posterior manager with
      Thompson sampling, smoothing, floor/ceiling clamping, and cycle
      caching as described in plan §8.2–§8.5.
    * ``DEFAULT_STRATEGY_FAMILIES`` — the canonical strategy-family tuple
      the bandit will keep posteriors for.  The service will upsert rows
      for any family it hasn't seen before, so the list is an operator
      default rather than a hard schema.
"""
from __future__ import annotations

from .service import (
    DEFAULT_STRATEGY_FAMILIES,
    BanditUpdateResult,
    BanditWeights,
    StrategyBanditService,
)

__all__ = [
    "DEFAULT_STRATEGY_FAMILIES",
    "BanditUpdateResult",
    "BanditWeights",
    "StrategyBanditService",
]
