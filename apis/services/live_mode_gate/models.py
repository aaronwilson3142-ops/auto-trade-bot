"""
Live Mode Gate — domain models.

These models represent the result of validating gate criteria before the
system is promoted to a higher operating mode.

Spec references
---------------
- APIS_MASTER_SPEC.md §3.1 — Safety rollout discipline (no stage skipping)
- APIS_MASTER_SPEC.md §3.2 — Controlled self-improvement
- 04_APIS_BUILD_RUNBOOK.md §5 — Mandatory QA Gates
"""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class GateStatus(str, Enum):
    """Outcome of a single gate requirement check."""

    PASS = "pass"   # requirement met  # noqa: S105
    FAIL = "fail"   # requirement not met — blocks promotion
    WARN = "warn"   # requirement met with advisory note


@dataclass
class GateRequirement:
    """A single verifiable gate criterion.

    ``status=PASS`` or ``status=WARN`` both count as passed — WARN allows
    promotion while surfacing an advisory to the operator.
    ``status=FAIL`` blocks promotion.
    """

    name: str
    description: str
    status: GateStatus
    actual_value: Any
    required_value: Any
    detail: str = ""

    @property
    def passed(self) -> bool:
        """True when this requirement does NOT block promotion."""
        return self.status in (GateStatus.PASS, GateStatus.WARN)


@dataclass
class LiveModeGateResult:
    """Aggregate result of evaluating all live-mode gate requirements.

    Produced by ``LiveModeGateService.check_prerequisites()``.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    evaluated_at: dt.datetime = field(
        default_factory=lambda: dt.datetime.now(dt.UTC)
    )
    current_mode: str = ""
    target_mode: str = ""
    requirements: list[GateRequirement] = field(default_factory=list)

    # Set by the service when all requirements pass
    promotion_advisory: str | None = None

    @property
    def all_passed(self) -> bool:
        """True when every requirement either passed or warned."""
        if not self.requirements:
            return False
        return all(r.passed for r in self.requirements)

    @property
    def failed_requirements(self) -> list[GateRequirement]:
        """Requirements that are blocking promotion."""
        return [r for r in self.requirements if not r.passed]
