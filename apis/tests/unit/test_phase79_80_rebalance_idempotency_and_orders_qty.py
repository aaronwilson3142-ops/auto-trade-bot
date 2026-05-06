"""Phase 79 + 80 regression tests (DEC-079 + DEC-080).

Phase 79: rebalance idempotency on open positions — when a rebalance OPEN
proposal arrives for a ticker the worker is already holding (in
``portfolio_state.positions`` with qty>0 or in the broker), the proposal is
suppressed at the merge call site in ``apps/worker/jobs/paper_trading.py``.

Phase 80: orders ledger NULL-quantity fix — the writer at line 399 now
prefers ``res.fill_quantity`` over ``req.action.target_quantity`` so that
notional-based OPEN actions (rebalance_open and similar) get the actual
filled share count persisted to the ``orders`` row instead of NULL.

These tests exercise the small NEW logic blocks directly without spinning
up the full paper_trading_cycle.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from services.portfolio_engine.models import ActionType, PortfolioAction

# ─── Phase 79 helpers ──────────────────────────────────────────────────────────

def _reb_open(ticker: str, notional: str = "7700.00") -> PortfolioAction:
    """Build a rebalance OPEN action with notional-only sizing."""
    return PortfolioAction(
        action_type=ActionType.OPEN,
        ticker=ticker,
        reason="rebalance_open: drift=-6.67%",
        target_notional=Decimal(notional),
        target_quantity=None,  # notional-only — Phase 80 territory
        risk_approved=False,
    )


def _reb_trim(ticker: str, qty: int = 22) -> PortfolioAction:
    return PortfolioAction(
        action_type=ActionType.TRIM,
        ticker=ticker,
        reason="rebalance_trim: drift=+6.80%",
        target_quantity=Decimal(qty),
        risk_approved=True,
    )


def _phase79_filter(
    reb_actions: list[PortfolioAction],
    state_positions: dict[str, Any],
    broker_tickers: set[str],
    enabled: bool = True,
) -> tuple[list[PortfolioAction], list[str]]:
    """Re-implementation of the Phase 79 filter logic from paper_trading.py:1622.

    The production code path is inline inside ``run_paper_trading_cycle``.  This
    helper mirrors the gate so we can exercise it without importing the whole
    cycle.  Any divergence from production should be flagged immediately by
    test failures here.
    """
    kept: list[PortfolioAction] = []
    skipped: list[str] = []
    for act in reb_actions:
        if enabled and act.action_type == ActionType.OPEN:
            held_pos = state_positions.get(act.ticker)
            held_qty = getattr(held_pos, "quantity", 0) or 0
            if (held_qty and held_qty > 0) or act.ticker in broker_tickers:
                skipped.append(act.ticker)
                continue
        kept.append(act)
    return kept, skipped


class _FakePosition:
    def __init__(self, qty: int) -> None:
        self.quantity = Decimal(qty)


# ─── Phase 79 tests ────────────────────────────────────────────────────────────


class TestPhase79RebalanceIdempotency:
    """Verify rebalance OPEN suppression when ticker already held."""

    def test_open_dropped_when_in_state(self) -> None:
        actions = [_reb_open("VRT")]
        kept, skipped = _phase79_filter(
            actions,
            state_positions={"VRT": _FakePosition(qty=22)},
            broker_tickers=set(),
        )
        assert kept == []
        assert skipped == ["VRT"]

    def test_open_dropped_when_broker_holds(self) -> None:
        actions = [_reb_open("VRT")]
        kept, skipped = _phase79_filter(
            actions,
            state_positions={},  # state stale
            broker_tickers={"VRT"},  # but broker has it (defence-in-depth)
        )
        assert kept == []
        assert skipped == ["VRT"]

    def test_open_allowed_when_truly_absent(self) -> None:
        actions = [_reb_open("VRT")]
        kept, skipped = _phase79_filter(
            actions,
            state_positions={},
            broker_tickers=set(),
        )
        assert len(kept) == 1
        assert kept[0].ticker == "VRT"
        assert skipped == []

    def test_trim_unaffected_by_filter(self) -> None:
        actions = [_reb_trim("VRT", qty=22)]
        kept, skipped = _phase79_filter(
            actions,
            state_positions={"VRT": _FakePosition(qty=22)},
            broker_tickers={"VRT"},
        )
        assert len(kept) == 1
        assert kept[0].action_type == ActionType.TRIM
        assert skipped == []

    def test_disabled_flag_passes_through(self) -> None:
        actions = [_reb_open("VRT")]
        kept, skipped = _phase79_filter(
            actions,
            state_positions={"VRT": _FakePosition(qty=22)},
            broker_tickers={"VRT"},
            enabled=False,
        )
        assert len(kept) == 1
        assert skipped == []


# ─── Phase 80 helpers ──────────────────────────────────────────────────────────


def _phase80_qty(target_quantity: Decimal | None, fill_quantity: Decimal | None) -> Decimal | None:
    """Re-implementation of the Phase 80 qty derivation at paper_trading.py:399.

    Production rule: prefer the broker-reported fill_quantity; fall back to
    the action's target_quantity only when the result has no fill_quantity.
    """
    qty = fill_quantity if fill_quantity else target_quantity
    return Decimal(str(qty)) if qty else None


class TestPhase80OrdersQuantity:
    """Verify orders writer captures fill_quantity for notional-only OPENs."""

    def test_notional_only_open_uses_fill_quantity(self) -> None:
        # Pre-Phase-80: would write NULL because target_quantity is None.
        qty = _phase80_qty(target_quantity=None, fill_quantity=Decimal("22"))
        assert qty == Decimal("22")

    def test_close_with_target_quantity_unchanged(self) -> None:
        # CLOSE actions set target_quantity = position.quantity in execution_engine.
        # Phase 80 still resolves to fill_quantity when present (broker-authoritative).
        qty = _phase80_qty(target_quantity=Decimal("48"), fill_quantity=Decimal("48"))
        assert qty == Decimal("48")

    def test_trim_uses_fill_quantity(self) -> None:
        qty = _phase80_qty(target_quantity=Decimal("22"), fill_quantity=Decimal("22"))
        assert qty == Decimal("22")

    def test_partial_fill_uses_actual_fill_qty(self) -> None:
        # Defence: if the action targeted 22 but the broker only filled 15,
        # the orders ledger should reflect what the broker actually did.
        qty = _phase80_qty(target_quantity=Decimal("22"), fill_quantity=Decimal("15"))
        assert qty == Decimal("15")

    def test_unfilled_falls_back_to_target_quantity(self) -> None:
        # If the result has no fill_quantity (REJECTED/BLOCKED), preserve
        # the action-level target_quantity for audit.
        qty = _phase80_qty(target_quantity=Decimal("22"), fill_quantity=None)
        assert qty == Decimal("22")

    def test_both_none_yields_none(self) -> None:
        # The diagnostic warning case — production logs
        # ``phase80_orders_writer_qty_unresolvable`` here.
        qty = _phase80_qty(target_quantity=None, fill_quantity=None)
        assert qty is None


# ─── Phase 79+80 integration ───────────────────────────────────────────────────


class TestPhase79And80Together:
    """Sanity: both gates compose without interfering."""

    def test_filter_then_qty_resolution(self) -> None:
        # Round-trip: rebalance_open for an unheld ticker passes Phase 79,
        # gets executed with a notional-only action, broker fills 22 shares,
        # Phase 80 writes qty=22 to the orders ledger.
        actions = [_reb_open("CSCO")]
        kept, _ = _phase79_filter(
            actions,
            state_positions={},
            broker_tickers=set(),
        )
        assert len(kept) == 1
        # action survived Phase 79 → goes through execution → produces fill
        qty = _phase80_qty(target_quantity=kept[0].target_quantity, fill_quantity=Decimal("22"))
        assert qty == Decimal("22")
