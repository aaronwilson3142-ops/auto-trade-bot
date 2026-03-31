"""Response / request schemas for /api/v1/live-gate/* endpoints."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class PromotableMode(str, Enum):
    """The only modes that can be targeted via the live-gate promote endpoint."""

    HUMAN_APPROVED = "human_approved"
    RESTRICTED_LIVE = "restricted_live"


class GateRequirementSchema(BaseModel):
    name: str
    description: str
    status: str         # "pass" | "fail" | "warn"
    passed: bool
    actual_value: Any
    required_value: Any
    detail: str


class LiveGateStatusResponse(BaseModel):
    id: str
    evaluated_at: str
    current_mode: str
    target_mode: str
    all_passed: bool
    requirements: list[GateRequirementSchema]
    failed_count: int
    promotion_advisory: str | None


class LiveGatePromoteRequest(BaseModel):
    target_mode: PromotableMode


class LiveGatePromoteResponse(BaseModel):
    gate_result: LiveGateStatusResponse
    promotion_recorded: bool
    message: str
