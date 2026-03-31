"""
Pydantic schemas for the Live-Mode Readiness Report API (Phases 53 + 56).

GET /api/v1/system/readiness-report
GET /api/v1/system/readiness-report/history
"""
from __future__ import annotations

from pydantic import BaseModel


class ReadinessGateRowSchema(BaseModel):
    """One gate requirement row in the readiness report."""

    gate_name: str
    description: str
    status: str          # "PASS" | "WARN" | "FAIL"
    actual_value: str
    required_value: str
    detail: str = ""


class ReadinessReportResponse(BaseModel):
    """Full readiness report response."""

    generated_at: str         # ISO-8601 UTC datetime string
    current_mode: str
    target_mode: str          # next gated target or "n/a"
    overall_status: str       # "PASS" | "WARN" | "FAIL" | "NO_GATE"
    gate_rows: list[ReadinessGateRowSchema]
    gate_count: int
    pass_count: int
    warn_count: int
    fail_count: int
    recommendation: str
    is_ready: bool


class ReadinessSnapshotSchema(BaseModel):
    """One persisted readiness snapshot (for history endpoint)."""

    id: str
    captured_at: str          # ISO-8601 UTC datetime string
    overall_status: str       # "PASS" | "WARN" | "FAIL" | "NO_GATE"
    current_mode: str
    target_mode: str
    pass_count: int = 0
    warn_count: int = 0
    fail_count: int = 0
    gate_count: int = 0
    recommendation: str | None = None


class ReadinessHistoryResponse(BaseModel):
    """Response for GET /system/readiness-report/history."""

    snapshots: list[ReadinessSnapshotSchema] = []
    count: int = 0
