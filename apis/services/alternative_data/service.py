"""AlternativeDataService — manages alternative data ingestion and retrieval.

Public API
----------
ingest(adapter, tickers)    — fetch records from an adapter, merge into store
get_records(ticker, limit)  — retrieve stored records (optional ticker filter)
get_ticker_sentiment(ticker) — aggregate sentiment score for one ticker

Design
------
- In-memory store (list[AlternativeDataRecord]) partitioned by ticker.
- Fire-and-forget: ingest() never raises — errors are logged and skipped.
- Thread-safe via simple list copy (single-process, GIL-protected).

Phase 36 — Alternative Data Integration
"""
from __future__ import annotations

from typing import Optional, Sequence

from config.logging_config import get_logger
from services.alternative_data.adapters import BaseAlternativeAdapter
from services.alternative_data.models import AlternativeDataRecord

logger = get_logger(__name__)


class AlternativeDataService:
    """In-memory store and retrieval for alternative data records."""

    def __init__(self) -> None:
        self._records: list[AlternativeDataRecord] = []

    # ── Ingestion ─────────────────────────────────────────────────────────────

    def ingest(
        self,
        adapter: BaseAlternativeAdapter,
        tickers: Sequence[str],
    ) -> int:
        """Fetch records from adapter and append to the in-memory store.

        Returns:
            Number of new records ingested (0 if adapter failed).
        """
        try:
            new_records = adapter.fetch(tickers)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "alternative_data_ingest_failed",
                adapter=adapter.source.value,
                error=str(exc),
            )
            return 0

        self._records.extend(new_records)
        logger.info(
            "alternative_data_ingested",
            adapter=adapter.source.value,
            count=len(new_records),
            total_stored=len(self._records),
        )
        return len(new_records)

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def get_records(
        self,
        ticker: Optional[str] = None,
        limit: int = 100,
    ) -> list[AlternativeDataRecord]:
        """Return stored records, newest-first, optionally filtered by ticker.

        Args:
            ticker: Optional uppercase ticker symbol.
            limit:  Maximum records to return (default 100).
        """
        records = list(reversed(self._records))
        if ticker:
            upper = ticker.upper()
            records = [r for r in records if r.ticker == upper]
        return records[:limit]

    def get_ticker_sentiment(self, ticker: str) -> Optional[float]:
        """Return the average sentiment_score for ticker, or None if no data."""
        records = self.get_records(ticker=ticker)
        if not records:
            return None
        return round(sum(r.sentiment_score for r in records) / len(records), 4)

    def clear(self) -> None:
        """Reset the in-memory store.  Useful for tests."""
        self._records.clear()

    @property
    def record_count(self) -> int:
        return len(self._records)
