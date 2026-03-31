"""Self-improvement execution API routes.

Endpoints
---------
POST /self-improvement/proposals/{proposal_id}/execute
    Execute a specific PROMOTED proposal from app_state.improvement_proposals.
    Returns 404 if not found, 400 if not PROMOTED or protected.

POST /self-improvement/executions/{execution_id}/rollback
    Roll back a previously applied execution from app_state.applied_executions.
    Returns 404 if execution_id not found, 400 if already rolled back.

GET  /self-improvement/executions
    List all in-memory execution records (newest-first, max 100).

POST /self-improvement/auto-execute
    Batch-execute all currently PROMOTED proposals in app_state.improvement_proposals.
    Skips protected components and already-applied proposals.

Phase 35 — Self-Improvement Proposal Auto-Execution
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException

from apps.api.deps import AppStateDep
from apps.api.schemas.self_improvement import (
    AutoExecuteSummaryResponse,
    ExecuteProposalResponse,
    ExecutionListResponse,
    ExecutionRecordSchema,
    RollbackExecutionResponse,
)

router = APIRouter(prefix="/self-improvement", tags=["Self-Improvement"])


def _get_service():
    from services.self_improvement.execution import AutoExecutionService
    return AutoExecutionService()


# ---------------------------------------------------------------------------
# POST /self-improvement/proposals/{proposal_id}/execute
# ---------------------------------------------------------------------------

@router.post(
    "/proposals/{proposal_id}/execute",
    response_model=ExecuteProposalResponse,
)
async def execute_proposal(
    proposal_id: str,
    state: AppStateDep,
) -> ExecuteProposalResponse:
    """Execute a specific PROMOTED improvement proposal."""
    proposals = getattr(state, "improvement_proposals", [])
    proposal = next((p for p in proposals if p.id == proposal_id), None)

    if proposal is None:
        raise HTTPException(
            status_code=404,
            detail=f"Proposal '{proposal_id}' not found in current improvement_proposals.",
        )

    svc = _get_service()
    try:
        record = svc.execute_proposal(proposal, state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Execution failed: {exc}") from exc

    return ExecuteProposalResponse(
        status="executed",
        execution_id=record.id,
        proposal_id=proposal_id,
        message=f"Proposal executed. Applied {len(record.config_delta)} config key(s).",
    )


# ---------------------------------------------------------------------------
# POST /self-improvement/executions/{execution_id}/rollback
# ---------------------------------------------------------------------------

@router.post(
    "/executions/{execution_id}/rollback",
    response_model=RollbackExecutionResponse,
)
async def rollback_execution(
    execution_id: str,
    state: AppStateDep,
) -> RollbackExecutionResponse:
    """Roll back a previously applied proposal execution."""
    svc = _get_service()
    success = svc.rollback_execution(execution_id, state)

    if not success:
        applied = getattr(state, "applied_executions", [])
        record = next((r for r in applied if r.id == execution_id), None)
        if record is None:
            return RollbackExecutionResponse(
                status="not_found",
                execution_id=execution_id,
                message=f"Execution '{execution_id}' not found.",
            )
        return RollbackExecutionResponse(
            status="already_rolled_back",
            execution_id=execution_id,
            message=f"Execution '{execution_id}' was already rolled back.",
        )

    return RollbackExecutionResponse(
        status="rolled_back",
        execution_id=execution_id,
        message="Execution rolled back successfully.",
    )


# ---------------------------------------------------------------------------
# GET /self-improvement/executions
# ---------------------------------------------------------------------------

@router.get(
    "/executions",
    response_model=ExecutionListResponse,
)
async def list_executions(
    state: AppStateDep,
    limit: int = 50,
) -> ExecutionListResponse:
    """Return in-memory execution records, newest-first."""
    applied: list = getattr(state, "applied_executions", [])
    # newest-first, capped
    items = list(reversed(applied))[:min(limit, 100)]
    return ExecutionListResponse(
        count=len(items),
        items=[
            ExecutionRecordSchema(
                id=r.id,
                proposal_id=r.proposal_id,
                proposal_type=r.proposal_type,
                target_component=r.target_component,
                config_delta=r.config_delta,
                baseline_params=r.baseline_params,
                status=r.status,
                executed_at=r.executed_at,
                rolled_back_at=r.rolled_back_at,
                notes=r.notes,
            )
            for r in items
        ],
    )


# ---------------------------------------------------------------------------
# POST /self-improvement/auto-execute
# ---------------------------------------------------------------------------

@router.post(
    "/auto-execute",
    response_model=AutoExecuteSummaryResponse,
)
async def auto_execute(
    state: AppStateDep,
) -> AutoExecuteSummaryResponse:
    """Batch-execute all PROMOTED proposals in the current improvement_proposals list."""
    proposals = getattr(state, "improvement_proposals", [])
    svc = _get_service()

    from services.self_improvement.config import SelfImprovementConfig
    cfg = SelfImprovementConfig()
    result = svc.auto_execute_promoted(
        proposals, state, min_confidence=cfg.min_auto_execute_confidence
    )

    return AutoExecuteSummaryResponse(
        status="ok",
        executed_count=result["executed_count"],
        skipped_count=result["skipped_count"],
        skipped_low_confidence=result.get("skipped_low_confidence", 0),
        error_count=result["error_count"],
        errors=result["errors"],
        run_at=dt.datetime.now(dt.UTC),
    )
