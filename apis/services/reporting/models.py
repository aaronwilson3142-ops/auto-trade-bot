"""
Reporting service domain models.

Covers two responsibilities that satisfy Gate F:
  1. FillReconciliation — compare expected fills from execution engine vs
     actual fills from the broker, flagging discrepancies and measuring slippage.
  2. DailyOperationalReport — the end-of-day summary that ties together
     portfolio state, evaluation scorecard, fill reconciliation, and
     self-improvement proposals.

All models are plain dataclasses (no ORM dependency).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

# ── Fill reconciliation ────────────────────────────────────────────────────────

class ReconciliationStatus(str, Enum):
    MATCHED       = "matched"       # fill price and quantity reconcile within tolerance
    PRICE_DRIFT   = "price_drift"   # quantity matched but fill price differs > tolerance
    QTY_MISMATCH  = "qty_mismatch"  # filled quantity differs from requested quantity
    MISSING_FILL  = "missing_fill"  # expected fill never appeared from broker
    DUPLICATE_ORDER = "duplicate_order"  # broker reported duplicate submission


@dataclass
class FillExpectation:
    """The fill that the execution engine expected from the broker."""
    idempotency_key: str
    ticker: str
    expected_quantity: Decimal
    expected_price: Decimal      # price at which the order was submitted (pre-slippage)
    submitted_at: dt.datetime


@dataclass
class FillReconciliationRecord:
    """Result of reconciling one expected fill against the broker's actual fill.

    slippage_bps: basis-points deviation between expected and actual fill price.
                  Positive = filled worse than expected (paid more / received less).
    """
    idempotency_key: str
    ticker: str
    status: ReconciliationStatus
    expected_quantity: Decimal
    actual_quantity: Decimal
    expected_price: Decimal
    actual_price: Decimal
    slippage_bps: Decimal           # (actual - expected) / expected * 10_000
    reconciled_at: dt.datetime = field(
        default_factory=lambda: dt.datetime.now(dt.UTC)
    )
    notes: str = ""

    @property
    def is_clean(self) -> bool:
        """True when status is MATCHED — no manual review needed."""
        return self.status == ReconciliationStatus.MATCHED


@dataclass
class FillReconciliationSummary:
    """Aggregate result of reconciling all fills in one session/day."""
    records: list[FillReconciliationRecord]
    reconciled_at: dt.datetime = field(
        default_factory=lambda: dt.datetime.now(dt.UTC)
    )

    @property
    def total(self) -> int:
        return len(self.records)

    @property
    def matched(self) -> int:
        return sum(1 for r in self.records if r.status == ReconciliationStatus.MATCHED)

    @property
    def discrepancies(self) -> int:
        return self.total - self.matched

    @property
    def avg_slippage_bps(self) -> Decimal:
        if not self.records:
            return Decimal("0")
        return (
            sum((r.slippage_bps for r in self.records), Decimal("0"))
            / Decimal(len(self.records))
        ).quantize(Decimal("0.01"))

    @property
    def max_slippage_bps(self) -> Decimal:
        if not self.records:
            return Decimal("0")
        return max(r.slippage_bps for r in self.records)

    @property
    def is_clean(self) -> bool:
        """True when all fills reconciled without discrepancy."""
        return self.discrepancies == 0


# ── Daily operational report ────────────────────────────────────────────────────

@dataclass
class DailyOperationalReport:
    """End-of-day summary combining portfolio state, evaluation, reconciliation.

    Produced by ReportingService.generate_daily_report() and satisfies the
    Gate F criterion: 'daily operational report works'.
    """
    report_date: dt.date
    report_timestamp: dt.datetime

    # Portfolio summary
    equity: Decimal
    cash: Decimal
    gross_exposure: Decimal
    position_count: int

    # P&L
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    daily_return_pct: Decimal        # fraction, e.g. 0.005 = 0.5 %

    # Trade activity
    orders_submitted: int
    orders_filled: int
    orders_cancelled: int
    orders_rejected: int

    # Fill reconciliation
    reconciliation: FillReconciliationSummary

    # Scorecard (from evaluation engine) — optional for first-pass
    scorecard_grade: str | None = None        # A/B/C/D/F
    benchmark_differentials: dict[str, Decimal] = field(default_factory=dict)

    # Self-improvement — optional
    improvement_proposals_generated: int = 0
    improvement_proposals_promoted: int = 0

    # Human-readable narrative
    narrative: str = ""

    @property
    def reconciliation_clean(self) -> bool:
        """True when all fills reconciled without discrepancies."""
        return self.reconciliation.discrepancies == 0

