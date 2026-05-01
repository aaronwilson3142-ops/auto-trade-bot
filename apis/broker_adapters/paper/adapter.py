"""
Paper Broker Adapter.

A fully in-memory paper trading implementation of BaseBrokerAdapter.

This adapter:
- Simulates order placement, fills, and account state with no real broker calls
- Supports configurable starting cash, slippage model, and fill latency
- Enforces all the same structural invariants as real adapters
  (idempotency, kill switch, duplicate prevention)
- Uses Decimal arithmetic throughout to avoid float rounding errors
- Is the mandatory first broker for all APIS testing and paper trading

Spec reference:
- APIS_MASTER_SPEC.md § 11 (Execution Layer)
- APIS_BUILD_RUNBOOK.md § 4 Step 1 (paper broker adapter)
- API_AND_SERVICE_BOUNDARIES_SPEC.md § 3.12
"""
from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from broker_adapters.base.adapter import BaseBrokerAdapter
from broker_adapters.base.exceptions import (
    DuplicateOrderError,
    InsufficientFundsError,
    KillSwitchActiveError,
    MarketClosedError,
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
)


class PaperBrokerAdapter(BaseBrokerAdapter):
    """
    In-memory paper broker with simulated execution.

    Thread-safety note: this implementation is not thread-safe.
    For concurrent use, callers must coordinate access externally.

    Args:
        starting_cash: Initial cash balance in USD.
        slippage_bps: Bid/ask slippage in basis points applied to market orders.
        fill_immediately: If True, market orders fill at placement with slippage.
                          Limit orders fill if the limit price >= current price (buy)
                          or <= current price (sell).
        market_open: Override market hours for testing. If None, uses UTC business-hours check.
    """

    _CENTS = Decimal("0.01")

    def __init__(
        self,
        starting_cash: Decimal = Decimal("100000.00"),
        slippage_bps: int = 5,
        fill_immediately: bool = True,
        market_open: bool | None = None,
    ) -> None:
        self._cash: Decimal = starting_cash
        self._starting_cash: Decimal = starting_cash
        self._slippage_bps: int = slippage_bps
        self._fill_immediately: bool = fill_immediately
        self._market_open_override: bool | None = market_open
        self._kill_switch: bool = False
        self._connected: bool = False

        # Phase 70: serialise all order placement so concurrent threads
        # cannot race past the InsufficientFundsError check.
        self._order_lock = threading.Lock()

        # State maps
        self._orders: dict[str, Order] = {}               # broker_order_id -> Order
        self._idempotency_keys: set[str] = set()           # guard against duplicates
        self._fills: dict[str, list[Fill]] = {}            # broker_order_id -> [Fill]
        self._positions: dict[str, _InternalPosition] = {} # ticker -> internal position
        self._price_overrides: dict[str, Decimal] = {}     # ticker -> price for testing

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def adapter_name(self) -> str:
        return "paper"

    # ── Public test helpers ────────────────────────────────────────────────────

    def set_price(self, ticker: str, price: Decimal) -> None:
        """
        Inject a price for a ticker (for testing only).

        In paper mode, prices are not fetched from a real feed.
        Tests and callers must inject prices via this method.
        """
        if price <= Decimal("0"):
            raise ValueError(f"Price must be positive, got {price}")
        self._price_overrides[ticker] = price

    def activate_kill_switch(self) -> None:
        """Activate the kill switch — no more orders accepted."""
        self._kill_switch = True

    def deactivate_kill_switch(self) -> None:
        """Deactivate the kill switch."""
        self._kill_switch = False

    # ── Phase 72: broker health drift check interface ──────────────────────────

    @property
    def positions_by_ticker(self) -> dict[str, Decimal]:
        """Return {ticker: quantity} for all open positions.

        Used by ``services.broker_adapter.health.check_broker_health`` to
        compare broker state against DB positions and detect drift.
        """
        return {
            ticker: internal.quantity
            for ticker, internal in self._positions.items()
            if internal.quantity > Decimal("0")
        }

    # ── Connection / lifecycle ─────────────────────────────────────────────────

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def ping(self) -> bool:
        return self._connected

    # ── Account ────────────────────────────────────────────────────────────────

    def get_account_state(self) -> AccountState:
        positions = self.list_positions()
        gross_exposure = sum((p.market_value for p in positions), Decimal("0"))
        equity = self._cash + gross_exposure

        return AccountState(
            account_id="paper-account-001",
            cash_balance=self._cash,
            buying_power=self._cash,
            equity_value=equity,
            gross_exposure=gross_exposure,
            positions=positions,
            is_pattern_day_trader=False,
            is_account_blocked=self._kill_switch,
            snapshot_at=datetime.now(tz=UTC),
        )

    # ── Orders ────────────────────────────────────────────────────────────────

    def place_order(self, request: OrderRequest) -> Order:
        """
        Place a paper order.

        Phase 70: the entire order path (check → fill → cash update) is
        serialised under ``_order_lock`` so that concurrent threads cannot
        race past InsufficientFundsError.

        Raises:
            KillSwitchActiveError: If kill switch is on.
            DuplicateOrderError: If idempotency_key was already submitted.
            InsufficientFundsError: If cash is insufficient for a buy.
            MarketClosedError: If market is closed and order type is market.
            OrderRejectedError: If no price is available for the ticker.
        """
        with self._order_lock:
            self._guard_kill_switch()
            self._guard_duplicate(request.idempotency_key)

            price = self._resolve_price(request.ticker, request.order_type)
            if price is None:
                raise OrderRejectedError(
                    f"No price available for {request.ticker}. "
                    "Call set_price() before placing orders in paper mode.",
                    order_id=None,
                )

            if request.order_type == OrderType.MARKET and not self.is_market_open():
                raise MarketClosedError(
                    "Market is closed. Market orders are not accepted outside market hours."
                )

            fill_price = self._apply_slippage(price, request.side, request.order_type)

            if request.side == OrderSide.BUY:
                cost = (fill_price * request.quantity).quantize(self._CENTS, ROUND_HALF_UP)
                if cost > self._cash:
                    raise InsufficientFundsError(
                        f"Insufficient cash: need {cost}, have {self._cash}"
                    )

            broker_order_id = str(uuid.uuid4())
            now = datetime.now(tz=UTC)

            order = Order(
                idempotency_key=request.idempotency_key,
                broker_order_id=broker_order_id,
                ticker=request.ticker,
                side=request.side,
                order_type=request.order_type,
                requested_quantity=request.quantity,
                filled_quantity=Decimal("0"),
                status=OrderStatus.SUBMITTED,
                submitted_at=now,
                limit_price=request.limit_price,
                stop_price=request.stop_price,
            )

            self._orders[broker_order_id] = order
            self._idempotency_keys.add(request.idempotency_key)

            if self._fill_immediately:
                order = self._execute_fill(order, fill_price, now)

            return order

    def cancel_order(self, broker_order_id: str) -> Order:
        order = self._get_order_or_raise(broker_order_id)
        if order.status in (OrderStatus.FILLED, OrderStatus.CANCELLED):
            return order
        order.status = OrderStatus.CANCELLED
        self._orders[broker_order_id] = order
        return order

    def get_order(self, broker_order_id: str) -> Order:
        return self._get_order_or_raise(broker_order_id)

    def list_open_orders(self) -> list[Order]:
        return [
            o
            for o in self._orders.values()
            if o.status in (OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED)
        ]

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_position(self, ticker: str) -> Position:
        internal = self._positions.get(ticker)
        if internal is None or internal.quantity == Decimal("0"):
            raise PositionNotFoundError(f"No open position for {ticker}")
        return self._to_position(ticker, internal)

    def list_positions(self) -> list[Position]:
        return [
            self._to_position(ticker, internal)
            for ticker, internal in self._positions.items()
            if internal.quantity > Decimal("0")
        ]

    # ── Fills ─────────────────────────────────────────────────────────────────

    def get_fills_for_order(self, broker_order_id: str) -> list[Fill]:
        return self._fills.get(broker_order_id, [])

    def list_fills_since(self, since: datetime) -> list[Fill]:
        return [
            fill
            for fills in self._fills.values()
            for fill in fills
            if fill.filled_at >= since
        ]

    # ── Market hours ──────────────────────────────────────────────────────────

    def is_market_open(self) -> bool:
        if self._market_open_override is not None:
            return self._market_open_override
        # Default: treat market as open Monday–Friday 09:30–16:00 ET
        # This is a simplified approximation for paper testing.
        # Production should check an authoritative calendar.
        now = datetime.now(tz=UTC)
        weekday = now.weekday()
        if weekday >= 5:  # Saturday=5, Sunday=6
            return False
        # Rough UTC approximation: NYSE open 13:30–20:00 UTC (ET is UTC-5 no DST, UTC-4 DST)
        hour = now.hour
        minute = now.minute
        time_minutes = hour * 60 + minute
        return 810 <= time_minutes < 1200  # 13:30–20:00 UTC

    def next_market_open(self) -> datetime:
        # Simplified: return next Monday 13:30 UTC or today's open if before open
        from datetime import timedelta

        now = datetime.now(tz=UTC)
        today_open = now.replace(hour=13, minute=30, second=0, microsecond=0)
        if now.weekday() < 5 and now < today_open:
            return today_open
        days_ahead = (7 - now.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 1  # next Monday
        return (now + timedelta(days=days_ahead)).replace(
            hour=13, minute=30, second=0, microsecond=0
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _guard_kill_switch(self) -> None:
        if self._kill_switch:
            raise KillSwitchActiveError("Kill switch is active. No orders accepted.")

    def _guard_duplicate(self, idempotency_key: str) -> None:
        if idempotency_key in self._idempotency_keys:
            raise DuplicateOrderError(
                f"Duplicate order submission detected: idempotency_key={idempotency_key}",
                idempotency_key=idempotency_key,
            )

    def _resolve_price(
        self, ticker: str, order_type: OrderType
    ) -> Decimal | None:
        return self._price_overrides.get(ticker)

    def _apply_slippage(
        self, price: Decimal, side: OrderSide, order_type: OrderType
    ) -> Decimal:
        """Apply slippage for market orders only; limit orders fill at limit price."""
        if order_type != OrderType.MARKET:
            return price
        slippage_factor = Decimal(self._slippage_bps) / Decimal("10000")
        if side == OrderSide.BUY:
            return (price * (1 + slippage_factor)).quantize(self._CENTS, ROUND_HALF_UP)
        else:
            return (price * (1 - slippage_factor)).quantize(self._CENTS, ROUND_HALF_UP)

    def _execute_fill(self, order: Order, fill_price: Decimal, now: datetime) -> Order:
        """Immediately fill an order and update cash + position state."""
        fill_id = str(uuid.uuid4())
        fill_qty = order.requested_quantity

        fill = Fill(
            broker_fill_id=fill_id,
            broker_order_id=order.broker_order_id,
            ticker=order.ticker,
            side=order.side,
            fill_quantity=fill_qty,
            fill_price=fill_price,
            fees=Decimal("0"),  # paper broker has no fees
            filled_at=now,
            liquidity_flag="taker",
        )

        self._fills.setdefault(order.broker_order_id, []).append(fill)
        self._update_position(order.ticker, order.side, fill_qty, fill_price)

        cost = (fill_price * fill_qty).quantize(self._CENTS, ROUND_HALF_UP)
        if order.side == OrderSide.BUY:
            self._cash -= cost
        else:
            self._cash += cost

        # Phase 70: invariant — paper broker cash must never go negative.
        # If it does, a concurrent race slipped past InsufficientFundsError.
        # Reverse the fill so the damage doesn't propagate to snapshots.
        if self._cash < Decimal("0"):
            # Undo the cash change
            if order.side == OrderSide.BUY:
                self._cash += cost
            else:
                self._cash -= cost
            raise InsufficientFundsError(
                f"Phase 70 invariant: cash would go negative ({self._cash - cost if order.side == OrderSide.BUY else self._cash + cost}). "
                f"Reversing fill for {order.ticker}."
            )

        order.filled_quantity = fill_qty
        order.average_fill_price = fill_price
        order.status = OrderStatus.FILLED
        order.filled_at = now
        self._orders[order.broker_order_id] = order
        return order

    def _update_position(
        self, ticker: str, side: OrderSide, quantity: Decimal, price: Decimal
    ) -> None:
        internal = self._positions.get(ticker, _InternalPosition())
        if side == OrderSide.BUY:
            new_qty = internal.quantity + quantity
            if internal.quantity == Decimal("0"):
                internal.avg_entry_price = price
            else:
                # Weighted average for adds
                total_cost = internal.avg_entry_price * internal.quantity + price * quantity
                internal.avg_entry_price = (total_cost / new_qty).quantize(
                    self._CENTS, ROUND_HALF_UP
                )
            internal.quantity = new_qty
        else:
            # Sell
            internal.quantity = max(Decimal("0"), internal.quantity - quantity)
            if internal.quantity == Decimal("0"):
                internal.avg_entry_price = Decimal("0")
        self._positions[ticker] = internal

    def _to_position(self, ticker: str, internal: _InternalPosition) -> Position:
        current_price = self._price_overrides.get(ticker, internal.avg_entry_price)
        market_value = (current_price * internal.quantity).quantize(
            self._CENTS, ROUND_HALF_UP
        )
        cost_basis = (internal.avg_entry_price * internal.quantity).quantize(
            self._CENTS, ROUND_HALF_UP
        )
        unrealized_pnl = market_value - cost_basis
        unrealized_pnl_pct = (
            (unrealized_pnl / cost_basis * 100).quantize(Decimal("0.0001"), ROUND_HALF_UP)
            if cost_basis != Decimal("0")
            else Decimal("0")
        )
        return Position(
            ticker=ticker,
            quantity=internal.quantity,
            average_entry_price=internal.avg_entry_price,
            current_price=current_price,
            market_value=market_value,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
        )

    def _get_order_or_raise(self, broker_order_id: str) -> Order:
        order = self._orders.get(broker_order_id)
        if order is None:
            raise OrderRejectedError(
                f"Order not found: {broker_order_id}", order_id=broker_order_id
            )
        return order


class _InternalPosition:
    """Internal mutable position state (not exposed externally)."""

    __slots__ = ("quantity", "avg_entry_price")

    def __init__(self) -> None:
        self.quantity: Decimal = Decimal("0")
        self.avg_entry_price: Decimal = Decimal("0")
