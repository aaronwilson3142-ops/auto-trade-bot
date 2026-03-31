"""Pydantic schemas for self-improvement execution endpoints.

Phase 35 — Self-Improvement Proposal Auto-Execution
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel


class ExecutionRecordSchema(BaseModel):
    """Serialized view of a single ProposalExecution row / in-memory record."""

    id: str
    proposal_id: str
    proposal_type: str
    target_component: str
    config_delta: dict[str, Any]
    baseline_params: dict[str, Any]
    status: str                          # "applied" | "rolled_back"
    executed_at: dt.datetime
    rolled_back_at: dt.datetime | None = None
    notes: str = ""

    model_config = {"from_attributes": True}


class ExecutionListResponse(BaseModel):
    """Response for GET /self-improvement/executions."""

    count: int
    items: list[ExecutionRecordSchema]


class ExecuteProposalResponse(BaseModel):
    """Response for POST /self-improvement/proposals/{proposal_id}/execute."""

    status: str          # "executed" | "error"
    execution_id: str | None = None
    proposal_id: str
    message: str


class RollbackExecutionResponse(BaseModel):
    """Response for POST /self-improvement/executions/{execution_id}/rollback."""

    status: str          # "rolled_back" | "not_found" | "already_rolled_back" | "error"
    execution_id: str
    message: str


class AutoExecuteSummaryResponse(BaseModel):
    """Response for POST /self-improvement/auto-execute."""

    status: str          # "ok" | "error"
    executed_count: int
    skipped_count: int
    skipped_low_confidence: int = 0   # Phase 36: proposals below confidence threshold
    error_count: int
    errors: list[str]
    run_at: dt.datetime
