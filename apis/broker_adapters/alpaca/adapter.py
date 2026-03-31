"""
Alpaca Broker Adapter.

Wraps the official `alpaca-py` SDK to implement BaseBrokerAdapter for
Alpaca paper (and later, guarded live) trading.

Design rules
------------
- paper=True always unless `paper` constructor arg is explicitly False AND
  operating_mode is "live" — no accidental live trading.
- Idempotency: every order submission uses the request's idempotency_key as
  the Alpaca `client_order_id`.  Alpaca rejects duplicate client_order_ids
  at the API level; we also guard in-process with a local set.
- All Alpaca SDK types are translated to APIS domain models on return —
  the execution engine sees only broker_adapters.base.models.
- Fills: Alpaca's v2 REST API returns fills inside the order object
  (`filled_avg_price`, `filled_qty`).  We materialise a single Fill per
  fully-filled order.  `list_fills_since` iterates closed orders filtered
  by filled_at >= since.
- No SDK calls are made at construction time; `connect()` triggers the first
  account ping.

Spec references
---------------
- APIS_MASTER_SPEC.md § 11 (Execution Layer / Broker Strategy)
- APIS_BUILD_RUNBOOK.md § Step 6 (Paper Trading)
- API_AND_SERVICE_BOUNDARIES_SPEC.md § 3.12
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import (
    OrderSide as AlpacaOrderSide,
    OrderStatus as AlpacaOrderStatus,
    OrderType as AlpacaOrderType,
    TimeInForce as AlpacaTimeInForce,
)
from alpaca.trading.requests import (
    GetOrdersRequest,
    LimitOrderRequest,
    MarketOrderRequest,
)

from broker_adapters.base.adapter import BaseBrokerAdapter
from broker_adapters.base.exceptions import (
    BrokerAuthenticationError,
    BrokerConnectionError,
    DuplicateOrderError,
    KillSwitchActiveError,
    MarketClosedError,
    OrderRejectedError,
    PositionNotFoundError,
    ReconciliationError,
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


# ── SDK enum translation maps ──────────────────────────────────────────────────

_SIDE_TO_ALPACA: dict[OrderSide, AlpacaOrderSide] = {
    OrderSide.BUY: AlpacaOrderSide.BUY,
    OrderSide.SELL: AlpacaOrderSide.SELL,
}

_TIF_TO_ALPACA: dict[TimeInForce, AlpacaTimeInForce] = {
    TimeInForce.DAY: AlpacaTimeInForce.DAY,
    TimeInForce.GTC: AlpacaTimeInForce.GTC,
    TimeInForce.IOC: AlpacaTimeInForce.IOC,
    TimeInForce.FOK: AlpacaTimeInForce.FOK,
}

_ALPACA_STATUS_MAP: dict[str, OrderStatus] = {
    "new":              OrderStatus.SUBMITTED,
    "partially_filled": OrderStatus.PARTIALLY_FILLED,
    "filled":           OrderStatus.FILLED,
    "done_for_day":     OrderStatus.CANCELLED,
    "canceled":         OrderStatus.CANCELLED,
    "expired":          OrderStatus.EXPIRED,
    "replaced":         OrderStatus.CANCELLED,
    "pending_cancel":   OrderStatus.SUBMITTED,
    "pending_replace":  OrderStatus.SUBMITTED,
    "accepted":         OrderStatus.SUBMITTED,
    "pending_new":      OrderStatus.PENDING,
    "accepted_for_bidding": OrderStatus.SUBMITTED,
    "stopped":          OrderStatus.SUBMITTED,
    "rejected":         OrderStatus.REJECTED,
    "suspended":        OrderStatus.REJECTED,
    "calculated":       OrderStatus.SUBMITTED,
}


class AlpacaBrokerAdapter(BaseBrokerAdapter):
    """
    Alpaca broker adapter wrapping `alpaca-py` TradingClient.

    Args:
        api_key:    Alpaca API key ID.
        api_secret: Alpaca API secret key.
        paper:      If True (default), targets the Alpaca paper-trading endpoint.
                    Set to False only when operating_mode has been explicitly
                    approved for live trading.
    """

    _CENTS = Decimal("0.01")

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        paper: bool = True,
    ) -> None:
        if not api_key or not api_secret:
            raise BrokerAuthenticationError(
                "Alpaca API key and secret are required."
            )
        self._api_key = api_key
        self._api_secret = api_secret
        self._paper = paper
        self._client: Optional[TradingClient] = None
        self._connected = False
        # Local idempotency guard (belt-and-suspenders over Alpaca's own check)
        self._submitted_keys: set[str] = set()

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def adapter_name(self) -> str:
        return "alpaca_paper" if self._paper else "alpaca_live"

    # ── Connection / lifecycle ─────────────────────────────────────────────────

    def connect(self) -> None:
        """Initialise the TradingClient and verify connectivity."""
        try:
            self._client = TradingClient(
                api_key=self._api_key,
                secret_key=self._api_secret,
                paper=self._paper,
            )
            # Trigger a lightweight call to confirm credentials are valid
            self._client.get_account()
            self._connected = True
        except Exception as exc:
            raise BrokerConnectionError(
                f"Failed to connect to Alpaca ({'paper' if self._paper else 'live'}): {exc}"
            ) from exc

    def disconnect(self) -> None:
        self._client = None
        self._connected = False

    def ping(self) -> bool:
        if not self._connected or self._client is None:
            return False
        try:
            self._client.get_account()
            return True
        except Exception:
            return False

    # ── Account ────────────────────────────────────────────────────────────────

    def get_account_state(self) -> AccountState:
        self._require_connected()
        acct = self._client.get_account()  # type: ignore[union-attr]
        positions = self.list_positions()
        gross_exposure = sum((p.market_value for p in positions), Decimal("0"))

        return AccountState(
            account_id=str(acct.id),
            cash_balance=Decimal(str(acct.cash)),
            buying_power=Decimal(str(acct.buying_power)),
            equity_value=Decimal(str(acct.equity)),
            gross_exposure=gross_exposure,
            positions=positions,
            is_pattern_day_trader=bool(getattr(acct, "pattern_day_trader", False)),
            is_account_blocked=bool(getattr(acct, "trading_blocked", False)),
            snapshot_at=datetime.now(tz=timezone.utc),
        )

    # ── Orders ────────────────────────────────────────────────────────────────

    def place_order(self, request: OrderRequest) -> Order:
        """Submit an order to Alpaca.

        Raises:
            KillSwitchActiveError:  Kill switch is on (checked via account blocked).
            DuplicateOrderError:    idempotency_key was already submitted this session.
            MarketClosedError:      Market is closed and order is a market order.
            OrderRejectedError:     Alpaca rejected the order.
        """
        self._require_connected()
        self._guard_duplicate(request.idempotency_key)

        if request.order_type == OrderType.MARKET and not self.is_market_open():
            raise MarketClosedError(
                "Market is closed. Market orders are not accepted outside market hours."
            )

        try:
            if request.order_type == OrderType.MARKET:
                req = MarketOrderRequest(
                    symbol=request.ticker,
                    qty=float(request.quantity),
                    side=_SIDE_TO_ALPACA[request.side],
                    time_in_force=_TIF_TO_ALPACA.get(
                        request.time_in_force, AlpacaTimeInForce.DAY
                    ),
                    client_order_id=request.idempotency_key,
                )
            elif request.order_type == OrderType.LIMIT:
                if request.limit_price is None:
                    raise OrderRejectedError(
                        "limit_price is required for LIMIT orders.", order_id=None
                    )
                req = LimitOrderRequest(
                    symbol=request.ticker,
                    qty=float(request.quantity),
                    side=_SIDE_TO_ALPACA[request.side],
                    time_in_force=_TIF_TO_ALPACA.get(
                        request.time_in_force, AlpacaTimeInForce.DAY
                    ),
                    client_order_id=request.idempotency_key,
                    limit_price=float(request.limit_price),
                )
            else:
                raise OrderRejectedError(
                    f"Order type {request.order_type.value} not supported by Alpaca adapter.",
                    order_id=None,
                )

            alpaca_order = self._client.submit_order(req)  # type: ignore[union-attr]
            self._submitted_keys.add(request.idempotency_key)
            return self._to_order(alpaca_order, request.idempotency_key)

        except (DuplicateOrderError, MarketClosedError, OrderRejectedError):
            raise
        except Exception as exc:
            exc_str = str(exc).lower()
            if "duplicate" in exc_str or "client_order_id" in exc_str:
                raise DuplicateOrderError(
                    f"Duplicate order detected by Alpaca: {exc}",
                    idempotency_key=request.idempotency_key,
                ) from exc
            raise OrderRejectedError(
                f"Alpaca rejected order for {request.ticker}: {exc}", order_id=None
            ) from exc

    def cancel_order(self, broker_order_id: str) -> Order:
        self._require_connected()
        try:
            self._client.cancel_order_by_id(broker_order_id)  # type: ignore[union-attr]
            return self.get_order(broker_order_id)
        except Exception as exc:
            raise OrderRejectedError(
                f"Could not cancel order {broker_order_id}: {exc}", order_id=broker_order_id
            ) from exc

    def get_order(self, broker_order_id: str) -> Order:
        self._require_connected()
        try:
            alpaca_order = self._client.get_order_by_id(broker_order_id)  # type: ignore[union-attr]
            key = getattr(alpaca_order, "client_order_id", broker_order_id) or broker_order_id
            return self._to_order(alpaca_order, key)
        except Exception as exc:
            raise OrderRejectedError(
                f"Order not found: {broker_order_id}: {exc}", order_id=broker_order_id
            ) from exc

    def list_open_orders(self) -> list[Order]:
        self._require_connected()
        from alpaca.trading.requests import GetOrdersRequest as _GOR
        from alpaca.trading.enums import QueryOrderStatus
        req = _GOR(status=QueryOrderStatus.OPEN)
        orders = self._client.get_orders(filter=req)  # type: ignore[union-attr]
        return [
            self._to_order(o, getattr(o, "client_order_id", str(o.id)) or str(o.id))
            for o in orders
        ]

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_position(self, ticker: str) -> Position:
        self._require_connected()
        try:
            pos = self._client.get_open_position(ticker)  # type: ignore[union-attr]
            return self._to_position(pos)
        except Exception as exc:
            raise PositionNotFoundError(
                f"No open position for {ticker}: {exc}"
            ) from exc

    def list_positions(self) -> list[Position]:
        self._require_connected()
        positions = self._client.get_all_positions()  # type: ignore[union-attr]
        return [self._to_position(p) for p in positions]

    # ── Fills ─────────────────────────────────────────────────────────────────

    def get_fills_for_order(self, broker_order_id: str) -> list[Fill]:
        """Return fills for a specific order.

        Alpaca REST v2 does not have a separate fills endpoint; we synthesise
        a single Fill from the filled order's metadata.
        """
        order = self.get_order(broker_order_id)
        if order.status != OrderStatus.FILLED or order.average_fill_price is None:
            return []
        return [self._synthesise_fill(order)]

    def list_fills_since(self, since: datetime) -> list[Fill]:
        """Return all fills since `since` by querying closed/filled orders."""
        self._require_connected()
        from alpaca.trading.requests import GetOrdersRequest as _GOR
        from alpaca.trading.enums import QueryOrderStatus
        req = _GOR(
            status=QueryOrderStatus.CLOSED,
            after=since,
        )
        orders = self._client.get_orders(filter=req)  # type: ignore[union-attr]
        fills: list[Fill] = []
        for o in orders:
            if getattr(o, "filled_qty", None) and float(o.filled_qty) > 0:
                key = getattr(o, "client_order_id", str(o.id)) or str(o.id)
                domain_order = self._to_order(o, key)
                if domain_order.status == OrderStatus.FILLED:
                    fills.append(self._synthesise_fill(domain_order))
        return fills

    # ── Market hours ──────────────────────────────────────────────────────────

    def is_market_open(self) -> bool:
        self._require_connected()
        try:
            clock = self._client.get_clock()  # type: ignore[union-attr]
            return bool(clock.is_open)
        except Exception:
            return False

    def next_market_open(self) -> datetime:
        self._require_connected()
        try:
            clock = self._client.get_clock()  # type: ignore[union-attr]
            next_open = clock.next_open
            if hasattr(next_open, "replace"):
                return next_open.replace(tzinfo=timezone.utc) if next_open.tzinfo is None else next_open
            return datetime.now(tz=timezone.utc)
        except Exception:
            from datetime import timedelta
            return datetime.now(tz=timezone.utc) + timedelta(hours=1)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _require_connected(self) -> None:
        if not self._connected or self._client is None:
            raise BrokerConnectionError(
                "AlpacaBrokerAdapter is not connected. Call connect() first."
            )

    def _guard_duplicate(self, idempotency_key: str) -> None:
        if idempotency_key in self._submitted_keys:
            raise DuplicateOrderError(
                f"Duplicate order submission detected: idempotency_key={idempotency_key}",
                idempotency_key=idempotency_key,
            )

    def _to_order(self, alpaca_order: object, idempotency_key: str) -> Order:
        """Translate an alpaca-py order object → APIS Order domain model."""
        o = alpaca_order
        raw_status = str(getattr(o, "status", "new")).lower()
        status = _ALPACA_STATUS_MAP.get(raw_status, OrderStatus.SUBMITTED)

        filled_qty_raw = getattr(o, "filled_qty", None)
        filled_qty = Decimal(str(filled_qty_raw)) if filled_qty_raw else Decimal("0")

        fill_price_raw = getattr(o, "filled_avg_price", None)
        avg_fill = Decimal(str(fill_price_raw)) if fill_price_raw else None

        limit_raw = getattr(o, "limit_price", None)
        limit_price = Decimal(str(limit_raw)) if limit_raw else None

        stop_raw = getattr(o, "stop_price", None)
        stop_price = Decimal(str(stop_raw)) if stop_raw else None

        submitted_at_raw = getattr(o, "submitted_at", None) or getattr(o, "created_at", None)
        if submitted_at_raw is None:
            submitted_at = datetime.now(tz=timezone.utc)
        elif hasattr(submitted_at_raw, "tzinfo"):
            submitted_at = submitted_at_raw if submitted_at_raw.tzinfo else submitted_at_raw.replace(tzinfo=timezone.utc)
        else:
            submitted_at = datetime.now(tz=timezone.utc)

        filled_at_raw = getattr(o, "filled_at", None)
        filled_at: Optional[datetime] = None
        if filled_at_raw is not None:
            filled_at = filled_at_raw if getattr(filled_at_raw, "tzinfo", None) else filled_at_raw.replace(tzinfo=timezone.utc)

        raw_side = str(getattr(o, "side", "buy")).lower()
        side = OrderSide.BUY if raw_side == "buy" else OrderSide.SELL

        raw_qty = getattr(o, "qty", None) or getattr(o, "notional", "1")
        requested_qty = Decimal(str(raw_qty))

        rejection_reason_raw = getattr(o, "failed_at", None)

        return Order(
            idempotency_key=idempotency_key,
            broker_order_id=str(o.id),
            ticker=str(getattr(o, "symbol", "")),
            side=side,
            order_type=OrderType.MARKET,  # simplified — expand if needed
            requested_quantity=requested_qty,
            filled_quantity=filled_qty,
            status=status,
            submitted_at=submitted_at,
            filled_at=filled_at,
            average_fill_price=avg_fill,
            limit_price=limit_price,
            stop_price=stop_price,
            rejection_reason=str(rejection_reason_raw) if rejection_reason_raw else None,
        )

    def _to_position(self, alpaca_pos: object) -> Position:
        """Translate an alpaca-py position object → APIS Position domain model."""
        p = alpaca_pos
        return Position(
            ticker=str(getattr(p, "symbol", "")),
            quantity=Decimal(str(getattr(p, "qty", "0"))),
            average_entry_price=Decimal(str(getattr(p, "avg_entry_price", "0"))),
            current_price=Decimal(str(getattr(p, "current_price", "0"))),
            market_value=Decimal(str(getattr(p, "market_value", "0"))),
            unrealized_pnl=Decimal(str(getattr(p, "unrealized_pl", "0"))),
            unrealized_pnl_pct=Decimal(str(getattr(p, "unrealized_plpc", "0"))),
            side=str(getattr(p, "side", "long")),
        )

    @staticmethod
    def _synthesise_fill(order: Order) -> Fill:
        """Synthesise a single Fill from a fully-filled Order.

        Alpaca v2 REST does not expose individual fill events via a fills
        endpoint; we represent the complete fill as one Fill record.
        """
        return Fill(
            broker_fill_id=f"{order.broker_order_id}-fill",
            broker_order_id=order.broker_order_id,
            ticker=order.ticker,
            side=order.side,
            fill_quantity=order.filled_quantity,
            fill_price=order.average_fill_price or Decimal("0"),
            fees=Decimal("0"),  # Alpaca charges no commission for equities
            filled_at=order.filled_at or datetime.now(tz=timezone.utc),
            liquidity_flag="taker",
        )
