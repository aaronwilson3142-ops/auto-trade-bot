"""
Data-ingestion domain models (plain dataclasses — no ORM dependency).

These are the internal transport types that flow between adapters and the
DataIngestionService.  They are deliberately decoupled from the ORM so that
adapters can be unit-tested without a database.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional


class IngestionStatus(str, Enum):
    """Terminal states for a single ingestion request."""
    SUCCESS = "success"
    PARTIAL = "partial"     # some tickers failed, others succeeded
    FAILED = "failed"
    SKIPPED = "skipped"     # already up-to-date, nothing to fetch


@dataclass
class BarRecord:
    """Normalised single OHLCV bar from any market-data adapter."""
    ticker: str
    trade_date: dt.date
    open: Optional[Decimal]
    high: Optional[Decimal]
    low: Optional[Decimal]
    close: Optional[Decimal]
    adjusted_close: Optional[Decimal]
    volume: Optional[int]
    vwap: Optional[Decimal] = None
    source_key: str = "yfinance"        # reliability tag — matches Source.source_key


@dataclass
class IngestionRequest:
    """Parameters for a batch ingestion run."""
    tickers: list[str]
    period: str = "1y"                  # yfinance period string e.g. "1y", "6mo", "3mo"
    start_date: Optional[dt.date] = None
    end_date: Optional[dt.date] = None
    source_key: str = "yfinance"


@dataclass
class TickerResult:
    """Per-ticker outcome within a batch ingestion run."""
    ticker: str
    status: IngestionStatus
    bars_fetched: int = 0
    bars_persisted: int = 0
    error: Optional[str] = None


@dataclass
class IngestionResult:
    """Aggregate result for an IngestionRequest batch."""
    request: IngestionRequest
    ticker_results: list[TickerResult] = field(default_factory=list)
    status: IngestionStatus = IngestionStatus.SUCCESS

    @property
    def total_bars_persisted(self) -> int:
        return sum(r.bars_persisted for r in self.ticker_results)

    @property
    def failed_tickers(self) -> list[str]:
        return [r.ticker for r in self.ticker_results if r.status == IngestionStatus.FAILED]

    def finalise(self) -> None:
        """Set aggregate status from individual ticker results."""
        failures = self.failed_tickers
        if not failures:
            self.status = IngestionStatus.SUCCESS
        elif len(failures) == len(self.ticker_results):
            self.status = IngestionStatus.FAILED
        else:
            self.status = IngestionStatus.PARTIAL

