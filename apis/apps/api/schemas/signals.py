"""Pydantic response schemas for signal run and ranking run history endpoints.

Phase 30 — DB-backed signal/rank persistence.
"""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Signal run schemas
# ---------------------------------------------------------------------------

class SignalRunRecord(BaseModel):
    """Summary of one persisted signal generation run."""
    run_id: str
    run_timestamp: dt.datetime
    run_mode: str
    universe_name: str | None
    status: str
    signal_count: int           # number of security_signal rows for this run
    strategy_count: int         # number of distinct strategy_ids in this run


class SignalRunHistoryResponse(BaseModel):
    """Paginated list of recent signal runs."""
    count: int
    runs: list[SignalRunRecord]


# ---------------------------------------------------------------------------
# Ranking run schemas
# ---------------------------------------------------------------------------

class RankedOpportunityRecord(BaseModel):
    """One ranked opportunity row from a ranking run."""
    rank_position: int
    ticker: str | None           # resolved via securities join; None if unknown
    composite_score: float | None
    portfolio_fit_score: float | None
    recommended_action: str
    target_horizon: str | None
    thesis_summary: str | None
    disconfirming_factors: str | None
    sizing_hint_pct: float | None


class RankingRunRecord(BaseModel):
    """Summary of one persisted ranking run."""
    run_id: str
    signal_run_id: str
    run_timestamp: dt.datetime
    status: str
    ranked_count: int


class RankingRunHistoryResponse(BaseModel):
    """Paginated list of recent ranking runs."""
    count: int
    runs: list[RankingRunRecord]


class RankingRunDetailResponse(BaseModel):
    """Full detail for a single ranking run including all opportunities."""
    run_id: str
    signal_run_id: str
    run_timestamp: dt.datetime
    status: str
    opportunities: list[RankedOpportunityRecord]
