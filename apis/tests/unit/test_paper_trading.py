"""
Gate F — Paper Trading Integration Tests.

Verifies (Gate F criteria from APIS_BUILD_RUNBOOK.md § Gate F):
  ✅ order flow works           — Alpaca adapter correctly wraps SDK calls
                                  (mocked; no live API calls in unit tests)
  ✅ reconciliations work       — ReportingService.reconcile_fills() covers
                                  all ReconciliationStatus paths
  ✅ duplicate order prevention — AlpacaBrokerAdapter raises DuplicateOrderError
                                  on repeated idempotency_key
  ✅ P&L and holdings consistent — check_pnl_consistency() validates drift
  ✅ daily operational report    — generate_daily_report() produces fully-
                                  populated DailyOperationalReport
  ✅ slippage monitoring         — slippage_bps computed and surfaced in report

Test classes
------------
  TestAlpacaAdapterConstruction  — init, adapter_name, auth guards
  TestAlpacaAdapterNotConnected  — every method raises BrokerConnectionError
  TestAlpacaAdapterOrderFlow     — place_order / cancel / get (mocked SDK)
  TestAlpacaAdapterDuplicateGuard — duplicate key prevention
  TestAlpacaAdapterFillSynthesis — _synthesise_fill helper
  TestAlpacaAdapterTranslation   — _to_order / _to_position helpers
  TestFillReconciliationModels   — FillReconciliationRecord / Summary properties
  TestReconcilefills             — ReportingService.reconcile_fills() all paths
  TestPnlConsistency             — check_pnl_consistency() pass + drift
  TestGenerateDailyReport        — generate_daily_report() all fields
  TestSlippageCalc               — _calc_slippage_bps helper
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from broker_adapters.alpaca.adapter import AlpacaBrokerAdapter
from broker_adapters.base.exceptions import (
    BrokerAuthenticationError,
    BrokerConnectionError,
    DuplicateOrderError,
    MarketClosedError,
    OrderRejectedError,
    PositionNotFoundError,
)
from broker_adapters.base.models import (
    Fill,
    Order,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
)
from services.reporting.models import (
    DailyOperationalReport,
    FillExpectation,
    FillReconciliationRecord,
    FillReconciliationSummary,
    ReconciliationStatus,
)
from services.reporting.service import ReportingService

# ─────────────────────── helpers ──────────────────────────────────────────────

_NOW = dt.datetime(2026, 3, 17, 16, 0, 0, tzinfo=dt.UTC)
_TODAY = _NOW.date()


def _adapter(paper: bool = True) -> AlpacaBrokerAdapter:
    return AlpacaBrokerAdapter(api_key="test-key", api_secret="test-secret", paper=paper)


def _expectation(
    key: str = "idem-001",
    ticker: str = "AAPL",
    qty: str = "10",
    price: str = "150.00",
) -> FillExpectation:
    return FillExpectation(
        idempotency_key=key,
        ticker=ticker,
        expected_quantity=Decimal(qty),
        expected_price=Decimal(price),
        submitted_at=_NOW,
    )


def _fill(
    broker_order_id: str = "idem-001",
    ticker: str = "AAPL",
    qty: str = "10",
    price: str = "150.00",
    side: OrderSide = OrderSide.BUY,
) -> Fill:
    return Fill(
        broker_fill_id=f"{broker_order_id}-fill",
        broker_order_id=broker_order_id,
        ticker=ticker,
        side=side,
        fill_quantity=Decimal(qty),
        fill_price=Decimal(price),
        fees=Decimal("0"),
        filled_at=_NOW,
    )


def _order(
    broker_order_id: str = "ord-001",
    ticker: str = "AAPL",
    side: OrderSide = OrderSide.BUY,
    status: OrderStatus = OrderStatus.FILLED,
    filled_qty: str = "10",
    avg_price: str = "150.00",
    idempotency_key: str = "idem-001",
) -> Order:
    return Order(
        idempotency_key=idempotency_key,
        broker_order_id=broker_order_id,
        ticker=ticker,
        side=side,
        order_type=OrderType.MARKET,
        requested_quantity=Decimal(filled_qty),
        filled_quantity=Decimal(filled_qty),
        status=status,
        submitted_at=_NOW,
        filled_at=_NOW,
        average_fill_price=Decimal(avg_price),
    )


def _svc(tolerance_bps: int = 50) -> ReportingService:
    return ReportingService(slippage_tolerance_bps=tolerance_bps)


def _simple_reconciliation(
    n: int = 1, status: ReconciliationStatus = ReconciliationStatus.MATCHED
) -> FillReconciliationSummary:
    records = [
        FillReconciliationRecord(
            idempotency_key=f"key-{i}",
            ticker="AAPL",
            status=status,
            expected_quantity=Decimal("10"),
            actual_quantity=Decimal("10"),
            expected_price=Decimal("150.00"),
            actual_price=Decimal("150.00"),
            slippage_bps=Decimal("0"),
        )
        for i in range(n)
    ]
    return FillReconciliationSummary(records=records)


# ─────────────────────── TestAlpacaAdapterConstruction ────────────────────────

class TestAlpacaAdapterConstruction:
    def test_adapter_name_paper(self) -> None:
        a = _adapter(paper=True)
        assert a.adapter_name == "alpaca_paper"

    def test_adapter_name_live(self) -> None:
        a = _adapter(paper=False)
        assert a.adapter_name == "alpaca_live"

    def test_empty_api_key_raises_auth_error(self) -> None:
        with pytest.raises(BrokerAuthenticationError):
            AlpacaBrokerAdapter(api_key="", api_secret="secret")

    def test_empty_api_secret_raises_auth_error(self) -> None:
        with pytest.raises(BrokerAuthenticationError):
            AlpacaBrokerAdapter(api_key="key", api_secret="")

    def test_not_connected_after_init(self) -> None:
        a = _adapter()
        assert a.ping() is False


# ─────────────────────── TestAlpacaAdapterNotConnected ────────────────────────

class TestAlpacaAdapterNotConnected:
    def test_get_account_state_raises(self) -> None:
        with pytest.raises(BrokerConnectionError):
            _adapter().get_account_state()

    def test_place_order_raises(self) -> None:
        req = OrderRequest(
            idempotency_key="k1",
            ticker="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("5"),
        )
        with pytest.raises(BrokerConnectionError):
            _adapter().place_order(req)

    def test_list_positions_raises(self) -> None:
        with pytest.raises(BrokerConnectionError):
            _adapter().list_positions()

    def test_get_position_raises(self) -> None:
        with pytest.raises(BrokerConnectionError):
            _adapter().get_position("AAPL")

    def test_get_order_raises(self) -> None:
        with pytest.raises(BrokerConnectionError):
            _adapter().get_order("some-id")

    def test_list_open_orders_raises(self) -> None:
        with pytest.raises(BrokerConnectionError):
            _adapter().list_open_orders()

    def test_is_market_open_raises(self) -> None:
        with pytest.raises(BrokerConnectionError):
            _adapter().is_market_open()


# ─────────────────────── TestAlpacaAdapterDuplicateGuard ─────────────────────

class TestAlpacaAdapterDuplicateGuard:
    def _connected_adapter(self) -> AlpacaBrokerAdapter:
        a = _adapter()
        # Simulate connected state without a real API call
        a._connected = True
        a._client = MagicMock()
        return a

    def test_duplicate_key_raises_duplicate_order_error(self) -> None:
        a = self._connected_adapter()
        # Pre-seed the key as if an order was already submitted
        a._submitted_keys.add("idem-dup")

        req = OrderRequest(
            idempotency_key="idem-dup",
            ticker="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("10"),
        )
        # Market open
        a._client.get_clock.return_value = MagicMock(is_open=True)
        with pytest.raises(DuplicateOrderError):
            a.place_order(req)

    def test_different_key_does_not_raise(self) -> None:
        a = self._connected_adapter()
        a._submitted_keys.add("idem-001")  # different key already used

        # Mock a successful submit
        mock_order = MagicMock()
        mock_order.id = uuid.uuid4()
        mock_order.status = "new"
        mock_order.symbol = "AAPL"
        mock_order.side = "buy"
        mock_order.qty = "5"
        mock_order.filled_qty = "0"
        mock_order.filled_avg_price = None
        mock_order.limit_price = None
        mock_order.stop_price = None
        mock_order.submitted_at = _NOW
        mock_order.filled_at = None
        mock_order.failed_at = None
        mock_order.client_order_id = "idem-002"

        a._client.get_clock.return_value = MagicMock(is_open=True)
        a._client.submit_order.return_value = mock_order

        req = OrderRequest(
            idempotency_key="idem-002",
            ticker="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("5"),
        )
        result = a.place_order(req)
        assert result.idempotency_key == "idem-002"
        assert "idem-002" in a._submitted_keys


# ─────────────────────── TestAlpacaAdapterOrderFlow ───────────────────────────

class TestAlpacaAdapterOrderFlow:
    def _connected_adapter(self) -> AlpacaBrokerAdapter:
        a = _adapter()
        a._connected = True
        a._client = MagicMock()
        return a

    def _mock_alpaca_order(
        self,
        status: str = "filled",
        filled_qty: str = "10",
        avg_price: str = "150.00",
        client_order_id: str = "idem-001",
    ) -> MagicMock:
        o = MagicMock()
        o.id = str(uuid.uuid4())
        o.status = status
        o.symbol = "AAPL"
        o.side = "buy"
        o.qty = "10"
        o.filled_qty = filled_qty
        o.filled_avg_price = avg_price
        o.limit_price = None
        o.stop_price = None
        o.submitted_at = _NOW
        o.filled_at = _NOW if status == "filled" else None
        o.failed_at = None
        o.client_order_id = client_order_id
        return o

    def test_place_market_order_returns_order(self) -> None:
        a = self._connected_adapter()
        a._client.get_clock.return_value = MagicMock(is_open=True)
        a._client.submit_order.return_value = self._mock_alpaca_order()

        req = OrderRequest(
            idempotency_key="idem-001",
            ticker="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("10"),
        )
        result = a.place_order(req)
        assert result.ticker == "AAPL"
        assert result.idempotency_key == "idem-001"

    def test_place_order_market_closed_raises(self) -> None:
        a = self._connected_adapter()
        a._client.get_clock.return_value = MagicMock(is_open=False)

        req = OrderRequest(
            idempotency_key="idem-mc",
            ticker="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("5"),
        )
        with pytest.raises(MarketClosedError):
            a.place_order(req)

    def test_place_limit_order_no_price_raises(self) -> None:
        a = self._connected_adapter()
        a._client.get_clock.return_value = MagicMock(is_open=True)

        req = OrderRequest(
            idempotency_key="idem-lim",
            ticker="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("5"),
            limit_price=None,
        )
        with pytest.raises(OrderRejectedError):
            a.place_order(req)

    def test_get_order_calls_sdk(self) -> None:
        a = self._connected_adapter()
        mo = self._mock_alpaca_order()
        a._client.get_order_by_id.return_value = mo

        result = a.get_order(str(mo.id))
        assert result.status == OrderStatus.FILLED

    def test_get_fills_for_filled_order_returns_one_fill(self) -> None:
        a = self._connected_adapter()
        mo = self._mock_alpaca_order(status="filled", avg_price="151.00")
        a._client.get_order_by_id.return_value = mo

        fills = a.get_fills_for_order(str(mo.id))
        assert len(fills) == 1
        assert fills[0].fill_price == Decimal("151.00")

    def test_get_fills_for_unfilled_order_returns_empty(self) -> None:
        a = self._connected_adapter()
        mo = self._mock_alpaca_order(status="new", filled_qty="0", avg_price=None)
        mo.filled_avg_price = None
        a._client.get_order_by_id.return_value = mo

        fills = a.get_fills_for_order(str(mo.id))
        assert fills == []

    def test_list_positions_empty(self) -> None:
        a = self._connected_adapter()
        a._client.get_all_positions.return_value = []
        assert a.list_positions() == []

    def test_get_position_not_found_raises(self) -> None:
        a = self._connected_adapter()
        a._client.get_open_position.side_effect = Exception("position not found")
        with pytest.raises(PositionNotFoundError):
            a.get_position("AAPL")


# ─────────────────────── TestAlpacaAdapterFillSynthesis ───────────────────────

class TestAlpacaAdapterFillSynthesis:
    def test_synthesise_fill_fields(self) -> None:
        o = _order(broker_order_id="ord-99", avg_price="200.50", filled_qty="7")
        fill = AlpacaBrokerAdapter._synthesise_fill(o)
        assert fill.broker_order_id == "ord-99"
        assert fill.fill_price == Decimal("200.50")
        assert fill.fill_quantity == Decimal("7")
        assert fill.fees == Decimal("0")

    def test_synthesise_fill_id_contains_order_id(self) -> None:
        o = _order(broker_order_id="ord-abc")
        fill = AlpacaBrokerAdapter._synthesise_fill(o)
        assert "ord-abc" in fill.broker_fill_id


# ─────────────────────── TestAlpacaAdapterTranslation ─────────────────────────

class TestAlpacaAdapterTranslation:
    def test_to_order_filled_status(self) -> None:
        a = _adapter()
        mock = MagicMock()
        mock.id = str(uuid.uuid4())
        mock.status = "filled"
        mock.symbol = "TSLA"
        mock.side = "sell"
        mock.qty = "5"
        mock.filled_qty = "5"
        mock.filled_avg_price = "300.00"
        mock.limit_price = None
        mock.stop_price = None
        mock.submitted_at = _NOW
        mock.filled_at = _NOW
        mock.failed_at = None

        o = a._to_order(mock, "idem-xyz")
        assert o.status == OrderStatus.FILLED
        assert o.ticker == "TSLA"
        assert o.side == OrderSide.SELL
        assert o.average_fill_price == Decimal("300.00")

    def test_to_order_pending_status(self) -> None:
        a = _adapter()
        mock = MagicMock()
        mock.id = str(uuid.uuid4())
        mock.status = "pending_new"
        mock.symbol = "AAPL"
        mock.side = "buy"
        mock.qty = "3"
        mock.filled_qty = "0"
        mock.filled_avg_price = None
        mock.limit_price = None
        mock.stop_price = None
        mock.submitted_at = _NOW
        mock.filled_at = None
        mock.failed_at = None

        o = a._to_order(mock, "idem-pend")
        assert o.status == OrderStatus.PENDING

    def test_to_position_fields(self) -> None:
        a = _adapter()
        mock = MagicMock()
        mock.symbol = "MSFT"
        mock.qty = "20"
        mock.avg_entry_price = "400.00"
        mock.current_price = "410.00"
        mock.market_value = "8200.00"
        mock.unrealized_pl = "200.00"
        mock.unrealized_plpc = "0.025"
        mock.side = "long"

        pos = a._to_position(mock)
        assert pos.ticker == "MSFT"
        assert pos.quantity == Decimal("20")
        assert pos.unrealized_pnl == Decimal("200.00")


# ─────────────────────── TestFillReconciliationModels ─────────────────────────

class TestFillReconciliationModels:
    def test_is_clean_matched(self) -> None:
        r = FillReconciliationRecord(
            idempotency_key="k",
            ticker="AAPL",
            status=ReconciliationStatus.MATCHED,
            expected_quantity=Decimal("10"),
            actual_quantity=Decimal("10"),
            expected_price=Decimal("150"),
            actual_price=Decimal("150"),
            slippage_bps=Decimal("0"),
        )
        assert r.is_clean is True

    def test_is_clean_false_for_missing_fill(self) -> None:
        r = FillReconciliationRecord(
            idempotency_key="k",
            ticker="AAPL",
            status=ReconciliationStatus.MISSING_FILL,
            expected_quantity=Decimal("10"),
            actual_quantity=Decimal("0"),
            expected_price=Decimal("150"),
            actual_price=Decimal("0"),
            slippage_bps=Decimal("0"),
        )
        assert r.is_clean is False

    def test_summary_total_and_matched(self) -> None:
        s = _simple_reconciliation(n=3, status=ReconciliationStatus.MATCHED)
        assert s.total == 3
        assert s.matched == 3
        assert s.discrepancies == 0

    def test_summary_discrepancies(self) -> None:
        records = [
            FillReconciliationRecord(
                idempotency_key=f"k{i}",
                ticker="AAPL",
                status=ReconciliationStatus.MATCHED if i < 2 else ReconciliationStatus.PRICE_DRIFT,
                expected_quantity=Decimal("10"),
                actual_quantity=Decimal("10"),
                expected_price=Decimal("150"),
                actual_price=Decimal("152") if i >= 2 else Decimal("150"),
                slippage_bps=Decimal("133.33") if i >= 2 else Decimal("0"),
            )
            for i in range(3)
        ]
        s = FillReconciliationSummary(records=records)
        assert s.matched == 2
        assert s.discrepancies == 1

    def test_avg_slippage_bps_zero_when_no_records(self) -> None:
        s = FillReconciliationSummary(records=[])
        assert s.avg_slippage_bps == Decimal("0")

    def test_max_slippage_bps_zero_when_no_records(self) -> None:
        s = FillReconciliationSummary(records=[])
        assert s.max_slippage_bps == Decimal("0")

    def test_avg_slippage_bps_computed(self) -> None:
        records = [
            FillReconciliationRecord(
                idempotency_key=f"k{i}",
                ticker="AAPL",
                status=ReconciliationStatus.MATCHED,
                expected_quantity=Decimal("10"),
                actual_quantity=Decimal("10"),
                expected_price=Decimal("100"),
                actual_price=Decimal("100"),
                slippage_bps=Decimal(str(i * 10)),
            )
            for i in range(3)
        ]
        s = FillReconciliationSummary(records=records)
        # avg of 0, 10, 20 = 10
        assert s.avg_slippage_bps == Decimal("10.00")


# ─────────────────────── TestReconcileFills ───────────────────────────────────

class TestReconcileFills:
    def test_exact_match_is_matched(self) -> None:
        svc = _svc()
        exp = _expectation(key="idem-001", price="150.00")
        fill = _fill(broker_order_id="idem-001", price="150.00")
        summary = svc.reconcile_fills([exp], [fill])
        assert summary.records[0].status == ReconciliationStatus.MATCHED

    def test_missing_fill_detected(self) -> None:
        svc = _svc()
        exp = _expectation(key="idem-no-fill")
        summary = svc.reconcile_fills([exp], [])
        assert summary.records[0].status == ReconciliationStatus.MISSING_FILL

    def test_price_drift_above_tolerance(self) -> None:
        # tolerance 50 bps; expected 150.00, actual 151.50 → 100 bps
        svc = _svc(tolerance_bps=50)
        exp = _expectation(key="idem-drift", price="150.00")
        fill = _fill(broker_order_id="idem-drift", price="151.50")
        summary = svc.reconcile_fills([exp], [fill])
        assert summary.records[0].status == ReconciliationStatus.PRICE_DRIFT

    def test_price_within_tolerance_is_matched(self) -> None:
        # tolerance 50 bps; expected 150.00, actual 150.05 → ~3.3 bps
        svc = _svc(tolerance_bps=50)
        exp = _expectation(key="idem-ok", price="150.00")
        fill = _fill(broker_order_id="idem-ok", price="150.05")
        summary = svc.reconcile_fills([exp], [fill])
        assert summary.records[0].status == ReconciliationStatus.MATCHED

    def test_qty_mismatch_detected(self) -> None:
        svc = _svc()
        exp = _expectation(key="idem-qty", qty="10")
        fill = _fill(broker_order_id="idem-qty", qty="9")
        summary = svc.reconcile_fills([exp], [fill])
        assert summary.records[0].status == ReconciliationStatus.QTY_MISMATCH

    def test_empty_expectations_returns_empty_summary(self) -> None:
        svc = _svc()
        summary = svc.reconcile_fills([], [])
        assert summary.total == 0

    def test_multiple_expectations_all_matched(self) -> None:
        svc = _svc()
        exps = [_expectation(key=f"k{i}") for i in range(3)]
        fills = [_fill(broker_order_id=f"k{i}") for i in range(3)]
        summary = svc.reconcile_fills(exps, fills)
        assert summary.matched == 3
        assert summary.discrepancies == 0

    def test_slippage_bps_populated(self) -> None:
        svc = _svc(tolerance_bps=200)
        exp = _expectation(key="idem-slip", price="100.00")
        fill = _fill(broker_order_id="idem-slip", price="100.50")
        summary = svc.reconcile_fills([exp], [fill])
        # 0.50 / 100.00 * 10000 = 50 bps
        assert summary.records[0].slippage_bps == Decimal("50.00")

    def test_negative_slippage_bps_for_buy_below_expected(self) -> None:
        # Got filled cheaper than expected (negative slippage = favourable)
        svc = _svc(tolerance_bps=200)
        exp = _expectation(key="idem-fav", price="100.00")
        fill = _fill(broker_order_id="idem-fav", price="99.50")
        summary = svc.reconcile_fills([exp], [fill])
        assert summary.records[0].slippage_bps < Decimal("0")


# ─────────────────────── TestPnlConsistency ───────────────────────────────────

class TestPnlConsistency:
    def test_consistent_passes(self) -> None:
        svc = _svc()
        # equity = cash + sum(positions)
        assert svc.check_pnl_consistency(
            Decimal("105000"),
            Decimal("90000"),
            [Decimal("10000"), Decimal("5000")],
        )

    def test_within_tolerance_passes(self) -> None:
        svc = _svc()
        assert svc.check_pnl_consistency(
            Decimal("105000.04"),   # 4 cents drift — within 5 cent tolerance
            Decimal("90000"),
            [Decimal("10000"), Decimal("5000")],
        )

    def test_drift_exceeds_tolerance_raises(self) -> None:
        svc = _svc()
        with pytest.raises(ValueError, match="consistency check failed"):
            svc.check_pnl_consistency(
                Decimal("105010"),  # $10 drift
                Decimal("90000"),
                [Decimal("10000"), Decimal("5000")],
            )

    def test_zero_positions_passes(self) -> None:
        svc = _svc()
        assert svc.check_pnl_consistency(Decimal("100000"), Decimal("100000"), [])

    def test_all_zero_passes(self) -> None:
        svc = _svc()
        assert svc.check_pnl_consistency(Decimal("0"), Decimal("0"), [])


# ─────────────────────── TestGenerateDailyReport ──────────────────────────────

class TestGenerateDailyReport:
    def _base_report(
        self,
        svc: ReportingService | None = None,
        orders: list[Order] | None = None,
        reconciliation: FillReconciliationSummary | None = None,
        **kwargs: Any,
    ) -> DailyOperationalReport:
        svc = svc or _svc()
        orders = orders or [_order(status=OrderStatus.FILLED)]
        reconciliation = reconciliation or _simple_reconciliation(n=1)
        return svc.generate_daily_report(
            report_date=_TODAY,
            equity=Decimal("102000"),
            cash=Decimal("92000"),
            gross_exposure=Decimal("10000"),
            position_count=1,
            realized_pnl=Decimal("500"),
            unrealized_pnl=Decimal("200"),
            start_of_day_equity=Decimal("100000"),
            orders=orders,
            reconciliation=reconciliation,
            **kwargs,
        )

    def test_report_date_set(self) -> None:
        report = self._base_report()
        assert report.report_date == _TODAY

    def test_equity_stored(self) -> None:
        report = self._base_report()
        assert report.equity == Decimal("102000")

    def test_daily_return_pct_computed(self) -> None:
        report = self._base_report()
        # (102000 - 100000) / 100000 = 0.02
        assert report.daily_return_pct == Decimal("0.020000")

    def test_orders_submitted_count(self) -> None:
        orders = [
            _order(idempotency_key="k1", status=OrderStatus.FILLED),
            _order(idempotency_key="k2", status=OrderStatus.CANCELLED),
            _order(idempotency_key="k3", status=OrderStatus.REJECTED),
        ]
        report = self._base_report(orders=orders)
        assert report.orders_submitted == 3
        assert report.orders_filled == 1
        assert report.orders_cancelled == 1
        assert report.orders_rejected == 1

    def test_reconciliation_embedded(self) -> None:
        rec = _simple_reconciliation(n=5)
        report = self._base_report(reconciliation=rec)
        assert report.reconciliation.total == 5
        assert report.reconciliation_clean is True

    def test_reconciliation_not_clean_when_discrepancies(self) -> None:
        rec = _simple_reconciliation(n=2, status=ReconciliationStatus.PRICE_DRIFT)
        report = self._base_report(reconciliation=rec)
        assert report.reconciliation_clean is False

    def test_scorecard_grade_stored(self) -> None:
        report = self._base_report(scorecard_grade="B")
        assert report.scorecard_grade == "B"

    def test_benchmark_differentials_stored(self) -> None:
        diffs = {"SPY": Decimal("0.005"), "QQQ": Decimal("-0.002")}
        report = self._base_report(benchmark_differentials=diffs)
        assert report.benchmark_differentials["SPY"] == Decimal("0.005")

    def test_improvement_proposals_stored(self) -> None:
        report = self._base_report(
            improvement_proposals_generated=4,
            improvement_proposals_promoted=1,
        )
        assert report.improvement_proposals_generated == 4
        assert report.improvement_proposals_promoted == 1

    def test_narrative_not_empty(self) -> None:
        report = self._base_report()
        assert len(report.narrative) > 0

    def test_narrative_contains_date(self) -> None:
        report = self._base_report()
        assert str(_TODAY) in report.narrative

    def test_zero_start_equity_returns_zero_return_pct(self) -> None:
        svc = _svc()
        report = svc.generate_daily_report(
            report_date=_TODAY,
            equity=Decimal("100000"),
            cash=Decimal("100000"),
            gross_exposure=Decimal("0"),
            position_count=0,
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            start_of_day_equity=Decimal("0"),
            orders=[],
            reconciliation=_simple_reconciliation(n=0),
        )
        assert report.daily_return_pct == Decimal("0")

    def test_report_timestamp_is_datetime(self) -> None:
        report = self._base_report()
        assert isinstance(report.report_timestamp, dt.datetime)


# ─────────────────────── TestSlippageCalc ─────────────────────────────────────

class TestSlippageCalc:
    def test_zero_slippage(self) -> None:
        assert ReportingService._calc_slippage_bps(
            Decimal("150.00"), Decimal("150.00")
        ) == Decimal("0")

    def test_positive_slippage(self) -> None:
        # filled 1 % higher → 100 bps
        result = ReportingService._calc_slippage_bps(
            Decimal("100.00"), Decimal("101.00")
        )
        assert result == Decimal("100.00")

    def test_negative_slippage_favourable(self) -> None:
        result = ReportingService._calc_slippage_bps(
            Decimal("100.00"), Decimal("99.00")
        )
        assert result == Decimal("-100.00")

    def test_zero_expected_returns_zero(self) -> None:
        assert ReportingService._calc_slippage_bps(
            Decimal("0"), Decimal("150.00")
        ) == Decimal("0")

    def test_small_slippage_computed(self) -> None:
        # 5 bps: 150.075 vs 150.00
        result = ReportingService._calc_slippage_bps(
            Decimal("150.00"), Decimal("150.075")
        )
        assert result == Decimal("5.00")
