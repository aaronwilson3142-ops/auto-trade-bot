"""Alternative data source adapters.

BaseAlternativeAdapter defines the adapter interface.
SocialMentionAdapter is a deterministic stub that returns synthetic social
sentiment scores derived from ticker hash — no external API required.
Operators may replace this with a real Reddit/StockTwits/Twitter adapter.

Phase 36 — Alternative Data Integration
"""
from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from typing import Sequence

from services.alternative_data.models import AlternativeDataRecord, AlternativeDataSource


class BaseAlternativeAdapter(ABC):
    """Abstract base for pluggable alternative data source adapters."""

    @property
    @abstractmethod
    def source(self) -> AlternativeDataSource:
        """Identifier for this adapter's data source."""

    @abstractmethod
    def fetch(self, tickers: Sequence[str]) -> list[AlternativeDataRecord]:
        """Fetch alternative data records for the given tickers.

        Args:
            tickers: Sequence of uppercase ticker symbols to fetch data for.

        Returns:
            List of AlternativeDataRecord objects (may be empty).
        """


class SocialMentionAdapter(BaseAlternativeAdapter):
    """Synthetic social-mention sentiment adapter (deterministic stub).

    Generates repeatable sentiment scores from ticker hash so tests and
    paper-trading backtests are deterministic without any external API calls.

    In production this class would be replaced by a real adapter that queries
    Reddit's Pushshift API, StockTwits stream, or a licensed data feed.

    Sentiment formula:
      seed   = sum(ord(c) for c in ticker)
      raw    = ((seed * 7919) % 2001 - 1000) / 1000.0   → [-1.0, 1.0]
      mentions = (seed % 50) + 1
    """

    @property
    def source(self) -> AlternativeDataSource:
        return AlternativeDataSource.SOCIAL_MENTION

    def fetch(self, tickers: Sequence[str]) -> list[AlternativeDataRecord]:
        records: list[AlternativeDataRecord] = []
        now = dt.datetime.now(dt.timezone.utc)

        for ticker in tickers:
            seed = sum(ord(c) for c in ticker.upper())
            raw_score = ((seed * 7919) % 2001 - 1000) / 1000.0
            mentions = (seed % 50) + 1
            records.append(
                AlternativeDataRecord(
                    ticker=ticker.upper(),
                    source=self.source,
                    sentiment_score=round(raw_score, 4),
                    mention_count=mentions,
                    raw_snippet=f"Synthetic social sentiment for {ticker.upper()} (seed={seed})",
                    captured_at=now,
                )
            )

        return records
