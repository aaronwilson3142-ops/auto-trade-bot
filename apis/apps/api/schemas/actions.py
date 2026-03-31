"""Response schemas for /api/v1/actions/* endpoints."""
from __future__ import annotations

from pydantic import BaseModel


class ProposedActionSchema(BaseModel):
    action_type: str
    ticker: str
    reason: str
    target_notional: float
    thesis_summary: str
    risk_approved: bool


class ProposedActionsResponse(BaseModel):
    count: int
    mode: str   # operating mode — clients use this to understand approval context
    actions: list[ProposedActionSchema]


class ActionReviewRequest(BaseModel):
    action_ids: list[str]
    decision: str   # "approve" | "reject"
    note: str | None = ""
    prices: dict[str, float] = {}  # ticker → current market price for OPEN sizing


class ExecutionResultSchema(BaseModel):
    ticker: str
    status: str
    broker_order_id: str | None = None
    fill_price: float | None = None
    fill_quantity: float | None = None
    error_message: str | None = None


class ActionReviewResponse(BaseModel):
    processed: int
    decision: str
    message: str
    execution_results: list[ExecutionResultSchema] = []
