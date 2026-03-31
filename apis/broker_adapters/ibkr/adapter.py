"""
IBKR Broker Adapter — Concrete ib_insync implementation.

Wraps ``ib_insync`` to implement ``BaseBrokerAdapter`` for Interactive
Brokers TWS / IB Gateway.

Prerequisites
-------------
- ``ib_insync`` must be installed (``pip install ib_insync``).
- TWS Desktop or IB Gateway must be running and accepting socket connections.
- Paper-trading port defaults: TWS=7497, Gateway=4002
- "Enable ActiveX and Socket Clients" checked in TWS API settings.

Safety
------
When ``paper=True`` (default) the constructor rejects live-trading ports
(7496 / 4001) to prevent accidental live orders during development.

Spec references
---------------
- APIS_MASTER_SPEC.md § 11
- API_AND_SERVICE_BOUNDARIES_SPEC.md § 3.12
"""
from __future__ import annotations

import datetime as dt
from datetime import timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

try:
    from ib_insync import IB, Fill as IbFill, Position as IbPosition
    from ib_insync import MarketOrder, LimitOrder, StopOrder, StopLimitOrder
    from ib_insync import Stock
    from ib_insync import Trade as IbTrade
    _IB_AVAILABLE = True
except ImportError:  # pragma: no cover
    _IB_AVAILABLE = False

from broker_adapters.base.adapter import BaseBrokerAdapter
from broker_adapters.base.exceptions import (
    BrokerConnectionError,
    DuplicateOrderError,
    OrderRejectedError,
    PositionNotFoundError,
)
from broker_adapters.base.models import (
    AccountState,
    Fill,
    Order,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    TimeInForce,
)

_NOT_INSTALLED = (
    "ib_insync is not installed. Run: pip install ib_insync"
)


def _d(value: object) -> Decimal:
    """Convert value to Decimal; returns 0 on failure."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


class IBKRBrokerAdapter(BaseBrokerAdapter):
    """
    Concrete ib_insync implementation of BaseBrokerAdapter.

    Supports paper-trading TWS (port 7497) and IB Gateway (port 4002).
    All methods translate between APIS domain models and ib_insync objects.

    Args:
        host:      IP / hostname of TWS / Gateway. Default ``"127.0.0.1"``.
        port:      TWS API port. Paper TWS=7497, Paper Gateway=4002,
                   Live TWS=7496, Live Gateway=4001. Default ``7497``.
        client_id: Unique integer client ID for this session. Default ``1``.
        paper:     Enforce paper-mode safety check. Default ``True``.
    """

    _PAPER_PORTS: frozenset[int] = frozenset({7497, 4002})
    _LIVE_PORTS:  frozenset[int] = frozenset({7496, 4001})

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7497,
        client_id: int = 1,
        paper: bool = True,
    ) -> None:
        self._host = host
        self._port = port
        self._client_id = client_id
        self._paper = paper
        self._ib: Optional[IB] = None  # type: ignore[type-arg]
        # Idempotency tracking: idempotency_key → broker_order_id
        self._submitted: dict[str, str] = {}

        if paper and port in self._LIVE_PORTS:
            raise ValueError(
                f"Refusing to connect to known live-trading port {port} with "
                f"paper=True. Use port {sorted(self._PAPER_PORTS)} or set paper=False."
            )

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def adapter_name(self) -> str:
        return "ibkr"

    # ── Connection / lifecycle ─────────────────────────────────────────────────

    def connect(self) -> None:
        """Connect to TWS / IB Gateway via ib_insync."""
        if not _IB_AVAILABLE:
            raise BrokerConnectionError(_NOT_INSTALLED)
        try:
            self._ib = IB()
            self._ib.connect(self._host, self._port, clientId=self._client_id)
        except Exception as exc:
            raise BrokerConnectionError(
                f"Failed to connect to TWS at {self._host}:{self._port}: {exc}"
            ) from exc

    def disconnect(self) -> None:
        """Disconnect from TWS / IB Gateway."""
        if self._ib and self._ib.isConnected():
            self._ib.disconnect()
        self._ib = None

    def ping(self) -> bool:
        """Return True if the TWS connection is alive."""
        if self._ib is None:
            return False
        return bool(self._ib.isConnected())

    # ── Account ────────────────────────────────────────────────────────────────

    def get_account_state(self) -> AccountState:
        """Return current account state (cash, equity, positions)."""
        self._require_connection()
        summary = self._ib.accountSummary()
        cash = Decimal("0")
        equity = Decimal("0")
        buying_power = Decimal("0")
        for item in summary:
            if item.tag == "CashBalance" and item.currency == "BASE":
                cash = _d(item.value)
            elif item.tag == "NetLiquidation" and item.currency == "BASE":
                equity = _d(item.value)
            elif item.tag == "BuyingPower" and item.currency == "BASE":
                buying_power = _d(item.value)
        positions = self.list_positions()
        gross_exposure = sum((p.market_value for p in positions), Decimal("0"))
        return AccountState(
            account_id=f"ibkr_{self._client_id}",
            cash_balance=cash,
            buying_power=buying_power or cash,
            equity_value=equity,
            gross_exposure=gross_exposure,
            positions=positions,
            snapshot_at=dt.datetime.now(timezone.utc),
        )

    # ── Orders ────────────────────────────────────────────────────────────────

    def place_order(self, request: OrderRequest) -> Order:
        """Submit a market or limit order via TWS API."""
        self._require_connection()
        if request.idempotency_key in self._submitted:
            raise DuplicateOrderError(
                f"Order with idempotency_key {request.idempotency_key!r} "
                "was already submitted.",
                request.idempotency_key,
            )
        contract = Stock(request.ticker, "SMART", "USD")
        side_str = request.side.value.upper()
        qty = float(request.quantity)

        if request.order_type == OrderType.MARKET:
            ib_order = MarketOrder(side_str, qty)
        elif request.order_type == OrderType.LIMIT:
            lp = float(request.limit_price or 0)
            ib_order = LimitOrder(side_str, qty, lp)
        elif request.order_type == OrderType.STOP:
            sp = float(request.stop_price or 0)
            ib_order = StopOrder(side_str, qty, sp)
        elif request.order_type == OrderType.STOP_LIMIT:
            lp = float(request.limit_price or 0)
            sp = float(request.stop_price or 0)
            ib_order = StopLimitOrder(side_str, qty, lp, sp)
        else:
            ib_order = MarketOrder(side_str, qty)

        # Attach idempotency key as orderRef for duplicate detection
        ib_order.orderRef = request.idempotency_key

        trade: IbTrade = self._ib.placeOrder(contract, ib_order)
        self._ib.sleep(0)  # allow EClient callbacks to process

        broker_order_id = str(trade.order.orderId)
        self._submitted[request.idempotency_key] = broker_order_id
        return self._to_order(trade, request.idempotency_key)

    def cancel_order(self, broker_order_id: str) -> Order:
        """Cancel a pending order."""
        self._require_connection()
        trade = self._find_trade(broker_order_id)
        self._ib.cancelOrder(trade.order)
        self._ib.sleep(0)
        return self._to_order(trade, str(trade.order.orderRef))

    def get_order(self, broker_order_id: str) -> Order:
        """Retrieve current state of a submitted order."""
        self._require_connection()
        trade = self._find_trade(broker_order_id)
        return self._to_order(trade, str(trade.order.orderRef))

    def list_open_orders(self) -> list[Order]:
        """Return all open (unfilled, non-cancelled) orders."""
        self._require_connection()
        trades = self._ib.openTrades()
        return [self._to_order(t, str(t.order.orderRef)) for t in trades]

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_position(self, ticker: str) -> Position:
        """Return the current position for a ticker."""
        self._require_connection()
        positions = self._ib.positions()
        match = next(
            (p for p in positions if p.contract.symbol == ticker.upper()), None
        )
        if match is None:
            raise PositionNotFoundError(
                f"No open position for {ticker!r}"
            )
        return self._to_position(match)

    def list_positions(self) -> list[Position]:
        """Return all current open positions."""
        self._require_connection()
        return [self._to_position(p) for p in self._ib.positions()]

    # ── Fills ─────────────────────────────────────────────────────────────────

    def get_fills_for_order(self, broker_order_id: str) -> list[Fill]:
        """Return fills associated with a specific order."""
        self._require_connection()
        fills = self._ib.fills()
        return [
            self._to_fill(f) for f in fills
            if str(f.execution.orderId) == broker_order_id
        ]

    def list_fills_since(self, since: dt.datetime) -> list[Fill]:
        """Return all fills since *since*, for reconciliation."""
        self._require_connection()
        since_utc = since.astimezone(timezone.utc) if since.tzinfo else since
        fills = self._ib.fills()
        result: list[Fill] = []
        for f in fills:
            exec_time = f.execution.time
            if exec_time.tzinfo:
                exec_time = exec_time.astimezone(timezone.utc)
            if exec_time >= since_utc:
                result.append(self._to_fill(f))
        return result

    # ── Market hours ──────────────────────────────────────────────────────────

    def is_market_open(self) -> bool:
        """Return True if NYSE primary session is currently open (ET 09:30–16:00)."""
        import pytz
        et = pytz.timezone("US/Eastern")
        now_et = dt.datetime.now(et)
        if now_et.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        return market_open <= now_et < market_close

    def next_market_open(self) -> dt.datetime:
        """Return UTC datetime of the next NYSE market open (09:30 ET)."""
        import pytz
        et = pytz.timezone("US/Eastern")
        now_et = dt.datetime.now(et)
        candidate = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        # If we've already passed today's open, move to tomorrow
        if now_et >= candidate:
            candidate += dt.timedelta(days=1)
        # Skip weekends
        while candidate.weekday() >= 5:
            candidate += dt.timedelta(days=1)
        return candidate.astimezone(timezone.utc)

    # ── Private helpers ────────────────────────────────────────────────────────

    def _require_connection(self) -> None:
        """Raise BrokerConnectionError if not connected."""
        if self._ib is None or not self._ib.isConnected():
            raise BrokerConnectionError(
                "IBKRBrokerAdapter is not connected. Call connect() first."
            )

    def _find_trade(self, broker_order_id: str) -> "IbTrade":
        """Find an ib_insync Trade by broker_order_id string."""
        trades = self._ib.trades()
        match = next(
            (t for t in trades if str(t.order.orderId) == broker_order_id), None
        )
        if match is None:
            raise OrderRejectedError(
                f"No trade found for broker_order_id={broker_order_id!r}",
                order_id=broker_order_id,
            )
        return match

    # ── Model translators ──────────────────────────────────────────────────────

    def _to_order(self, trade: "IbTrade", idempotency_key: str) -> Order:
        """Translate an ib_insync Trade → APIS Order."""
        order_status_map = {
            "PreSubmitted": OrderStatus.PENDING,
            "Submitted": OrderStatus.SUBMITTED,
            "Filled": OrderStatus.FILLED,
            "Cancelled": OrderStatus.CANCELLED,
            "Inactive": OrderStatus.REJECTED,
            "PartiallyFilled": OrderStatus.PARTIALLY_FILLED,
        }
        ib_status = trade.orderStatus.status
        status = order_status_map.get(ib_status, OrderStatus.PENDING)

        side = (
            OrderSide.BUY
            if trade.order.action.upper() == "BUY"
            else OrderSide.SELL
        )
        order_type_map = {
            "MKT": OrderType.MARKET,
            "LMT": OrderType.LIMIT,
            "STP": OrderType.STOP,
            "STP LMT": OrderType.STOP_LIMIT,
        }
        order_type = order_type_map.get(
            trade.order.orderType, OrderType.MARKET
        )

        filled_at: Optional[dt.datetime] = None
        avg_fill_price: Optional[Decimal] = None
        if trade.orderStatus.avgFillPrice:
            avg_fill_price = _d(trade.orderStatus.avgFillPrice)
        if status == OrderStatus.FILLED and trade.fills:
            last_fill_time = trade.fills[-1].execution.time
            filled_at = (
                last_fill_time.astimezone(timezone.utc)
                if last_fill_time.tzinfo
                else last_fill_time.replace(tzinfo=timezone.utc)
            )

        return Order(
            idempotency_key=idempotency_key,
            broker_order_id=str(trade.order.orderId),
            ticker=trade.contract.symbol,
            side=side,
            order_type=order_type,
            requested_quantity=_d(trade.order.totalQuantity),
            filled_quantity=_d(trade.orderStatus.filled),
            status=status,
            submitted_at=dt.datetime.now(timezone.utc),
            filled_at=filled_at,
            average_fill_price=avg_fill_price,
        )

    def _to_position(self, pos: "IbPosition") -> Position:
        """Translate an ib_insync Position → APIS Position."""
        from broker_adapters.base.models import Position as ApisPosition
        avg_cost = _d(pos.avgCost)
        qty = _d(pos.position)
        market_val = qty * avg_cost  # approximation without live price
        unrealized_pnl_pct = (
            Decimal("0")
            if avg_cost == Decimal("0")
            else (market_val - qty * avg_cost) / (qty * avg_cost) * Decimal("100")
        )
        return ApisPosition(
            ticker=pos.contract.symbol,
            quantity=qty,
            average_entry_price=avg_cost,
            current_price=avg_cost,  # approximation; live price requires market data
            market_value=market_val,
            unrealized_pnl=Decimal("0"),
            unrealized_pnl_pct=Decimal("0"),
        )

    def _to_fill(self, fill: "IbFill") -> Fill:
        """Translate an ib_insync Fill → APIS Fill."""
        exec_time = fill.execution.time
        if exec_time.tzinfo:
            exec_time = exec_time.astimezone(timezone.utc)
        else:
            exec_time = exec_time.replace(tzinfo=timezone.utc)
        side = (
            OrderSide.BUY
            if fill.execution.side.upper() in ("BOT", "BUY")
            else OrderSide.SELL
        )
        commission = (
            _d(fill.commissionReport.commission)
            if fill.commissionReport and fill.commissionReport.commission
            else Decimal("0")
        )
        return Fill(
            broker_fill_id=str(fill.execution.execId),
            broker_order_id=str(fill.execution.orderId),
            ticker=fill.contract.symbol,
            side=side,
            fill_quantity=_d(fill.execution.shares),
            fill_price=_d(fill.execution.price),
            fees=commission,
            filled_at=exec_time,
        )

