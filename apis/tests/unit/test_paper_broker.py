"""
Gate A — Paper Broker tests.

Validates that the PaperBrokerAdapter implements the BaseBrokerAdapter contract
correctly and enforces all required safety invariants.

Test coverage:
- Basic lifecycle (connect/disconnect/ping)
- Order placement and fill
- Cash accounting
- Position tracking
- Kill switch
- Duplicate order prevention
- Insufficient funds
- Order cancellation
- Account state
- Fill retrieval
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from broker_adapters.base.exceptions import (
    DuplicateOrderError,
    InsufficientFundsError,
    KillSwitchActiveError,
    MarketClosedError,
    OrderRejectedError,
    PositionNotFoundError,
)
from broker_adapters.base.models import (
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from broker_adapters.paper.adapter import PaperBrokerAdapter


def _buy_request(
    ticker: str = "AAPL",
    qty: str = "10",
    key: str = "order-001",
) -> OrderRequest:
    return OrderRequest(
        idempotency_key=key,
        ticker=ticker,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal(qty),
        time_in_force=TimeInForce.DAY,
    )


def _sell_request(
    ticker: str = "AAPL",
    qty: str = "5",
    key: str = "order-002",
) -> OrderRequest:
    return OrderRequest(
        idempotency_key=key,
        ticker=ticker,
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal(qty),
        time_in_force=TimeInForce.DAY,
    )


class TestLifecycle:
    def test_adapter_name(self, paper_broker: PaperBrokerAdapter) -> None:
        assert paper_broker.adapter_name == "paper"

    def test_ping_after_connect(self, paper_broker: PaperBrokerAdapter) -> None:
        assert paper_broker.ping() is True

    def test_ping_after_disconnect(self, paper_broker: PaperBrokerAdapter) -> None:
        paper_broker.disconnect()
        assert paper_broker.ping() is False


class TestOrderPlacementAndFill:
    def test_place_market_buy_order(self, paper_broker: PaperBrokerAdapter) -> None:
        order = paper_broker.place_order(_buy_request())
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == Decimal("10")
        assert order.average_fill_price is not None

    def test_fill_applies_slippage_to_buy(self, paper_broker: PaperBrokerAdapter) -> None:
        """Buy orders should fill slightly above the set price (positive slippage)."""
        order = paper_broker.place_order(_buy_request(qty="1"))
        base_price = Decimal("175.00")
        assert order.average_fill_price is not None
        assert order.average_fill_price >= base_price

    def test_fill_applies_slippage_to_sell(self, paper_broker: PaperBrokerAdapter) -> None:
        """Sell orders should fill slightly below the set price (negative slippage)."""
        paper_broker.place_order(_buy_request(qty="10"))
        order = paper_broker.place_order(_sell_request(qty="5"))
        base_price = Decimal("175.00")
        assert order.average_fill_price is not None
        assert order.average_fill_price <= base_price

    def test_order_retrievable_after_fill(self, paper_broker: PaperBrokerAdapter) -> None:
        order = paper_broker.place_order(_buy_request())
        retrieved = paper_broker.get_order(order.broker_order_id)
        assert retrieved.broker_order_id == order.broker_order_id
        assert retrieved.status == OrderStatus.FILLED

    def test_fills_associated_with_order(self, paper_broker: PaperBrokerAdapter) -> None:
        order = paper_broker.place_order(_buy_request())
        fills = paper_broker.get_fills_for_order(order.broker_order_id)
        assert len(fills) == 1
        assert fills[0].fill_quantity == Decimal("10")

    def test_no_open_orders_after_fill(self, paper_broker: PaperBrokerAdapter) -> None:
        paper_broker.place_order(_buy_request())
        assert paper_broker.list_open_orders() == []


class TestCashAccounting:
    def test_cash_decreases_on_buy(self, paper_broker: PaperBrokerAdapter) -> None:
        starting_cash = paper_broker.get_account_state().cash_balance
        paper_broker.place_order(_buy_request(qty="10"))
        new_cash = paper_broker.get_account_state().cash_balance
        assert new_cash < starting_cash

    def test_cash_increases_on_sell(self, paper_broker: PaperBrokerAdapter) -> None:
        paper_broker.place_order(_buy_request(qty="10"))
        after_buy = paper_broker.get_account_state().cash_balance
        paper_broker.place_order(_sell_request(qty="5"))
        after_sell = paper_broker.get_account_state().cash_balance
        assert after_sell > after_buy

    def test_cash_exact_deduction(self, paper_broker: PaperBrokerAdapter) -> None:
        """Buying 1 share at 175.00 with 5bps slippage should deduct ~175.09."""
        state_before = paper_broker.get_account_state()
        order = paper_broker.place_order(_buy_request(qty="1"))
        state_after = paper_broker.get_account_state()
        assert order.average_fill_price is not None
        expected_cost = order.average_fill_price * Decimal("1")
        assert state_before.cash_balance - state_after.cash_balance == expected_cost


class TestPositions:
    def test_position_created_after_buy(self, paper_broker: PaperBrokerAdapter) -> None:
        paper_broker.place_order(_buy_request(qty="10"))
        position = paper_broker.get_position("AAPL")
        assert position.quantity == Decimal("10")

    def test_position_quantity_reduces_on_partial_sell(
        self, paper_broker: PaperBrokerAdapter
    ) -> None:
        paper_broker.place_order(_buy_request(qty="10"))
        paper_broker.place_order(_sell_request(qty="4"))
        position = paper_broker.get_position("AAPL")
        assert position.quantity == Decimal("6")

    def test_position_removed_on_full_sell(self, paper_broker: PaperBrokerAdapter) -> None:
        paper_broker.place_order(_buy_request(qty="10"))
        paper_broker.place_order(_sell_request(qty="10", key="order-003"))
        with pytest.raises(PositionNotFoundError):
            paper_broker.get_position("AAPL")

    def test_list_positions_returns_open_positions(
        self, paper_broker: PaperBrokerAdapter
    ) -> None:
        paper_broker.place_order(_buy_request("AAPL", "5", "order-aapl"))
        paper_broker.place_order(_buy_request("NVDA", "2", "order-nvda"))
        positions = paper_broker.list_positions()
        tickers = {p.ticker for p in positions}
        assert "AAPL" in tickers
        assert "NVDA" in tickers

    def test_get_position_not_found_raises(self, paper_broker: PaperBrokerAdapter) -> None:
        with pytest.raises(PositionNotFoundError):
            paper_broker.get_position("UNKNOWN")

    def test_position_market_value_reflects_current_price(
        self, paper_broker: PaperBrokerAdapter
    ) -> None:
        paper_broker.place_order(_buy_request(qty="10"))
        paper_broker.set_price("AAPL", Decimal("200.00"))
        position = paper_broker.get_position("AAPL")
        assert position.current_price == Decimal("200.00")
        assert position.market_value == Decimal("2000.00")

    def test_unrealized_pnl_positive_when_price_rises(
        self, paper_broker: PaperBrokerAdapter
    ) -> None:
        paper_broker.place_order(_buy_request(qty="10"))
        paper_broker.set_price("AAPL", Decimal("200.00"))
        position = paper_broker.get_position("AAPL")
        assert position.unrealized_pnl > Decimal("0")


class TestSafetyInvariants:
    def test_kill_switch_blocks_orders(self, paper_broker: PaperBrokerAdapter) -> None:
        paper_broker.activate_kill_switch()
        with pytest.raises(KillSwitchActiveError):
            paper_broker.place_order(_buy_request())

    def test_kill_switch_can_be_deactivated(self, paper_broker: PaperBrokerAdapter) -> None:
        paper_broker.activate_kill_switch()
        paper_broker.deactivate_kill_switch()
        order = paper_broker.place_order(_buy_request())
        assert order.status == OrderStatus.FILLED

    def test_duplicate_idempotency_key_rejected(
        self, paper_broker: PaperBrokerAdapter
    ) -> None:
        paper_broker.place_order(_buy_request(key="dup-key"))
        with pytest.raises(DuplicateOrderError):
            paper_broker.place_order(_buy_request(key="dup-key"))

    def test_insufficient_funds_rejected(self) -> None:
        broker = PaperBrokerAdapter(
            starting_cash=Decimal("100.00"),
            market_open=True,
        )
        broker.connect()
        broker.set_price("AAPL", Decimal("175.00"))
        with pytest.raises(InsufficientFundsError):
            broker.place_order(_buy_request(qty="10"))

    def test_market_order_rejected_when_market_closed(self) -> None:
        broker = PaperBrokerAdapter(
            starting_cash=Decimal("100000.00"),
            market_open=False,
        )
        broker.connect()
        broker.set_price("AAPL", Decimal("175.00"))
        with pytest.raises(MarketClosedError):
            broker.place_order(_buy_request())

    def test_order_rejected_when_no_price_set(self, paper_broker: PaperBrokerAdapter) -> None:
        req = OrderRequest(
            idempotency_key="no-price",
            ticker="NOPRICE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )
        with pytest.raises(OrderRejectedError):
            paper_broker.place_order(req)


class TestOrderCancellation:
    def test_cancel_open_order(self) -> None:
        """With fill_immediately=False, order stays open until explicitly filled."""
        broker = PaperBrokerAdapter(
            starting_cash=Decimal("100000.00"),
            fill_immediately=False,
            market_open=True,
        )
        broker.connect()
        broker.set_price("AAPL", Decimal("175.00"))
        order = broker.place_order(_buy_request())
        assert order.status == OrderStatus.SUBMITTED
        cancelled = broker.cancel_order(order.broker_order_id)
        assert cancelled.status == OrderStatus.CANCELLED

    def test_cancel_filled_order_is_noop(self, paper_broker: PaperBrokerAdapter) -> None:
        order = paper_broker.place_order(_buy_request())
        assert order.status == OrderStatus.FILLED
        # Cancelling a filled order should return the same state, not raise
        result = paper_broker.cancel_order(order.broker_order_id)
        assert result.status == OrderStatus.FILLED


class TestAccountState:
    def test_account_state_initial(self) -> None:
        broker = PaperBrokerAdapter(starting_cash=Decimal("50000.00"), market_open=True)
        broker.connect()
        state = broker.get_account_state()
        assert state.cash_balance == Decimal("50000.00")
        assert state.equity_value == Decimal("50000.00")
        assert state.positions == []
        assert state.is_account_blocked is False

    def test_account_state_blocked_when_kill_switch_on(
        self, paper_broker: PaperBrokerAdapter
    ) -> None:
        paper_broker.activate_kill_switch()
        state = paper_broker.get_account_state()
        assert state.is_account_blocked is True

    def test_account_equity_includes_position_value(
        self, paper_broker: PaperBrokerAdapter
    ) -> None:
        paper_broker.place_order(_buy_request(qty="10"))
        state = paper_broker.get_account_state()
        assert state.equity_value > Decimal("0")
        assert state.gross_exposure > Decimal("0")


class TestFillRetrieval:
    def test_list_fills_since_returns_fills_after_timestamp(
        self, paper_broker: PaperBrokerAdapter
    ) -> None:
        from datetime import datetime, timezone, timedelta

        paper_broker.place_order(_buy_request())
        since = datetime.now(tz=timezone.utc) - timedelta(minutes=5)
        fills = paper_broker.list_fills_since(since)
        assert len(fills) >= 1

    def test_list_fills_since_empty_for_future_timestamp(
        self, paper_broker: PaperBrokerAdapter
    ) -> None:
        from datetime import datetime, timezone, timedelta

        paper_broker.place_order(_buy_request())
        future = datetime.now(tz=timezone.utc) + timedelta(hours=1)
        fills = paper_broker.list_fills_since(future)
        assert fills == []
