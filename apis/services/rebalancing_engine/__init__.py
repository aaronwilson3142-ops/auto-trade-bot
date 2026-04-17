"""Rebalancing engine — score-weighted allocator (Deep-Dive Plan Step 4)."""
from services.rebalancing_engine.allocator import (
    AllocationResult,
    RebalanceAllocator,
    compute_weights,
)

__all__ = ["AllocationResult", "RebalanceAllocator", "compute_weights"]
