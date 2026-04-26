"""
Shared pytest fixtures for APIS tests.
"""
from __future__ import annotations

import os
from decimal import Decimal

import pytest

# Set test environment before any config module loads
os.environ.setdefault("APIS_ENV", "development")
os.environ.setdefault("APIS_OPERATING_MODE", "research")
os.environ.setdefault("APIS_DB_URL", "postgresql+psycopg://test:test@localhost:5432/apis_test")
os.environ.setdefault("APIS_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("APIS_KILL_SWITCH", "false")


# ── Test isolation guard: refuse to run if APIS_DB_URL points at production ──
# The 2026-04-19 test pollution incident happened because a test runner's
# DATABASE_URL fell through to the Docker Compose Postgres.  This guard
# blocks that at the earliest possible point in the pytest session.
_PRODUCTION_DB_MARKERS = ("docker-postgres", "/apis\"", "/apis'", "/apis ")
_db_url = os.environ.get("APIS_DB_URL", "")
if _db_url and "apis_test" not in _db_url and "test" not in _db_url:
    # If the URL doesn't contain "test" anywhere, it's almost certainly
    # pointing at the production-paper database.  Fail hard.
    raise RuntimeError(
        f"REFUSING TO RUN TESTS: APIS_DB_URL appears to point at a "
        f"non-test database ({_db_url!r}).  Set APIS_DB_URL to an "
        f"isolated test database (containing 'test' in the DB name) "
        f"before running pytest.  See: 2026-04-19 test pollution incident."
    )


@pytest.fixture()
def paper_broker():
    """Provide a connected PaperBrokerAdapter with market open and test prices injected."""
    from broker_adapters.paper.adapter import PaperBrokerAdapter

    broker = PaperBrokerAdapter(
        starting_cash=Decimal("100000.00"),
        slippage_bps=5,
        fill_immediately=True,
        market_open=True,      # override market hours check for tests
    )
    broker.connect()
    broker.set_price("AAPL", Decimal("175.00"))
    broker.set_price("NVDA", Decimal("900.00"))
    broker.set_price("MSFT", Decimal("420.00"))
    yield broker
    broker.disconnect()


@pytest.fixture()
def settings():
    """Return the Settings object (test environment)."""
    from config.settings import Settings

    return Settings()


@pytest.fixture(autouse=True)
def _reset_admin_rate_limiter():
    """Clear the admin endpoint rate limiter store before every test.

    Prevents cross-test contamination: tests that hammer the admin endpoint
    (TestAdminRateLimitIntegration) must not leak state into subsequent test
    classes that expect the admin endpoints to respond normally.
    """
    try:
        import apps.api.routes.admin as admin_mod
        with admin_mod._rate_limit_lock:
            admin_mod._rate_limit_store.clear()
    except (ImportError, AttributeError):
        pass  # admin module not yet loaded or rate limiter not present — no-op
    yield
