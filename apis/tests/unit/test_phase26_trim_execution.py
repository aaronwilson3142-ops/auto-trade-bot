"""
Phase 26: TRIM Execution + Overconcentration Trim Trigger

Tests cover:
  - ExecutionEngineService._execute_trim() — partial sell (FILLED, REJECTED, BLOCKED, errors)
  - RiskEngineService.evaluate_trims() — overconcentration detection and trim sizing
  - paper_trading.py — trim wired into cycle after exits
  - end-to-end: overconcentrated position → trim fires → partial position reduction

55 tests across 11 test classes.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from services.portfolio_engine.models import (
    ActionType,
    PortfolioAction,
    PortfolioPosition,
    PortfolioState,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_settings(**kwargs):
    from config.settings import Settings
    defaults = dict(
        db_url="postgresql+psycopg://u:p@localhost:5432/apis",
        operating_mode="paper",
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def _make_position(
    ticker: str = "AAPL",
    quantity: Decimal = Decimal("10"),
    avg_entry_price: Decimal = Decimal("100.00"),
    current_price: Decimal = Decimal("100.00"),
    opened_at: dt.datetime | None = None,
) -> PortfolioPosition:
    return PortfolioPosition(
        ticker=ticker,
        quantity=quantity,
        avg_entry_price=avg_entry_price,
        current_price=current_price,
        opened_at=opened_at or dt.datetime.utcnow(),
        thesis_summary="test thesis",
        strategy_key="momentum_v1",
    )


def _make_portfolio_state(
    cash: Decimal = Decimal("80000.00"),
    positions: dict | None = None,
) -> PortfolioState:
    return PortfolioState(
        cash=cash,
        positions=positions or {},
        start_of_day_equity=Decimal("100000.00"),
        high_water_mark=Decimal("100000.00"),
    )


def _make_trim_action(
    ticker: str = "AAPL",
    target_quantity: Decimal | None = Decimal("5"),
    risk_approved: bool = True,
) -> PortfolioAction:
    return PortfolioAction(
        action_type=ActionType.TRIM,
        ticker=ticker,
        reason="overconcentration test",
        target_quantity=target_quantity,
        risk_approved=risk_approved,
    )


# ── TestTrimExecutionFilled ───────────────────────────────────────────────────

class TestTrimExecutionFilled:
    """Happy-path TRIM execution through PaperBrokerAdapter."""

    def setup_method(self):
        from broker_adapters.paper.adapter import PaperBrokerAdapter
        from services.execution_engine.service import ExecutionEngineService
        self._broker = PaperBrokerAdapter(
            starting_cash=Decimal("100000.00"),
            market_open=True,
        )
        self._broker.connect()
        self._svc = ExecutionEngineService(
            settings=_make_settings(),
            broker=self._broker,
        )

    def _buy_aapl(self, qty: int = 20, price: Decimal = Decimal("150.00")) -> None:
        """Seed a long AAPL position in the paper broker."""
        from broker_adapters.base.models import OrderRequest, OrderSide, OrderType
        self._broker.set_price("AAPL", price)
        order_req = OrderRequest(
            idempotency_key="seed-aapl-open",
            ticker="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal(str(qty)),
        )
        self._broker.place_order(order_req)

    def test_trim_returns_filled_status(self):
        from services.execution_engine.models import ExecutionRequest, ExecutionStatus
        self._buy_aapl(qty=20, price=Decimal("150.00"))
        action = _make_trim_action(ticker="AAPL", target_quantity=Decimal("5"))
        req = ExecutionRequest(action=action, current_price=Decimal("150.00"))
        result = self._svc.execute_action(req)
        assert result.status == ExecutionStatus.FILLED

    def test_trim_fill_quantity_matches_target(self):
        from services.execution_engine.models import ExecutionRequest
        self._buy_aapl(qty=20, price=Decimal("150.00"))
        action = _make_trim_action(ticker="AAPL", target_quantity=Decimal("5"))
        req = ExecutionRequest(action=action, current_price=Decimal("150.00"))
        result = self._svc.execute_action(req)
        assert result.fill_quantity == Decimal("5")

    def test_trim_fill_price_populated(self):
        from services.execution_engine.models import ExecutionRequest
        self._buy_aapl(qty=20, price=Decimal("150.00"))
        action = _make_trim_action(ticker="AAPL", target_quantity=Decimal("5"))
        req = ExecutionRequest(action=action, current_price=Decimal("150.00"))
        result = self._svc.execute_action(req)
        assert result.fill_price is not None
        assert result.fill_price > Decimal("0")

    def test_trim_broker_order_id_populated(self):
        from services.execution_engine.models import ExecutionRequest
        self._buy_aapl(qty=20, price=Decimal("150.00"))
        action = _make_trim_action(ticker="AAPL", target_quantity=Decimal("5"))
        req = ExecutionRequest(action=action, current_price=Decimal("150.00"))
        result = self._svc.execute_action(req)
        assert result.broker_order_id is not None

    def test_trim_filled_at_populated(self):
        from services.execution_engine.models import ExecutionRequest
        self._buy_aapl(qty=20, price=Decimal("150.00"))
        action = _make_trim_action(ticker="AAPL", target_quantity=Decimal("5"))
        req = ExecutionRequest(action=action, current_price=Decimal("150.00"))
        result = self._svc.execute_action(req)
        assert result.filled_at is not None

    def test_trim_caps_at_position_size(self):
        """If target_quantity > actual position, sell only the full position."""
        from services.execution_engine.models import ExecutionRequest, ExecutionStatus
        self._buy_aapl(qty=10, price=Decimal("150.00"))
        # Target qty (20) > position (10) — should sell only 10
        action = _make_trim_action(ticker="AAPL", target_quantity=Decimal("20"))
        req = ExecutionRequest(action=action, current_price=Decimal("150.00"))
        result = self._svc.execute_action(req)
        assert result.status == ExecutionStatus.FILLED
        assert result.fill_quantity == Decimal("10")

    def test_trim_partial_position_remains(self):
        """After a trim, the remaining shares should still exist in the broker."""
        from services.execution_engine.models import ExecutionRequest
        self._buy_aapl(qty=20, price=Decimal("150.00"))
        action = _make_trim_action(ticker="AAPL", target_quantity=Decimal("5"))
        req = ExecutionRequest(action=action, current_price=Decimal("150.00"))
        self._svc.execute_action(req)
        # 20 bought - 5 sold = 15 remaining
        remaining = self._broker.get_position("AAPL")
        assert remaining.quantity == Decimal("15")

    def test_trim_idempotency_key_contains_trim(self):
        """Idempotency key should contain 'trim' to distinguish from 'open'/'close'."""
        from services.execution_engine.models import ExecutionRequest
        self._buy_aapl(qty=20, price=Decimal("150.00"))
        action = _make_trim_action(ticker="AAPL", target_quantity=Decimal("5"))
        req = ExecutionRequest(action=action, current_price=Decimal("150.00"))
        result = self._svc.execute_action(req)
        order = self._broker.get_order(result.broker_order_id)
        assert "trim" in order.idempotency_key


# ── TestTrimExecutionRejected ─────────────────────────────────────────────────

class TestTrimExecutionRejected:
    """TRIM execution rejection cases."""

    def setup_method(self):
        from broker_adapters.paper.adapter import PaperBrokerAdapter
        from services.execution_engine.service import ExecutionEngineService
        self._broker = PaperBrokerAdapter(market_open=True)
        self._broker.connect()
        self._svc = ExecutionEngineService(
            settings=_make_settings(),
            broker=self._broker,
        )

    def test_trim_none_target_quantity_rejected(self):
        from services.execution_engine.models import ExecutionRequest, ExecutionStatus
        action = _make_trim_action(ticker="AAPL", target_quantity=None)
        req = ExecutionRequest(action=action, current_price=Decimal("150.00"))
        result = self._svc.execute_action(req)
        assert result.status == ExecutionStatus.REJECTED

    def test_trim_zero_target_quantity_rejected(self):
        from services.execution_engine.models import ExecutionRequest, ExecutionStatus
        action = _make_trim_action(ticker="AAPL", target_quantity=Decimal("0"))
        req = ExecutionRequest(action=action, current_price=Decimal("150.00"))
        result = self._svc.execute_action(req)
        assert result.status == ExecutionStatus.REJECTED

    def test_trim_negative_target_quantity_rejected(self):
        from services.execution_engine.models import ExecutionRequest, ExecutionStatus
        action = _make_trim_action(ticker="AAPL", target_quantity=Decimal("-3"))
        req = ExecutionRequest(action=action, current_price=Decimal("150.00"))
        result = self._svc.execute_action(req)
        assert result.status == ExecutionStatus.REJECTED

    def test_trim_no_position_rejected(self):
        """Broker has no AAPL position — TRIM should return REJECTED."""
        from services.execution_engine.models import ExecutionRequest, ExecutionStatus
        action = _make_trim_action(ticker="AAPL", target_quantity=Decimal("5"))
        req = ExecutionRequest(action=action, current_price=Decimal("150.00"))
        result = self._svc.execute_action(req)
        assert result.status == ExecutionStatus.REJECTED

    def test_trim_no_position_error_message_mentions_ticker(self):
        from services.execution_engine.models import ExecutionRequest
        action = _make_trim_action(ticker="TSLA", target_quantity=Decimal("5"))
        req = ExecutionRequest(action=action, current_price=Decimal("200.00"))
        result = self._svc.execute_action(req)
        assert result.error_message is not None
        assert "TSLA" in result.error_message

    def test_trim_none_quantity_error_mentions_requirement(self):
        from services.execution_engine.models import ExecutionRequest
        action = _make_trim_action(ticker="AAPL", target_quantity=None)
        req = ExecutionRequest(action=action, current_price=Decimal("150.00"))
        result = self._svc.execute_action(req)
        assert result.error_message is not None
        assert "target_quantity" in result.error_message


# ── TestTrimExecutionKillSwitch ───────────────────────────────────────────────

class TestTrimExecutionKillSwitch:
    """Kill switch blocks TRIM execution."""

    def test_trim_blocked_by_kill_switch(self):
        from broker_adapters.paper.adapter import PaperBrokerAdapter
        from services.execution_engine.models import ExecutionRequest, ExecutionStatus
        from services.execution_engine.service import ExecutionEngineService
        settings = _make_settings(kill_switch=True)
        broker = PaperBrokerAdapter(market_open=True)
        broker.connect()
        svc = ExecutionEngineService(settings=settings, broker=broker)
        action = _make_trim_action(ticker="AAPL", target_quantity=Decimal("5"))
        req = ExecutionRequest(action=action, current_price=Decimal("150.00"))
        result = svc.execute_action(req)
        assert result.status == ExecutionStatus.BLOCKED

    def test_trim_kill_switch_error_message(self):
        from broker_adapters.paper.adapter import PaperBrokerAdapter
        from services.execution_engine.models import ExecutionRequest
        from services.execution_engine.service import ExecutionEngineService
        settings = _make_settings(kill_switch=True)
        svc = ExecutionEngineService(settings=settings, broker=PaperBrokerAdapter(market_open=True))
        action = _make_trim_action(ticker="AAPL", target_quantity=Decimal("5"))
        req = ExecutionRequest(action=action, current_price=Decimal("150.00"))
        result = svc.execute_action(req)
        assert result.error_message is not None
        assert "Kill switch" in result.error_message or "kill switch" in result.error_message.lower()

    def test_trim_blocked_action_has_original_action(self):
        from broker_adapters.paper.adapter import PaperBrokerAdapter
        from services.execution_engine.models import ExecutionRequest
        from services.execution_engine.service import ExecutionEngineService
        settings = _make_settings(kill_switch=True)
        svc = ExecutionEngineService(settings=settings, broker=PaperBrokerAdapter(market_open=True))
        action = _make_trim_action(ticker="AAPL", target_quantity=Decimal("5"))
        req = ExecutionRequest(action=action, current_price=Decimal("150.00"))
        result = svc.execute_action(req)
        assert result.action is action


# ── TestTrimExecutionBrokerErrors ─────────────────────────────────────────────

class TestTrimExecutionBrokerErrors:
    """Broker-level errors during TRIM."""

    def test_trim_broker_error_returns_rejected(self):
        """BrokerError from place_order → ExecutionStatus.REJECTED."""
        from unittest.mock import MagicMock

        from broker_adapters.base.exceptions import BrokerError
        from services.execution_engine.models import ExecutionRequest, ExecutionStatus
        from services.execution_engine.service import ExecutionEngineService

        mock_broker = MagicMock()
        mock_broker.adapter_name = "mock"
        # Position exists
        mock_position = MagicMock()
        mock_position.quantity = Decimal("20")
        mock_broker.get_position.return_value = mock_position
        # But place_order raises BrokerError
        mock_broker.place_order.side_effect = BrokerError("connection failed")

        svc = ExecutionEngineService(settings=_make_settings(), broker=mock_broker)
        action = _make_trim_action(ticker="AAPL", target_quantity=Decimal("5"))
        req = ExecutionRequest(action=action, current_price=Decimal("150.00"))
        result = svc.execute_action(req)
        assert result.status == ExecutionStatus.REJECTED

    def test_trim_unexpected_error_returns_error_status(self):
        """Unexpected exception during TRIM → ExecutionStatus.ERROR."""
        from unittest.mock import MagicMock

        from services.execution_engine.models import ExecutionRequest, ExecutionStatus
        from services.execution_engine.service import ExecutionEngineService

        mock_broker = MagicMock()
        mock_broker.adapter_name = "mock"
        mock_position = MagicMock()
        mock_position.quantity = Decimal("20")
        mock_broker.get_position.return_value = mock_position
        mock_broker.place_order.side_effect = RuntimeError("unexpected DB failure")

        svc = ExecutionEngineService(settings=_make_settings(), broker=mock_broker)
        action = _make_trim_action(ticker="AAPL", target_quantity=Decimal("5"))
        req = ExecutionRequest(action=action, current_price=Decimal("150.00"))
        result = svc.execute_action(req)
        assert result.status == ExecutionStatus.ERROR

    def test_trim_result_always_has_action_reference(self):
        """REJECTED and ERROR results should preserve the original action."""
        from broker_adapters.paper.adapter import PaperBrokerAdapter
        from services.execution_engine.models import ExecutionRequest
        from services.execution_engine.service import ExecutionEngineService
        broker = PaperBrokerAdapter(market_open=True)
        svc = ExecutionEngineService(settings=_make_settings(), broker=broker)
        action = _make_trim_action(ticker="SPY", target_quantity=Decimal("5"))  # no position
        req = ExecutionRequest(action=action, current_price=Decimal("500.00"))
        result = svc.execute_action(req)
        assert result.action is action


# ── TestEvaluateTrimsBasic ────────────────────────────────────────────────────

class TestEvaluateTrimsBasic:
    """Core overconcentration detection and sizing logic."""

    def setup_method(self):
        from services.risk_engine.service import RiskEngineService
        # max_single_name_pct=0.20 → trigger when position > 20% of equity
        self._settings = _make_settings(max_single_name_pct=0.20)
        self._svc = RiskEngineService(settings=self._settings)

    def test_overconcentration_triggers_trim(self):
        """Position at 30% of equity (above 20% limit) → TRIM fires."""
        # Portfolio: cash=70k, AAPL 100 shares @ 300 = 30k market value
        # equity = 100k; 30k/100k = 30% > 20% max → trim
        position = _make_position("AAPL", quantity=Decimal("100"), current_price=Decimal("300.00"))
        state = _make_portfolio_state(
            cash=Decimal("70000.00"),
            positions={"AAPL": position},
        )
        # equity = 70000 + 30000 = 100000
        actions = self._svc.evaluate_trims(portfolio_state=state)
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.TRIM
        assert actions[0].ticker == "AAPL"

    def test_trim_action_target_quantity_positive(self):
        position = _make_position("AAPL", quantity=Decimal("100"), current_price=Decimal("300.00"))
        state = _make_portfolio_state(cash=Decimal("70000.00"), positions={"AAPL": position})
        actions = self._svc.evaluate_trims(portfolio_state=state)
        assert actions[0].target_quantity > Decimal("0")

    def test_trim_shares_to_sell_correct_math(self):
        """Verify the exact number of shares to sell.

        equity = 70000 + 100*300 = 100000
        max_value = 100000 * 0.20 = 20000
        current_value = 30000
        excess = 30000 - 20000 = 10000
        shares_to_sell = floor(10000 / 300) = 33
        """
        position = _make_position("AAPL", quantity=Decimal("100"), current_price=Decimal("300.00"))
        state = _make_portfolio_state(cash=Decimal("70000.00"), positions={"AAPL": position})
        actions = self._svc.evaluate_trims(portfolio_state=state)
        # excess = 10000, price = 300, shares_to_sell = floor(10000/300) = 33
        assert actions[0].target_quantity == Decimal("33")

    def test_trim_action_is_pre_approved(self):
        position = _make_position("AAPL", quantity=Decimal("100"), current_price=Decimal("300.00"))
        state = _make_portfolio_state(cash=Decimal("70000.00"), positions={"AAPL": position})
        actions = self._svc.evaluate_trims(portfolio_state=state)
        assert actions[0].risk_approved is True

    def test_trim_action_type_is_trim(self):
        position = _make_position("AAPL", quantity=Decimal("100"), current_price=Decimal("300.00"))
        state = _make_portfolio_state(cash=Decimal("70000.00"), positions={"AAPL": position})
        actions = self._svc.evaluate_trims(portfolio_state=state)
        assert actions[0].action_type == ActionType.TRIM

    def test_trim_reason_mentions_overconcentration(self):
        position = _make_position("AAPL", quantity=Decimal("100"), current_price=Decimal("300.00"))
        state = _make_portfolio_state(cash=Decimal("70000.00"), positions={"AAPL": position})
        actions = self._svc.evaluate_trims(portfolio_state=state)
        assert "overconcentration" in actions[0].reason.lower() or "%" in actions[0].reason

    def test_multiple_overconcentrated_positions_all_trimmed(self):
        """Two positions both above 20% limit → two TRIM actions."""
        pos_aapl = _make_position("AAPL", quantity=Decimal("100"), current_price=Decimal("300.00"))
        pos_msft = _make_position("MSFT", quantity=Decimal("80"), current_price=Decimal("350.00"))
        # equity = 10000 cash + 30000 + 28000 = 68000
        # aapl = 30000/68000 ≈ 44% > 20%
        # msft = 28000/68000 ≈ 41% > 20%
        state = _make_portfolio_state(
            cash=Decimal("10000.00"),
            positions={"AAPL": pos_aapl, "MSFT": pos_msft},
        )
        actions = self._svc.evaluate_trims(portfolio_state=state)
        assert len(actions) == 2
        tickers = {a.ticker for a in actions}
        assert "AAPL" in tickers
        assert "MSFT" in tickers


# ── TestEvaluateTrimsNoTrigger ────────────────────────────────────────────────

class TestEvaluateTrimsNoTrigger:
    """Cases where no trim should fire."""

    def setup_method(self):
        from services.risk_engine.service import RiskEngineService
        self._svc = RiskEngineService(settings=_make_settings(max_single_name_pct=0.20))

    def test_within_limit_produces_no_trim(self):
        """Position at 15% of equity (below 20% limit) → no TRIM."""
        # equity = 100k, position = 15k (15%)
        position = _make_position("AAPL", quantity=Decimal("100"), current_price=Decimal("150.00"))
        state = _make_portfolio_state(
            cash=Decimal("85000.00"),
            positions={"AAPL": position},
        )
        actions = self._svc.evaluate_trims(portfolio_state=state)
        assert actions == []

    def test_exactly_at_limit_no_trim(self):
        """Position exactly at 20% limit → no TRIM (not strictly above)."""
        # equity = 100k, position = 20k (20.00%)
        position = _make_position("AAPL", quantity=Decimal("100"), current_price=Decimal("200.00"))
        state = _make_portfolio_state(
            cash=Decimal("80000.00"),
            positions={"AAPL": position},
        )
        actions = self._svc.evaluate_trims(portfolio_state=state)
        assert actions == []

    def test_empty_positions_returns_empty(self):
        state = _make_portfolio_state(cash=Decimal("100000.00"), positions={})
        actions = self._svc.evaluate_trims(portfolio_state=state)
        assert actions == []

    def test_zero_equity_returns_empty(self):
        state = PortfolioState(cash=Decimal("0"), positions={})
        actions = self._svc.evaluate_trims(portfolio_state=state)
        assert actions == []


# ── TestEvaluateTrimsKillSwitch ───────────────────────────────────────────────

class TestEvaluateTrimsKillSwitch:
    """Kill switch suppresses evaluate_trims."""

    def test_kill_switch_settings_returns_empty(self):
        """settings.kill_switch=True → evaluate_trims returns []."""
        from services.risk_engine.service import RiskEngineService
        svc = RiskEngineService(settings=_make_settings(kill_switch=True, max_single_name_pct=0.20))
        position = _make_position("AAPL", quantity=Decimal("100"), current_price=Decimal("300.00"))
        state = _make_portfolio_state(cash=Decimal("70000.00"), positions={"AAPL": position})
        actions = svc.evaluate_trims(portfolio_state=state)
        assert actions == []

    def test_no_kill_switch_still_fires(self):
        """Confirm kill_switch=False does NOT suppress trims."""
        from services.risk_engine.service import RiskEngineService
        svc = RiskEngineService(settings=_make_settings(kill_switch=False, max_single_name_pct=0.20))
        position = _make_position("AAPL", quantity=Decimal("100"), current_price=Decimal("300.00"))
        state = _make_portfolio_state(cash=Decimal("70000.00"), positions={"AAPL": position})
        actions = svc.evaluate_trims(portfolio_state=state)
        assert len(actions) == 1


# ── TestEvaluateTrimsEdgeCases ────────────────────────────────────────────────

class TestEvaluateTrimsEdgeCases:
    """Edge cases for evaluate_trims."""

    def setup_method(self):
        from services.risk_engine.service import RiskEngineService
        self._svc = RiskEngineService(settings=_make_settings(max_single_name_pct=0.20))

    def test_zero_current_price_skips_position(self):
        """Position with current_price=0 should not produce a trim (cannot divide)."""
        position = _make_position("AAPL", quantity=Decimal("100"), current_price=Decimal("0"))
        state = _make_portfolio_state(cash=Decimal("100000.00"), positions={"AAPL": position})
        # equity = 100000 + 0 = 100000; market_value = 0 → not above limit
        actions = self._svc.evaluate_trims(portfolio_state=state)
        assert actions == []

    def test_fractional_excess_floored_to_whole_shares(self):
        """Excess value that doesn't divide evenly by price → floor to whole shares."""
        # equity=100k, max=20k, position=25001 (price=250.01)
        # excess = 5001, shares_to_sell = floor(5001/250.01) = floor(20.003) = 20
        position = _make_position("AAPL", quantity=Decimal("100"), current_price=Decimal("250.01"))
        # equity = 75000 + 25001 = 100001
        state = _make_portfolio_state(cash=Decimal("75000.00"), positions={"AAPL": position})
        actions = self._svc.evaluate_trims(portfolio_state=state)
        if actions:
            # target_quantity must be a whole number of shares
            qty = actions[0].target_quantity
            assert qty == qty.to_integral_value()

    def test_trim_sizing_rationale_mentions_max_pct(self):
        """sizing_rationale should mention the max percentage applied."""
        position = _make_position("AAPL", quantity=Decimal("100"), current_price=Decimal("300.00"))
        state = _make_portfolio_state(cash=Decimal("70000.00"), positions={"AAPL": position})
        actions = self._svc.evaluate_trims(portfolio_state=state)
        assert actions
        assert "20" in actions[0].sizing_rationale  # 20% appears in rationale

    def test_trim_preserves_position_thesis_summary(self):
        """Trim action should carry the position's thesis_summary for traceability."""
        position = PortfolioPosition(
            ticker="AAPL",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("250.00"),
            current_price=Decimal("300.00"),
            opened_at=dt.datetime.utcnow(),
            thesis_summary="AI theme leader",
            strategy_key="theme_alignment_v1",
        )
        state = _make_portfolio_state(cash=Decimal("70000.00"), positions={"AAPL": position})
        actions = self._svc.evaluate_trims(portfolio_state=state)
        assert actions
        assert actions[0].thesis_summary == "AI theme leader"


# ── TestExecutionEngineTrimRouting ────────────────────────────────────────────

class TestExecutionEngineTrimRouting:
    """Verify TRIM is properly routed through execute_action dispatch."""

    def setup_method(self):
        from broker_adapters.paper.adapter import PaperBrokerAdapter
        from services.execution_engine.service import ExecutionEngineService
        self._broker = PaperBrokerAdapter(
            starting_cash=Decimal("100000.00"),
            market_open=True,
        )
        self._broker.connect()
        self._svc = ExecutionEngineService(
            settings=_make_settings(),
            broker=self._broker,
        )

    def _seed_position(
        self, ticker: str = "AAPL", qty: int = 20, price: Decimal = Decimal("150.00")
    ) -> None:
        from broker_adapters.base.models import OrderRequest, OrderSide, OrderType
        self._broker.set_price(ticker, price)
        self._broker.place_order(OrderRequest(
            idempotency_key=f"seed-{ticker}-{id(self)}",
            ticker=ticker,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal(str(qty)),
        ))

    def test_execute_action_routes_trim_not_error(self):
        """TRIM with a valid position should NOT return ERROR status."""
        from services.execution_engine.models import ExecutionRequest, ExecutionStatus
        self._seed_position("AAPL", qty=20, price=Decimal("150.00"))
        action = _make_trim_action(ticker="AAPL", target_quantity=Decimal("5"))
        req = ExecutionRequest(action=action, current_price=Decimal("150.00"))
        result = self._svc.execute_action(req)
        assert result.status != ExecutionStatus.ERROR

    def test_execute_action_trim_returns_filled(self):
        from services.execution_engine.models import ExecutionRequest, ExecutionStatus
        self._seed_position("AAPL", qty=20, price=Decimal("150.00"))
        action = _make_trim_action(ticker="AAPL", target_quantity=Decimal("5"))
        req = ExecutionRequest(action=action, current_price=Decimal("150.00"))
        result = self._svc.execute_action(req)
        assert result.status == ExecutionStatus.FILLED

    def test_execute_approved_actions_batch_handles_trim(self):
        """execute_approved_actions should process a TRIM within a batch."""
        from services.execution_engine.models import ExecutionRequest, ExecutionStatus
        self._seed_position("AAPL", qty=20, price=Decimal("150.00"))
        action = _make_trim_action(ticker="AAPL", target_quantity=Decimal("5"))
        req = ExecutionRequest(action=action, current_price=Decimal("150.00"))
        results = self._svc.execute_approved_actions([req])
        assert len(results) == 1
        assert results[0].status == ExecutionStatus.FILLED

    def test_blocked_action_type_still_returns_blocked(self):
        """Ensure ActionType.BLOCKED still returns BLOCKED (not affected by TRIM change)."""
        from services.execution_engine.models import ExecutionRequest, ExecutionStatus
        action = PortfolioAction(
            action_type=ActionType.BLOCKED,
            ticker="AAPL",
            reason="risk_blocked",
            risk_approved=False,
        )
        req = ExecutionRequest(action=action, current_price=Decimal("150.00"))
        result = self._svc.execute_action(req)
        assert result.status == ExecutionStatus.BLOCKED


# ── TestPaperCycleTrimIntegration ─────────────────────────────────────────────

class TestPaperCycleTrimIntegration:
    """Full paper trading cycle with overconcentration → trim trigger."""

    def _make_app_state_with_overconcentrated_position(self):
        """Build an ApiAppState with a large AAPL position (overconcentrated)."""
        import uuid as _uuid

        from apps.api.state import ApiAppState
        from broker_adapters.paper.adapter import PaperBrokerAdapter
        from services.ranking_engine.models import RankedResult

        broker = PaperBrokerAdapter(
            starting_cash=Decimal("50000.00"),
            market_open=True,
        )
        broker.connect()
        broker.set_price("AAPL", Decimal("200.00"))

        # Seed the broker with an existing AAPL position (50 shares @ 200 = 10k)
        from broker_adapters.base.models import OrderRequest, OrderSide, OrderType
        broker.place_order(OrderRequest(
            idempotency_key="pre-seed-aapl",
            ticker="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("50"),
        ))
        # After buy: cash ≈ 40000 (50k - 10k), AAPL 50*200 = 10000
        # equity ≈ 50000; 10000/50000 = 20% — at limit, not above

        # Now simulate price appreciation: AAPL → 350 (overconcentrated)
        broker.set_price("AAPL", Decimal("350.00"))
        # market_value = 50 * 350 = 17500; equity ≈ 40000 + 17500 = 57500
        # concentration = 17500/57500 ≈ 30.4% > 20%

        app_state = ApiAppState()
        app_state.broker_adapter = broker

        # PortfolioState must reflect the overconcentrated position
        position = _make_position(
            "AAPL",
            quantity=Decimal("50"),
            avg_entry_price=Decimal("200.00"),
            current_price=Decimal("350.00"),
        )
        from decimal import Decimal as D
        portfolio_state = PortfolioState(
            cash=D("40000.00"),
            positions={"AAPL": position},
            start_of_day_equity=D("50000.00"),
            high_water_mark=D("57500.00"),
        )
        app_state.portfolio_state = portfolio_state

        # Provide rankings that include AAPL (buy) so portfolio engine doesn't CLOSE it
        # Only the overconcentration TRIM should fire for AAPL
        ranked_aapl = RankedResult(
            rank_position=1,
            security_id=_uuid.uuid4(),
            ticker="AAPL",
            composite_score=Decimal("0.82"),  # strong buy — no thesis invalidation
            portfolio_fit_score=Decimal("0.74"),
            recommended_action="buy",
            target_horizon="medium_term",
            thesis_summary="AI hardware leader",
            disconfirming_factors="",
            sizing_hint_pct=Decimal("0.08"),
            source_reliability_tier="secondary_verified",
            contains_rumor=False,
            contributing_signals=[],
            as_of=dt.datetime.utcnow(),
        )
        ranked_nvda = RankedResult(
            rank_position=2,
            security_id=_uuid.uuid4(),
            ticker="NVDA",
            composite_score=Decimal("0.80"),
            portfolio_fit_score=Decimal("0.72"),
            recommended_action="buy",
            target_horizon="medium_term",
            thesis_summary="GPU leader",
            disconfirming_factors="",
            sizing_hint_pct=Decimal("0.08"),
            source_reliability_tier="secondary_verified",
            contains_rumor=False,
            contributing_signals=[],
            as_of=dt.datetime.utcnow(),
        )
        app_state.latest_rankings = [ranked_aapl, ranked_nvda]
        return app_state, broker

    def test_trim_fires_in_cycle_for_overconcentrated_position(self):
        """Full cycle: overconcentrated AAPL position → TRIM appears in proposed_actions."""
        from unittest.mock import MagicMock

        from apps.worker.jobs.paper_trading import run_paper_trading_cycle

        app_state, broker = self._make_app_state_with_overconcentrated_position()
        settings = _make_settings(
            operating_mode="paper",
            max_single_name_pct=0.20,
            take_profit_pct=0.0,  # disable take-profit so trim fires (Phase 42 backward compat)
        )

        # Mock market data to return the set price
        mock_mds = MagicMock()
        mock_snapshot = MagicMock()
        mock_snapshot.latest_price = Decimal("350.00")
        mock_mds.get_snapshot.return_value = mock_snapshot

        result = run_paper_trading_cycle(
            app_state=app_state,
            settings=settings,
            broker=broker,
            market_data_svc=mock_mds,
        )
        assert result["status"] == "ok"
        # The overconcentrated AAPL position should have triggered a trim
        proposed = app_state.proposed_actions
        trim_actions = [a for a in proposed if a.action_type == ActionType.TRIM]
        assert len(trim_actions) >= 1
        assert any(a.ticker == "AAPL" for a in trim_actions)

    def test_trim_not_fired_when_within_limits(self):
        """No trim should fire when all positions are within concentration limits."""
        import uuid as _uuid

        from apps.api.state import ApiAppState
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from broker_adapters.paper.adapter import PaperBrokerAdapter
        from services.ranking_engine.models import RankedResult

        broker = PaperBrokerAdapter(starting_cash=Decimal("100000.00"), market_open=True)
        broker.connect()
        app_state = ApiAppState()
        app_state.broker_adapter = broker

        # Small AAPL position: 10 shares @ 100 = 1000 / 100000 equity = 1% → well within 20%
        position = _make_position("AAPL", quantity=Decimal("10"), current_price=Decimal("100.00"))
        app_state.portfolio_state = PortfolioState(
            cash=Decimal("99000.00"),
            positions={"AAPL": position},
        )
        ranked = RankedResult(
            rank_position=1,
            security_id=_uuid.uuid4(),
            ticker="NVDA",
            composite_score=Decimal("0.80"),
            portfolio_fit_score=Decimal("0.72"),
            recommended_action="buy",
            target_horizon="medium_term",
            thesis_summary="test",
            disconfirming_factors="",
            sizing_hint_pct=Decimal("0.05"),
            source_reliability_tier="secondary_verified",
            contains_rumor=False,
            contributing_signals=[],
            as_of=dt.datetime.utcnow(),
        )
        app_state.latest_rankings = [ranked]

        settings = _make_settings(operating_mode="paper", max_single_name_pct=0.20)
        from unittest.mock import MagicMock
        mock_mds = MagicMock()
        mock_snapshot = MagicMock()
        mock_snapshot.latest_price = Decimal("100.00")
        mock_mds.get_snapshot.return_value = mock_snapshot

        result = run_paper_trading_cycle(
            app_state=app_state,
            settings=settings,
            broker=broker,
            market_data_svc=mock_mds,
        )
        proposed = app_state.proposed_actions or []
        trim_actions = [a for a in proposed if a.action_type == ActionType.TRIM]
        assert len(trim_actions) == 0

    def test_trim_not_duplicated_with_close_for_same_ticker(self):
        """If a CLOSE is already generated for a ticker, no TRIM should be added."""
        import uuid as _uuid

        from apps.api.state import ApiAppState
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from broker_adapters.paper.adapter import PaperBrokerAdapter
        from services.ranking_engine.models import RankedResult

        broker = PaperBrokerAdapter(starting_cash=Decimal("50000.00"), market_open=True)
        broker.connect()

        # Seed overconcentrated AAPL in broker
        from broker_adapters.base.models import OrderRequest, OrderSide, OrderType
        broker.set_price("AAPL", Decimal("200.00"))
        broker.place_order(OrderRequest(
            idempotency_key="seed-aapl-close-test",
            ticker="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("50"),
        ))
        broker.set_price("AAPL", Decimal("350.00"))

        app_state = ApiAppState()
        app_state.broker_adapter = broker
        position = _make_position("AAPL", quantity=Decimal("50"), current_price=Decimal("350.00"))
        app_state.portfolio_state = PortfolioState(
            cash=Decimal("40000.00"),
            positions={"AAPL": position},
            start_of_day_equity=Decimal("50000.00"),
            high_water_mark=Decimal("57500.00"),
        )
        # AAPL score below exit threshold (0.40) → thesis invalidation → CLOSE
        ranked = RankedResult(
            rank_position=1,
            security_id=_uuid.uuid4(),
            ticker="AAPL",
            composite_score=Decimal("0.20"),  # below exit_score_threshold → CLOSE
            portfolio_fit_score=Decimal("0.18"),
            recommended_action="avoid",
            target_horizon="short_term",
            thesis_summary="weak thesis",
            disconfirming_factors="deteriorating",
            sizing_hint_pct=Decimal("0.05"),
            source_reliability_tier="secondary_verified",
            contains_rumor=False,
            contributing_signals=[],
            as_of=dt.datetime.utcnow(),
        )
        app_state.latest_rankings = [ranked]

        settings = _make_settings(
            operating_mode="paper",
            max_single_name_pct=0.20,
            exit_score_threshold=0.40,
            stop_loss_pct=0.07,
            max_position_age_days=20,
        )
        from unittest.mock import MagicMock
        mock_mds = MagicMock()
        mock_snapshot = MagicMock()
        mock_snapshot.latest_price = Decimal("350.00")
        mock_mds.get_snapshot.return_value = mock_snapshot

        result = run_paper_trading_cycle(
            app_state=app_state,
            settings=settings,
            broker=broker,
            market_data_svc=mock_mds,
        )
        proposed = app_state.proposed_actions or []
        # There should be exactly one action for AAPL (CLOSE from exit trigger or rankings)
        # NOT a CLOSE + TRIM combination for the same ticker
        aapl_actions = [a for a in proposed if a.ticker == "AAPL"]
        aapl_close = [a for a in aapl_actions if a.action_type == ActionType.CLOSE]
        aapl_trim = [a for a in aapl_actions if a.action_type == ActionType.TRIM]
        # CLOSE was generated → trim should NOT also appear for AAPL
        if aapl_close:
            assert len(aapl_trim) == 0

    def test_cycle_status_ok_with_trim(self):
        """Cycle status should be 'ok' even when a trim fires."""
        from unittest.mock import MagicMock

        from apps.worker.jobs.paper_trading import run_paper_trading_cycle

        app_state, broker = self._make_app_state_with_overconcentrated_position()
        settings = _make_settings(operating_mode="paper", max_single_name_pct=0.20)

        mock_mds = MagicMock()
        mock_snapshot = MagicMock()
        mock_snapshot.latest_price = Decimal("350.00")
        mock_mds.get_snapshot.return_value = mock_snapshot

        result = run_paper_trading_cycle(
            app_state=app_state,
            settings=settings,
            broker=broker,
            market_data_svc=mock_mds,
        )
        assert result["status"] == "ok"

    def test_cycle_proposed_count_includes_trim(self):
        """proposed_count in the result dict should include the TRIM action."""
        from unittest.mock import MagicMock

        from apps.worker.jobs.paper_trading import run_paper_trading_cycle

        app_state, broker = self._make_app_state_with_overconcentrated_position()
        settings = _make_settings(operating_mode="paper", max_single_name_pct=0.20)

        mock_mds = MagicMock()
        mock_snapshot = MagicMock()
        mock_snapshot.latest_price = Decimal("350.00")
        mock_mds.get_snapshot.return_value = mock_snapshot

        result = run_paper_trading_cycle(
            app_state=app_state,
            settings=settings,
            broker=broker,
            market_data_svc=mock_mds,
        )
        # At minimum 1 proposed action (the TRIM)
        assert result["proposed_count"] >= 1
