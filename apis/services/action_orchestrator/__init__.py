"""Action orchestrator service package.

Cross-cutting invariants applied AFTER action sources (portfolio engine,
rebalancer, signal-driven) have been merged, but BEFORE the risk engine
validates them.  Deep-Dive Plan Step 2 (2026-04-16).
"""
from services.action_orchestrator.invariants import (
    ActionConflict,
    ActionConflictReport,
    assert_no_action_conflicts,
    resolve_action_conflicts,
)

__all__ = [
    "ActionConflict",
    "ActionConflictReport",
    "assert_no_action_conflicts",
    "resolve_action_conflicts",
]
