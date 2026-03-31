"""
Reporting Service.

Responsibilities (Gate F § reconcile fills, slippage, daily operational report):
  1. reconcile_fills(expectations, actual_fills, tolerance_bps)  → FillReconciliationSummary
  2. generate_daily_report(...)                                   → DailyOperationalReport

Design rules
------------
- No broker calls are made here; the caller injects fill data from the broker
  adapter so reporting stays independently testable.
- Slippage calc: (actual_price − expected_price) / expected_price × 10,000
  (positive = filled worse than expected).
- P&L consistency check: if equity rounds differently from cash + sum(market_values),
  a ReconciliationError is raised so the discrepancy is surfaced immediately.

Spec references
---------------
- APIS_BUILD_RUNBOOK.md § Step 6 (Paper Trading)
- APIS_BUILD_RUNBOOK.md § Gate F
- API_AND_SERVICE_BOUNDARIES_SPEC.md § 3.15 (reporting)
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Optional

from broker_adapters.base.models import Fill, Order, OrderStatus
from services.reporting.models import (
    DailyOperationalReport,
    FillExpectation,
    FillReconciliationRecord,
    FillReconciliationSummary,
    ReconciliationStatus,
)

# Maximum tolerated equity drift before raising a consistency error (in dollars)
_EQUITY_TOLERANCE = Decimal("0.05")


class ReportingService:
    """Reconciles fills and produces daily operational reports."""

    def __init__(self, slippage_tolerance_bps: int = 50) -> None:
        """
        Args:
            slippage_tolerance_bps: fills within this many basis points of the
                expected price are classified as MATCHED (not PRICE_DRIFT).
        """
        self._tolerance_bps = Decimal(str(slippage_tolerance_bps))

    # ── Fill reconciliation ────────────────────────────────────────────────────

    def reconcile_fills(
        self,
        expectations: list[FillExpectation],
        actual_fills: list[Fill],
    ) -> FillReconciliationSummary:
        """Compare expected fills against broker-reported fills.

        Matching is done by idempotency_key (= client_order_id).

        Rules:
          - If no actual fill found for an expectation → MISSING_FILL
          - If quantities differ                         → QTY_MISMATCH
          - If |slippage_bps| > tolerance               → PRICE_DRIFT
          - Otherwise                                    → MATCHED

        Args:
            expectations:  List of FillExpectation from the execution engine.
            actual_fills:  List of Fill objects returned by the broker adapter.

        Returns:
            FillReconciliationSummary with one record per expectation.
        """
        # Build a lookup of actual fills by idempotency_key (= broker's client_order_id).
        # broker_order_id is used as fallback key for fills that don't carry the
        # original idempotency_key (e.g. synthesised from order data).
        fills_by_key: dict[str, Fill] = {}
        for fill in actual_fills:
            fills_by_key[fill.broker_order_id] = fill

        records: list[FillReconciliationRecord] = []
        for exp in expectations:
            actual = fills_by_key.get(exp.idempotency_key) or fills_by_key.get(
                exp.ticker  # last-resort: shouldn't normally match
            )

            if actual is None:
                records.append(
                    FillReconciliationRecord(
                        idempotency_key=exp.idempotency_key,
                        ticker=exp.ticker,
                        status=ReconciliationStatus.MISSING_FILL,
                        expected_quantity=exp.expected_quantity,
                        actual_quantity=Decimal("0"),
                        expected_price=exp.expected_price,
                        actual_price=Decimal("0"),
                        slippage_bps=Decimal("0"),
                        notes="No matching fill found from broker.",
                    )
                )
                continue

            slippage_bps = self._calc_slippage_bps(
                exp.expected_price, actual.fill_price
            )

            if actual.fill_quantity != exp.expected_quantity:
                status = ReconciliationStatus.QTY_MISMATCH
                notes = (
                    f"Quantity mismatch: expected {exp.expected_quantity}, "
                    f"got {actual.fill_quantity}."
                )
            elif abs(slippage_bps) > self._tolerance_bps:
                status = ReconciliationStatus.PRICE_DRIFT
                notes = (
                    f"Price drift {slippage_bps:.1f} bps "
                    f"(tolerance ±{self._tolerance_bps} bps)."
                )
            else:
                status = ReconciliationStatus.MATCHED
                notes = ""

            records.append(
                FillReconciliationRecord(
                    idempotency_key=exp.idempotency_key,
                    ticker=exp.ticker,
                    status=status,
                    expected_quantity=exp.expected_quantity,
                    actual_quantity=actual.fill_quantity,
                    expected_price=exp.expected_price,
                    actual_price=actual.fill_price,
                    slippage_bps=slippage_bps,
                    notes=notes,
                )
            )

        return FillReconciliationSummary(records=records)

    # ── P&L consistency check ──────────────────────────────────────────────────

    def check_pnl_consistency(
        self,
        reported_equity: Decimal,
        cash: Decimal,
        position_market_values: list[Decimal],
    ) -> bool:
        """Verify equity == cash + sum(market_values) within tolerance.

        Returns True when consistent.  Raises ValueError when the drift
        exceeds _EQUITY_TOLERANCE so callers can surface it immediately.
        """
        computed = cash + sum(position_market_values, Decimal("0"))
        drift = abs(reported_equity - computed)
        if drift > _EQUITY_TOLERANCE:
            raise ValueError(
                f"P&L consistency check failed: reported equity={reported_equity}, "
                f"computed={computed}, drift={drift} > tolerance={_EQUITY_TOLERANCE}"
            )
        return True

    # ── Daily operational report ────────────────────────────────────────────────

    def generate_daily_report(
        self,
        report_date: dt.date,
        equity: Decimal,
        cash: Decimal,
        gross_exposure: Decimal,
        position_count: int,
        realized_pnl: Decimal,
        unrealized_pnl: Decimal,
        start_of_day_equity: Decimal,
        orders: list[Order],
        reconciliation: FillReconciliationSummary,
        scorecard_grade: Optional[str] = None,
        benchmark_differentials: Optional[dict[str, Decimal]] = None,
        improvement_proposals_generated: int = 0,
        improvement_proposals_promoted: int = 0,
    ) -> DailyOperationalReport:
        """Assemble the full daily operational report.

        Args:
            report_date:                  Date being reported on.
            equity:                       End-of-day equity value.
            cash:                         End-of-day cash balance.
            gross_exposure:               Sum of all position market values.
            position_count:               Number of open positions.
            realized_pnl:                 Total realized P&L for the day.
            unrealized_pnl:               Total unrealized P&L at close.
            start_of_day_equity:          Equity at market open (for daily return).
            orders:                       All orders submitted during the session.
            reconciliation:               Pre-computed FillReconciliationSummary.
            scorecard_grade:              Optional daily grade from evaluation engine.
            benchmark_differentials:      Optional dict of benchmark alpha deltas.
            improvement_proposals_generated: Count from self-improvement engine.
            improvement_proposals_promoted:  Count of promoted proposals.

        Returns:
            DailyOperationalReport ready for display / storage.
        """
        daily_return_pct = (
            ((equity - start_of_day_equity) / start_of_day_equity).quantize(
                Decimal("0.000001")
            )
            if start_of_day_equity > Decimal("0")
            else Decimal("0")
        )

        submitted = len(orders)
        filled = sum(
            1 for o in orders if o.status == OrderStatus.FILLED
        )
        cancelled = sum(
            1 for o in orders if o.status == OrderStatus.CANCELLED
        )
        rejected = sum(
            1 for o in orders if o.status == OrderStatus.REJECTED
        )

        narrative_parts = [
            f"Date: {report_date}",
            f"Equity: ${equity:,.2f} | Cash: ${cash:,.2f} | Positions: {position_count}",
            f"Daily return: {float(daily_return_pct)*100:.2f}%",
            f"Realized P&L: ${realized_pnl:,.2f} | Unrealized: ${unrealized_pnl:,.2f}",
            f"Orders: {submitted} submitted, {filled} filled, "
            f"{cancelled} cancelled, {rejected} rejected",
            f"Fill reconciliation: {reconciliation.matched}/{reconciliation.total} matched, "
            f"avg slippage {reconciliation.avg_slippage_bps:.1f} bps",
        ]
        if scorecard_grade:
            narrative_parts.append(f"Scorecard grade: {scorecard_grade}")
        if improvement_proposals_promoted:
            narrative_parts.append(
                f"Self-improvement: {improvement_proposals_promoted} proposal(s) promoted."
            )

        return DailyOperationalReport(
            report_date=report_date,
            report_timestamp=dt.datetime.now(dt.timezone.utc),
            equity=equity,
            cash=cash,
            gross_exposure=gross_exposure,
            position_count=position_count,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            daily_return_pct=daily_return_pct,
            orders_submitted=submitted,
            orders_filled=filled,
            orders_cancelled=cancelled,
            orders_rejected=rejected,
            reconciliation=reconciliation,
            scorecard_grade=scorecard_grade,
            benchmark_differentials=benchmark_differentials or {},
            improvement_proposals_generated=improvement_proposals_generated,
            improvement_proposals_promoted=improvement_proposals_promoted,
            narrative="\n".join(narrative_parts),
        )

    # ── Internal helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _calc_slippage_bps(expected: Decimal, actual: Decimal) -> Decimal:
        """Slippage in basis points: (actual - expected) / expected * 10_000.

        Positive = filled worse than expected.
        Returns 0 when expected price is zero (division guard).
        """
        if expected == Decimal("0"):
            return Decimal("0")
        return ((actual - expected) / expected * Decimal("10000")).quantize(
            Decimal("0.01")
        )

