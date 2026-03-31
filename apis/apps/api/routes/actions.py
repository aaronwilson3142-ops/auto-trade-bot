"""Route handlers for /api/v1/actions/*.

GET  /actions/proposed  — read proposed portfolio actions.
POST /actions/review    — approve or reject proposed actions (mode-guarded).
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException

from apps.api.deps import AppStateDep, SettingsDep
from apps.api.schemas.actions import (
    ActionReviewRequest,
    ActionReviewResponse,
    ExecutionResultSchema,
    ProposedActionSchema,
    ProposedActionsResponse,
)
from config.settings import OperatingMode
from services.execution_engine.models import ExecutionRequest

router = APIRouter(prefix="/actions", tags=["Actions"])

# Modes where the review/approve workflow is permitted
_APPROVAL_MODES = {OperatingMode.HUMAN_APPROVED, OperatingMode.PAPER}


def _to_action_schema(action: object) -> ProposedActionSchema:
    action_type = (
        action.action_type.value
        if hasattr(action.action_type, "value")
        else str(action.action_type)
    )
    return ProposedActionSchema(
        action_type=action_type,
        ticker=action.ticker,
        reason=action.reason,
        target_notional=float(action.target_notional),
        thesis_summary=action.thesis_summary,
        risk_approved=action.risk_approved,
    )


@router.get("/proposed", response_model=ProposedActionsResponse)
async def get_proposed_actions(
    state: AppStateDep,
    settings: SettingsDep,
) -> ProposedActionsResponse:
    """Return currently proposed portfolio actions awaiting review."""
    actions = [_to_action_schema(a) for a in state.proposed_actions]
    return ProposedActionsResponse(
        count=len(actions),
        mode=settings.operating_mode.value,
        actions=actions,
    )


@router.post("/review", response_model=ActionReviewResponse)
async def review_actions(
    body: ActionReviewRequest,
    state: AppStateDep,
    settings: SettingsDep,
) -> ActionReviewResponse:
    """Approve or reject proposed actions.

    Only permitted in PAPER and HUMAN_APPROVED modes.
    Returns 403 in RESEARCH or BACKTEST mode with a structured error body.
    """
    if settings.operating_mode not in _APPROVAL_MODES:
        raise HTTPException(
            status_code=403,
            detail={
                "error": {
                    "code": "MODE_RESTRICTION",
                    "message": (
                        f"Action review is not permitted in "
                        f"'{settings.operating_mode.value}' mode. "
                        "Switch to PAPER or HUMAN_APPROVED mode first."
                    ),
                    "source": "api_actions_router",
                }
            },
        )

    if body.decision not in ("approve", "reject"):
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "INVALID_DECISION",
                    "message": "decision must be 'approve' or 'reject'.",
                    "source": "api_actions_router",
                }
            },
        )

    if body.decision == "reject":
        # Remove rejected actions from the proposed queue
        rejected_ids = set(body.action_ids)
        state.proposed_actions = [
            a for a in state.proposed_actions if getattr(a, "id", None) not in rejected_ids
        ]
        return ActionReviewResponse(
            processed=len(body.action_ids),
            decision=body.decision,
            message=f"Rejected {len(body.action_ids)} action(s).",
        )

    # decision == "approve"
    if not body.action_ids:
        return ActionReviewResponse(
            processed=0,
            decision=body.decision,
            message="No action IDs provided — nothing to approve.",
        )

    if state.execution_engine is None:
        # Execution engine not yet wired — record intent only
        return ActionReviewResponse(
            processed=len(body.action_ids),
            decision=body.decision,
            message=f"Recorded approve for {len(body.action_ids)} action(s) (execution engine not configured).",
        )

    # Wire to ExecutionEngineService
    approved_ids = set(body.action_ids)
    matched = [a for a in state.proposed_actions if getattr(a, "id", None) in approved_ids]

    requests = [
        ExecutionRequest(
            action=action,
            current_price=Decimal(str(body.prices.get(action.ticker, 100.0))),
        )
        for action in matched
    ]

    exec_results = state.execution_engine.execute_approved_actions(requests)

    # Remove executed actions from proposed queue
    executed_ids = {a.id for a in matched}
    state.proposed_actions = [
        a for a in state.proposed_actions if getattr(a, "id", None) not in executed_ids
    ]

    ex_schemas = [
        ExecutionResultSchema(
            ticker=r.action.ticker,
            status=r.status.value,
            broker_order_id=r.broker_order_id,
            fill_price=float(r.fill_price) if r.fill_price is not None else None,
            fill_quantity=float(r.fill_quantity) if r.fill_quantity is not None else None,
            error_message=r.error_message,
        )
        for r in exec_results
    ]

    return ActionReviewResponse(
        processed=len(body.action_ids),
        decision=body.decision,
        message=f"Executed {len(exec_results)} action(s) via execution engine.",
        execution_results=ex_schemas,
    )
