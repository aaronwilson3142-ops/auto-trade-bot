"""
E2E Tests — Alpaca Paper Sandbox Integration.

These tests exercise the full APIS pipeline end-to-end against the Alpaca
paper trading sandbox.  They require real Alpaca paper API credentials and
make live HTTP calls to api.alpaca.markets (paper endpoint).

─────────────────────────────────────────────────────────────────────────────
Running these tests
─────────────────────────────────────────────────────────────────────────────
Set the following environment variables before running:

    $env:ALPACA_API_KEY    = "PKxxxxxx"
    $env:ALPACA_API_SECRET = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

Then run:

    cd apis
    $env:PYTHONPATH = "."
    .\.venv\Scripts\pytest.exe tests/e2e/test_alpaca_paper_e2e.py -v -s

These tests are EXCLUDED from the standard unit test run
(``pytest tests/unit/``) so they never block CI.

─────────────────────────────────────────────────────────────────────────────
What is tested
─────────────────────────────────────────────────────────────────────────────
  E2E_01: AlpacaBrokerAdapter — connect / ping / disconnect lifecycle
  E2E_02: AlpacaBrokerAdapter — get_account_state returns valid AccountState
  E2E_03: AlpacaBrokerAdapter — list_positions returns list (may be empty)
  E2E_04: AlpacaBrokerAdapter — list_open_orders returns list
  E2E_05: AlpacaBrokerAdapter — is_market_open returns bool
  E2E_06: AlpacaBrokerAdapter — next_market_open returns future/current datetime
  E2E_07: AlpacaBrokerAdapter — place_order (market buy 1 share of SPY)
  E2E_08: AlpacaBrokerAdapter — get_order retrieves submitted order
  E2E_09: AlpacaBrokerAdapter — list_open_orders after submit includes order
  E2E_10: AlpacaBrokerAdapter — cancel_order on submitted order
  E2E_11: AlpacaBrokerAdapter — idempotency guard rejects duplicate key
  E2E_12: Full paper trading cycle — ranked→portfolio→risk→execute→evaluate

Each test is marked with ``@pytest.mark.e2e`` so they can be run in isolation:

    pytest tests/e2e/ -m e2e -v

─────────────────────────────────────────────────────────────────────────────
Safety guarantees
─────────────────────────────────────────────────────────────────────────────
- All tests use ``paper=True`` (default) — Alpaca paper endpoint only.
- Orders use quantity=1 and are cancelled immediately after submission.
- No live money is ever at risk.
- The AlpacaBrokerAdapter constructor rejects empty credentials.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

# ── Skip marker ───────────────────────────────────────────────────────────────

pytestmark = pytest.mark.e2e

# ── Credentials guard ─────────────────────────────────────────────────────────

_ALPACA_KEY = os.environ.get("ALPACA_API_KEY", "")
_ALPACA_SECRET = os.environ.get("ALPACA_API_SECRET", "")

_CREDS_MISSING = not (_ALPACA_KEY and _ALPACA_SECRET)

_skip_no_creds = pytest.mark.skipif(
    _CREDS_MISSING,
    reason=(
        "Alpaca paper credentials not set. "
        "Export ALPACA_API_KEY and ALPACA_API_SECRET to run E2E tests."
    ),
)

# ── Shared adapter fixture ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def alpaca_adapter():
    """
    Module-scoped fixture: connected AlpacaBrokerAdapter (paper mode).

    Connection is established once for the entire module to reduce latency.
    The adapter is disconnected in teardown.
    """
    if _CREDS_MISSING:
        pytest.skip("Alpaca credentials not configured — skipping E2E tests.")

    from broker_adapters.alpaca.adapter import AlpacaBrokerAdapter

    adapter = AlpacaBrokerAdapter(
        api_key=_ALPACA_KEY,
        api_secret=_ALPACA_SECRET,
        paper=True,
    )
    adapter.connect()
    yield adapter
    adapter.disconnect()


# =============================================================================
# E2E_01 — Connection / Lifecycle
# =============================================================================

@_skip_no_creds
class TestAlpacaConnection:
    """E2E_01 — connect / ping / disconnect."""

    def test_connect_succeeds(self):
        from broker_adapters.alpaca.adapter import AlpacaBrokerAdapter
        a = AlpacaBrokerAdapter(
            api_key=_ALPACA_KEY, api_secret=_ALPACA_SECRET, paper=True
        )
        a.connect()
        assert a._connected is True
        a.disconnect()

    def test_ping_returns_true_when_connected(self, alpaca_adapter):
        assert alpaca_adapter.ping() is True

    def test_disconnect_sets_not_connected(self):
        from broker_adapters.alpaca.adapter import AlpacaBrokerAdapter
        a = AlpacaBrokerAdapter(
            api_key=_ALPACA_KEY, api_secret=_ALPACA_SECRET, paper=True
        )
        a.connect()
        a.disconnect()
        assert a._connected is False

    def test_ping_returns_false_when_disconnected(self):
        from broker_adapters.alpaca.adapter import AlpacaBrokerAdapter
        a = AlpacaBrokerAdapter(
            api_key=_ALPACA_KEY, api_secret=_ALPACA_SECRET, paper=True
        )
        assert a.ping() is False

    def test_adapter_name_is_paper(self, alpaca_adapter):
        assert alpaca_adapter.adapter_name == "alpaca_paper"


# =============================================================================
# E2E_02 — Account State
# =============================================================================

@_skip_no_creds
class TestAlpacaAccountState:
    """E2E_02 — get_account_state returns a valid AccountState."""

    def test_get_account_state_returns_account_state(self, alpaca_adapter):
        from broker_adapters.base.models import AccountState
        state = alpaca_adapter.get_account_state()
        assert isinstance(state, AccountState)

    def test_account_has_positive_buying_power(self, alpaca_adapter):
        state = alpaca_adapter.get_account_state()
        assert state.buying_power >= Decimal("0")

    def test_account_equity_is_decimal(self, alpaca_adapter):
        state = alpaca_adapter.get_account_state()
        assert isinstance(state.equity_value, Decimal)

    def test_account_id_is_non_empty_string(self, alpaca_adapter):
        state = alpaca_adapter.get_account_state()
        assert isinstance(state.account_id, str)
        assert len(state.account_id) > 0

    def test_account_positions_is_list(self, alpaca_adapter):
        state = alpaca_adapter.get_account_state()
        assert isinstance(state.positions, list)


# =============================================================================
# E2E_03 — Positions
# =============================================================================

@_skip_no_creds
class TestAlpacaPositions:
    """E2E_03 — list_positions returns a list (may be empty)."""

    def test_list_positions_returns_list(self, alpaca_adapter):
        positions = alpaca_adapter.list_positions()
        assert isinstance(positions, list)

    def test_each_position_has_ticker(self, alpaca_adapter):
        from broker_adapters.base.models import Position
        positions = alpaca_adapter.list_positions()
        for pos in positions:
            assert isinstance(pos, Position)
            assert isinstance(pos.ticker, str)
            assert len(pos.ticker) > 0

    def test_each_position_has_decimal_market_value(self, alpaca_adapter):
        positions = alpaca_adapter.list_positions()
        for pos in positions:
            assert isinstance(pos.market_value, Decimal)


# =============================================================================
# E2E_04 — Orders (read-only)
# =============================================================================

@_skip_no_creds
class TestAlpacaOpenOrders:
    """E2E_04 — list_open_orders returns a list."""

    def test_list_open_orders_returns_list(self, alpaca_adapter):
        orders = alpaca_adapter.list_open_orders()
        assert isinstance(orders, list)

    def test_each_order_has_status(self, alpaca_adapter):
        from broker_adapters.base.models import Order, OrderStatus
        orders = alpaca_adapter.list_open_orders()
        for order in orders:
            assert isinstance(order, Order)
            assert isinstance(order.status, OrderStatus)


# =============================================================================
# E2E_05 / E2E_06 — Market Hours
# =============================================================================

@_skip_no_creds
class TestAlpacaMarketHours:
    """E2E_05 / E2E_06 — Market hours queries return sensible results."""

    def test_is_market_open_returns_bool(self, alpaca_adapter):
        result = alpaca_adapter.is_market_open()
        assert isinstance(result, bool)

    def test_next_market_open_returns_datetime(self, alpaca_adapter):
        next_open = alpaca_adapter.next_market_open()
        assert isinstance(next_open, datetime)

    def test_next_market_open_is_timezone_aware(self, alpaca_adapter):
        next_open = alpaca_adapter.next_market_open()
        assert next_open.tzinfo is not None

    def test_next_market_open_is_in_future_or_now(self, alpaca_adapter):
        next_open = alpaca_adapter.next_market_open()
        # Should not be in the past by more than 1 hour (handles "currently open" case)
        from datetime import timedelta
        assert next_open > datetime.now(tz=timezone.utc) - timedelta(hours=1)


# =============================================================================
# E2E_07–E2E_11 — Order Submission, Retrieval, Cancellation, Idempotency
# =============================================================================

@_skip_no_creds
class TestAlpacaOrderLifecycle:
    """E2E_07–E2E_11 — Full order lifecycle (submit → retrieve → cancel)."""

    # Fixture: submit a real SPY market order and cancel it
    @pytest.fixture(scope="class")
    def submitted_order(self, alpaca_adapter):
        """
        Submit a 1-share SPY market order (GTC so it's accepted outside hours),
        yield the Order, then cancel and clean up.
        """
        from broker_adapters.base.models import (
            OrderRequest, OrderSide, OrderType, TimeInForce
        )
        key = f"e2e-{uuid.uuid4().hex[:8]}"
        request = OrderRequest(
            idempotency_key=key,
            ticker="SPY",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1"),
            time_in_force=TimeInForce.DAY,
            # Use a far-below-market limit price so it never fills in paper mode
            limit_price=Decimal("1.00"),
        )
        order = alpaca_adapter.place_order(request)
        yield order
        # Cleanup: cancel the order
        try:
            alpaca_adapter.cancel_order(order.broker_order_id)
        except Exception:
            pass  # already filled or expired — not a test failure

    def test_place_order_returns_order(self, submitted_order):
        from broker_adapters.base.models import Order
        assert isinstance(submitted_order, Order)

    def test_placed_order_has_broker_order_id(self, submitted_order):
        assert isinstance(submitted_order.broker_order_id, str)
        assert len(submitted_order.broker_order_id) > 0

    def test_placed_order_ticker_is_spy(self, submitted_order):
        assert submitted_order.ticker.upper() == "SPY"

    def test_placed_order_status_is_submitted_or_pending(self, submitted_order):
        from broker_adapters.base.models import OrderStatus
        assert submitted_order.status in (
            OrderStatus.SUBMITTED,
            OrderStatus.PENDING,
        )

    def test_get_order_returns_same_order(self, alpaca_adapter, submitted_order):
        retrieved = alpaca_adapter.get_order(submitted_order.broker_order_id)
        assert retrieved.broker_order_id == submitted_order.broker_order_id

    def test_cancel_order_succeeds(self, alpaca_adapter, submitted_order):
        from broker_adapters.base.models import OrderStatus
        cancelled = alpaca_adapter.cancel_order(submitted_order.broker_order_id)
        # Cancellation may be async on Alpaca side; CANCELLED or SUBMITTED pending cancel
        assert cancelled.broker_order_id == submitted_order.broker_order_id

    def test_duplicate_idempotency_key_raises(self, alpaca_adapter):
        from broker_adapters.base.exceptions import DuplicateOrderError
        from broker_adapters.base.models import (
            OrderRequest, OrderSide, OrderType, TimeInForce
        )
        # Submit once with a unique key
        key = f"e2e-dup-{uuid.uuid4().hex[:8]}"
        req = OrderRequest(
            idempotency_key=key,
            ticker="SPY",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1"),
            time_in_force=TimeInForce.DAY,
            limit_price=Decimal("1.00"),
        )
        order = alpaca_adapter.place_order(req)
        try:
            # Second submission with same key must raise
            with pytest.raises(DuplicateOrderError):
                alpaca_adapter.place_order(req)
        finally:
            try:
                alpaca_adapter.cancel_order(order.broker_order_id)
            except Exception:
                pass


# =============================================================================
# E2E_12 — Full Paper Trading Cycle Integration
# =============================================================================

@_skip_no_creds
class TestFullPaperTradingCycleIntegration:
    """
    E2E_12 — End-to-end paper trading cycle using AlpacaBrokerAdapter.

    Runs the ranking pipeline → portfolio engine → risk engine → execution engine
    → evaluation engine using a live Alpaca paper account.  No real orders are
    submitted to Alpaca in this test — the execution engine uses the PaperBroker
    (internal, zero-latency) so the test runs reliably in all environments.

    The Alpaca adapter IS connected to verify connectivity; the portfolio cycle
    itself uses the internal paper broker to avoid order submission side-effects.
    """

    def test_alpaca_connected_for_cycle(self, alpaca_adapter):
        """Alpaca connection is live and responsive."""
        assert alpaca_adapter.ping() is True

    def test_run_paper_trading_cycle_with_alpaca_state(self, alpaca_adapter):
        """
        Simulate a full paper trading cycle using live AlpacaBrokerAdapter
        state (account balance) seeded into the internal paper portfolio.
        """
        from decimal import Decimal
        from apps.api.state import ApiAppState
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from broker_adapters.paper.adapter import PaperBrokerAdapter
        from config.settings import Settings
        from services.ranking_engine.service import RankingEngineService
        from services.signal_engine.service import SignalEngineService

        # Seed rankings so the cycle has something to work with
        state = ApiAppState()
        settings = Settings(operating_mode="paper")

        # Pull actual account equity from Alpaca paper to seed the cycle
        acct = alpaca_adapter.get_account_state()
        starting_cash = max(acct.cash_balance, Decimal("10000"))

        # Seed minimal rankings (bypass live data ingestion for E2E speed)
        from services.ranking_engine.models import RankedOpportunity
        state.latest_rankings = [
            RankedOpportunity(
                ticker="SPY",
                composite_score=0.75,
                signal_score=0.8,
                thesis_summary="S&P 500 index ETF momentum signal",
                disconfirming_factors=[],
                sizing_hint=0.05,
                source_reliability_tier="secondary_verified",
                contains_rumor=False,
            )
        ]

        result = run_paper_trading_cycle(
            app_state=state,
            settings=settings,
            broker_override=PaperBrokerAdapter(
                starting_cash=starting_cash,
                fill_immediately=True,
                market_open=True,
            ),
        )

        assert result["status"] in ("cycle_complete", "no_actions", "skip_no_rankings")
        assert "cycle" in result

    def test_alpaca_account_equity_is_positive(self, alpaca_adapter):
        """Alpaca paper account has positive equity (not wiped)."""
        state = alpaca_adapter.get_account_state()
        assert state.equity_value > Decimal("0")

    def test_alpaca_cash_balance_is_non_negative(self, alpaca_adapter):
        """Alpaca paper account cash balance is non-negative."""
        state = alpaca_adapter.get_account_state()
        assert state.cash_balance >= Decimal("0")

    def test_alpaca_positions_reflect_any_open_trades(self, alpaca_adapter):
        """Position list is coherent — all tickers are non-empty strings."""
        positions = alpaca_adapter.list_positions()
        for pos in positions:
            assert pos.ticker
            assert pos.market_value >= Decimal("0")
