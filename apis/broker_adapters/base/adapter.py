"""
Abstract base class for all APIS broker adapters.

Every broker adapter (paper, Alpaca, IBKR, etc.) must inherit from
BaseBrokerAdapter and implement all abstract methods.

The execution engine interacts ONLY with this interface — it has no
knowledge of broker-specific APIs or SDKs.

Spec reference: API_AND_SERVICE_BOUNDARIES_SPEC.md § 3.12
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from broker_adapters.base.models import (
    AccountState,
    Fill,
    Order,
    OrderRequest,
    Position,
)


class BaseBrokerAdapter(ABC):
    """
    Abstract broker adapter interface.

    All implementations must:
    - enforce idempotent order submission (duplicate key prevention)
    - respect the kill switch
    - never bypass risk checks (that is the risk_engine's job upstream)
    - operate within the operating mode constraints set by the caller
    """

    @property
    @abstractmethod
    def adapter_name(self) -> str:
        """Human-readable identifier for this adapter (e.g. 'paper', 'alpaca_paper')."""

    # ── Connection / lifecycle ─────────────────────────────────────────────────

    @abstractmethod
    def connect(self) -> None:
        """Initialize connection to the broker. Called once at startup."""

    @abstractmethod
    def disconnect(self) -> None:
        """Clean shutdown of broker connection."""

    @abstractmethod
    def ping(self) -> bool:
        """Return True if the broker connection is alive."""

    # ── Account ────────────────────────────────────────────────────────────────

    @abstractmethod
    def get_account_state(self) -> AccountState:
        """Return the current account state including cash, positions, and equity."""

    # ── Orders ────────────────────────────────────────────────────────────────

    @abstractmethod
    def place_order(self, request: OrderRequest) -> Order:
        """
        Submit an order to the broker.

        Must:
        - Reject duplicate idempotency_key with DuplicateOrderError
        - Reject if kill switch is active
        - Return a submitted Order object
        """

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> Order:
        """Cancel a pending order. Return the updated Order."""

    @abstractmethod
    def get_order(self, broker_order_id: str) -> Order:
        """Retrieve current state of a submitted order."""

    @abstractmethod
    def list_open_orders(self) -> list[Order]:
        """Return all currently open (unfilled, non-cancelled) orders."""

    # ── Positions ─────────────────────────────────────────────────────────────

    @abstractmethod
    def get_position(self, ticker: str) -> Position:
        """Return the current position for a ticker. Raises PositionNotFoundError if none."""

    @abstractmethod
    def list_positions(self) -> list[Position]:
        """Return all current open positions."""

    # ── Fills ─────────────────────────────────────────────────────────────────

    @abstractmethod
    def get_fills_for_order(self, broker_order_id: str) -> list[Fill]:
        """Return fills associated with a specific order."""

    @abstractmethod
    def list_fills_since(self, since: datetime) -> list[Fill]:
        """Return all fills since a given timestamp, for reconciliation."""

    # ── Market hours ──────────────────────────────────────────────────────────

    @abstractmethod
    def is_market_open(self) -> bool:
        """Return True if the equity market is currently open."""

    @abstractmethod
    def next_market_open(self) -> datetime:
        """Return the datetime of the next market open (UTC)."""
