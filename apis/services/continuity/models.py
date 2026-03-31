"""Continuity service models.

Dataclasses used by ContinuityService for snapshot serialization and
session context generation.  These are intentionally simple — they
serialize to/from plain dicts so no heavy framework is required.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class ContinuitySnapshot:
    """A point-in-time snapshot of key ApiAppState values.

    Designed to be serialized as JSON and written to disk so the state
    can be inspected or partially restored after a process restart.
    """

    snapshot_at: str                          # ISO-format datetime string
    operating_mode: str                       # e.g. "PAPER"
    kill_switch_active: bool
    paper_cycle_count: int
    portfolio_equity: Optional[float]
    portfolio_cash: Optional[float]
    portfolio_positions: int
    ranking_count: int
    broker_auth_expired: bool
    last_paper_cycle_at: Optional[str]        # ISO-format or None
    pending_proposals: int

    def to_dict(self) -> dict[str, Any]:
        """Return a plain-dict representation suitable for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContinuitySnapshot":
        """Deserialize from a plain dict (e.g. loaded from JSON)."""
        return cls(
            snapshot_at=data.get("snapshot_at", ""),
            operating_mode=data.get("operating_mode", "RESEARCH"),
            kill_switch_active=bool(data.get("kill_switch_active", False)),
            paper_cycle_count=int(data.get("paper_cycle_count", 0)),
            portfolio_equity=data.get("portfolio_equity"),
            portfolio_cash=data.get("portfolio_cash"),
            portfolio_positions=int(data.get("portfolio_positions", 0)),
            ranking_count=int(data.get("ranking_count", 0)),
            broker_auth_expired=bool(data.get("broker_auth_expired", False)),
            last_paper_cycle_at=data.get("last_paper_cycle_at"),
            pending_proposals=int(data.get("pending_proposals", 0)),
        )


@dataclass
class SessionContext:
    """Human-readable summary of current system state for handoff logging."""

    snapshot_at: str                          # ISO-format datetime
    operating_mode: str
    paper_cycle_count: int
    portfolio_equity: float
    portfolio_positions: int
    kill_switch_active: bool
    broker_auth_expired: bool
    ranking_count: int
    pending_proposals: int
    summary_lines: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
