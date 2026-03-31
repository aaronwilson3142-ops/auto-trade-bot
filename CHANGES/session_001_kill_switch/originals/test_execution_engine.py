"""
Gate C — Execution Engine Tests.

Verifies:
  - kill_switch blocks execution before any broker call
  - OPEN action → BUY market order → FILLED result with quantity / fill_price
  - CLOSE action → SELL market order → FILLED result using broker position quantity
  - CLOSE with no held position → REJECTED result (no exception)
  - BLOCKED action passed through → BLOCKED result
  - zero-notional OPEN (price too high) → REJECTED result
  - batch execution collects all results
  - broker exceptions are caught and returned as structured results
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from broker_adapters.paper.adapter import PaperBrokerAdapter
from config.settings import Settings
from services.execution_engine.models import ExecutionRequest, ExecutionStatus
from services.execution_engine.service import ExecutionEngineService
from services.portfolio_engine.models import ActionType, PortfolioAction


# ─────────────────────────── helpers ─────────────────────────────────────────

def _settings(**overrides) -> Settings:
    import os
    os.environ.setdefault("APIS_ENV", "development")
    os.environ.setdefault("APIS_OPERATING_MODE", "research")
    os.environ.setdefault("APIS_DB_URL", "postgresql+psycopg://test:test@localhost:5432/apis_test")
    s = Settings()
    for k, v in overrides.items():
        object.__setattr__(s, k, v)
    return s


def _broker(
    cash: Decimal = Decimal("100000.00"),
    prices: dict | None = None,
) -> PaperBrokerAdapter:
    b = PaperBrokerAdapter(
        starting_cash=cash,
        slippage_bps=0,         # no slippage: keeps arithmetic simple in tests
        fill_immediately=True,
        market_open=True,
    )
    b.connect()
    for ticker, price in (prices or {}).items():
        b.set_price(ticker, price)
    return b


def _open_action(
    ticker: str = "AAPL",
    notional: Decimal = Decimal("17500.00"),  # 100 shares @ 175
) -> PortfolioAction:
    return PortfolioAction(
        action_type=ActionType.OPEN,
        ticker=ticker,
        reason="test_open",
        target_notional=notional,
        thesis_summary=f"Long {ticker}",
        risk_approved=True,
    )


def _close_action(ticker: str = "AAPL") -> PortfolioAction:
    return PortfolioAction(
        action_type=ActionType.CLOSE,
        ticker=ticker,
        reason="test_close",
        thesis_summary=f"Exit {ticker}: stop-loss triggered",
        risk_approved=True,
    )


def _buy_into_broker(broker: PaperBrokerAdapter, ticker: str, price: Decimal, qty: Decimal) -> None:
    """Helper: open a position in the broker for CLOSE tests."""
    from broker_adapters.base.models import OrderRequest, OrderSide, OrderType
    import uuid
    req = OrderRequest(
        idempotency_key=str(uuid.uuid4()),
        ticker=ticker,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=qty,
    )
    broker.place_order(req)


# ─────────────────────────────────────────────────────────────────────────────
# TestKillSwitchBlocking
# ─────────────────────────────────────────────────────────────────────────────

class TestKillSwitchBlocking:
    def test_kill_switch_active_blocks_open(self):
        broker = _broker(prices={"AAPL": Decimal("175.00")})
        svc = ExecutionEngineService(settings=_settings(kill_switch=True), broker=broker)

        req = ExecutionRequest(action=_open_action(), current_price=Decimal("175.00"))
        result = svc.execute_action(req)
        assert result.status == ExecutionStatus.BLOCKED
        assert result.fill_price is None

    def test_kill_switch_inactive_proceeds(self):
        broker = _broker(prices={"AAPL": Decimal("175.00")})
        svc = ExecutionEngineService(settings=_settings(kill_switch=False), broker=broker)

        req = ExecutionRequest(action=_open_action(), current_price=Decimal("175.00"))
        result = svc.execute_action(req)
        assert result.status == ExecutionStatus.FILLED


# ─────────────────────────────────────────────────────────────────────────────
# TestExecuteOpenAction
# ─────────────────────────────────────────────────────────────────────────────

class TestExecuteOpenAction:
    def test_open_fills_successfully(self):
        broker = _broker(prices={"AAPL": Decimal("175.00")})
        svc = ExecutionEngineService(settings=_settings(), broker=broker)

        req = ExecutionRequest(
            action=_open_action("AAPL", notional=Decimal("17500.00")),
            current_price=Decimal("175.00"),
        )
        result = svc.execute_action(req)
        assert result.status == ExecutionStatus.FILLED
        assert result.fill_quantity == Decimal("100")   # floor(17500/175)

    def test_fill_price_populated(self):
        broker = _broker(prices={"NVDA": Decimal("900.00")})
        svc = ExecutionEngineService(settings=_settings(), broker=broker)

        req = ExecutionRequest(
            action=_open_action("NVDA", notional=Decimal("9000.00")),
            current_price=Decimal("900.00"),
        )
        result = svc.execute_action(req)
        assert result.fill_price is not None
        assert result.fill_price > Decimal("0")

    def test_broker_order_id_populated(self):
        broker = _broker(prices={"AAPL": Decimal("175.00")})
        svc = ExecutionEngineService(settings=_settings(), broker=broker)

        req = ExecutionRequest(action=_open_action(), current_price=Decimal("175.00"))
        result = svc.execute_action(req)
        assert result.broker_order_id is not None

    def test_zero_quantity_from_notional_rejected(self):
        """Notional $10 at $175/share → 0 shares → REJECTED (no order)."""
        broker = _broker(prices={"AAPL": Decimal("175.00")})
        svc = ExecutionEngineService(settings=_settings(), broker=broker)

        req = ExecutionRequest(
            action=_open_action("AAPL", notional=Decimal("10.00")),
            current_price=Decimal("175.00"),
        )
        result = svc.execute_action(req)
        assert result.status == ExecutionStatus.REJECTED
        assert result.fill_quantity is None

    def test_invalid_price_returns_error(self):
        broker = _broker(prices={"AAPL": Decimal("175.00")})
        svc = ExecutionEngineService(settings=_settings(), broker=broker)

        req = ExecutionRequest(
            action=_open_action(),
            current_price=Decimal("0"),
        )
        result = svc.execute_action(req)
        assert result.status == ExecutionStatus.ERROR

    def test_insufficient_cash_returns_rejected(self):
        """Broker has only $100 cash; notional $17500 → InsufficientFundsError → REJECTED."""
        broker = _broker(cash=Decimal("100.00"), prices={"AAPL": Decimal("175.00")})
        svc = ExecutionEngineService(settings=_settings(), broker=broker)

        req = ExecutionRequest(action=_open_action(), current_price=Decimal("175.00"))
        result = svc.execute_action(req)
        assert result.status == ExecutionStatus.REJECTED


# ─────────────────────────────────────────────────────────────────────────────
# TestExecuteCloseAction
# ─────────────────────────────────────────────────────────────────────────────

class TestExecuteCloseAction:
    def test_close_existing_position_fills(self):
        broker = _broker(prices={"AAPL": Decimal("175.00")})
        _buy_into_broker(broker, "AAPL", Decimal("175.00"), Decimal("50"))
        svc = ExecutionEngineService(settings=_settings(), broker=broker)

        req = ExecutionRequest(action=_close_action("AAPL"), current_price=Decimal("175.00"))
        result = svc.execute_action(req)
        assert result.status == ExecutionStatus.FILLED
        assert result.fill_quantity == Decimal("50")

    def test_close_nonexistent_position_rejected(self):
        broker = _broker(prices={"AAPL": Decimal("175.00")})
        # No position opened
        svc = ExecutionEngineService(settings=_settings(), broker=broker)

        req = ExecutionRequest(action=_close_action("AAPL"), current_price=Decimal("175.00"))
        result = svc.execute_action(req)
        assert result.status == ExecutionStatus.REJECTED
        assert "AAPL" in (result.error_message or "")

    def test_close_fill_price_populated(self):
        broker = _broker(prices={"MSFT": Decimal("420.00")})
        _buy_into_broker(broker, "MSFT", Decimal("420.00"), Decimal("25"))
        svc = ExecutionEngineService(settings=_settings(), broker=broker)

        req = ExecutionRequest(action=_close_action("MSFT"), current_price=Decimal("420.00"))
        result = svc.execute_action(req)
        assert result.fill_price is not None


# ─────────────────────────────────────────────────────────────────────────────
# TestBlockedAction
# ─────────────────────────────────────────────────────────────────────────────

class TestBlockedAction:
    def test_blocked_action_returns_blocked(self):
        broker = _broker(prices={"AAPL": Decimal("175.00")})
        svc = ExecutionEngineService(settings=_settings(), broker=broker)

        action = PortfolioAction(
            action_type=ActionType.BLOCKED,
            ticker="AAPL",
            reason="risk_limit",
            risk_approved=False,
        )
        req = ExecutionRequest(action=action, current_price=Decimal("175.00"))
        result = svc.execute_action(req)
        assert result.status == ExecutionStatus.BLOCKED


# ─────────────────────────────────────────────────────────────────────────────
# TestBatchExecution
# ─────────────────────────────────────────────────────────────────────────────

class TestBatchExecution:
    def test_batch_all_fills(self):
        broker = _broker(
            cash=Decimal("200000.00"),
            prices={"AAPL": Decimal("175.00"), "MSFT": Decimal("420.00")},
        )
        svc = ExecutionEngineService(settings=_settings(), broker=broker)

        requests = [
            ExecutionRequest(action=_open_action("AAPL", Decimal("8750.00")), current_price=Decimal("175.00")),
            ExecutionRequest(action=_open_action("MSFT", Decimal("8400.00")), current_price=Decimal("420.00")),
        ]
        results = svc.execute_approved_actions(requests)
        assert len(results) == 2
        assert all(r.status == ExecutionStatus.FILLED for r in results)

    def test_batch_partial_failure_does_not_abort(self):
        """First order fails (no cash), second ticker still attempted."""
        broker = _broker(
            cash=Decimal("100.00"),                         # not enough for first order
            prices={"AAPL": Decimal("175.00"), "MSFT": Decimal("420.00")},
        )
        # Reload broker with enough cash only for MSFT small lot
        broker2 = _broker(
            cash=Decimal("900.00"),
            prices={"AAPL": Decimal("900.00"), "MSFT": Decimal("420.00")},  # AAPL unaffordable at 900
        )
        svc = ExecutionEngineService(settings=_settings(), broker=broker2)

        requests = [
            ExecutionRequest(action=_open_action("AAPL", Decimal("8100.00")), current_price=Decimal("900.00")),  # needs $8100, have $900
            ExecutionRequest(action=_open_action("MSFT", Decimal("420.00")), current_price=Decimal("420.00")),   # 1 share, should work
        ]
        results = svc.execute_approved_actions(requests)
        assert len(results) == 2
        statuses = {r.action.ticker: r.status for r in results}
        assert statuses["AAPL"] == ExecutionStatus.REJECTED
        assert statuses["MSFT"] == ExecutionStatus.FILLED

    def test_batch_empty_list_returns_empty(self):
        broker = _broker()
        svc = ExecutionEngineService(settings=_settings(), broker=broker)
        results = svc.execute_approved_actions([])
        assert results == []
