"""
Shared pytest fixtures for APIS tests.
"""
from __future__ import annotations

import os
from decimal import Decimal
from unittest.mock import MagicMock

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
#
# Phase 69: APIS_PYTEST_SMOKE=1 bypasses the guard for health-check smoke
# runs that only exercise pure unit tests (no DB writes).  The health check
# invokes pytest with ``--no-cov -k unit -x`` so only non-DB tests run.
_PRODUCTION_DB_MARKERS = ("docker-postgres", "/apis\"", "/apis'", "/apis ")
_db_url = os.environ.get("APIS_DB_URL", "")
_smoke_mode = os.environ.get("APIS_PYTEST_SMOKE", "").strip().lower() in ("1", "true", "yes")
if _db_url and "apis_test" not in _db_url and "test" not in _db_url and not _smoke_mode:
    # If the URL doesn't contain "test" anywhere, it's almost certainly
    # pointing at the production-paper database.  Fail hard.
    raise RuntimeError(
        f"REFUSING TO RUN TESTS: APIS_DB_URL appears to point at a "
        f"non-test database ({_db_url!r}).  Set APIS_DB_URL to an "
        f"isolated test database (containing 'test' in the DB name) "
        f"before running pytest.  See: 2026-04-19 test pollution incident.  "
        f"For health-check smoke runs, set APIS_PYTEST_SMOKE=1."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 74 — Smoke-mode write blocker (extends Phase 68 conftest isolation)
# ─────────────────────────────────────────────────────────────────────────────
# The 2026-05-04 test pollution incident (3rd documented occurrence) happened
# because a phase59 test (`test_catchup_fires_correlation_when_empty`) only
# mocks `run_correlation_refresh` and lets the other 8+ catchup branches in
# `_run_startup_catchup()` fire REAL jobs (run_signal_generation,
# run_ranking_generation, run_universe_refresh, ...) against the production
# paper Postgres.  Those jobs grab `infra.db.session.SessionLocal` directly
# via `_session_factory()`, bypassing any test-level patch of `db_session`.
#
# Phase 74 defense: when APIS_PYTEST_SMOKE=1, monkey-patch
# `infra.db.session.SessionLocal` (and `db_session`) to return sessions whose
# write methods (add/add_all/delete/merge/flush/commit) are no-ops, and whose
# `execute()` no-ops on Insert/Update/Delete statements while passing
# Select/text-SELECT through.  Reads still work; writes can never reach the
# bound engine regardless of which code path requests a session.
#
# Scope: SESSION-scoped autouse fixture so the patch is in place for the
# entire pytest run, including module-level imports that may eagerly bind
# to SessionLocal.


def _is_dml_statement(statement) -> bool:
    """Return True if a SQLAlchemy statement is INSERT/UPDATE/DELETE."""
    try:
        from sqlalchemy.sql import Delete, Insert, Update
        from sqlalchemy.sql.dml import UpdateBase
    except ImportError:
        return False
    if isinstance(statement, (Insert, Update, Delete, UpdateBase)):
        return True
    # Detect raw text() with leading INSERT/UPDATE/DELETE
    text_value = getattr(statement, "text", None)
    if isinstance(text_value, str):
        head = text_value.lstrip().upper()
        if head.startswith(("INSERT", "UPDATE", "DELETE", "TRUNCATE", "MERGE", "REPLACE")):
            return True
    return False


def _make_write_blocking_session_class(base_session_cls):
    """Build a Session subclass that swallows writes.

    Uses the imported `Session` class as base so SQLAlchemy's session
    machinery (registry lookups, identity map, etc.) keeps working for
    any reads that pass through.
    """

    class WriteBlockingSession(base_session_cls):
        """Session whose write methods are no-ops; SELECTs pass through.

        Phase 74 (2026-05-04): defense against pytest fixtures that fire
        production-DB writes despite APIS_PYTEST_SMOKE=1.  Replaces the
        previous behaviour where Phase 68's conftest only blocked at the
        env-guard level — which doesn't help once the env guard is bypassed
        for legitimate smoke runs that need to import the module.
        """

        def add(self, *args, **kwargs):  # type: ignore[override]
            return None

        def add_all(self, *args, **kwargs):  # type: ignore[override]
            return None

        def delete(self, *args, **kwargs):  # type: ignore[override]
            return None

        def merge(self, instance, *args, **kwargs):  # type: ignore[override]
            return instance

        def flush(self, *args, **kwargs):  # type: ignore[override]
            # Drop any pending state instead of flushing it to the engine.
            try:
                self.expunge_all()
            except Exception:
                pass
            return None

        def commit(self):  # type: ignore[override]
            # Roll back any in-flight transaction so the bound engine
            # never sees writes.  Safe to call even if no txn is open.
            try:
                self.rollback()
            except Exception:
                pass
            return None

        def execute(self, statement, *args, **kwargs):  # type: ignore[override]
            if _is_dml_statement(statement):
                # Return a stub that mimics a CursorResult enough for callers
                # that read .rowcount / .scalar() / .all() / .scalars().
                stub = MagicMock()
                stub.rowcount = 0
                stub.scalar.return_value = None
                stub.scalar_one_or_none.return_value = None
                stub.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
                stub.all.return_value = []
                stub.first.return_value = None
                stub.fetchall.return_value = []
                stub.fetchone.return_value = None
                stub.mappings.return_value = MagicMock(all=MagicMock(return_value=[]))
                return stub
            return super().execute(statement, *args, **kwargs)

    return WriteBlockingSession


@pytest.fixture(scope="session", autouse=True)
def _phase74_block_production_writes_in_smoke_mode():
    """Phase 74: prevent any pytest fixture from writing to production DB
    when APIS_PYTEST_SMOKE=1, regardless of which code path requests a
    session.

    Trigger: 3rd documented test-pollution incident (2026-05-04) in which
    `test_catchup_fires_correlation_when_empty` only mocked
    `run_correlation_refresh` and let the other 8 catchup branches in
    `_run_startup_catchup()` fire real signal/ranking/universe jobs against
    the production paper Postgres via `infra.db.session.SessionLocal`.
    Those jobs are downstream of `db_session()` and direct `SessionLocal()`
    calls — patching `db_session` alone wasn't enough.

    Implementation: monkey-patch the module-global `SessionLocal` on
    `infra.db.session` to return WriteBlockingSession instances bound to
    the same engine.  All callers (db_session() context manager, get_db()
    FastAPI dependency, _run_startup_catchup()._session_factory(), direct
    `from infra.db.session import SessionLocal` calls) re-read the module
    attribute at call time, so they all pick up the patch.
    """
    if not _smoke_mode:
        yield
        return

    try:
        import infra.db.session as session_mod
        from sqlalchemy.orm import Session as _BaseSession
        from sqlalchemy.orm import sessionmaker as _sessionmaker
    except ImportError:
        # If the DB layer can't import (e.g. no SQLAlchemy install in this
        # virtualenv), the tests don't have a way to write anyway.  No-op.
        yield
        return

    blocking_cls = _make_write_blocking_session_class(_BaseSession)

    original_SessionLocal = session_mod.SessionLocal
    blocking_factory = _sessionmaker(
        bind=session_mod.engine,
        class_=blocking_cls,
        autocommit=False,
        autoflush=False,
    )
    session_mod.SessionLocal = blocking_factory  # type: ignore[assignment]

    # Also intercept `db_session()` directly — it pulls SessionLocal from
    # the module global, so swapping that should be enough, but we keep the
    # original reference for restoration in `finally`.
    try:
        yield
    finally:
        session_mod.SessionLocal = original_SessionLocal  # type: ignore[assignment]


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
