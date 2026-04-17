"""
Unit tests for PointInTimeUniverseService (Phase A.2).

No network, no NDU — the underlying PointInTimeAdapter is replaced with
a stub, and the module-level ``_was_index_member`` helper is patched
with a lookup table so tests run anywhere.
"""
from __future__ import annotations

import datetime as dt
import sys
import types
from unittest.mock import MagicMock

import pandas as pd
import pytest


# ----------------------------------------------------------------------
# Stub adapter — keeps the interface we consume (watchlist_symbols)
# ----------------------------------------------------------------------
class _StubAdapter:
    def __init__(self, watchlist: list[str]) -> None:
        self._watchlist = list(watchlist)
        self.watchlist_symbols_calls: list[str] = []

    def watchlist_symbols(self, name: str) -> list[str]:
        self.watchlist_symbols_calls.append(name)
        return list(self._watchlist)


def _install_fake_norgatedata(
    monkeypatch: pytest.MonkeyPatch,
    membership_table: dict[tuple[str, str, dt.date], bool],
) -> types.ModuleType:
    """Install a fake ``norgatedata`` module that answers constituent queries
    from a (ticker, index_name, date) lookup table.
    """
    fake = types.ModuleType("norgatedata")

    class _PaddingType:
        NONE = 0

    fake.PaddingType = _PaddingType  # type: ignore[attr-defined]

    def _index_constituent_timeseries(ticker, **kwargs):  # noqa: ANN001
        index_name = kwargs["indexname"]
        as_of = dt.date.fromisoformat(kwargs["start_date"])
        is_member = membership_table.get((ticker, index_name, as_of), False)
        return pd.DataFrame(
            {"Index Constituent": [1 if is_member else 0]},
            index=[pd.Timestamp(as_of)],
        )

    fake.index_constituent_timeseries = _index_constituent_timeseries  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "norgatedata", fake)
    return fake


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------


class TestPointInTimeUniverseServiceBasics:

    def test_candidate_pool_reads_watchlist(self) -> None:
        from services.universe_management.pointintime_source import (
            PointInTimeUniverseService,
        )
        stub = _StubAdapter(["AAPL", "MSFT", "LEH-200809"])
        svc = PointInTimeUniverseService(adapter=stub)
        pool = svc.get_candidate_pool()
        assert pool == ["AAPL", "MSFT", "LEH-200809"]
        assert stub.watchlist_symbols_calls == ["S&P 500 Current & Past"]

    def test_candidate_pool_is_cached(self) -> None:
        from services.universe_management.pointintime_source import (
            PointInTimeUniverseService,
        )
        stub = _StubAdapter(["AAPL"])
        svc = PointInTimeUniverseService(adapter=stub)
        svc.get_candidate_pool()
        svc.get_candidate_pool()
        # watchlist_symbols hit the adapter only once
        assert len(stub.watchlist_symbols_calls) == 1

    def test_empty_candidate_pool_short_circuits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services.universe_management.pointintime_source import (
            PointInTimeUniverseService,
        )
        _install_fake_norgatedata(monkeypatch, {})
        stub = _StubAdapter([])
        svc = PointInTimeUniverseService(adapter=stub)
        assert svc.get_universe_as_of(dt.date(2024, 1, 3)) == []


class TestUniverseAsOf:

    def test_filters_candidates_by_as_of_membership(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services.universe_management.pointintime_source import (
            PointInTimeUniverseService,
        )
        # Setup: on 2010-01-04 only AAPL + LEH were S&P 500 members
        as_of = dt.date(2010, 1, 4)
        table = {
            ("AAPL",       "S&P 500", as_of): True,
            ("MSFT",       "S&P 500", as_of): False,  # assume not yet
            ("LEH-200809", "S&P 500", as_of): True,
            ("NEW-2023",   "S&P 500", as_of): False,
        }
        _install_fake_norgatedata(monkeypatch, table)

        stub = _StubAdapter(["AAPL", "MSFT", "LEH-200809", "NEW-2023"])
        svc = PointInTimeUniverseService(adapter=stub)

        members = svc.get_universe_as_of(as_of)
        assert members == ["AAPL", "LEH-200809"]  # sorted, survivorship-safe

    def test_universe_cache_hits_second_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services.universe_management.pointintime_source import (
            PointInTimeUniverseService,
        )
        as_of = dt.date(2015, 6, 30)
        table = {("AAPL", "S&P 500", as_of): True}
        fake = _install_fake_norgatedata(monkeypatch, table)
        # Wrap the constituent function in a MagicMock to count calls
        fake.index_constituent_timeseries = MagicMock(  # type: ignore[attr-defined]
            wraps=fake.index_constituent_timeseries
        )

        stub = _StubAdapter(["AAPL"])
        svc = PointInTimeUniverseService(adapter=stub)
        svc.get_universe_as_of(as_of)
        svc.get_universe_as_of(as_of)   # cache hit
        assert fake.index_constituent_timeseries.call_count == 1

    def test_different_dates_are_cached_independently(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services.universe_management.pointintime_source import (
            PointInTimeUniverseService,
        )
        d1 = dt.date(2010, 1, 4)
        d2 = dt.date(2020, 1, 2)
        table = {
            ("AAPL", "S&P 500", d1): True,
            ("AAPL", "S&P 500", d2): True,
            ("MSFT", "S&P 500", d1): False,
            ("MSFT", "S&P 500", d2): True,
        }
        _install_fake_norgatedata(monkeypatch, table)
        stub = _StubAdapter(["AAPL", "MSFT"])
        svc = PointInTimeUniverseService(adapter=stub)

        assert svc.get_universe_as_of(d1) == ["AAPL"]
        assert svc.get_universe_as_of(d2) == ["AAPL", "MSFT"]

    def test_empty_dataframe_treated_as_non_member(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services.universe_management.pointintime_source import (
            PointInTimeUniverseService,
        )
        fake = types.ModuleType("norgatedata")

        class _P:
            NONE = 0
        fake.PaddingType = _P  # type: ignore[attr-defined]

        def _empty(*args, **kwargs):  # noqa: ANN001, ANN002
            return pd.DataFrame()
        fake.index_constituent_timeseries = _empty  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "norgatedata", fake)

        stub = _StubAdapter(["AAPL"])
        svc = PointInTimeUniverseService(adapter=stub)
        assert svc.get_universe_as_of(dt.date(2010, 1, 4)) == []

    def test_constituent_exception_is_logged_not_raised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services.universe_management.pointintime_source import (
            PointInTimeUniverseService,
        )
        fake = types.ModuleType("norgatedata")

        class _P:
            NONE = 0
        fake.PaddingType = _P  # type: ignore[attr-defined]
        fake.index_constituent_timeseries = MagicMock(side_effect=RuntimeError("NDU offline"))  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "norgatedata", fake)

        stub = _StubAdapter(["AAPL", "MSFT"])
        svc = PointInTimeUniverseService(adapter=stub)
        # Should swallow and return empty, not propagate
        assert svc.get_universe_as_of(dt.date(2010, 1, 4)) == []


class TestRangeIteration:

    def test_iter_universe_over_range_yields_per_day(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services.universe_management.pointintime_source import (
            PointInTimeUniverseService,
        )
        d1 = dt.date(2020, 1, 2)
        d2 = dt.date(2020, 1, 3)
        d3 = dt.date(2020, 1, 4)
        table = {
            ("AAPL", "S&P 500", d1): True,
            ("AAPL", "S&P 500", d2): True,
            ("AAPL", "S&P 500", d3): True,
        }
        _install_fake_norgatedata(monkeypatch, table)
        stub = _StubAdapter(["AAPL"])
        svc = PointInTimeUniverseService(adapter=stub)
        got = list(svc.iter_universe_over_range(d1, d3))
        assert [d for d, _ in got] == [d1, d2, d3]
        assert all(members == ["AAPL"] for _, members in got)

    def test_iter_respects_step_days(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services.universe_management.pointintime_source import (
            PointInTimeUniverseService,
        )
        d1 = dt.date(2020, 1, 1)
        d8 = dt.date(2020, 1, 8)
        table = {
            ("AAPL", "S&P 500", d1): True,
            ("AAPL", "S&P 500", d8): True,
        }
        _install_fake_norgatedata(monkeypatch, table)
        stub = _StubAdapter(["AAPL"])
        svc = PointInTimeUniverseService(adapter=stub)
        got = list(svc.iter_universe_over_range(d1, d8, step_days=7))
        assert [d for d, _ in got] == [d1, d8]


class TestCacheControl:

    def test_clear_cache_forces_refetch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services.universe_management.pointintime_source import (
            PointInTimeUniverseService,
        )
        as_of = dt.date(2015, 6, 30)
        table = {("AAPL", "S&P 500", as_of): True}
        fake = _install_fake_norgatedata(monkeypatch, table)
        fake.index_constituent_timeseries = MagicMock(  # type: ignore[attr-defined]
            wraps=fake.index_constituent_timeseries
        )

        stub = _StubAdapter(["AAPL"])
        svc = PointInTimeUniverseService(adapter=stub)
        svc.get_universe_as_of(as_of)
        svc.clear_cache()
        svc.get_universe_as_of(as_of)
        # Called twice because cache was cleared
        assert fake.index_constituent_timeseries.call_count == 2
        # Watchlist also refetched
        assert len(stub.watchlist_symbols_calls) == 2
