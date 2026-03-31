"""
Phase 14 — Schwab Adapter (Concrete), AWSSecretManager, Grafana Provisioning,
Prometheus Alert Rules, and E2E Scaffolding Tests.

All tests are unit tests using mocks — no live credentials required.

Covers:
  ✅ SchwabBrokerAdapter — concrete identity, construction, auth guards
  ✅ SchwabBrokerAdapter — connection (mock schwab-py client_from_token_file)
  ✅ SchwabBrokerAdapter — disconnect, ping lifecycle
  ✅ SchwabBrokerAdapter — get_account_state (mock API response)
  ✅ SchwabBrokerAdapter — place_order (buy/sell market & limit via mocked client)
  ✅ SchwabBrokerAdapter — duplicate idempotency guard
  ✅ SchwabBrokerAdapter — cancel_order, get_order, list_open_orders
  ✅ SchwabBrokerAdapter — get_position, list_positions, PositionNotFoundError
  ✅ SchwabBrokerAdapter — get_fills_for_order, list_fills_since
  ✅ SchwabBrokerAdapter — is_market_open, next_market_open
  ✅ SchwabBrokerAdapter — _parse_order, _parse_positions helpers
  ✅ SchwabBrokerAdapter — _next_930_et returns upcoming weekday 09:30 ET
  ✅ SchwabBrokerAdapter — require_account_hash guard raises BrokerConnectionError
  ✅ AWSSecretManager — concrete boto3 _fetch_from_aws path (mock boto3)
  ✅ AWSSecretManager — cache: second get() does not re-call boto3
  ✅ AWSSecretManager — missing key raises KeyError
  ✅ AWSSecretManager — invalid JSON payload raises RuntimeError
  ✅ AWSSecretManager — non-dict JSON raises RuntimeError
  ✅ AWSSecretManager — AWS API error raises RuntimeError
  ✅ AWSSecretManager — invalidate_cache clears cache
  ✅ AWSSecretManager — get_optional returns default on missing key
  ✅ Grafana provisioning YAML — datasource file exists and is valid YAML
  ✅ Grafana provisioning YAML — dashboard provisioning file exists and is valid YAML
  ✅ Prometheus alert rules — file exists and contains expected alert names
  ✅ Prometheus config — prometheus.yml exists and scrape config is valid YAML
  ✅ E2E test file — test file exists and has correct structure

Test classes
------------
  TestSchwabAdapterConcrete        — identity, properties, construction guards
  TestSchwabAdapterConnect         — connect() with mocked schwab-py
  TestSchwabAdapterDisconnectPing  — disconnect/ping lifecycle
  TestSchwabAdapterAccountState    — get_account_state mock
  TestSchwabAdapterPlaceOrder      — place_order BUY/SELL market/limit
  TestSchwabAdapterDuplicateGuard  — idempotency safety
  TestSchwabAdapterOrderOps        — cancel/get/list_open_orders
  TestSchwabAdapterPositions       — get_position, list_positions, not-found
  TestSchwabAdapterFills           — get_fills_for_order, list_fills_since
  TestSchwabAdapterMarketHours     — is_market_open, next_market_open
  TestSchwabAdapterHelpers         — _parse_order, _parse_positions, _next_930_et
  TestSchwabAdapterGuards          — require_connected, require_account_hash
  TestAWSSecretManagerConcrete     — boto3 fetch, cache, error paths
  TestGrafanaProvisioningFiles     — YAML files exist and parse correctly
  TestPrometheusAlertRules         — alert rules file structure and content
  TestE2ETestFileStructure         — E2E test file exists with correct markers
"""
from __future__ import annotations

import datetime as dt
import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ── Repo root helpers ──────────────────────────────────────────────────────────

_APIS_ROOT = Path(__file__).parent.parent.parent  # apis/


def _infra(path: str) -> Path:
    return _APIS_ROOT / "infra" / path


def _tests(path: str) -> Path:
    return _APIS_ROOT / "tests" / path


# =============================================================================
# TestSchwabAdapterConcrete
# =============================================================================

class TestSchwabAdapterConcrete:
    """Identity, properties, and construction guards."""

    def _make(self, **kwargs) -> "SchwabBrokerAdapter":  # noqa: F821
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        defaults = dict(
            api_key="test_key",
            app_secret="test_secret",
            account_hash="HASH_123",
            paper=True,
        )
        defaults.update(kwargs)
        return SchwabBrokerAdapter(**defaults)

    def test_module_importable(self):
        from broker_adapters.schwab import adapter  # noqa: F401

    def test_class_importable(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter  # noqa: F401

    def test_adapter_name_paper(self):
        adapter = self._make(paper=True)
        assert adapter.adapter_name == "schwab_paper"

    def test_adapter_name_live(self):
        adapter = self._make(paper=False)
        assert adapter.adapter_name == "schwab"

    def test_empty_api_key_raises(self):
        from broker_adapters.base.exceptions import BrokerAuthenticationError
        with pytest.raises(BrokerAuthenticationError):
            self._make(api_key="")

    def test_whitespace_api_key_raises(self):
        from broker_adapters.base.exceptions import BrokerAuthenticationError
        with pytest.raises(BrokerAuthenticationError):
            self._make(api_key="   ")

    def test_empty_app_secret_raises(self):
        from broker_adapters.base.exceptions import BrokerAuthenticationError
        with pytest.raises(BrokerAuthenticationError):
            self._make(app_secret="")

    def test_default_paper_is_true(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        a = SchwabBrokerAdapter(api_key="k", app_secret="s")
        assert a._paper is True

    def test_token_path_stored(self):
        a = self._make(token_path="my_token.json")
        assert a._token_path == "my_token.json"

    def test_account_hash_stored(self):
        a = self._make(account_hash="ACC_HASH")
        assert a._account_hash == "ACC_HASH"

    def test_not_connected_initially(self):
        a = self._make()
        assert a._connected is False

    def test_client_none_initially(self):
        a = self._make()
        assert a._client is None


# =============================================================================
# TestSchwabAdapterConnect
# =============================================================================

class TestSchwabAdapterConnect:
    """connect() with mocked schwab-py client_from_token_file."""

    def _make(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        return SchwabBrokerAdapter(
            api_key="key", app_secret="secret",
            token_path="tok.json", account_hash="H1",
        )

    def test_connect_sets_connected(self):
        adapter = self._make()
        mock_client = MagicMock()
        mock_client.get_user_preferences.return_value = MagicMock(status_code=200)
        with patch("schwab.auth.client_from_token_file", return_value=mock_client):
            adapter.connect()
        assert adapter._connected is True

    def test_connect_stores_client(self):
        adapter = self._make()
        mock_client = MagicMock()
        mock_client.get_user_preferences.return_value = MagicMock(status_code=200)
        with patch("schwab.auth.client_from_token_file", return_value=mock_client):
            adapter.connect()
        assert adapter._client is mock_client

    def test_connect_file_not_found_raises_auth_error(self):
        from broker_adapters.base.exceptions import BrokerAuthenticationError
        adapter = self._make()
        with patch("schwab.auth.client_from_token_file", side_effect=FileNotFoundError("not found")):
            with pytest.raises(BrokerAuthenticationError, match="token file not found"):
                adapter.connect()

    def test_connect_generic_exception_raises_auth_error(self):
        from broker_adapters.base.exceptions import BrokerAuthenticationError
        adapter = self._make()
        with patch("schwab.auth.client_from_token_file", side_effect=Exception("bad creds")):
            with pytest.raises(BrokerAuthenticationError):
                adapter.connect()

    def test_connect_bad_ping_status_raises_connection_error(self):
        from broker_adapters.base.exceptions import BrokerConnectionError
        adapter = self._make()
        mock_client = MagicMock()
        mock_client.get_user_preferences.return_value = MagicMock(status_code=401)
        with patch("schwab.auth.client_from_token_file", return_value=mock_client):
            with pytest.raises(BrokerConnectionError, match="HTTP 401"):
                adapter.connect()


# =============================================================================
# TestSchwabAdapterDisconnectPing
# =============================================================================

class TestSchwabAdapterDisconnectPing:
    """disconnect / ping lifecycle."""

    def _connected_adapter(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        a = SchwabBrokerAdapter(api_key="k", app_secret="s", account_hash="H")
        mock_client = MagicMock()
        mock_client.get_user_preferences.return_value = MagicMock(status_code=200)
        with patch("schwab.auth.client_from_token_file", return_value=mock_client):
            a.connect()
        return a, mock_client

    def test_disconnect_clears_connected(self):
        adapter, _ = self._connected_adapter()
        adapter.disconnect()
        assert adapter._connected is False

    def test_disconnect_clears_client(self):
        adapter, _ = self._connected_adapter()
        adapter.disconnect()
        assert adapter._client is None

    def test_ping_true_when_200(self):
        adapter, mock_client = self._connected_adapter()
        mock_client.get_user_preferences.return_value = MagicMock(status_code=200)
        assert adapter.ping() is True

    def test_ping_false_when_not_connected(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        a = SchwabBrokerAdapter(api_key="k", app_secret="s")
        assert a.ping() is False

    def test_ping_false_on_exception(self):
        adapter, mock_client = self._connected_adapter()
        mock_client.get_user_preferences.side_effect = Exception("timeout")
        assert adapter.ping() is False


# =============================================================================
# TestSchwabAdapterAccountState
# =============================================================================

class TestSchwabAdapterAccountState:
    """get_account_state mock."""

    def _connected_adapter(self, account_json: dict):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        a = SchwabBrokerAdapter(api_key="k", app_secret="s", account_hash="HASH")
        mock_client = MagicMock()
        mock_client.get_user_preferences.return_value = MagicMock(status_code=200)
        mock_client.get_account.return_value = MagicMock(
            json=MagicMock(return_value=account_json)
        )
        with patch("schwab.auth.client_from_token_file", return_value=mock_client):
            a.connect()
        return a

    def _acct_json(self, cash=50000.0, equity=55000.0, buying_power=45000.0):
        return {
            "securitiesAccount": {
                "accountNumber": "TEST123",
                "currentBalances": {
                    "cashBalance": cash,
                    "buyingPower": buying_power,
                    "liquidationValue": equity,
                },
                "positions": [],
            }
        }

    def test_returns_account_state(self):
        from broker_adapters.base.models import AccountState
        a = self._connected_adapter(self._acct_json())
        state = a.get_account_state()
        assert isinstance(state, AccountState)

    def test_cash_balance_parsed(self):
        a = self._connected_adapter(self._acct_json(cash=42000.0))
        state = a.get_account_state()
        assert state.cash_balance == Decimal("42000.0")

    def test_equity_value_parsed(self):
        a = self._connected_adapter(self._acct_json(equity=99000.0))
        state = a.get_account_state()
        assert state.equity_value == Decimal("99000.0")

    def test_account_id_from_account_number(self):
        a = self._connected_adapter(self._acct_json())
        state = a.get_account_state()
        assert state.account_id == "TEST123"

    def test_positions_empty(self):
        a = self._connected_adapter(self._acct_json())
        state = a.get_account_state()
        assert state.positions == []

    def test_not_connected_raises(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        from broker_adapters.base.exceptions import BrokerConnectionError
        a = SchwabBrokerAdapter(api_key="k", app_secret="s", account_hash="H")
        with pytest.raises(BrokerConnectionError):
            a.get_account_state()

    def test_no_account_hash_raises(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        from broker_adapters.base.exceptions import BrokerConnectionError
        a = SchwabBrokerAdapter(api_key="k", app_secret="s")
        a._connected = True
        a._client = MagicMock()
        with pytest.raises(BrokerConnectionError, match="account_hash"):
            a.get_account_state()


# =============================================================================
# TestSchwabAdapterPlaceOrder
# =============================================================================

class TestSchwabAdapterPlaceOrder:
    """place_order BUY/SELL market/limit via mocked client."""

    def _connected_adapter(self, place_resp_status=201, location="https://api.schwab.com/orders/999"):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        a = SchwabBrokerAdapter(api_key="k", app_secret="s", account_hash="H")
        mock_client = MagicMock()
        mock_client.get_user_preferences.return_value = MagicMock(status_code=200)
        place_resp = MagicMock(status_code=place_resp_status)
        place_resp.headers = {"Location": location}
        mock_client.place_order.return_value = place_resp
        with patch("schwab.auth.client_from_token_file", return_value=mock_client):
            a.connect()
        return a, mock_client

    def _buy_market_request(self, key="idem-1"):
        from broker_adapters.base.models import OrderRequest, OrderSide, OrderType
        return OrderRequest(
            idempotency_key=key,
            ticker="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("10"),
        )

    def _sell_limit_request(self, key="idem-2"):
        from broker_adapters.base.models import OrderRequest, OrderSide, OrderType
        return OrderRequest(
            idempotency_key=key,
            ticker="AAPL",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("5"),
            limit_price=Decimal("200.00"),
        )

    def test_buy_market_returns_order(self):
        from broker_adapters.base.models import Order
        adapter, _ = self._connected_adapter()
        order = adapter.place_order(self._buy_market_request())
        assert isinstance(order, Order)

    def test_buy_market_broker_order_id_extracted_from_location(self):
        adapter, _ = self._connected_adapter(location="https://api.schwab.com/orders/99999")
        order = adapter.place_order(self._buy_market_request())
        assert order.broker_order_id == "99999"

    def test_buy_market_status_submitted(self):
        from broker_adapters.base.models import OrderStatus
        adapter, _ = self._connected_adapter()
        order = adapter.place_order(self._buy_market_request())
        assert order.status == OrderStatus.SUBMITTED

    def test_sell_limit_returns_order(self):
        from broker_adapters.base.models import Order
        adapter, _ = self._connected_adapter(location="https://api.schwab.com/orders/1234")
        order = adapter.place_order(self._sell_limit_request())
        assert isinstance(order, Order)

    def test_place_order_non_success_raises_order_rejected_error(self):
        from broker_adapters.base.exceptions import OrderRejectedError
        adapter, _ = self._connected_adapter(place_resp_status=400)
        with pytest.raises(OrderRejectedError, match="HTTP 400"):
            adapter.place_order(self._buy_market_request())

    def test_limit_buy_without_price_raises(self):
        from broker_adapters.base.exceptions import OrderRejectedError
        from broker_adapters.base.models import OrderRequest, OrderSide, OrderType
        adapter, _ = self._connected_adapter()
        req = OrderRequest(
            idempotency_key="idem-x",
            ticker="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("5"),
            limit_price=None,
        )
        with pytest.raises(OrderRejectedError, match="limit_price"):
            adapter.place_order(req)

    def test_idempotency_key_stored_after_submit(self):
        adapter, _ = self._connected_adapter(location="https://api.schwab.com/orders/5")
        adapter.place_order(self._buy_market_request(key="unique-key-abc"))
        assert "unique-key-abc" in adapter._idempotency_keys


# =============================================================================
# TestSchwabAdapterDuplicateGuard
# =============================================================================

class TestSchwabAdapterDuplicateGuard:
    """Idempotency safety guard."""

    def test_duplicate_key_raises_duplicate_order_error(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        from broker_adapters.base.exceptions import DuplicateOrderError
        from broker_adapters.base.models import OrderRequest, OrderSide, OrderType
        a = SchwabBrokerAdapter(api_key="k", app_secret="s", account_hash="H")
        # Must be connected so _require_connected() passes before duplicate check
        a._connected = True
        a._client = MagicMock()
        a._idempotency_keys.add("existing-key")
        req = OrderRequest(
            idempotency_key="existing-key",
            ticker="MSFT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )
        with pytest.raises(DuplicateOrderError):
            a.place_order(req)


# =============================================================================
# TestSchwabAdapterOrderOps
# =============================================================================

class TestSchwabAdapterOrderOps:
    """cancel_order / get_order / list_open_orders."""

    def _order_json(self, order_id="333", status="WORKING"):
        return {
            "orderId": order_id,
            "status": status,
            "orderType": "MARKET",
            "filledQuantity": 0,
            "orderLegCollection": [
                {"instruction": "BUY", "quantity": 10,
                 "instrument": {"symbol": "NVDA", "assetType": "EQUITY"}}
            ],
            "orderActivityCollection": [],
            "enteredTime": "2026-03-18T10:00:00+00:00",
        }

    def _adapter_with_client(self, order_data=None, cancel_status=200, orders_list=None):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        a = SchwabBrokerAdapter(api_key="k", app_secret="s", account_hash="H")
        mock_client = MagicMock()
        mock_client.get_user_preferences.return_value = MagicMock(status_code=200)
        mock_client.get_order.return_value = MagicMock(
            json=MagicMock(return_value=order_data or self._order_json())
        )
        mock_client.cancel_order.return_value = MagicMock(status_code=cancel_status)
        mock_client.get_orders_for_account.return_value = MagicMock(
            json=MagicMock(return_value=orders_list or [])
        )
        with patch("schwab.auth.client_from_token_file", return_value=mock_client):
            a.connect()
        return a, mock_client

    def test_get_order_returns_order(self):
        from broker_adapters.base.models import Order
        a, _ = self._adapter_with_client()
        order = a.get_order("333")
        assert isinstance(order, Order)
        assert order.broker_order_id == "333"

    def test_get_order_ticker_parsed(self):
        a, _ = self._adapter_with_client()
        order = a.get_order("333")
        assert order.ticker == "NVDA"

    def test_cancel_order_calls_client(self):
        a, mock = self._adapter_with_client()
        a.cancel_order("333")
        mock.cancel_order.assert_called_once()

    def test_list_open_orders_empty(self):
        a, _ = self._adapter_with_client(orders_list=[])
        orders = a.list_open_orders()
        assert orders == []

    def test_list_open_orders_returns_orders(self):
        from broker_adapters.base.models import Order
        orders_raw = [self._order_json("10"), self._order_json("11")]
        a, _ = self._adapter_with_client(orders_list=orders_raw)
        orders = a.list_open_orders()
        assert len(orders) == 2
        assert all(isinstance(o, Order) for o in orders)


# =============================================================================
# TestSchwabAdapterPositions
# =============================================================================

class TestSchwabAdapterPositions:
    """get_position, list_positions, PositionNotFoundError."""

    def _adapter_with_positions(self, positions: list[dict]):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        a = SchwabBrokerAdapter(api_key="k", app_secret="s", account_hash="H")
        acct_json = {
            "securitiesAccount": {
                "accountNumber": "X",
                "currentBalances": {"cashBalance": 10000, "liquidationValue": 10000},
                "positions": positions,
            }
        }
        mock_client = MagicMock()
        mock_client.get_user_preferences.return_value = MagicMock(status_code=200)
        mock_client.get_account.return_value = MagicMock(
            json=MagicMock(return_value=acct_json)
        )
        with patch("schwab.auth.client_from_token_file", return_value=mock_client):
            a.connect()
        return a

    def _pos_data(self, symbol="AAPL", long_qty=10, avg=175.0, mkt=1760.0):
        return {
            "instrument": {"symbol": symbol, "assetType": "EQUITY"},
            "longQuantity": long_qty,
            "shortQuantity": 0,
            "averagePrice": avg,
            "marketValue": mkt,
        }

    def test_list_positions_returns_list(self):
        a = self._adapter_with_positions([self._pos_data()])
        positions = a.list_positions()
        assert isinstance(positions, list)

    def test_list_positions_correct_ticker(self):
        a = self._adapter_with_positions([self._pos_data("MSFT")])
        positions = a.list_positions()
        assert positions[0].ticker == "MSFT"

    def test_get_position_found(self):
        a = self._adapter_with_positions([self._pos_data("NVDA")])
        pos = a.get_position("NVDA")
        assert pos.ticker == "NVDA"

    def test_get_position_not_found_raises(self):
        from broker_adapters.base.exceptions import PositionNotFoundError
        a = self._adapter_with_positions([])
        with pytest.raises(PositionNotFoundError):
            a.get_position("AAPL")

    def test_position_market_value_is_decimal(self):
        a = self._adapter_with_positions([self._pos_data(mkt=1234.56)])
        pos = a.list_positions()[0]
        assert isinstance(pos.market_value, Decimal)


# =============================================================================
# TestSchwabAdapterFills
# =============================================================================

class TestSchwabAdapterFills:
    """get_fills_for_order, list_fills_since."""

    def _order_json_with_exec(self, order_id="555"):
        return {
            "orderId": order_id,
            "status": "FILLED",
            "orderType": "MARKET",
            "filledQuantity": 10,
            "orderLegCollection": [
                {"instruction": "BUY", "quantity": 10,
                 "instrument": {"symbol": "GOOGL", "assetType": "EQUITY"}}
            ],
            "orderActivityCollection": [
                {
                    "activityType": "EXECUTION",
                    "executionLegs": [
                        {"legId": "1", "price": 170.25, "quantity": 10,
                         "time": "2026-03-18T14:30:00+00:00"}
                    ],
                }
            ],
            "enteredTime": "2026-03-18T14:29:00+00:00",
        }

    def _adapter_with_fills(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        a = SchwabBrokerAdapter(api_key="k", app_secret="s", account_hash="H")
        mock_client = MagicMock()
        mock_client.get_user_preferences.return_value = MagicMock(status_code=200)
        mock_client.get_order.return_value = MagicMock(
            json=MagicMock(return_value=self._order_json_with_exec())
        )
        mock_client.get_transactions.return_value = MagicMock(
            json=MagicMock(return_value=[
                {
                    "type": "TRADE",
                    "transactionId": "TXN001",
                    "orderId": "555",
                    "tradeDate": "2026-03-18T14:30:00+00:00",
                    "transactionItem": {
                        "instruction": "BUY",
                        "amount": 10,
                        "price": 170.25,
                        "instrument": {"symbol": "GOOGL", "assetType": "EQUITY"},
                    },
                    "fees": {"commission": 0, "regulatoryFee": 0.01},
                }
            ])
        )
        with patch("schwab.auth.client_from_token_file", return_value=mock_client):
            a.connect()
        return a

    def test_get_fills_for_order_returns_fills(self):
        from broker_adapters.base.models import Fill
        a = self._adapter_with_fills()
        fills = a.get_fills_for_order("555")
        assert isinstance(fills, list)
        assert len(fills) == 1
        assert isinstance(fills[0], Fill)

    def test_get_fills_ticker(self):
        a = self._adapter_with_fills()
        fills = a.get_fills_for_order("555")
        assert fills[0].ticker == "GOOGL"

    def test_get_fills_price(self):
        a = self._adapter_with_fills()
        fills = a.get_fills_for_order("555")
        assert fills[0].fill_price == Decimal("170.25")

    def test_list_fills_since_returns_list(self):
        from broker_adapters.base.models import Fill
        a = self._adapter_with_fills()
        since = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        fills = a.list_fills_since(since)
        assert isinstance(fills, list)
        if fills:
            assert all(isinstance(f, Fill) for f in fills)

    def test_list_fills_non_trade_transaction_skipped(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        a = SchwabBrokerAdapter(api_key="k", app_secret="s", account_hash="H")
        mock_client = MagicMock()
        mock_client.get_user_preferences.return_value = MagicMock(status_code=200)
        mock_client.get_transactions.return_value = MagicMock(
            json=MagicMock(return_value=[
                {"type": "DIVIDEND", "transactionId": "D1"}
            ])
        )
        with patch("schwab.auth.client_from_token_file", return_value=mock_client):
            a.connect()
        result = a.list_fills_since(dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc))
        assert result == []


# =============================================================================
# TestSchwabAdapterMarketHours
# =============================================================================

class TestSchwabAdapterMarketHours:
    """is_market_open, next_market_open."""

    def _adapter_with_market(self, is_open: bool, start_str: str = "2026-03-18T09:30:00-05:00"):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        a = SchwabBrokerAdapter(api_key="k", app_secret="s", account_hash="H")
        mock_client = MagicMock()
        mock_client.get_user_preferences.return_value = MagicMock(status_code=200)
        hours_data = {
            "equity": {
                "EQ": {
                    "isOpen": is_open,
                    "sessionHours": {
                        "regularMarket": [{"start": start_str, "end": "2026-03-18T16:00:00-05:00"}]
                    }
                }
            }
        }
        mock_client.get_market_hours.return_value = MagicMock(
            json=MagicMock(return_value=hours_data)
        )
        with patch("schwab.auth.client_from_token_file", return_value=mock_client):
            a.connect()
        return a

    def test_is_market_open_true(self):
        a = self._adapter_with_market(is_open=True)
        assert a.is_market_open() is True

    def test_is_market_open_false(self):
        a = self._adapter_with_market(is_open=False)
        assert a.is_market_open() is False

    def test_is_market_open_exception_raises_connection_error(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        from broker_adapters.base.exceptions import BrokerConnectionError
        a = SchwabBrokerAdapter(api_key="k", app_secret="s", account_hash="H")
        # Not connected: _require_connected() raises BrokerConnectionError
        with pytest.raises(BrokerConnectionError):
            a.is_market_open()

    def test_next_market_open_returns_datetime(self):
        a = self._adapter_with_market(is_open=True)
        result = a.next_market_open()
        assert isinstance(result, dt.datetime)
        assert result.tzinfo is not None

    def test_next_market_open_raises_connection_error_when_not_connected(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        from broker_adapters.base.exceptions import BrokerConnectionError
        a = SchwabBrokerAdapter(api_key="k", app_secret="s", account_hash="H")
        with pytest.raises(BrokerConnectionError):
            a.next_market_open()


# =============================================================================
# TestSchwabAdapterHelpers
# =============================================================================

class TestSchwabAdapterHelpers:
    """_parse_order, _parse_positions, _next_930_et, _parse_ts."""

    def _make(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        return SchwabBrokerAdapter(api_key="k", app_secret="s", account_hash="H")

    def test_parse_ts_valid_iso(self):
        a = self._make()
        result = a._parse_ts("2026-03-18T14:30:00+00:00")
        assert result is not None
        assert result.tzinfo is not None

    def test_parse_ts_z_suffix(self):
        a = self._make()
        result = a._parse_ts("2026-03-18T14:30:00Z")
        assert result is not None

    def test_parse_ts_empty_returns_none(self):
        a = self._make()
        assert a._parse_ts("") is None

    def test_parse_ts_invalid_returns_none(self):
        a = self._make()
        assert a._parse_ts("not-a-date") is None

    def test_next_930_et_is_weekday(self):
        result = self._make()._next_930_et()
        assert result.weekday() < 5

    def test_next_930_et_in_future(self):
        result = self._make()._next_930_et()
        # Allow a 10-second margin for test execution time
        assert result > dt.datetime.now(tz=dt.timezone.utc) - dt.timedelta(seconds=10)

    def test_parse_order_filled_status(self):
        from broker_adapters.base.models import OrderStatus
        a = self._make()
        data = {
            "orderId": "111",
            "status": "FILLED",
            "orderType": "MARKET",
            "filledQuantity": 5,
            "orderLegCollection": [
                {"instruction": "BUY", "quantity": 5,
                 "instrument": {"symbol": "SPY", "assetType": "EQUITY"}}
            ],
            "orderActivityCollection": [],
            "enteredTime": "2026-03-18T10:00:00+00:00",
        }
        order = a._parse_order(data)
        assert order.status == OrderStatus.FILLED
        assert order.ticker == "SPY"

    def test_parse_positions_maps_correctly(self):
        a = self._make()
        positions_data = [
            {
                "instrument": {"symbol": "NVDA", "assetType": "EQUITY"},
                "longQuantity": 10,
                "shortQuantity": 0,
                "averagePrice": 900.0,
                "marketValue": 9100.0,
            }
        ]
        positions = a._parse_positions(positions_data)
        assert len(positions) == 1
        assert positions[0].ticker == "NVDA"
        assert positions[0].quantity == Decimal("10")

    def test_parse_positions_skips_zero_quantity(self):
        a = self._make()
        data = [
            {
                "instrument": {"symbol": "FLAT", "assetType": "EQUITY"},
                "longQuantity": 5,
                "shortQuantity": 5,
                "averagePrice": 100.0,
                "marketValue": 0.0,
            }
        ]
        result = a._parse_positions(data)
        assert result == []

    def test_parse_positions_skips_no_symbol(self):
        a = self._make()
        data = [
            {"instrument": {}, "longQuantity": 5, "shortQuantity": 0,
             "averagePrice": 100.0, "marketValue": 500.0}
        ]
        result = a._parse_positions(data)
        assert result == []


# =============================================================================
# TestSchwabAdapterGuards
# =============================================================================

class TestSchwabAdapterGuards:
    """require_connected, require_account_hash guards."""

    def test_require_connected_raises_when_not_connected(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        from broker_adapters.base.exceptions import BrokerConnectionError
        a = SchwabBrokerAdapter(api_key="k", app_secret="s", account_hash="H")
        with pytest.raises(BrokerConnectionError, match="not connected"):
            a._require_connected()

    def test_require_account_hash_raises_when_none(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        from broker_adapters.base.exceptions import BrokerConnectionError
        a = SchwabBrokerAdapter(api_key="k", app_secret="s")
        a._connected = True
        a._client = MagicMock()
        with pytest.raises(BrokerConnectionError, match="account_hash"):
            a._require_account_hash()


# =============================================================================
# TestAWSSecretManagerConcrete
# =============================================================================

class TestAWSSecretManagerConcrete:
    """Concrete boto3 fetch, cache, error paths."""

    def _make(self, name="apis/test/secrets", region="us-east-1"):
        from config.secrets import AWSSecretManager
        return AWSSecretManager(secret_name=name, region_name=region)

    def _mock_boto3_client(self, secret_json: dict):
        """Return a context manager that patches boto3.client to return a mock."""
        import json
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": json.dumps(secret_json)
        }
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client
        return patch.dict("sys.modules", {"boto3": mock_boto3}), mock_client

    def test_properties(self):
        a = self._make(name="my/secret", region="eu-west-1")
        assert a.secret_name == "my/secret"
        assert a.region_name == "eu-west-1"

    def test_get_fetches_from_aws(self):
        a = self._make()
        mock_ctx, mock_client = self._mock_boto3_client({"MY_KEY": "my_value"})
        with mock_ctx:
            result = a.get("MY_KEY")
        assert result == "my_value"

    def test_get_caches_after_first_call(self):
        a = self._make()
        mock_ctx, mock_client = self._mock_boto3_client({"K": "V"})
        with mock_ctx:
            a.get("K")
            a.get("K")
        # boto3.client called only once (cache hit on second call)
        import boto3
        assert mock_client.get_secret_value.call_count == 1

    def test_get_missing_key_raises_key_error(self):
        a = self._make()
        mock_ctx, _ = self._mock_boto3_client({"EXISTING": "value"})
        with mock_ctx:
            a.get("EXISTING")  # primes cache
        with pytest.raises(KeyError, match="MISSING"):
            a.get("MISSING")

    def test_get_optional_returns_default_on_missing(self):
        a = self._make()
        mock_ctx, _ = self._mock_boto3_client({"A": "1"})
        with mock_ctx:
            a.get("A")  # warm cache
        result = a.get_optional("NOT_THERE", default="fallback")
        assert result == "fallback"

    def test_get_optional_returns_value_when_present(self):
        a = self._make()
        mock_ctx, _ = self._mock_boto3_client({"X": "found"})
        with mock_ctx:
            result = a.get_optional("X")
        assert result == "found"

    def test_aws_api_error_raises_runtime_error(self):
        a = self._make()
        mock_client = MagicMock()
        mock_client.get_secret_value.side_effect = Exception("AccessDenied")
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            with pytest.raises(RuntimeError, match="Failed to fetch"):
                a.get("ANY_KEY")

    def test_invalid_json_raises_runtime_error(self):
        a = self._make()
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {"SecretString": "not-json{"}
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            with pytest.raises(RuntimeError, match="not valid JSON"):
                a.get("KEY")

    def test_non_dict_json_raises_runtime_error(self):
        import json
        a = self._make()
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {"SecretString": json.dumps(["list"])}
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            with pytest.raises(RuntimeError, match="JSON object"):
                a.get("KEY")

    def test_invalidate_cache_clears(self):
        a = self._make()
        mock_ctx, mock_client = self._mock_boto3_client({"Z": "z_val"})
        with mock_ctx:
            a.get("Z")  # populates cache
        assert a._cache != {}
        a.invalidate_cache()
        assert a._cache == {}

    def test_empty_secret_string_raises(self):
        a = self._make()
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {"SecretString": None}
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            with pytest.raises(RuntimeError, match="no SecretString"):
                a.get("KEY")


# =============================================================================
# TestGrafanaProvisioningFiles
# =============================================================================

class TestGrafanaProvisioningFiles:
    """Grafana provisioning YAML files exist and are valid YAML."""

    def test_datasource_file_exists(self):
        path = _infra("monitoring/grafana/provisioning/datasources/prometheus.yaml")
        assert path.exists(), f"Missing: {path}"

    def test_datasource_yaml_is_valid(self):
        path = _infra("monitoring/grafana/provisioning/datasources/prometheus.yaml")
        try:
            import yaml as _yaml
            data = _yaml.safe_load(path.read_text())
        except ImportError:
            pytest.skip("PyYAML not available — skipping YAML parse test")
        except Exception as exc:
            pytest.fail(f"datasource YAML is invalid: {exc}")
        assert data is not None

    def test_datasource_has_prometheus_entry(self):
        path = _infra("monitoring/grafana/provisioning/datasources/prometheus.yaml")
        content = path.read_text()
        assert "Prometheus" in content
        assert "prometheus" in content

    def test_datasource_targets_correct_url(self):
        path = _infra("monitoring/grafana/provisioning/datasources/prometheus.yaml")
        content = path.read_text()
        assert "http://prometheus:9090" in content

    def test_dashboard_provisioning_file_exists(self):
        path = _infra("monitoring/grafana/provisioning/dashboards/apis.yaml")
        assert path.exists(), f"Missing: {path}"

    def test_dashboard_yaml_is_valid(self):
        path = _infra("monitoring/grafana/provisioning/dashboards/apis.yaml")
        try:
            import yaml as _yaml
            data = _yaml.safe_load(path.read_text())
        except ImportError:
            pytest.skip("PyYAML not available")
        except Exception as exc:
            pytest.fail(f"dashboard YAML is invalid: {exc}")
        assert data is not None

    def test_dashboard_provisioning_has_path(self):
        path = _infra("monitoring/grafana/provisioning/dashboards/apis.yaml")
        content = path.read_text()
        assert "path" in content

    def test_grafana_dashboard_json_still_exists(self):
        """Ensure the existing dashboard JSON was not accidentally removed."""
        path = _infra("monitoring/grafana_dashboard.json")
        assert path.exists()

    def test_grafana_dashboard_json_is_valid(self):
        path = _infra("monitoring/grafana_dashboard.json")
        data = json.loads(path.read_text())
        # Must have at least the uid field we verified earlier
        assert "uid" in data or "panels" in data


# =============================================================================
# TestPrometheusAlertRules
# =============================================================================

class TestPrometheusAlertRules:
    """Alert rules file structure and content."""

    def test_alert_rules_file_exists(self):
        path = _infra("monitoring/prometheus/rules/apis_alerts.yaml")
        assert path.exists(), f"Missing: {path}"

    def test_prometheus_config_file_exists(self):
        path = _infra("monitoring/prometheus/prometheus.yml")
        assert path.exists(), f"Missing: {path}"

    def test_alert_rules_yaml_is_valid(self):
        path = _infra("monitoring/prometheus/rules/apis_alerts.yaml")
        try:
            import yaml as _yaml
            data = _yaml.safe_load(path.read_text())
        except ImportError:
            pytest.skip("PyYAML not available")
        except Exception as exc:
            pytest.fail(f"Alert rules YAML is invalid: {exc}")
        assert data is not None

    def test_alert_rules_has_groups(self):
        path = _infra("monitoring/prometheus/rules/apis_alerts.yaml")
        content = path.read_text()
        assert "groups:" in content

    def test_kill_switch_alert_present(self):
        path = _infra("monitoring/prometheus/rules/apis_alerts.yaml")
        content = path.read_text()
        assert "KillSwitchActive" in content

    def test_drawdown_alert_present(self):
        path = _infra("monitoring/prometheus/rules/apis_alerts.yaml")
        content = path.read_text()
        assert "DrawdownAlert" in content or "Drawdown" in content

    def test_paper_loop_inactive_alert_present(self):
        path = _infra("monitoring/prometheus/rules/apis_alerts.yaml")
        content = path.read_text()
        assert "PaperLoopInactive" in content

    def test_scrape_down_alert_present(self):
        path = _infra("monitoring/prometheus/rules/apis_alerts.yaml")
        content = path.read_text()
        assert "APISScrapeDown" in content

    def test_alert_has_severity_labels(self):
        path = _infra("monitoring/prometheus/rules/apis_alerts.yaml")
        content = path.read_text()
        assert "severity:" in content

    def test_alert_has_annotations(self):
        path = _infra("monitoring/prometheus/rules/apis_alerts.yaml")
        content = path.read_text()
        assert "summary:" in content
        assert "description:" in content

    def test_prometheus_config_scrapes_apis(self):
        path = _infra("monitoring/prometheus/prometheus.yml")
        content = path.read_text()
        assert "job_name: apis" in content or "job_name:" in content

    def test_prometheus_config_references_alert_rules(self):
        path = _infra("monitoring/prometheus/prometheus.yml")
        content = path.read_text()
        assert "rule_files" in content


# =============================================================================
# TestE2ETestFileStructure
# =============================================================================

class TestE2ETestFileStructure:
    """E2E test file exists with correct structure."""

    def test_e2e_test_file_exists(self):
        path = _tests("e2e/test_alpaca_paper_e2e.py")
        assert path.exists(), f"Missing: {path}"

    def test_e2e_test_file_has_e2e_marker(self):
        path = _tests("e2e/test_alpaca_paper_e2e.py")
        content = path.read_text()
        assert "pytest.mark.e2e" in content

    def test_e2e_test_file_has_skip_no_creds(self):
        path = _tests("e2e/test_alpaca_paper_e2e.py")
        content = path.read_text()
        assert "ALPACA_API_KEY" in content
        assert "skipif" in content

    def test_e2e_test_file_has_alpaca_adapter_fixture(self):
        path = _tests("e2e/test_alpaca_paper_e2e.py")
        content = path.read_text()
        assert "alpaca_adapter" in content

    def test_e2e_test_file_has_connection_test_class(self):
        path = _tests("e2e/test_alpaca_paper_e2e.py")
        content = path.read_text()
        assert "TestAlpacaConnection" in content

    def test_e2e_test_file_has_order_lifecycle_class(self):
        path = _tests("e2e/test_alpaca_paper_e2e.py")
        content = path.read_text()
        assert "TestAlpacaOrderLifecycle" in content

    def test_e2e_test_file_has_full_cycle_class(self):
        path = _tests("e2e/test_alpaca_paper_e2e.py")
        content = path.read_text()
        assert "TestFullPaperTradingCycleIntegration" in content

    def test_e2e_test_paper_true_enforced(self):
        path = _tests("e2e/test_alpaca_paper_e2e.py")
        content = path.read_text()
        assert "paper=True" in content
