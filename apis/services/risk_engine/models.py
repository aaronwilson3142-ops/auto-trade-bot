"""
Risk engine domain models (plain dataclasses, no ORM dependency).

These are the result objects returned by RiskEngineService checks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum


class RiskSeverity(str, Enum):
    HARD_BLOCK = "hard_block"   # action must not proceed
    WARNING = "warning"          # action may proceed with a logged warning


@dataclass
class RiskViolation:
    """A single rule failure discovered during a risk check."""

    rule_name: str              # e.g. "max_positions", "max_single_name_pct"
    reason: str                 # human-readable explanation
    severity: RiskSeverity = RiskSeverity.HARD_BLOCK


@dataclass
class RiskCheckResult:
    """Aggregated result from one or more risk-engine checks.

    passed == True means every check cleared (no hard blocks); this is the
    gate condition that execution_engine requires before routing an order.
    """

    passed: bool
    violations: list[RiskViolation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # When a size reduction (rather than full block) is possible, this is set.
    adjusted_max_notional: Decimal | None = None

    @property
    def is_hard_blocked(self) -> bool:
        return any(v.severity == RiskSeverity.HARD_BLOCK for v in self.violations)

