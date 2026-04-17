"""Broker-adapter service package.

Houses cross-adapter invariants and health checks that sit above the concrete
``broker_adapters/*`` implementations.  Deep-Dive Plan Step 2 (2026-04-16).
"""
from services.broker_adapter.health import (
    BrokerAdapterHealthError,
    HealthResult,
    check_broker_adapter_health,
)

__all__ = [
    "BrokerAdapterHealthError",
    "HealthResult",
    "check_broker_adapter_health",
]
