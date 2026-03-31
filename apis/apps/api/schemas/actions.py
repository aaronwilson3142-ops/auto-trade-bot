"""Response schemas for /api/v1/actions/* endpoints."""
from __future__ import annotations

from typing import Optional

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
    note: Optional[str] = ""
    prices: dict[str, float] = {}  # ticker → current market price for OPEN sizing


class ExecutionResultSchema(BaseModel):
    ticker: str
    status: str
    broker_order_id: Optional[str] = None
    fill_price: Optional[float] = None
    fill_quantity: Optional[float] = None
    error_message: Optional[str] = None


class ActionReviewResponse(BaseModel):
    processed: int
    decision: str
    message: str
    execution_results: list[ExecutionResultSchema] = []
