"""Response schemas for /api/v1/reports/* endpoints."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from pydantic import BaseModel


class DailyReportResponse(BaseModel):
    report_date: dt.date
    equity: float
    cash: float
    gross_exposure: float
    daily_return_pct: float
    orders_submitted: int
    orders_filled: int
    orders_cancelled: int
    orders_rejected: int
    reconciliation_clean: bool
    avg_slippage_bps: float
    max_slippage_bps: float
    scorecard_grade: Optional[str]
    narrative: str
    benchmark_differentials: dict[str, float]
    improvement_proposals_generated: int
    improvement_proposals_promoted: int


class DailyReportLatestResponse(BaseModel):
    found: bool
    report: Optional[DailyReportResponse]


class ReportHistoryResponse(BaseModel):
    count: int
    items: list[DailyReportResponse]
