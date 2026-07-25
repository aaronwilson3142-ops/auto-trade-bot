"""
Phase 87 (2026-07-25) — No-Price Execution Guards.

Root cause under test: on 2026-07-24, after a machine outage + total yfinance
failure, 8 CLOSE actions reached the paper broker with no real market price
and were filled at the adapter's $1.00 default price, realizing a -$61.6k
phantom loss (55% fake drawdown → risk lockout).

Guards verified here:
  1. ExecutionEngineService.execute_action REJECTS any action whose
     current_price is None or <= 0 — for OPEN, CLOSE, and TRIM alike.
  2. A positive price still executes normally (guard is not over-broad).
"""
from __future__ import annotations

from decimal import Decimal

from broker_adapters.paper.adapter import PaperBrokerAdapter
from config.settings import Settings
from services.execution_engine.models import ExecutionRequest, ExecutionStatus
from services.execution_engine.service import ExecutionEngineService
from services.portfolio_engine.models import ActionType, PortfolioAction


def _settings(**overrides) -> Settings:
    import os
    os.environ.setdefault("APIS_ENV", "development")
    os.environ.setdefault("APIS_OPERATING_MODE", "research")
    os.environ.setdefault("APIS_DB_URL", "postgresql+psycopg://test:test@localhost:5432/apis_test")
    s = Settings()
    for k, v in overrides.items():
        object.__setattr__(s, k, v)
    return s


def _broker(prices: dict | None = None) -> PaperBrokerAdapter:
    b = PaperBrokerAdapter(
        starting_cash=Decimal("100000.00"),
        slippage_bps=0,
        fill_immediately=True,
        market_open=True,
    )
    b.connect()
    for ticker, price in (prices or {}).items():
        b.set_price(ticker, price)
    return b


def _action(action_type: ActionType, ticker: str = "NTRS") -> PortfolioAction:
    return PortfolioAction(
        action_type=action_type,
        ticker=ticker,
        reason="not_in_buy_set" if action_type == ActionType.CLOSE else "test",
        target_notional=Decimal("7500.00") if action_type == ActionType.OPEN else Decimal("0"),
        thesis_summary=f"phase87 {action_type.value} {ticker}",
        risk_approved=True,
    )


class TestPhase87NoPriceGuard:
    """No order may execute without a positive, real market price."""

    def test_close_with_no_price_rejected_never_fills_at_default(self):
        # Broker holds NO price for NTRS — its internal default would be $1.00.
        broker = _broker()
        svc = ExecutionEngineService(settings=_settings(), broker=broker)
        req = ExecutionRequest(
            action=_action(ActionType.CLOSE), current_price=Decimal("0")
        )
        result = svc.execute_action(req)
        assert result.status == ExecutionStatus.REJECTED
        assert "Phase 87" in (result.error_message or "")
        assert result.fill_quantity is None

    def test_open_with_no_price_rejected(self):
        broker = _broker()
        svc = ExecutionEngineService(settings=_settings(), broker=broker)
        req = ExecutionRequest(
            action=_action(ActionType.OPEN), current_price=Decimal("0")
        )
        result = svc.execute_action(req)
        assert result.status == ExecutionStatus.REJECTED

    def test_trim_with_no_price_rejected(self):
        broker = _broker()
        svc = ExecutionEngineService(settings=_settings(), broker=broker)
        req = ExecutionRequest(
            action=_action(ActionType.TRIM), current_price=Decimal("0")
        )
        result = svc.execute_action(req)
        assert result.status == ExecutionStatus.REJECTED

    def test_negative_price_rejected(self):
        broker = _broker()
        svc = ExecutionEngineService(settings=_settings(), broker=broker)
        req = ExecutionRequest(
            action=_action(ActionType.OPEN), current_price=Decimal("-1")
        )
        result = svc.execute_action(req)
        assert result.status == ExecutionStatus.REJECTED

    def test_positive_price_still_executes(self):
        broker = _broker(prices={"NTRS": Decimal("185.44")})
        svc = ExecutionEngineService(settings=_settings(), broker=broker)
        req = ExecutionRequest(
            action=_action(ActionType.OPEN), current_price=Decimal("185.44")
        )
        result = svc.execute_action(req)
        assert result.status == ExecutionStatus.FILLED
        assert result.fill_price == Decimal("185.44")
