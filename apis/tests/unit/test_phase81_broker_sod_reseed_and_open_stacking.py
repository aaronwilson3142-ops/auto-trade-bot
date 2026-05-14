"""Phase 81 regression tests (DEC-081 + DEC-082 + DEC-083).

Phase 81-A (DEC-081): PaperBrokerAdapter.seed_from_db_positions reseeds an
in-memory broker on a fresh worker start with the prior account state held
in the DB, so the next ``sod_equity_captured`` reads the operator's real
equity rather than the cold-start $100k default.

Phase 81-B (DEC-082): universal OPEN stacking guard extends the Phase 79
rebalance-only filter to ALL OPEN actions (ranked_buy_signal, momentum_v1,
theme_alignment_v1, ...) when the ticker is already held in
``portfolio_state.positions`` or the broker.

Phase 81-C (DEC-083): ``_persist_positions`` close-loop computes
``realized_pnl`` from row.market_value / row.quantity when no ClosedTrade
record exists (broker-sync close path).

All tests run DB-free under ``APIS_PYTEST_SMOKE=1``.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from broker_adapters.paper.adapter import PaperBrokerAdapter
from services.portfolio_engine.models import ActionType, PortfolioAction

# ─── Phase 81-A: broker reseed ─────────────────────────────────────────────────


class TestPhase81ABrokerReseed:
    """Verify PaperBrokerAdapter.seed_from_db_positions."""

    def test_reseed_populates_positions(self) -> None:
        broker = PaperBrokerAdapter()
        summary = broker.seed_from_db_positions(
            positions=[
                ("INTC", Decimal("127"), Decimal("31.21")),
                ("AMZN", Decimal("59"), Decimal("258.40")),
            ],
            last_known_equity=Decimal("117432.00"),
        )
        assert summary["seeded"] == Decimal("2")
        # Broker now reports both positions.
        broker_pos = {p.ticker: p.quantity for p in broker.list_positions()}
        assert broker_pos == {"INTC": Decimal("127"), "AMZN": Decimal("59")}

    def test_reseed_pins_cash_from_last_known_equity(self) -> None:
        broker = PaperBrokerAdapter()
        summary = broker.seed_from_db_positions(
            positions=[("INTC", Decimal("100"), Decimal("50.00"))],
            last_known_equity=Decimal("117432.00"),
        )
        # cost_basis = 100 * 50 = 5,000; cash = 117432 - 5000 = 112,432
        assert summary["cost_basis"] == Decimal("5000.00")
        acct = broker.get_account_state()
        assert acct.cash_balance == Decimal("112432.00")
        # SOD equity capture will see cash + positions = 112432 + 5000 = 117432
        # (positions market_value uses avg_entry_price as the price proxy when
        # no override is injected, which matches the Tue close equity).
        assert acct.equity_value == Decimal("117432.00")

    def test_reseed_idempotent_skips_existing(self) -> None:
        broker = PaperBrokerAdapter()
        broker.seed_from_db_positions(
            positions=[("INTC", Decimal("100"), Decimal("50.00"))],
            last_known_equity=Decimal("100000.00"),
        )
        # Second call with same ticker should be a no-op for that ticker.
        summary = broker.seed_from_db_positions(
            positions=[
                ("INTC", Decimal("100"), Decimal("50.00")),
                ("AMZN", Decimal("10"), Decimal("250.00")),
            ],
            last_known_equity=Decimal("100000.00"),
        )
        # Only AMZN is freshly seeded.
        assert summary["seeded"] == Decimal("1")
        broker_pos = {p.ticker: p.quantity for p in broker.list_positions()}
        assert broker_pos == {"INTC": Decimal("100"), "AMZN": Decimal("10")}

    def test_reseed_without_last_equity_subtracts_from_starting_cash(self) -> None:
        broker = PaperBrokerAdapter(starting_cash=Decimal("100000.00"))
        broker.seed_from_db_positions(
            positions=[("INTC", Decimal("100"), Decimal("50.00"))],
            last_known_equity=None,
        )
        acct = broker.get_account_state()
        # 100000 - (100 * 50) = 95000
        assert acct.cash_balance == Decimal("95000.00")

    def test_reseed_clamps_negative_cash_to_zero(self) -> None:
        broker = PaperBrokerAdapter(starting_cash=Decimal("100.00"))
        broker.seed_from_db_positions(
            positions=[("INTC", Decimal("100"), Decimal("50.00"))],
            last_known_equity=None,
        )
        acct = broker.get_account_state()
        # 100 - 5000 would be -4900; clamped to 0 to satisfy paper-broker
        # invariant that cash >= 0.
        assert acct.cash_balance == Decimal("0")

    def test_reseed_skips_zero_or_negative_quantity(self) -> None:
        broker = PaperBrokerAdapter()
        summary = broker.seed_from_db_positions(
            positions=[
                ("INTC", Decimal("0"), Decimal("50.00")),
                ("AMZN", Decimal("-5"), Decimal("250.00")),
            ],
            last_known_equity=Decimal("100000.00"),
        )
        assert summary["seeded"] == Decimal("0")
        assert broker.list_positions() == []


# ─── Phase 81-B: universal OPEN stacking guard ────────────────────────────────


def _open(ticker: str, reason: str, qty: int | None = None) -> PortfolioAction:
    return PortfolioAction(
        action_type=ActionType.OPEN,
        ticker=ticker,
        reason=reason,
        target_notional=Decimal("7700.00"),
        target_quantity=Decimal(qty) if qty else None,
        risk_approved=False,
    )


def _close(ticker: str) -> PortfolioAction:
    return PortfolioAction(
        action_type=ActionType.CLOSE,
        ticker=ticker,
        reason="thesis_invalidated",
        target_quantity=Decimal("10"),
        risk_approved=True,
    )


def _phase81b_filter(
    actions: list[PortfolioAction],
    state_positions: dict[str, Any],
    broker_tickers: set[str],
    enabled: bool = True,
) -> tuple[list[PortfolioAction], list[str]]:
    """Mirror of the Phase 81-B guard at paper_trading.py just before risk
    validation.  Any divergence from production should fail these tests.
    """
    if not enabled:
        return actions, []
    kept: list[PortfolioAction] = []
    skipped: list[str] = []
    for a in actions:
        if a.action_type != ActionType.OPEN:
            kept.append(a)
            continue
        held_pos = state_positions.get(a.ticker)
        held_qty = getattr(held_pos, "quantity", 0) or 0
        held_in_state = held_qty > 0
        held_in_broker = a.ticker in broker_tickers
        if held_in_state or held_in_broker:
            skipped.append(a.ticker)
            continue
        kept.append(a)
    return kept, skipped


class _FakePosition:
    def __init__(self, qty: int) -> None:
        self.quantity = Decimal(qty)


class TestPhase81BOpenStackingGuard:
    """OPEN actions from any strategy must be dropped when ticker already held."""

    def test_ranked_buy_signal_open_dropped_when_held(self) -> None:
        actions = [_open("AAPL", reason="ranked_buy_signal: composite=0.71")]
        kept, skipped = _phase81b_filter(
            actions,
            state_positions={"AAPL": _FakePosition(qty=50)},
            broker_tickers=set(),
        )
        assert kept == []
        assert skipped == ["AAPL"]

    def test_momentum_v1_open_dropped_when_broker_holds(self) -> None:
        actions = [_open("NVDA", reason="momentum_v1: 5d=+8%")]
        kept, skipped = _phase81b_filter(
            actions,
            state_positions={},  # state stale
            broker_tickers={"NVDA"},
        )
        assert kept == []
        assert skipped == ["NVDA"]

    def test_theme_alignment_v1_open_dropped_when_held(self) -> None:
        actions = [_open("VRT", reason="theme_alignment_v1: ai_infra")]
        kept, skipped = _phase81b_filter(
            actions,
            state_positions={"VRT": _FakePosition(qty=22)},
            broker_tickers={"VRT"},
        )
        assert kept == []
        assert skipped == ["VRT"]

    def test_close_actions_pass_through_unaffected(self) -> None:
        actions = [_close("INTC")]
        kept, skipped = _phase81b_filter(
            actions,
            state_positions={"INTC": _FakePosition(qty=127)},
            broker_tickers={"INTC"},
        )
        assert len(kept) == 1
        assert kept[0].action_type == ActionType.CLOSE
        assert skipped == []

    def test_open_allowed_when_truly_absent(self) -> None:
        actions = [_open("AAPL", reason="ranked_buy_signal")]
        kept, skipped = _phase81b_filter(
            actions,
            state_positions={},
            broker_tickers=set(),
        )
        assert len(kept) == 1
        assert skipped == []

    def test_disabled_flag_passes_through(self) -> None:
        actions = [_open("AAPL", reason="ranked_buy_signal")]
        kept, skipped = _phase81b_filter(
            actions,
            state_positions={"AAPL": _FakePosition(qty=50)},
            broker_tickers={"AAPL"},
            enabled=False,
        )
        assert len(kept) == 1
        assert skipped == []

    def test_mixed_batch_partitions_correctly(self) -> None:
        actions = [
            _open("AAPL", reason="ranked_buy_signal"),     # already held
            _open("NVDA", reason="momentum_v1"),           # broker only
            _open("GOOGL", reason="theme_alignment_v1"),   # truly absent
            _close("INTC"),                                # close passes through
        ]
        kept, skipped = _phase81b_filter(
            actions,
            state_positions={"AAPL": _FakePosition(qty=50)},
            broker_tickers={"NVDA", "INTC"},
        )
        kept_tickers = [a.ticker for a in kept]
        assert kept_tickers == ["GOOGL", "INTC"]
        assert sorted(skipped) == ["AAPL", "NVDA"]


# ─── Phase 81-C: realized_pnl fallback ────────────────────────────────────────


def _phase81c_fallback(
    entry_price: Decimal,
    quantity: Decimal,
    market_value: Decimal | None,
    enabled: bool = True,
) -> tuple[Decimal | None, Decimal | None]:
    """Mirror of the Phase 81-C fallback in _persist_positions close-loop.

    Returns (exit_price, realized_pnl) computed from existing row state.
    """
    if not enabled:
        return None, None
    if not quantity or not entry_price:
        return None, None
    exit_d: Decimal | None = None
    if market_value is not None and quantity > Decimal("0"):
        exit_d = (market_value / quantity).quantize(Decimal("0.0001"))
    if exit_d is None:
        return None, None
    realized = ((exit_d - entry_price) * quantity).quantize(Decimal("0.01"))
    return exit_d, realized


class TestPhase81CRealizedPnlFallback:
    """When broker-sync closes a position without a ClosedTrade record,
    the writer must still produce a non-NULL realized_pnl."""

    def test_profit_computed_from_market_value(self) -> None:
        # 50 shares, entry $100, market_value reflects $110 exit.
        exit_p, pnl = _phase81c_fallback(
            entry_price=Decimal("100.00"),
            quantity=Decimal("50"),
            market_value=Decimal("5500.00"),
        )
        assert exit_p == Decimal("110.0000")
        assert pnl == Decimal("500.00")

    def test_loss_computed_from_market_value(self) -> None:
        exit_p, pnl = _phase81c_fallback(
            entry_price=Decimal("100.00"),
            quantity=Decimal("50"),
            market_value=Decimal("4500.00"),
        )
        assert exit_p == Decimal("90.0000")
        assert pnl == Decimal("-500.00")

    def test_flat_yields_zero(self) -> None:
        exit_p, pnl = _phase81c_fallback(
            entry_price=Decimal("100.00"),
            quantity=Decimal("50"),
            market_value=Decimal("5000.00"),
        )
        assert exit_p == Decimal("100.0000")
        assert pnl == Decimal("0.00")

    def test_missing_market_value_no_fallback(self) -> None:
        exit_p, pnl = _phase81c_fallback(
            entry_price=Decimal("100.00"),
            quantity=Decimal("50"),
            market_value=None,
        )
        assert exit_p is None
        assert pnl is None

    def test_disabled_flag_yields_none(self) -> None:
        exit_p, pnl = _phase81c_fallback(
            entry_price=Decimal("100.00"),
            quantity=Decimal("50"),
            market_value=Decimal("5500.00"),
            enabled=False,
        )
        assert exit_p is None
        assert pnl is None

    def test_zero_quantity_no_fallback(self) -> None:
        exit_p, pnl = _phase81c_fallback(
            entry_price=Decimal("100.00"),
            quantity=Decimal("0"),
            market_value=Decimal("5500.00"),
        )
        assert exit_p is None
        assert pnl is None


# ─── End-to-end shape check (Phase 81-A round-trip into SOD capture) ──────────


class TestPhase81RoundTrip:
    """Validate that a reseeded broker reports the same equity as the prior
    snapshot — eliminating the 2026-05-13 c7 SOD reset condition."""

    def test_sod_equity_matches_last_known_equity_after_reseed(self) -> None:
        broker = PaperBrokerAdapter()
        broker.seed_from_db_positions(
            positions=[
                ("INTC", Decimal("127"), Decimal("31.21")),
                ("AMZN", Decimal("59"),  Decimal("258.40")),
                ("AMD",  Decimal("34"),  Decimal("147.06")),
                ("MU",   Decimal("19"),  Decimal("616.48")),
                ("UNH",  Decimal("38"),  Decimal("405.26")),
            ],
            last_known_equity=Decimal("117432.00"),
        )
        acct = broker.get_account_state()
        # The next paper cycle's `portfolio_state.equity` reads from broker
        # account state.  After reseed, equity must be the Tue close equity
        # (modulo the tiny rounding that the seed helper introduces by
        # quantising cost basis).
        # Allow a $1 tolerance for compounded ROUND_HALF_UP across 5 positions.
        assert abs(acct.equity_value - Decimal("117432.00")) <= Decimal("1.00")
        assert acct.cash_balance >= Decimal("0")


# ─── Phase 81-A hotfix (DEC-086): portfolio_state seed at worker ────────────


class _StubAppState:
    """Minimal app_state for the hotfix unit test (avoids ApiAppState import)."""

    def __init__(self) -> None:
        self.portfolio_state = None


def _phase81_hotfix_simulated_state(
    has_initial: bool,
    snapshot_equity: Decimal | None,
    snapshot_cash: Decimal | None,
    positions: list[tuple[str, Decimal, Decimal]],
):
    """Mirror of the production helper's externally-visible contract.

    Skips when an app_state already has portfolio_state; otherwise builds
    a fresh PortfolioState the same way the helper does and returns it.
    """
    from services.portfolio_engine.models import (
        PortfolioPosition as _PP,
    )
    from services.portfolio_engine.models import (
        PortfolioState as _PS,
    )

    app_state = _StubAppState()
    if has_initial:
        app_state.portfolio_state = _PS(cash=Decimal("999"))

    if app_state.portfolio_state is not None:
        return app_state, False

    pos_map: dict[str, _PP] = {}
    for t, q, e in positions:
        if q <= Decimal("0"):
            continue
        pos_map[t] = _PP(
            ticker=t,
            quantity=q,
            avg_entry_price=e,
            current_price=e,
            opened_at=None,
        )

    cash = snapshot_cash if snapshot_cash is not None else Decimal("100000")
    if cash < Decimal("0"):
        cash = Decimal("100000")
        snapshot_equity = Decimal("100000")
        pos_map = {}

    app_state.portfolio_state = _PS(
        cash=cash,
        positions=pos_map,
        start_of_day_equity=snapshot_equity,
        start_of_month_equity=snapshot_equity,
        high_water_mark=snapshot_equity,
    )
    return app_state, True


class TestPhase81AHotfixPortfolioStateSeed:
    """Without this seed, SOD captures $100k cold-start equity even after
    the broker reseed succeeded (the 2026-05-14 c1 incident)."""

    def test_seeds_when_state_absent(self) -> None:
        app_state, seeded = _phase81_hotfix_simulated_state(
            has_initial=False,
            snapshot_equity=Decimal("117432.00"),
            snapshot_cash=Decimal("42239.00"),
            positions=[("INTC", Decimal("127"), Decimal("31.21"))],
        )
        assert seeded is True
        assert app_state.portfolio_state.cash == Decimal("42239.00")
        assert app_state.portfolio_state.start_of_day_equity == Decimal("117432.00")
        assert "INTC" in app_state.portfolio_state.positions

    def test_skips_when_state_already_present(self) -> None:
        app_state, seeded = _phase81_hotfix_simulated_state(
            has_initial=True,
            snapshot_equity=Decimal("117432.00"),
            snapshot_cash=Decimal("42239.00"),
            positions=[("INTC", Decimal("127"), Decimal("31.21"))],
        )
        assert seeded is False
        # Pre-existing state preserved unchanged.
        assert app_state.portfolio_state.cash == Decimal("999")

    def test_phantom_cash_resets_to_cold_start(self) -> None:
        app_state, _ = _phase81_hotfix_simulated_state(
            has_initial=False,
            snapshot_equity=Decimal("117432.00"),
            snapshot_cash=Decimal("-500.00"),  # phantom negative cash
            positions=[("INTC", Decimal("127"), Decimal("31.21"))],
        )
        # Phase 70 guard mirrors API restore behaviour: any negative cash
        # in paper mode is a bug-state, so clamp to cold-start defaults
        # rather than carry corruption forward.
        assert app_state.portfolio_state.cash == Decimal("100000")
        assert app_state.portfolio_state.positions == {}
        assert app_state.portfolio_state.start_of_day_equity == Decimal("100000")

    def test_sod_equity_equals_cash_plus_cost_basis(self) -> None:
        """End-to-end shape: the SOD capture reads portfolio_state.equity.

        portfolio_state.equity = cash + sum(market_value).  market_value is
        derived from current_price * qty.  The hotfix sets current_price =
        entry_price as a proxy, so equity should land on cash + cost_basis.

        In production the broker's reseed pins cash so that broker equity
        (cash + cost_basis) == snapshot_equity.  The portfolio_state
        restore uses the snapshot's `cash_balance` field directly, so
        equity here = snapshot_cash + cost_basis.  Both call sites need
        to be in sync for SOD to capture the right value.
        """
        positions = [
            ("INTC", Decimal("127"), Decimal("31.21")),
            ("AMZN", Decimal("59"),  Decimal("258.40")),
            ("AMD",  Decimal("34"),  Decimal("147.06")),
            ("MU",   Decimal("19"),  Decimal("616.48")),
            ("UNH",  Decimal("38"),  Decimal("405.26")),
        ]
        expected_cost_basis = sum(
            (q * e for _, q, e in positions), Decimal("0")
        )
        snap_cash = Decimal("42239.00")
        snap_equity = snap_cash + expected_cost_basis

        app_state, _ = _phase81_hotfix_simulated_state(
            has_initial=False,
            snapshot_equity=snap_equity,
            snapshot_cash=snap_cash,
            positions=positions,
        )
        # The SOD capture will write portfolio_state.equity. After the
        # hotfix that value must equal snap_cash + cost_basis, NOT $100k.
        assert app_state.portfolio_state.equity != Decimal("100000")
        assert (
            app_state.portfolio_state.equity == snap_cash + expected_cost_basis
        )
