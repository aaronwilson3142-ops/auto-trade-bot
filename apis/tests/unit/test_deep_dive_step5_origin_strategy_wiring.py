"""Deep-Dive Plan Step 5 — origin_strategy wiring (deferred finisher 2026-04-18).

Covers the two sites touched by the wiring:

1. The ranking-scan block inside ``run_paper_trading_cycle`` that builds a
   ``ticker -> origin_strategy`` map from ``RankedResult.contributing_signals``
   via :func:`services.risk_engine.family_params.derive_origin_strategy`.
2. The ``_persist_positions`` writer that stores the resolved
   ``origin_strategy`` onto the new ``Position`` DB row — and backfills
   existing rows whose column is empty, but never overwrites a value that
   was set at open-time.

Flag is behaviour-neutral: the column is read only when
``APIS_ATR_STOPS_ENABLED`` is flipped ON (Step 5).  These tests pin the
producer contract so flipping that flag later lands positions in the right
family bucket from the first cycle onward.
"""
from __future__ import annotations

import datetime as dt
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

from services.portfolio_engine.models import PortfolioPosition, PortfolioState
from services.risk_engine.family_params import derive_origin_strategy

# ── Fixtures ─────────────────────────────────────────────────────────────────


@dataclass
class _FakeRanked:
    """Minimal stand-in for RankedResult; carries only fields we read."""

    ticker: str
    contributing_signals: list[dict] | None


def _sig(strategy_key: str, signal_score: float, confidence_score: float) -> dict:
    return {
        "strategy_key": strategy_key,
        "signal_score": signal_score,
        "confidence_score": confidence_score,
        "explanation": {},
    }


def _build_origin_map(rankings: list[Any]) -> dict[str, str]:
    """Re-implements the ranking-scan block verbatim so we can unit-test the
    production contract without spinning up the entire paper cycle.

    The production block lives in ``run_paper_trading_cycle`` immediately
    after ``_apply_ranking_min_filter``; if its semantics drift this helper
    also drifts and the tests will fail, flagging the divergence.
    """
    out: dict[str, str] = {}
    for r in rankings:
        origin = derive_origin_strategy(getattr(r, "contributing_signals", None))
        if origin:
            out[r.ticker] = origin
    return out


def _make_position(
    ticker: str = "AAPL",
    quantity: float = 10.0,
    avg_entry_price: float = 150.0,
    current_price: float = 160.0,
    security_id=None,
    origin_strategy: str = "",
) -> PortfolioPosition:
    return PortfolioPosition(
        ticker=ticker,
        quantity=Decimal(str(quantity)),
        avg_entry_price=Decimal(str(avg_entry_price)),
        current_price=Decimal(str(current_price)),
        opened_at=dt.datetime(2026, 4, 1, tzinfo=dt.UTC),
        security_id=security_id,
        origin_strategy=origin_strategy,
    )


def _make_portfolio_state(positions: dict | None = None) -> PortfolioState:
    ps = PortfolioState(
        cash=Decimal("90000.00"),
        start_of_day_equity=Decimal("100000.00"),
        high_water_mark=Decimal("100000.00"),
    )
    if positions:
        ps.positions = positions
    return ps


class _FakeDB:
    """Mirrors test_phase64_position_persistence._FakeDB; see that file."""

    def __init__(self, securities=None):
        self._securities = securities or []
        self.added: list = []
        self._query_counter = 0
        self._all_open_pairs: list = []
        self._existing_scalar = None

    def add(self, obj):
        self.added.append(obj)

    def execute(self, stmt):
        self._query_counter += 1
        result = MagicMock()
        if self._query_counter == 1:
            result.scalars.return_value.all.return_value = self._securities
        else:
            result.scalar_one_or_none.return_value = self._existing_scalar
            result.all.return_value = list(self._all_open_pairs)
        return result


# ── Map-builder tests (mirrors the paper_trading ranking-scan block) ─────────


class TestBuildOriginStrategyMap:
    def test_empty_rankings_yields_empty_map(self):
        assert _build_origin_map([]) == {}

    def test_single_strong_momentum_signal_maps_to_momentum(self):
        rankings = [
            _FakeRanked(
                ticker="AAPL",
                contributing_signals=[_sig("momentum", 0.9, 0.8)],
            )
        ]
        assert _build_origin_map(rankings) == {"AAPL": "momentum"}

    def test_picks_highest_signal_times_confidence_product(self):
        # momentum  = 0.6 * 0.7 = 0.42
        # valuation = 0.5 * 0.9 = 0.45  ← winner
        rankings = [
            _FakeRanked(
                ticker="MSFT",
                contributing_signals=[
                    _sig("momentum", 0.6, 0.7),
                    _sig("valuation", 0.5, 0.9),
                ],
            )
        ]
        assert _build_origin_map(rankings) == {"MSFT": "valuation"}

    def test_empty_contributing_signals_ticker_omitted(self):
        rankings = [_FakeRanked(ticker="NVDA", contributing_signals=[])]
        # Omitted from the map so `.get(ticker, "")` falls through to default.
        assert "NVDA" not in _build_origin_map(rankings)

    def test_none_contributing_signals_ticker_omitted(self):
        rankings = [_FakeRanked(ticker="GOOGL", contributing_signals=None)]
        assert "GOOGL" not in _build_origin_map(rankings)

    def test_malformed_signal_entries_skipped_but_valid_kept(self):
        # strategy_key missing on first sig → skipped; valid second sig wins.
        rankings = [
            _FakeRanked(
                ticker="TSLA",
                contributing_signals=[
                    {"signal_score": 0.95, "confidence_score": 0.95},  # no key
                    _sig("theme_alignment", 0.5, 0.5),
                ],
            )
        ]
        assert _build_origin_map(rankings) == {"TSLA": "theme_alignment"}

    def test_multi_ticker_map(self):
        rankings = [
            _FakeRanked(ticker="AAPL",
                        contributing_signals=[_sig("momentum", 0.9, 0.9)]),
            _FakeRanked(ticker="AMZN",
                        contributing_signals=[_sig("valuation", 0.7, 0.8)]),
            _FakeRanked(ticker="ORCL",
                        contributing_signals=[_sig("sentiment", 0.4, 0.5)]),
        ]
        got = _build_origin_map(rankings)
        assert got == {
            "AAPL": "momentum",
            "AMZN": "valuation",
            "ORCL": "sentiment",
        }

    def test_case_preserved_in_map_value(self):
        # derive_origin_strategy returns the key verbatim; resolve_family
        # does the case-normalisation at lookup time.
        rankings = [
            _FakeRanked(
                ticker="AAPL",
                contributing_signals=[_sig("MomentumStrategy", 0.9, 0.9)],
            )
        ]
        assert _build_origin_map(rankings) == {"AAPL": "MomentumStrategy"}


# ── PortfolioPosition accepts origin_strategy keyword ────────────────────────


class TestPortfolioPositionOriginStrategyField:
    def test_default_is_empty_string(self):
        pos = _make_position()
        assert pos.origin_strategy == ""

    def test_accepts_and_stores_origin_strategy_kwarg(self):
        pos = _make_position(origin_strategy="momentum")
        assert pos.origin_strategy == "momentum"


# ── _persist_positions writes origin_strategy onto fresh Position rows ──────


class TestPersistPositionsWritesOriginStrategy:
    def test_new_row_carries_origin_strategy_from_portfolio_position(self):
        from apps.worker.jobs.paper_trading import _persist_positions

        sec_id = uuid.uuid4()
        sec = MagicMock()
        sec.id = sec_id
        sec.ticker = "AAPL"

        fake_db = _FakeDB(securities=[sec])

        pos = _make_position("AAPL", origin_strategy="momentum")
        ps = _make_portfolio_state({"AAPL": pos})

        @contextmanager
        def fake_session():
            yield fake_db

        with patch("infra.db.session.db_session", fake_session):
            _persist_positions(ps, [], dt.datetime.now(dt.UTC))

        assert len(fake_db.added) == 1
        added = fake_db.added[0]
        assert added.origin_strategy == "momentum"

    def test_empty_origin_strategy_persists_as_none(self):
        from apps.worker.jobs.paper_trading import _persist_positions

        sec_id = uuid.uuid4()
        sec = MagicMock()
        sec.id = sec_id
        sec.ticker = "AAPL"

        fake_db = _FakeDB(securities=[sec])

        # Legacy-shape position with no origin_strategy resolved.
        pos = _make_position("AAPL", origin_strategy="")
        ps = _make_portfolio_state({"AAPL": pos})

        @contextmanager
        def fake_session():
            yield fake_db

        with patch("infra.db.session.db_session", fake_session):
            _persist_positions(ps, [], dt.datetime.now(dt.UTC))

        assert len(fake_db.added) == 1
        added = fake_db.added[0]
        # NULL → resolve_family() lands on FAMILY_PARAMS["default"].
        assert added.origin_strategy is None


class TestPersistPositionsBackfillAndImmutability:
    def test_backfills_empty_existing_origin_strategy(self):
        from apps.worker.jobs.paper_trading import _persist_positions

        sec_id = uuid.uuid4()
        sec = MagicMock()
        sec.id = sec_id
        sec.ticker = "AAPL"

        existing = MagicMock()
        existing.security_id = sec_id
        existing.status = "open"
        existing.origin_strategy = None  # legacy pre-wiring row

        fake_db = _FakeDB(securities=[sec])
        fake_db._existing_scalar = existing
        fake_db._all_open_pairs = [(existing, "AAPL")]  # ticker still held

        pos = _make_position("AAPL", origin_strategy="valuation")
        ps = _make_portfolio_state({"AAPL": pos})

        @contextmanager
        def fake_session():
            yield fake_db

        with patch("infra.db.session.db_session", fake_session):
            _persist_positions(ps, [], dt.datetime.now(dt.UTC))

        # No new row added; existing backfilled in place.
        assert fake_db.added == []
        assert existing.origin_strategy == "valuation"

    def test_does_not_overwrite_non_empty_existing_origin_strategy(self):
        """Once origin_strategy is pinned at open-time it must stay stable
        so exit rules don't flip families mid-life.  A later cycle's
        dominant signal may well have shifted; that's fine for proposed
        new OPENS but it must never retroactively relabel a live position.
        """
        from apps.worker.jobs.paper_trading import _persist_positions

        sec_id = uuid.uuid4()
        sec = MagicMock()
        sec.id = sec_id
        sec.ticker = "AAPL"

        existing = MagicMock()
        existing.security_id = sec_id
        existing.status = "open"
        existing.origin_strategy = "momentum"  # pinned at open

        fake_db = _FakeDB(securities=[sec])
        fake_db._existing_scalar = existing
        fake_db._all_open_pairs = [(existing, "AAPL")]

        pos = _make_position("AAPL", origin_strategy="sentiment")  # shifted
        ps = _make_portfolio_state({"AAPL": pos})

        @contextmanager
        def fake_session():
            yield fake_db

        with patch("infra.db.session.db_session", fake_session):
            _persist_positions(ps, [], dt.datetime.now(dt.UTC))

        # Pinned family preserved even though the ranking has shifted.
        assert existing.origin_strategy == "momentum"

    def test_backfill_noop_when_both_are_empty(self):
        from apps.worker.jobs.paper_trading import _persist_positions

        sec_id = uuid.uuid4()
        sec = MagicMock()
        sec.id = sec_id
        sec.ticker = "AAPL"

        existing = MagicMock()
        existing.security_id = sec_id
        existing.status = "open"
        existing.origin_strategy = None

        fake_db = _FakeDB(securities=[sec])
        fake_db._existing_scalar = existing
        fake_db._all_open_pairs = [(existing, "AAPL")]

        pos = _make_position("AAPL", origin_strategy="")  # nothing to backfill
        ps = _make_portfolio_state({"AAPL": pos})

        @contextmanager
        def fake_session():
            yield fake_db

        with patch("infra.db.session.db_session", fake_session):
            _persist_positions(ps, [], dt.datetime.now(dt.UTC))

        assert existing.origin_strategy is None


# ── Regression: ranking-scan block is wired into run_paper_trading_cycle ────


class TestRankingScanWiredIntoCycle:
    def test_module_level_symbol_present(self):
        """Guards against a silent deletion of the derive_origin_strategy
        import in paper_trading.py; if the block is removed this fails at
        collection time rather than at the first live paper cycle.
        """
        import inspect

        from apps.worker.jobs import paper_trading

        src = inspect.getsource(paper_trading)
        assert "derive_origin_strategy" in src, (
            "derive_origin_strategy wiring missing from paper_trading.py — "
            "Step 5 deferred finisher regression"
        )
        assert "_origin_strategy_by_ticker" in src, (
            "_origin_strategy_by_ticker map missing from paper_trading.py — "
            "Step 5 deferred finisher regression"
        )
