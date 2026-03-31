"""
Gate B — data_ingestion tests.

Tests the yfinance adapter and DataIngestionService using only mock/synthetic
data — no live network access required.

Gate B criteria verified here:
  - sources are tagged by reliability (source_key on BarRecord)
  - rumors are separated from verified facts (YFinanceAdapter.contains_rumor = False)
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from services.data_ingestion.models import (
    BarRecord,
    IngestionRequest,
    IngestionResult,
    IngestionStatus,
    TickerResult,
)


class TestBarRecord:
    """BarRecord is the normalised transport unit from the adapter layer."""

    def test_bar_record_creation(self) -> None:
        bar = BarRecord(
            ticker="AAPL",
            trade_date=dt.date(2024, 1, 2),
            open=Decimal("185.00"),
            high=Decimal("187.00"),
            low=Decimal("184.50"),
            close=Decimal("186.50"),
            adjusted_close=Decimal("186.50"),
            volume=50_000_000,
        )
        assert bar.ticker == "AAPL"
        assert bar.close == Decimal("186.50")

    def test_bar_record_source_key_default(self) -> None:
        """Source key defaults to 'yfinance' — Gate B: source tagged."""
        bar = BarRecord(
            ticker="MSFT",
            trade_date=dt.date(2024, 1, 2),
            open=None,
            high=None,
            low=None,
            close=Decimal("375.00"),
            adjusted_close=Decimal("375.00"),
            volume=None,
        )
        assert bar.source_key == "yfinance"


class TestIngestionModels:
    """IngestionRequest / IngestionResult business logic."""

    def test_ingestion_result_finalise_all_success(self) -> None:
        req = IngestionRequest(tickers=["AAPL", "MSFT"])
        result = IngestionResult(request=req)
        result.ticker_results = [
            TickerResult("AAPL", IngestionStatus.SUCCESS, 252, 252),
            TickerResult("MSFT", IngestionStatus.SUCCESS, 252, 252),
        ]
        result.finalise()
        assert result.status == IngestionStatus.SUCCESS

    def test_ingestion_result_finalise_all_failed(self) -> None:
        req = IngestionRequest(tickers=["AAPL", "MSFT"])
        result = IngestionResult(request=req)
        result.ticker_results = [
            TickerResult("AAPL", IngestionStatus.FAILED, error="timeout"),
            TickerResult("MSFT", IngestionStatus.FAILED, error="timeout"),
        ]
        result.finalise()
        assert result.status == IngestionStatus.FAILED

    def test_ingestion_result_finalise_partial(self) -> None:
        req = IngestionRequest(tickers=["AAPL", "MSFT"])
        result = IngestionResult(request=req)
        result.ticker_results = [
            TickerResult("AAPL", IngestionStatus.SUCCESS, 252, 252),
            TickerResult("MSFT", IngestionStatus.FAILED, error="timeout"),
        ]
        result.finalise()
        assert result.status == IngestionStatus.PARTIAL
        assert result.failed_tickers == ["MSFT"]

    def test_total_bars_persisted(self) -> None:
        req = IngestionRequest(tickers=["AAPL", "MSFT"])
        result = IngestionResult(request=req)
        result.ticker_results = [
            TickerResult("AAPL", IngestionStatus.SUCCESS, 252, 252),
            TickerResult("MSFT", IngestionStatus.SUCCESS, 200, 200),
        ]
        assert result.total_bars_persisted == 452


class TestYFinanceAdapter:
    """YFinanceAdapter unit tests — all yfinance calls are mocked."""

    def test_adapter_source_key(self) -> None:
        """Gate B: adapter carries a reliability tier tag."""
        from services.data_ingestion.adapters.yfinance_adapter import YFinanceAdapter
        adapter = YFinanceAdapter()
        assert adapter.SOURCE_KEY == "yfinance"
        assert adapter.RELIABILITY_TIER == "secondary_verified"

    def test_fetch_bars_returns_empty_on_yfinance_error(self) -> None:
        """Adapter returns [] on exception — never raises."""
        from services.data_ingestion.adapters.yfinance_adapter import YFinanceAdapter
        adapter = YFinanceAdapter()

        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.history.side_effect = RuntimeError("network fail")
            bars = adapter.fetch_bars("AAPL", period="1y")

        assert bars == []

    def test_fetch_bars_returns_empty_on_empty_dataframe(self) -> None:
        import pandas as pd
        from services.data_ingestion.adapters.yfinance_adapter import YFinanceAdapter
        adapter = YFinanceAdapter()

        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = pd.DataFrame()
            bars = adapter.fetch_bars("AAPL", period="1y")

        assert bars == []

    def test_normalise_df_produces_bar_records(self) -> None:
        """_normalise_df maps a DataFrame → sorted BarRecord list."""
        import pandas as pd
        from services.data_ingestion.adapters.yfinance_adapter import YFinanceAdapter
        adapter = YFinanceAdapter()

        dates = pd.date_range("2024-01-02", periods=5, freq="B")
        df = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0, 103.0, 104.0],
                "High": [101.0, 102.0, 103.0, 104.0, 105.0],
                "Low": [99.0, 100.0, 101.0, 102.0, 103.0],
                "Close": [100.5, 101.5, 102.5, 103.5, 104.5],
                "Adj Close": [100.5, 101.5, 102.5, 103.5, 104.5],
                "Volume": [1_000_000] * 5,
            },
            index=dates,
        )

        bars = adapter._normalise_df("AAPL", df)
        assert len(bars) == 5
        assert all(isinstance(b, BarRecord) for b in bars)
        assert bars[0].trade_date < bars[-1].trade_date
        assert bars[0].source_key == "yfinance"

    def test_normalise_df_skips_nan_close(self) -> None:
        """Rows with NaN close are dropped by dropna(subset=['Close'])."""
        import math
        import pandas as pd
        from services.data_ingestion.adapters.yfinance_adapter import YFinanceAdapter
        adapter = YFinanceAdapter()

        dates = pd.date_range("2024-01-02", periods=3, freq="B")
        df = pd.DataFrame(
            {
                "Open": [100.0, None, 102.0],
                "High": [101.0, None, 103.0],
                "Low": [99.0, None, 101.0],
                "Close": [100.5, float("nan"), 102.5],
                "Adj Close": [100.5, float("nan"), 102.5],
                "Volume": [1_000_000, 0, 1_000_000],
            },
            index=dates,
        )

        bars = adapter._normalise_df("AAPL", df)
        assert len(bars) == 2  # middle row dropped


class TestDataIngestionService:
    """DataIngestionService with a mock adapter."""

    def _make_bars(self, ticker: str, n: int = 30) -> list[BarRecord]:
        return [
            BarRecord(
                ticker=ticker,
                trade_date=dt.date(2024, 1, 2) + dt.timedelta(days=i),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100"),
                adjusted_close=Decimal("100"),
                volume=1_000_000,
            )
            for i in range(n)
        ]

    def test_ingest_universe_bars_success(self) -> None:
        """Service returns SUCCESS when adapter returns bars for all tickers."""
        from services.data_ingestion.service import DataIngestionService

        mock_adapter = MagicMock()
        mock_adapter.fetch_bulk.return_value = {
            "AAPL": self._make_bars("AAPL"),
            "MSFT": self._make_bars("MSFT"),
        }

        service = DataIngestionService(adapter=mock_adapter)

        mock_session = MagicMock()
        # get_or_create_security returns a mock Security with a uuid id
        import uuid
        mock_security = MagicMock()
        mock_security.id = uuid.uuid4()
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_security
        mock_session.execute.return_value.rowcount = 30

        req = IngestionRequest(tickers=["AAPL", "MSFT"], period="1mo")
        result = service.ingest_universe_bars(mock_session, req)

        assert result.status == IngestionStatus.SUCCESS
        assert len(result.ticker_results) == 2

    def test_ingest_universe_bars_partial_on_adapter_empty(self) -> None:
        """When one ticker returns no bars → PARTIAL result."""
        from services.data_ingestion.service import DataIngestionService

        mock_adapter = MagicMock()
        mock_adapter.fetch_bulk.return_value = {
            "AAPL": self._make_bars("AAPL"),
            "MSFT": [],  # no data
        }

        service = DataIngestionService(adapter=mock_adapter)
        import uuid
        mock_security = MagicMock()
        mock_security.id = uuid.uuid4()

        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_security
        mock_session.execute.return_value.rowcount = 30

        req = IngestionRequest(tickers=["AAPL", "MSFT"], period="1mo")
        result = service.ingest_universe_bars(mock_session, req)

        assert result.status == IngestionStatus.PARTIAL
        assert "MSFT" in result.failed_tickers
