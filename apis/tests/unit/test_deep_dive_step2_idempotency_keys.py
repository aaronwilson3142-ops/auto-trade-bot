"""Deep-Dive Plan Step 2 Rec 4 — idempotency-key behavior tests.

These tests do NOT need a real PostgreSQL — they intercept the persist
call-paths and assert that:

* When ``cycle_id`` / ``run_id`` is provided, the generated
  ``idempotency_key`` follows the documented format.
* When the key is missing, the fallback path is taken (no ON CONFLICT
  branch, legacy ``db.add()``).
* The persist functions never raise on DB errors (fire-and-forget).
"""
from __future__ import annotations

import datetime as dt
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from unittest import mock

import pytest

# ── Lightweight fakes to stand in for PortfolioState and related types ───────


@dataclass
class _FakePosition:
    ticker: str
    quantity: Decimal
    avg_entry_price: Decimal
    current_price: Decimal
    market_value: Decimal
    cost_basis: Decimal
    unrealized_pnl: Decimal
    unrealized_pnl_pct: Decimal


@dataclass
class _FakePortfolioState:
    cash: Decimal = Decimal("100000")
    equity: Decimal = Decimal("105000")
    gross_exposure: Decimal = Decimal("5000")
    drawdown_pct: Decimal = Decimal("0")
    positions: dict[str, _FakePosition] = field(default_factory=dict)


class _FakeStmt:
    """Captures the values dict and constraint name used by pg_insert."""

    def __init__(self, values: dict[str, Any]):
        self.values_dict = dict(values)
        self.constraint: str | None = None

    def on_conflict_do_nothing(self, *, constraint: str | None = None) -> _FakeStmt:
        self.constraint = constraint
        return self


class _FakeDb:
    def __init__(self) -> None:
        self.executed: list[_FakeStmt] = []
        self.added: list[Any] = []

    def execute(self, stmt: Any) -> None:
        self.executed.append(stmt)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def add_all(self, objs: list[Any]) -> None:
        self.added.extend(objs)


@contextmanager
def _fake_session(db: _FakeDb):
    yield db


# ── Tests for _persist_portfolio_snapshot ────────────────────────────────────


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="paper_trading module imports datetime.UTC which requires 3.11+",
)
def test_persist_portfolio_snapshot_with_cycle_id_uses_idem_key():
    from apps.worker.jobs.paper_trading import _persist_portfolio_snapshot

    db = _FakeDb()
    state = _FakePortfolioState()

    # Patch pg_insert to return our _FakeStmt and db_session to yield our db.
    fake_pg_insert = mock.MagicMock()
    fake_pg_insert.return_value.values = lambda **kw: _FakeStmt(kw)

    with mock.patch(
        "sqlalchemy.dialects.postgresql.insert",
        side_effect=lambda _model: type(
            "PgInsert",
            (),
            {"values": staticmethod(lambda **kw: _FakeStmt(kw))},
        )(),
    ), mock.patch(
        "infra.db.session.db_session", lambda: _fake_session(db)
    ):
        _persist_portfolio_snapshot(state, "paper", cycle_id="abc123")

    # Exactly one execute, zero adds (ON CONFLICT path taken).
    assert len(db.executed) == 1
    assert db.added == []
    stmt = db.executed[0]
    assert stmt.values_dict["idempotency_key"] == "abc123:portfolio_snapshot"
    assert stmt.constraint == "uq_portfolio_snapshot_idempotency_key"


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="paper_trading module imports datetime.UTC which requires 3.11+",
)
def test_persist_portfolio_snapshot_without_cycle_id_uses_legacy_add():
    from apps.worker.jobs.paper_trading import _persist_portfolio_snapshot

    db = _FakeDb()
    state = _FakePortfolioState()

    with mock.patch(
        "infra.db.session.db_session", lambda: _fake_session(db)
    ):
        _persist_portfolio_snapshot(state, "paper")  # no cycle_id

    # Legacy path: db.add() only, no execute().
    assert len(db.executed) == 0
    assert len(db.added) == 1
    row = db.added[0]
    assert getattr(row, "idempotency_key", "SENTINEL") is None


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="paper_trading module imports datetime.UTC which requires 3.11+",
)
def test_persist_portfolio_snapshot_swallows_db_errors():
    """Fire-and-forget: DB errors must NOT bubble up to the scheduler."""
    from apps.worker.jobs.paper_trading import _persist_portfolio_snapshot

    @contextmanager
    def _broken_sess():
        raise RuntimeError("db down")
        yield  # unreachable

    state = _FakePortfolioState()
    with mock.patch("infra.db.session.db_session", _broken_sess):
        # Should return without raising.
        _persist_portfolio_snapshot(state, "paper", cycle_id="abc")


# ── Tests for _persist_position_history ──────────────────────────────────────


def _pos(ticker: str) -> _FakePosition:
    return _FakePosition(
        ticker=ticker,
        quantity=Decimal("10"),
        avg_entry_price=Decimal("100"),
        current_price=Decimal("101"),
        market_value=Decimal("1010"),
        cost_basis=Decimal("1000"),
        unrealized_pnl=Decimal("10"),
        unrealized_pnl_pct=Decimal("0.01"),
    )


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="paper_trading module imports datetime.UTC which requires 3.11+",
)
def test_persist_position_history_with_cycle_id_uses_per_ticker_idem():
    from apps.worker.jobs.paper_trading import _persist_position_history

    db = _FakeDb()
    state = _FakePortfolioState(positions={"AAPL": _pos("AAPL"), "MSFT": _pos("MSFT")})
    snapshot_at = dt.datetime(2026, 4, 16, 14, 0, 0)

    with mock.patch(
        "sqlalchemy.dialects.postgresql.insert",
        side_effect=lambda _model: type(
            "PgInsert",
            (),
            {"values": staticmethod(lambda **kw: _FakeStmt(kw))},
        )(),
    ), mock.patch(
        "infra.db.session.db_session", lambda: _fake_session(db)
    ):
        _persist_position_history(state, snapshot_at, cycle_id="cyc-42")

    # Two rows, both via execute() with ON CONFLICT constraint.
    assert len(db.executed) == 2
    assert db.added == []
    keys = {stmt.values_dict["idempotency_key"] for stmt in db.executed}
    assert keys == {
        "cyc-42:position_history:AAPL",
        "cyc-42:position_history:MSFT",
    }
    for stmt in db.executed:
        assert stmt.constraint == "uq_position_history_idempotency_key"


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="paper_trading module imports datetime.UTC which requires 3.11+",
)
def test_persist_position_history_without_cycle_id_uses_add_all():
    from apps.worker.jobs.paper_trading import _persist_position_history

    db = _FakeDb()
    state = _FakePortfolioState(positions={"AAPL": _pos("AAPL")})
    with mock.patch(
        "infra.db.session.db_session", lambda: _fake_session(db)
    ):
        _persist_position_history(state, dt.datetime(2026, 4, 16))

    assert len(db.executed) == 0
    assert len(db.added) == 1
    # No idempotency key on the legacy add() path.
    assert db.added[0].idempotency_key is None


# ── Tests for _persist_evaluation_run ────────────────────────────────────────


@dataclass
class _FakeScorecard:
    scorecard_date: dt.date = dt.date(2026, 4, 16)
    equity: Decimal = Decimal("100000")
    daily_return_pct: Decimal = Decimal("0")
    net_pnl: Decimal = Decimal("0")
    hit_rate: Decimal | None = None
    current_drawdown_pct: Decimal = Decimal("0")
    max_drawdown_pct: Decimal = Decimal("0")
    position_count: int = 0
    closed_trade_count: int = 0


class _FakeEvalDb:
    def __init__(self, existing_run: Any = None) -> None:
        self.existing_run = existing_run
        self.executed_queries: list[Any] = []
        self.added: list[Any] = []

    def execute(self, stmt: Any) -> Any:
        self.executed_queries.append(stmt)

        class _Result:
            def __init__(self, _existing):
                self._existing = _existing

            def scalar_one_or_none(self_inner):
                return self_inner._existing

        return _Result(self.existing_run)

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        # Simulate flush() assigning an id
        if not hasattr(obj, "id") or obj.id is None:
            obj.id = "fake-run-id"

    def flush(self) -> None:
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = "fake-run-id"


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="evaluation module imports datetime.UTC which requires 3.11+",
)
def test_persist_evaluation_run_with_run_id_populates_idem_key():
    from apps.worker.jobs.evaluation import _persist_evaluation_run

    db = _FakeEvalDb(existing_run=None)
    sc = _FakeScorecard()
    with mock.patch(
        "infra.db.session.db_session", lambda: _fake_session(db)
    ):
        _persist_evaluation_run(sc, "paper", run_id="2026-04-16:paper")

    # First added object is the run, then 8 metric rows.
    assert len(db.added) == 9
    run = db.added[0]
    assert run.idempotency_key == "2026-04-16:paper:evaluation_run"


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="evaluation module imports datetime.UTC which requires 3.11+",
)
def test_persist_evaluation_run_skips_when_key_already_exists():
    """If a row with matching idempotency_key already exists, skip insert."""
    from apps.worker.jobs.evaluation import _persist_evaluation_run

    # Simulate existing row returned by the SELECT.
    existing = object()
    db = _FakeEvalDb(existing_run=existing)
    sc = _FakeScorecard()
    with mock.patch(
        "infra.db.session.db_session", lambda: _fake_session(db)
    ):
        _persist_evaluation_run(sc, "paper", run_id="2026-04-16:paper")

    # No run or metric rows added.
    assert db.added == []


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="evaluation module imports datetime.UTC which requires 3.11+",
)
def test_persist_evaluation_run_without_run_id_takes_legacy_path():
    from apps.worker.jobs.evaluation import _persist_evaluation_run

    db = _FakeEvalDb(existing_run=None)
    sc = _FakeScorecard()
    with mock.patch(
        "infra.db.session.db_session", lambda: _fake_session(db)
    ):
        _persist_evaluation_run(sc, "paper")  # no run_id

    assert len(db.added) == 9
    run = db.added[0]
    assert run.idempotency_key is None
    # Legacy path must not issue a pre-flight SELECT.
    assert db.executed_queries == []
