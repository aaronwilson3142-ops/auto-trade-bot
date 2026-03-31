"""
Domain models shared across all broker adapters.

These are broker-agnostic representations. Adapter implementations must
translate between these models and broker-specific data structures.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class TimeInForce(str, Enum):
    DAY = "day"
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"


@dataclass
class OrderRequest:
    """
    An instruction to place an order with the broker.

    All monetary values use Decimal to avoid floating-point rounding errors.
    """

    idempotency_key: str
    ticker: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    time_in_force: TimeInForce = TimeInForce.DAY
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    client_order_id: str | None = None


@dataclass
class Order:
    """
    A submitted order with broker reference and current status.
    """

    idempotency_key: str
    broker_order_id: str
    ticker: str
    side: OrderSide
    order_type: OrderType
    requested_quantity: Decimal
    filled_quantity: Decimal
    status: OrderStatus
    submitted_at: datetime
    filled_at: datetime | None = None
    average_fill_price: Decimal | None = None
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    rejection_reason: str | None = None


@dataclass
class Fill:
    """
    A single execution fill associated with an order.
    """

    broker_fill_id: str
    broker_order_id: str
    ticker: str
    side: OrderSide
    fill_quantity: Decimal
    fill_price: Decimal
    fees: Decimal
    filled_at: datetime
    liquidity_flag: str | None = None  # "maker" | "taker" | None


@dataclass
class Position:
    """
    A current open position as reported by the broker.
    """

    ticker: str
    quantity: Decimal
    average_entry_price: Decimal
    current_price: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal
    unrealized_pnl_pct: Decimal
    side: str = "long"


@dataclass
class AccountState:
    """
    Snapshot of the broker account as returned by the broker adapter.
    """

    account_id: str
    cash_balance: Decimal
    buying_power: Decimal
    equity_value: Decimal
    gross_exposure: Decimal
    positions: list[Position] = field(default_factory=list)
    is_pattern_day_trader: bool = False
    is_account_blocked: bool = False
    snapshot_at: datetime = field(default_factory=datetime.utcnow)
