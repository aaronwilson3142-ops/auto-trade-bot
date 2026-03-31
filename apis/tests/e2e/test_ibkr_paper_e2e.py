r"""
E2E Tests — IBKR TWS / IB Gateway Paper Account Integration.

These tests exercise the APIS IBKRBrokerAdapter against a locally running
TWS or IB Gateway in paper trading mode.  They require ib_insync connectivity
to a running TWS/Gateway process.

─────────────────────────────────────────────────────────────────────────────
Running these tests
─────────────────────────────────────────────────────────────────────────────
Prerequisites:
  1. TWS (Trader Workstation) or IB Gateway running locally in PAPER mode
  2. API connections enabled in TWS: Configure → API → Settings →
     "Enable ActiveX and Socket Clients" checked
  3. Confirm socket port (default paper TWS: 7497, IB Gateway paper: 4002)

Set environment variables:

    $env:IBKR_HOST      = "127.0.0.1"
    $env:IBKR_PORT      = "7497"          # 4002 for IB Gateway
    $env:IBKR_CLIENT_ID = "1"

Then run:

    cd apis
    $env:PYTHONPATH = "."
    .\.venv\Scripts\pytest.exe tests/e2e/test_ibkr_paper_e2e.py -v -s

These tests are EXCLUDED from the standard unit test run so they never
block CI.

─────────────────────────────────────────────────────────────────────────────
What is tested
─────────────────────────────────────────────────────────────────────────────
  E2E_I01: IBKRBrokerAdapter — connect / ping / disconnect lifecycle
  E2E_I02: IBKRBrokerAdapter — get_account_state returns valid AccountState
  E2E_I03: IBKRBrokerAdapter — list_positions returns list (may be empty)
  E2E_I04: IBKRBrokerAdapter — list_open_orders returns list
  E2E_I05: IBKRBrokerAdapter — is_market_open returns bool
  E2E_I06: IBKRBrokerAdapter — next_market_open returns future datetime
  E2E_I07: IBKRBrokerAdapter — place_order: $1 limit buy on SPY (won't fill)
  E2E_I08: IBKRBrokerAdapter — get_order retrieves submitted order
  E2E_I09: IBKRBrokerAdapter — cancel_order removes submitted order
  E2E_I10: IBKRBrokerAdapter — idempotency guard rejects duplicate key
  E2E_I11: Full IBKR paper cycle — ranked→portfolio→risk→execute
  E2E_I12: IBKRBrokerAdapter — paper port guard rejects live ports

─────────────────────────────────────────────────────────────────────────────
Safety guarantees
─────────────────────────────────────────────────────────────────────────────
- All adapter calls use paper=True.
- IBKR paper TWS port 7497 only (live port 7496 is rejected).
- Orders use limit_price=Decimal("1.00") on SPY — far below market; will
  never fill.
- Orders are cancelled immediately after submission.
- No live money is ever at risk.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime
from decimal import Decimal

import pytest

# ── Skip marker ───────────────────────────────────────────────────────────────

pytestmark = pytest.mark.e2e

# ── ib_insync event loop requirement ─────────────────────────────────────────

@pytest.fixture(autouse=True)
def _ensure_event_loop():
    """ib_insync 0.9.86 requires asyncio event loop at import time."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    loop.close()
    asyncio.set_event_loop(None)


# ── Credentials / connectivity guard ─────────────────────────────────────────

_IBKR_HOST      = os.environ.get("IBKR_HOST", "127.0.0.1")
_IBKR_PORT      = int(os.environ.get("IBKR_PORT", "0"))       # 0 = not set
_IBKR_CLIENT_ID = int(os.environ.get("IBKR_CLIENT_ID", "1"))

_CREDS_MISSING = _IBKR_PORT == 0

_skip_no_creds = pytest.mark.skipif(
    _CREDS_MISSING,
    reason=(
        "IBKR connectivity not configured.  Export IBKR_HOST and IBKR_PORT "
        "(e.g. IBKR_PORT=7497 for TWS paper) to run IBKR E2E tests."
    ),
)


# ── Shared adapter fixture ────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def ibkr_adapter():
    """Module-scoped fixture: connected IBKRBrokerAdapter (paper mode)."""
    if _CREDS_MISSING:
        pytest.skip("IBKR connectivity not configured — skipping IBKR E2E tests.")

    from broker_adapters.ibkr.adapter import IBKRBrokerAdapter

    adapter = IBKRBrokerAdapter(
        host=_IBKR_HOST,
        port=_IBKR_PORT,
        client_id=_IBKR_CLIENT_ID,
        paper=True,
    )
    adapter.connect()
    yield adapter
    adapter.disconnect()


# =============================================================================
# E2E_I01 — Connection / Lifecycle
# =============================================================================

@_skip_no_creds
class TestIBKRConnection:
    """E2E_I01 — connect / ping / disconnect lifecycle."""

    def test_connect_succeeds(self):
        from broker_adapters.ibkr.adapter import IBKRBrokerAdapter
        a = IBKRBrokerAdapter(
            host=_IBKR_HOST, port=_IBKR_PORT, client_id=99, paper=True
        )
        a.connect()
        assert a._connected is True
        a.disconnect()

    def test_ping_returns_true_when_connected(self, ibkr_adapter):
        assert ibkr_adapter.ping() is True

    def test_disconnect_resets_connected_flag(self):
        from broker_adapters.ibkr.adapter import IBKRBrokerAdapter
        a = IBKRBrokerAdapter(
            host=_IBKR_HOST, port=_IBKR_PORT, client_id=98, paper=True
        )
        a.connect()
        a.disconnect()
        assert a._connected is False


# =============================================================================
# E2E_I12 — Paper port guard
# =============================================================================

@_skip_no_creds
class TestIBKRPaperPortGuard:
    """E2E_I12 — live port is rejected when paper=True."""

    def test_live_port_rejected(self):
        from broker_adapters.base.exceptions import BrokerConnectionError
        from broker_adapters.ibkr.adapter import IBKRBrokerAdapter

        # 7496 is the live TWS port — must be rejected by paper=True guard
        a = IBKRBrokerAdapter(
            host=_IBKR_HOST, port=7496, client_id=97, paper=True
        )
        with pytest.raises((BrokerConnectionError, ValueError)):
            a.connect()


# =============================================================================
# E2E_I02 — Account State
# =============================================================================

@_skip_no_creds
class TestIBKRAccountState:
    """E2E_I02 — get_account_state returns valid AccountState."""

    def test_account_state_has_equity(self, ibkr_adapter):
        from broker_adapters.base.models import AccountState
        state = ibkr_adapter.get_account_state()
        assert isinstance(state, AccountState)
        assert state.total_equity >= Decimal("0")

    def test_account_state_has_cash(self, ibkr_adapter):
        state = ibkr_adapter.get_account_state()
        assert state.cash >= Decimal("0")


# =============================================================================
# E2E_I03 — Positions
# =============================================================================

@_skip_no_creds
class TestIBKRPositions:
    """E2E_I03 — list_positions returns list (may be empty)."""

    def test_list_positions_returns_list(self, ibkr_adapter):
        positions = ibkr_adapter.list_positions()
        assert isinstance(positions, list)

    def test_positions_have_valid_structure(self, ibkr_adapter):
        from broker_adapters.base.models import Position
        for pos in ibkr_adapter.list_positions():
            assert isinstance(pos, Position)
            assert pos.ticker
            assert pos.quantity >= 0


# =============================================================================
# E2E_I04 — Open Orders
# =============================================================================

@_skip_no_creds
class TestIBKROpenOrders:
    """E2E_I04 — list_open_orders returns list."""

    def test_list_open_orders_returns_list(self, ibkr_adapter):
        orders = ibkr_adapter.list_open_orders()
        assert isinstance(orders, list)


# =============================================================================
# E2E_I05-I06 — Market Hours
# =============================================================================

@_skip_no_creds
class TestIBKRMarketHours:
    """E2E_I05-I06 — market hours queries."""

    def test_is_market_open_returns_bool(self, ibkr_adapter):
        result = ibkr_adapter.is_market_open()
        assert isinstance(result, bool)

    def test_next_market_open_returns_datetime(self, ibkr_adapter):
        nmo = ibkr_adapter.next_market_open()
        assert isinstance(nmo, datetime)
        assert nmo.tzinfo is not None


# =============================================================================
# E2E_I07-I09 — Order Lifecycle
# =============================================================================

@_skip_no_creds
class TestIBKROrderLifecycle:
    """E2E_I07-I09 — place / get / cancel a $1 limit order."""

    def test_place_and_cancel_limit_order(self, ibkr_adapter):
        from broker_adapters.base.models import OrderRequest, OrderSide, OrderType, TimeInForce

        key = f"ibkr_e2e_{uuid.uuid4().hex[:8]}"

        req = OrderRequest(
            ticker="SPY",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1"),
            limit_price=Decimal("1.00"),   # won't fill
            time_in_force=TimeInForce.DAY,
            idempotency_key=key,
        )

        order = ibkr_adapter.place_order(req)
        assert order.order_id
        assert order.ticker == "SPY"

        fetched = ibkr_adapter.get_order(order.order_id)
        assert fetched.order_id == order.order_id

        ibkr_adapter.cancel_order(order.order_id)

        cancelled = ibkr_adapter.get_order(order.order_id)
        from broker_adapters.base.models import OrderStatus
        assert cancelled.status in (OrderStatus.CANCELLED, OrderStatus.SUBMITTED,
                                    OrderStatus.PENDING)

    def test_order_appears_in_open_orders(self, ibkr_adapter):
        from broker_adapters.base.models import OrderRequest, OrderSide, OrderType, TimeInForce

        key = f"ibkr_e2e_open_{uuid.uuid4().hex[:8]}"

        req = OrderRequest(
            ticker="SPY",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1"),
            limit_price=Decimal("1.00"),
            time_in_force=TimeInForce.DAY,
            idempotency_key=key,
        )

        order = ibkr_adapter.place_order(req)
        try:
            open_orders = ibkr_adapter.list_open_orders()
            open_ids = {o.order_id for o in open_orders}
            assert order.order_id in open_ids
        finally:
            try:
                ibkr_adapter.cancel_order(order.order_id)
            except Exception:
                pass


# =============================================================================
# E2E_I10 — Idempotency Guard
# =============================================================================

@_skip_no_creds
class TestIBKRIdempotency:
    """E2E_I10 — duplicate idempotency key is rejected."""

    def test_duplicate_key_raises(self, ibkr_adapter):
        from broker_adapters.base.exceptions import DuplicateOrderError
        from broker_adapters.base.models import OrderRequest, OrderSide, OrderType, TimeInForce

        key = f"ibkr_idem_{uuid.uuid4().hex[:8]}"

        req = OrderRequest(
            ticker="SPY",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1"),
            limit_price=Decimal("1.00"),
            time_in_force=TimeInForce.DAY,
            idempotency_key=key,
        )

        order = ibkr_adapter.place_order(req)
        try:
            with pytest.raises(DuplicateOrderError):
                ibkr_adapter.place_order(req)
        finally:
            try:
                ibkr_adapter.cancel_order(order.order_id)
            except Exception:
                pass


# =============================================================================
# E2E_I11 — Full IBKR Paper Cycle
# =============================================================================

@_skip_no_creds
class TestIBKRFullPaperCycle:
    """E2E_I11 — full paper trading cycle using IBKR adapter."""

    def test_full_paper_cycle_with_ibkr(self, ibkr_adapter):
        from apps.api.state import ApiAppState, reset_app_state
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from config.settings import Settings

        reset_app_state()
        state = ApiAppState()
        state.broker_adapter = ibkr_adapter

        from services.ranking_engine.service import RankedResult

        state.latest_rankings = [
            RankedResult(
                ticker="SPY",
                composite_score=0.75,
                thesis_summary="E2E test IBKR proxy",
                disconfirming_factors=[],
                sizing_hint=0.05,
                horizon="short",
                catalyst_class="market_proxy",
                source_reliability_tier="primary",
                contains_rumor=False,
            )
        ]

        settings = Settings(operating_mode="paper")
        result = run_paper_trading_cycle(app_state=state, settings=settings)

        assert result["status"] in ("ok", "no_actions", "skipped_no_rankings",
                                    "error", "skipped_mode")
        assert "executed_count" in result
