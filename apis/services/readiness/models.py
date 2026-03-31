"""
Readiness Report models — Phase 53.

Dataclasses for the automated live-mode readiness report that synthesises
all live-gate requirements into a single, pre-computed snapshot.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field


@dataclass
class ReadinessGateRow:
    """One gate requirement row within a ReadinessReport."""

    gate_name: str
    description: str
    status: str              # "PASS" | "WARN" | "FAIL"
    actual_value: str        # stringified for display
    required_value: str      # stringified threshold / expectation
    detail: str = ""         # optional explanatory note


@dataclass
class ReadinessReport:
    """Pre-computed live-mode readiness snapshot.

    Generated once per evening by ``run_readiness_report_update`` and
    cached in ``app_state.latest_readiness_report``.  The report covers
    the next sequential gated promotion from the current operating mode.

    ``overall_status`` is:
      "PASS"    — all gate rows are PASS (system is promotion-ready)
      "WARN"    — no FAIL rows, but at least one WARN (advisory issues)
      "FAIL"    — at least one FAIL row (promotion blocked)
      "NO_GATE" — current mode has no gated promotion path
    """

    generated_at: dt.datetime
    current_mode: str
    target_mode: str           # next gated target, or "n/a"
    overall_status: str        # PASS | WARN | FAIL | NO_GATE
    gate_rows: list[ReadinessGateRow] = field(default_factory=list)
    pass_count: int = 0
    warn_count: int = 0
    fail_count: int = 0
    recommendation: str = ""

    # ── Computed properties ────────────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        """True when overall_status is PASS (no fails, no warns)."""
        return self.overall_status == "PASS"

    @property
    def gate_count(self) -> int:
        return len(self.gate_rows)
