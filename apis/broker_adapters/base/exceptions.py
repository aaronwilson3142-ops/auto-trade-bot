"""
Broker adapter exception hierarchy.

All broker adapters must raise exceptions from this hierarchy so that
the execution engine can handle them uniformly without knowledge of
broker-specific error codes.
"""
from __future__ import annotations


class BrokerError(Exception):
    """Base class for all broker-related errors."""

    def __init__(self, message: str, broker_code: str | None = None) -> None:
        super().__init__(message)
        self.broker_code = broker_code


class BrokerConnectionError(BrokerError):
    """Failed to connect to broker API."""


class BrokerAuthenticationError(BrokerError):
    """Authentication with broker failed."""


class OrderRejectedError(BrokerError):
    """Broker rejected the order."""

    def __init__(
        self,
        message: str,
        broker_code: str | None = None,
        order_id: str | None = None,
    ) -> None:
        super().__init__(message, broker_code)
        self.order_id = order_id


class DuplicateOrderError(BrokerError):
    """
    Attempted to submit an order with an idempotency key that already exists.

    This is a safety violation — duplicate-order prevention is a hard requirement.
    """

    def __init__(self, message: str, idempotency_key: str) -> None:
        super().__init__(message)
        self.idempotency_key = idempotency_key


class InsufficientFundsError(BrokerError):
    """Insufficient buying power for the order."""


class MarketClosedError(BrokerError):
    """Market is closed and the order type does not support extended hours."""


class StaleDataError(BrokerError):
    """Price or quote data is stale — order should not be submitted."""


class PositionNotFoundError(BrokerError):
    """No position found for the requested ticker."""


class ReconciliationError(BrokerError):
    """Order/fill reconciliation failed — manual review required."""


class KillSwitchActiveError(BrokerError):
    """Kill switch is active — no orders may be submitted."""
