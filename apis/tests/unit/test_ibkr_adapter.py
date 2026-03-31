"""
Phase 10 — Step 3: IBKR Adapter Scaffold Tests

Verifies that the IBKRBrokerAdapter scaffold:
- is importable and implements BaseBrokerAdapter
- has the correct adapter name
- instantiates cleanly with default and explicit constructor arguments
- enforces the live-port safety guard
- raises NotImplementedError on every operational method
- exports correctly from the package __init__
"""
from __future__ import annotations

import asyncio
import datetime as dt
from decimal import Decimal

import pytest


# ---------------------------------------------------------------------------
# Event-loop fixture (ib_insync/eventkit requires a running event loop on import)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _ensure_event_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    loop.close()
    asyncio.set_event_loop(None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_adapter(**kwargs):
    from broker_adapters.ibkr.adapter import IBKRBrokerAdapter
    return IBKRBrokerAdapter(**kwargs)


# ===========================================================================
# TestIBKRAdapterImportAndIdentity
# ===========================================================================

class TestIBKRAdapterImportAndIdentity:
    def test_import_adapter_class(self):
        from broker_adapters.ibkr.adapter import IBKRBrokerAdapter
        assert IBKRBrokerAdapter is not None

    def test_inherits_from_base_adapter(self):
        from broker_adapters.base.adapter import BaseBrokerAdapter
        from broker_adapters.ibkr.adapter import IBKRBrokerAdapter
        assert issubclass(IBKRBrokerAdapter, BaseBrokerAdapter)

    def test_adapter_name_is_ibkr(self):
        adapter = _make_adapter()
        assert adapter.adapter_name == "ibkr"

    def test_module_exports(self):
        from broker_adapters.ibkr import IBKRBrokerAdapter
        assert IBKRBrokerAdapter is not None


# ===========================================================================
# TestIBKRAdapterConstruction
# ===========================================================================

class TestIBKRAdapterConstruction:
    def test_instantiation_with_defaults(self):
        adapter = _make_adapter()
        assert adapter._host == "127.0.0.1"
        assert adapter._port == 7497
        assert adapter._client_id == 1
        assert adapter._paper is True

    def test_instantiation_with_explicit_paper_params(self):
        adapter = _make_adapter(host="10.0.0.1", port=4002, client_id=5, paper=True)
        assert adapter._host == "10.0.0.1"
        assert adapter._port == 4002
        assert adapter._client_id == 5

    def test_instantiation_live_mode_allowed_with_paper_false(self):
        # paper=False + live port is allowed (explicit approval simulation)
        adapter = _make_adapter(port=7496, paper=False)
        assert adapter._port == 7496
        assert adapter._paper is False

    def test_safety_guard_rejects_live_port_7496_when_paper(self):
        with pytest.raises(ValueError, match="live-trading port"):
            _make_adapter(port=7496, paper=True)

    def test_safety_guard_rejects_live_port_4001_when_paper(self):
        with pytest.raises(ValueError, match="live-trading port"):
            _make_adapter(port=4001, paper=True)

    def test_paper_port_7497_allowed_when_paper(self):
        adapter = _make_adapter(port=7497, paper=True)
        assert adapter._port == 7497

    def test_paper_port_4002_allowed_when_paper(self):
        adapter = _make_adapter(port=4002, paper=True)
        assert adapter._port == 4002


# ===========================================================================
# TestIBKRAdapterMethodStubs
# ===========================================================================

class TestIBKRAdapterMethodStubs:
    """Concrete adapter raises BrokerConnectionError (not NotImplementedError).

    The adapter is fully implemented; all methods require an active connection
    and raise BrokerConnectionError when called without one.  The two status
    methods (ping, is_market_open, next_market_open, disconnect) are
    connection-safe.
    """

    def setup_method(self):
        from broker_adapters.ibkr.adapter import IBKRBrokerAdapter
        self.adapter = IBKRBrokerAdapter()

    def _assert_requires_connection(self, fn, *args, **kwargs):
        from broker_adapters.base.exceptions import BrokerConnectionError
        with pytest.raises(BrokerConnectionError):
            fn(*args, **kwargs)

    def test_connect_raises_not_implemented(self):
        # connect() raises BrokerConnectionError wrapping the ib_insync connection error
        # (not NotImplementedError — the concrete implementation will fail to reach TWS)
        from broker_adapters.base.exceptions import BrokerConnectionError
        with pytest.raises(BrokerConnectionError):
            self.adapter.connect()

    def test_disconnect_raises_not_implemented(self):
        # disconnect() is a no-op when not connected (does not raise)
        self.adapter.disconnect()  # should not raise

    def test_ping_raises_not_implemented(self):
        # ping() returns False when not connected
        assert self.adapter.ping() is False

    def test_get_account_state_raises_not_implemented(self):
        self._assert_requires_connection(self.adapter.get_account_state)

    def test_place_order_raises_not_implemented(self):
        from broker_adapters.base.models import OrderRequest, OrderSide, OrderType
        req = OrderRequest(
            idempotency_key="key-001",
            ticker="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("10"),
        )
        self._assert_requires_connection(self.adapter.place_order, req)

    def test_cancel_order_raises_not_implemented(self):
        self._assert_requires_connection(self.adapter.cancel_order, "order-001")

    def test_get_order_raises_not_implemented(self):
        self._assert_requires_connection(self.adapter.get_order, "order-001")

    def test_list_open_orders_raises_not_implemented(self):
        self._assert_requires_connection(self.adapter.list_open_orders)

    def test_get_position_raises_not_implemented(self):
        self._assert_requires_connection(self.adapter.get_position, "AAPL")

    def test_list_positions_raises_not_implemented(self):
        self._assert_requires_connection(self.adapter.list_positions)

    def test_get_fills_for_order_raises_not_implemented(self):
        self._assert_requires_connection(self.adapter.get_fills_for_order, "order-001")

    def test_list_fills_since_raises_not_implemented(self):
        self._assert_requires_connection(
            self.adapter.list_fills_since,
            dt.datetime.now(dt.timezone.utc),
        )

    def test_is_market_open_raises_not_implemented(self):
        # is_market_open() works without a connection
        result = self.adapter.is_market_open()
        assert isinstance(result, bool)

    def test_next_market_open_raises_not_implemented(self):
        # next_market_open() works without a connection
        result = self.adapter.next_market_open()
        assert isinstance(result, dt.datetime)
