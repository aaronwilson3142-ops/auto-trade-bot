"""
Unit tests for PointInTimeAdapter (Norgate Data).

These tests do NOT require NDU to be running or the `norgatedata` package
to be installed — all calls into Norgate are patched.  This keeps CI clean
and means the suite passes regardless of whether the developer has a
Norgate subscription at the time of the test run.

Safe for the 2-year Norgate trial: dates chosen here are 2025-adjacent
so they fall inside the trial window if a developer ever wires this up
to live data for smoke-testing.
"""
from __future__ import annotations

import datetime as dt
import sys
import types
from decimal import Decimal
from unittest.mock import MagicMock

import pandas as pd
import pytest

from services.data_ingestion.models import BarRecord


def _install_fake_norgatedata(monkeypatch: pytest.MonkeyPatch, module: types.ModuleType) -> None:
    """Install a fake `norgatedata` module in sys.modules for the duration of a test."""
    monkeypatch.setitem(sys.modules, "norgatedata", module)


def _make_norgate_df() -> pd.DataFrame:
    """Build a DataFrame shaped like what nd.price_timeseries returns."""
    dates = pd.date_range("2025-01-02", periods=5, freq="B")
    return pd.DataFrame(
        {
            "Open":              [100.0, 101.0, 102.0, 103.0, 104.0],
            "High":              [101.0, 102.0, 103.0, 104.0, 105.0],
            "Low":               [ 99.0, 100.0, 101.0, 102.0, 103.0],
            "Close":             [100.5, 101.5, 102.5, 103.5, 104.5],  # adjusted
            "Unadjusted Close":  [ 50.0,  50.5,  51.0,  51.5,  52.0],  # raw printed
            "Volume":            [1_000_000] * 5,
        },
        index=dates,
    )


class TestPointInTimeAdapterBasics:
    """Core adapter surface — no external I/O."""

    def test_source_key_and_tier(self) -> None:
        """Reliability tag distinguishes Norgate from yfinance."""
        from services.data_ingestion.adapters.pointintime_adapter import (
            PointInTimeAdapter,
        )
        adapter = PointInTimeAdapter()
        assert adapter.SOURCE_KEY == "norgate_platinum"
        assert adapter.RELIABILITY_TIER == "primary_verified"

    def test_fetch_bars_returns_empty_when_package_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing `norgatedata` → log + return [], never raise."""
        from services.data_ingestion.adapters.pointintime_adapter import (
            PointInTimeAdapter,
        )

        # Make 'import norgatedata' raise ImportError
        monkeypatch.setitem(sys.modules, "norgatedata", None)
        adapter = PointInTimeAdapter()
        # Patch the builtin import to fail for this name specifically
        import builtins

        real_import = builtins.__import__

        def fake_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "norgatedata":
                raise ImportError("not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        bars = adapter.fetch_bars("AAPL", period="1y")
        assert bars == []

    def test_fetch_bars_returns_empty_on_norgate_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If Norgate raises, adapter swallows and returns []."""
        fake = types.ModuleType("norgatedata")
        fake.price_timeseries = MagicMock(side_effect=RuntimeError("NDU offline"))  # type: ignore[attr-defined]
        _install_fake_norgatedata(monkeypatch, fake)

        from services.data_ingestion.adapters.pointintime_adapter import (
            PointInTimeAdapter,
        )
        bars = PointInTimeAdapter().fetch_bars("AAPL", period="1y")
        assert bars == []

    def test_fetch_bars_returns_empty_on_empty_dataframe(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = types.ModuleType("norgatedata")
        fake.price_timeseries = MagicMock(return_value=pd.DataFrame())  # type: ignore[attr-defined]
        _install_fake_norgatedata(monkeypatch, fake)

        from services.data_ingestion.adapters.pointintime_adapter import (
            PointInTimeAdapter,
        )
        bars = PointInTimeAdapter().fetch_bars("AAPL", period="1y")
        assert bars == []


class TestPointInTimeAdapterNormalisation:
    """The DataFrame → BarRecord mapping is the trickiest part."""

    def test_normalise_maps_unadjusted_to_close_and_adjusted_to_adj_close(self) -> None:
        """
        Norgate's "Close" is split/div-adjusted; "Unadjusted Close" is the raw
        printed close.  Our BarRecord convention mirrors yfinance
        (auto_adjust=False): close=raw, adjusted_close=adjusted.
        """
        from services.data_ingestion.adapters.pointintime_adapter import (
            PointInTimeAdapter,
        )
        adapter = PointInTimeAdapter()

        bars = adapter._normalise_df("AAPL", _make_norgate_df())
        assert len(bars) == 5
        assert all(isinstance(b, BarRecord) for b in bars)
        # sorted ascending
        assert bars[0].trade_date < bars[-1].trade_date
        # source key is stamped
        assert bars[0].source_key == "norgate_platinum"
        # close == unadjusted; adjusted_close == adjusted
        assert bars[0].close == Decimal("50.0")
        assert bars[0].adjusted_close == Decimal("100.5")

    def test_normalise_falls_back_when_no_unadjusted_column(self) -> None:
        """If the Unadjusted Close column is absent, close == adjusted_close."""
        from services.data_ingestion.adapters.pointintime_adapter import (
            PointInTimeAdapter,
        )
        adapter = PointInTimeAdapter()

        df = _make_norgate_df().drop(columns=["Unadjusted Close"])
        bars = adapter._normalise_df("MSFT", df)
        assert len(bars) == 5
        assert bars[0].close == bars[0].adjusted_close

    def test_fetch_bars_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """End-to-end: Norgate returns 5 bars, adapter emits 5 BarRecords."""
        fake = types.ModuleType("norgatedata")
        fake.price_timeseries = MagicMock(return_value=_make_norgate_df())  # type: ignore[attr-defined]
        _install_fake_norgatedata(monkeypatch, fake)

        from services.data_ingestion.adapters.pointintime_adapter import (
            PointInTimeAdapter,
        )
        bars = PointInTimeAdapter().fetch_bars(
            "AAPL",
            start=dt.date(2025, 1, 1),
            end=dt.date(2025, 1, 10),
        )
        assert len(bars) == 5
        assert bars[0].source_key == "norgate_platinum"

        # Verify call shape: start_date/end_date/timeseriesformat kwargs used
        kwargs = fake.price_timeseries.call_args.kwargs
        assert kwargs["timeseriesformat"] == "pandas-dataframe"
        assert kwargs["start_date"] == "2025-01-01"
        assert kwargs["end_date"] == "2025-01-10"


class TestPointInTimeAdapterDateResolution:
    """period= strings must translate into start/end ranges."""

    def test_period_1y_resolves_to_roughly_one_year(self) -> None:
        from services.data_ingestion.adapters.pointintime_adapter import (
            PointInTimeAdapter,
        )
        adapter = PointInTimeAdapter()
        start, end = adapter._resolve_date_range("1y", None, None)
        assert start is not None
        assert end is not None
        assert (end - start).days >= 365

    def test_explicit_start_end_override_period(self) -> None:
        from services.data_ingestion.adapters.pointintime_adapter import (
            PointInTimeAdapter,
        )
        adapter = PointInTimeAdapter()
        s, e = adapter._resolve_date_range(
            "1y", dt.date(2025, 1, 1), dt.date(2025, 6, 30)
        )
        assert s == dt.date(2025, 1, 1)
        assert e == dt.date(2025, 6, 30)

    def test_period_max_resolves_to_none_start(self) -> None:
        from services.data_ingestion.adapters.pointintime_adapter import (
            PointInTimeAdapter,
        )
        adapter = PointInTimeAdapter()
        start, _ = adapter._resolve_date_range("max", None, None)
        assert start is None


class TestPointInTimeAdapterBulk:
    """fetch_bulk fans out over fetch_bars serially."""

    def test_fetch_bulk_returns_one_list_per_ticker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = types.ModuleType("norgatedata")
        fake.price_timeseries = MagicMock(return_value=_make_norgate_df())  # type: ignore[attr-defined]
        _install_fake_norgatedata(monkeypatch, fake)

        from services.data_ingestion.adapters.pointintime_adapter import (
            PointInTimeAdapter,
        )
        out = PointInTimeAdapter().fetch_bulk(["AAPL", "MSFT"], period="6mo")
        assert set(out.keys()) == {"AAPL", "MSFT"}
        assert len(out["AAPL"]) == 5
        assert len(out["MSFT"]) == 5

    def test_fetch_bulk_empty_tickers(self) -> None:
        from services.data_ingestion.adapters.pointintime_adapter import (
            PointInTimeAdapter,
        )
        assert PointInTimeAdapter().fetch_bulk([]) == {}


class TestAdapterFactorySelection:
    """The data_ingestion service picks the adapter based on settings.data_source."""

    def test_factory_defaults_to_yfinance_when_settings_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services.data_ingestion import service as svc_mod
        from services.data_ingestion.adapters.yfinance_adapter import YFinanceAdapter

        adapter = svc_mod._build_default_adapter()
        # Default data_source is YFINANCE
        assert isinstance(adapter, YFinanceAdapter)

    def test_factory_returns_pointintime_when_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from config.settings import DataSource, get_settings
        from services.data_ingestion import service as svc_mod
        from services.data_ingestion.adapters.pointintime_adapter import (
            PointInTimeAdapter,
        )

        settings = get_settings()
        monkeypatch.setattr(settings, "data_source", DataSource.POINTINTIME)
        adapter = svc_mod._build_default_adapter()
        assert isinstance(adapter, PointInTimeAdapter)
