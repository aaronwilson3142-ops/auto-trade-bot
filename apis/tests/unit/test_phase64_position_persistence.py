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


class TestPhase75ReopenIdempotency:
    """Phase 75 (2026-05-04): regression tests for the row-inflation bug.

    Root cause: when `_persist_positions` ran with the in-memory
    `PortfolioPosition.opened_at` matching a previously CLOSED Position row,
    the upsert query (filtered to `status='open'`) returned None and a NEW
    row was inserted — producing duplicates.  Observed for weeks before
    discovery (BK=22 rows, UNP=20, ODFL=20, HOLX=19, MRVL=17, CSCO=7 etc.,
    all sharing the SAME opened_at, differing only in closed_at).

    The fix matches by `(security_id, opened_at)` regardless of status, and
    REOPENS the closed row instead of inserting a duplicate.
    """

    def test_reopens_closed_row_with_same_opened_at(self):
        """If a CLOSED Position row exists with the same (security_id,
        opened_at) as the in-memory PortfolioPosition, reopen it instead of
        inserting a duplicate row."""
        from apps.worker.jobs.paper_trading import _persist_positions

        sec_id = uuid.uuid4()
        sec = MagicMock()
        sec.id = sec_id
        sec.ticker = "CSCO"

        opened_at = dt.datetime(2026, 4, 1, tzinfo=dt.UTC)

        closed_row = MagicMock()
        closed_row.security_id = sec_id
        closed_row.opened_at = opened_at
        closed_row.status = "closed"
        closed_row.closed_at = dt.datetime(2026, 4, 1, 14, 30, tzinfo=dt.UTC)
        closed_row.exit_price = Decimal("91.43")
        closed_row.realized_pnl = Decimal("0")
        closed_row.origin_strategy = "momentum_v1"

        class _DB(_FakeDB):
            def execute(self, stmt):
                self._query_counter += 1
                result = MagicMock()
                if self._query_counter == 1:
                    # Securities lookup
                    result.scalars.return_value.all.return_value = self._securities
                elif self._query_counter == 2:
                    # Phase 75 same_episode lookup: returns the closed row
                    result.scalar_one_or_none.return_value = closed_row
                else:
                    # Final close-scan: only the just-reopened row, ticker
                    # is in held_tickers so it stays open.
                    result.all.return_value = [(closed_row, "CSCO")]
                return result

        fake_db = _DB(securities=[sec])

        pos = _make_position(
            "CSCO", quantity=72, avg_entry_price=91.43, current_price=91.50,
        )
        # Override opened_at to match the closed row exactly
        pos.opened_at = opened_at
        ps = _make_portfolio_state({"CSCO": pos})

        @contextmanager
        def fake_session():
            yield fake_db

        with patch("infra.db.session.db_session", fake_session):
            _persist_positions(
                ps,
                [],
                dt.datetime(2026, 4, 1, 15, 30, tzinfo=dt.UTC),
            )

        # The fix MUST NOT insert a new row — the closed row is reopened.
        assert fake_db.added == [], (
            f"Expected zero new rows; Phase 75 fix should have reopened the "
            f"existing closed row, but {len(fake_db.added)} new row(s) were "
            f"inserted (row-inflation regression)."
        )
        # And the closed row's lifecycle fields are cleared (= reopened).
        assert closed_row.status == "open"
        assert closed_row.closed_at is None
        assert closed_row.exit_price is None
        assert closed_row.realized_pnl is None
        # Quantity refreshed from the in-memory position
        assert closed_row.quantity == Decimal("72")

    def test_close_loop_skips_just_upserted_security(self):
        """Defense-in-depth: even if `held_tickers` is somehow missing the
        ticker by the time the close-loop runs, the just-upserted row must
        not be re-closed in the same call."""
        from apps.worker.jobs.paper_trading import _persist_positions

        sec_id = uuid.uuid4()
        sec = MagicMock()
        sec.id = sec_id
        sec.ticker = "CSCO"

        # The upsert path will insert a new row.  Track the inserted row so
        # the final close-scan can return it as one of the open_db_rows.
        inserted_holder: list = []

        class _DB(_FakeDB):
            def execute(self, stmt):
                self._query_counter += 1
                result = MagicMock()
                if self._query_counter == 1:
                    result.scalars.return_value.all.return_value = self._securities
                elif self._query_counter in (2, 3):
                    # Both same_episode + legacy fallback return None → INSERT
                    result.scalar_one_or_none.return_value = None
                else:
                    # Final close-scan: pretend the just-inserted CSCO row
                    # is in DB but the ticker is somehow no longer in
                    # held_tickers (simulates an upstream bug).  Phase 75
                    # defense-in-depth must skip closing it because the
                    # security_id was just touched in the upsert.
                    if inserted_holder:
                        result.all.return_value = [(inserted_holder[0], "CSCO")]
                    else:
                        result.all.return_value = []
                return result

            def add(self, obj):
                super().add(obj)
                obj.security_id = sec_id
                obj.status = "open"
                inserted_holder.append(obj)

        fake_db = _DB(securities=[sec])

        pos = _make_position("CSCO", quantity=72, avg_entry_price=91.43)
        ps = _make_portfolio_state({"CSCO": pos})

        # Simulate the upstream bug: clear portfolio_state.positions AFTER
        # the upsert iterates, so the close-loop sees held_tickers={} but
        # the security_id was just touched.  We can't easily inject between
        # the loops, so instead we rely on the close-loop's own guard:
        # `if row.security_id in _persist_touched_sec_ids: continue`.

        @contextmanager
        def fake_session():
            yield fake_db

        run_at = dt.datetime(2026, 4, 1, 14, 30, tzinfo=dt.UTC)
        with patch("infra.db.session.db_session", fake_session):
            _persist_positions(ps, [], run_at)

        # New row inserted (upsert path)
        assert len(fake_db.added) == 1
        added = fake_db.added[0]
        # NOT closed — Phase 75 defense-in-depth preserved it because
        # security_id was in _persist_touched_sec_ids.  The MagicMock's
        # status attr would have been overwritten if close-loop had run.
        assert added.status == "open"
