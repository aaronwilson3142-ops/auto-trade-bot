"""
Phase 64 — Authoritative Position table persistence
====================================================

Root fix for the Phantom Broker Positions bug.  The paper trading cycle must
upsert a ``Position`` row per open position AND close rows that drop out, so
the ``_load_persisted_state`` restore path rehydrates real state instead of
falling back to the phantom-cash guard.

Tests
-----
TestPersistPositionsOpens    — opens a Position row for a new held ticker
TestPersistPositionsUpdates  — updates existing open Position row
TestPersistPositionsCloses   — marks DB rows closed when ticker drops out
TestPersistPositionsErrors   — fire-and-forget never raises
"""
from __future__ import annotations

import datetime as dt
import uuid
from contextlib import contextmanager
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


def _make_position(
    ticker: str = "AAPL",
    quantity: float = 10.0,
    avg_entry_price: float = 150.0,
    current_price: float = 160.0,
    security_id=None,
) -> Any:
    from services.portfolio_engine.models import PortfolioPosition
    return PortfolioPosition(
        ticker=ticker,
        quantity=Decimal(str(quantity)),
        avg_entry_price=Decimal(str(avg_entry_price)),
        current_price=Decimal(str(current_price)),
        opened_at=dt.datetime(2026, 4, 1, tzinfo=dt.UTC),
        security_id=security_id,
    )


def _make_portfolio_state(positions: dict | None = None) -> Any:
    from services.portfolio_engine.models import PortfolioState
    ps = PortfolioState(
        cash=Decimal("90000.00"),
        start_of_day_equity=Decimal("100000.00"),
        high_water_mark=Decimal("100000.00"),
    )
    if positions:
        ps.positions = positions
    return ps


class _FakeDB:
    """Minimal SQLAlchemy-like stub that records add / select results."""

    def __init__(self, securities=None, open_positions=None):
        self._securities = securities or []  # list of mock Security rows
        self._open_positions = open_positions or []  # list of mock Position rows
        self.added: list = []
        self._query_counter = 0

    def add(self, obj):
        self.added.append(obj)

    def execute(self, stmt):
        self._query_counter += 1
        result = MagicMock()
        # Heuristic based on call order:
        #   1st call: Security.in_(tickers) -> scalars().all() -> securities
        #   per-position: Position where security_id=... status='open'
        #                 -> scalar_one_or_none() -> matching open position or None
        #   final: Position.status=='open' join Security -> .all() -> open tuples
        call_idx = self._query_counter
        if call_idx == 1:
            result.scalars.return_value.all.return_value = self._securities
        else:
            # For simplicity: per-security scalar_one_or_none returns first
            # matching in _open_positions (by sec_id) or None. The final
            # "close" query is driven by _all_open_pairs.
            result.scalar_one_or_none.return_value = None
            result.all.return_value = list(getattr(self, "_all_open_pairs", []))
        return result


class TestPersistPositionsOpens:
    def test_adds_position_row_for_new_ticker(self):
        from apps.worker.jobs.paper_trading import _persist_positions

        sec_id = uuid.uuid4()
        sec = MagicMock()
        sec.id = sec_id
        sec.ticker = "AAPL"

        fake_db = _FakeDB(securities=[sec])
        fake_db._all_open_pairs = []  # no other open rows in DB

        pos = _make_position("AAPL", quantity=10, avg_entry_price=150,
                             current_price=160)
        ps = _make_portfolio_state({"AAPL": pos})

        @contextmanager
        def fake_session():
            yield fake_db

        with patch("infra.db.session.db_session", fake_session):
            _persist_positions(ps, [], dt.datetime.now(dt.UTC))

        assert len(fake_db.added) == 1
        added = fake_db.added[0]
        assert added.security_id == sec_id
        assert added.status == "open"
        assert added.quantity == Decimal("10")
        assert added.entry_price == Decimal("150")


class TestPersistPositionsUpdates:
    def test_updates_existing_open_row_instead_of_inserting(self):
        from apps.worker.jobs.paper_trading import _persist_positions

        sec_id = uuid.uuid4()
        sec = MagicMock()
        sec.id = sec_id
        sec.ticker = "AAPL"

        existing = MagicMock()
        existing.security_id = sec_id
        existing.status = "open"

        class _DB(_FakeDB):
            def execute(self, stmt):
                self._query_counter += 1
                result = MagicMock()
                if self._query_counter == 1:
                    result.scalars.return_value.all.return_value = self._securities
                elif self._query_counter == 2:
                    # Per-position open lookup: return the existing row
                    result.scalar_one_or_none.return_value = existing
                else:
                    # Final "close" scan: the ticker is still held, so the
                    # Security join should return it BUT it shouldn't be
                    # closed because it's in portfolio_state.
                    result.all.return_value = [(existing, "AAPL")]
                return result

        fake_db = _DB(securities=[sec])

        pos = _make_position("AAPL", quantity=15, avg_entry_price=155,
                             current_price=170)
        ps = _make_portfolio_state({"AAPL": pos})

        @contextmanager
        def fake_session():
            yield fake_db

        with patch("infra.db.session.db_session", fake_session):
            _persist_positions(ps, [], dt.datetime.now(dt.UTC))

        # No new row added — existing row mutated
        assert fake_db.added == []
        assert existing.quantity == Decimal("15")
        assert existing.entry_price == Decimal("155")
        # Still open because the ticker is still held
        assert existing.status == "open"


class TestPersistPositionsCloses:
    def test_marks_dropped_ticker_closed(self):
        from apps.worker.jobs.paper_trading import _persist_positions

        # Security for a ticker that WAS held but no longer is
        sec_id_msft = uuid.uuid4()
        stale_row = MagicMock()
        stale_row.security_id = sec_id_msft
        stale_row.status = "open"

        class _DB(_FakeDB):
            def execute(self, stmt):
                # With zero held positions the production code skips the
                # securities-by-ticker lookup entirely, so the ONLY query that
                # fires in this path is the final close-scan join.  Return the
                # stale row on every execute() call — ordering-agnostic.
                self._query_counter += 1
                result = MagicMock()
                result.scalars.return_value.all.return_value = []
                result.all.return_value = [(stale_row, "MSFT")]
                return result

        fake_db = _DB()

        ps = _make_portfolio_state({})  # no held positions

        class _CT:
            ticker = "MSFT"
            fill_price = Decimal("310.00")
            realized_pnl = Decimal("250.00")

        run_at = dt.datetime(2026, 4, 14, 14, 30, tzinfo=dt.UTC)

        @contextmanager
        def fake_session():
            yield fake_db

        with patch("infra.db.session.db_session", fake_session):
            _persist_positions(ps, [_CT()], run_at)

        assert stale_row.status == "closed"
        assert stale_row.closed_at == run_at
        assert stale_row.exit_price == Decimal("310.00")
        assert stale_row.realized_pnl == Decimal("250.00")


class TestPersistPositionsErrors:
    def test_never_raises_on_db_error(self):
        from apps.worker.jobs.paper_trading import _persist_positions

        ps = _make_portfolio_state({"AAPL": _make_position("AAPL")})

        @contextmanager
        def bad_session():
            raise RuntimeError("DB exploded")
            yield  # unreachable

        with patch("infra.db.session.db_session", bad_session):
            result = _persist_positions(ps, [], dt.datetime.now(dt.UTC))

        assert result is None

    def test_skips_position_with_no_security_id_resolvable(self):
        from apps.worker.jobs.paper_trading import _persist_positions

        fake_db = _FakeDB(securities=[])  # no Security row matches
        fake_db._all_open_pairs = []

        pos = _make_position("ZZZZ")  # security_id=None, no Security match
        ps = _make_portfolio_state({"ZZZZ": pos})

        @contextmanager
        def fake_session():
            yield fake_db

        with patch("infra.db.session.db_session", fake_session):
            _persist_positions(ps, [], dt.datetime.now(dt.UTC))

        # Nothing inserted because security_id couldn't be resolved
        assert fake_db.added == []
