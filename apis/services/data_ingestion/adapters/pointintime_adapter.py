"""
Norgate Data point-in-time market-data adapter.

Responsibility: fetch survivorship-bias-free OHLCV bars via the `norgatedata`
Python package (which reads from the locally-running Norgate Data Updater)
and normalise them into BarRecord objects.

Why this adapter exists
-----------------------
The yfinance adapter pulls only *currently listed* tickers — it cannot serve
bars for companies that have been delisted, merged, or ticker-changed.  That
produces survivorship bias in any historical backtest.  Norgate's Platinum
tier exposes both the `US Equities` and `US Equities Delisted` databases,
so this adapter is the foundation for Phase A of the APIS live-readiness
plan (APIS_IMPLEMENTATION_PLAN_2026-04-14.md).

Reliability tag: "norgate_platinum" — classified as a *primary verified*
source (exchange-sourced EOD with corporate-actions adjustments).

Trial-window caveat
-------------------
The 21-day Norgate free trial caps historical depth at ~2 years.  This
adapter works against trial data for wiring/smoke purposes, but a real
walk-forward run (Phase B) requires the paid subscription.
"""
from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal, InvalidOperation

import pandas as pd

from services.data_ingestion.models import BarRecord

logger = logging.getLogger(__name__)

# Reliability classification (primary exchange-sourced EOD, adjusted)
SOURCE_KEY = "norgate_platinum"
RELIABILITY_TIER = "primary_verified"

# Norgate database names we care about
DB_CURRENT = "US Equities"
DB_DELISTED = "US Equities Delisted"


def _to_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        import math
        if isinstance(value, float) and math.isnan(value):
            return None
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        import math
        if isinstance(value, float) and math.isnan(value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


class PointInTimeAdapter:
    """Fetches and normalises daily OHLCV data from Norgate (NDU).

    Drop-in replacement for YFinanceAdapter — same public surface so the
    DataIngestionService can switch providers via the APIS_DATA_SOURCE
    setting without other code changes.

    Usage::

        adapter = PointInTimeAdapter()
        bars = adapter.fetch_bars("AAPL", period="1y")
        bulk = adapter.fetch_bulk(["AAPL", "MSFT"], period="6mo")
    """

    SOURCE_KEY: str = SOURCE_KEY
    RELIABILITY_TIER: str = RELIABILITY_TIER

    # Norgate trial returns ~2 years; pad slightly so period="1y" still works.
    _PERIOD_TO_DAYS = {
        "1mo": 31,
        "3mo": 93,
        "6mo": 186,
        "1y": 366,
        "2y": 732,
        "5y": 1830,
        "10y": 3660,
        "ytd": None,   # handled specially
        "max": None,   # let Norgate decide
    }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_bars(
        self,
        ticker: str,
        *,
        period: str = "1y",
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> list[BarRecord]:
        """Fetch daily bars for a single ticker (live or delisted).

        Args:
            ticker: e.g. "AAPL" (current) or "LEH-200809" (delisted form
                used internally; plain "LEH" also resolves via Norgate)
            period: yfinance-style period string (ignored when start/end given)
            start:  inclusive start date
            end:    inclusive end date

        Returns:
            List of BarRecord sorted ascending by trade_date.  Returns an
            empty list on any error (logged as WARNING).
        """
        try:
            import norgatedata as nd
        except ImportError:
            logger.error("norgatedata package not installed")
            return []

        resolved_start, resolved_end = self._resolve_date_range(period, start, end)

        try:
            kwargs = {"timeseriesformat": "pandas-dataframe"}
            if resolved_start is not None:
                kwargs["start_date"] = resolved_start.isoformat()
            if resolved_end is not None:
                kwargs["end_date"] = resolved_end.isoformat()

            df = nd.price_timeseries(ticker, **kwargs)

            if df is None or df.empty:
                logger.warning(
                    "norgate returned no data for %s (start=%s end=%s)",
                    ticker, resolved_start, resolved_end,
                )
                return []

            return self._normalise_df(ticker, df)

        except Exception as exc:  # noqa: BLE001
            logger.warning("norgate fetch failed for %s: %s", ticker, exc)
            return []

    def fetch_bulk(
        self,
        tickers: list[str],
        *,
        period: str = "1y",
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> dict[str, list[BarRecord]]:
        """Fetch daily bars for multiple tickers.

        Norgate's Python API is per-symbol, so this is a serial loop — but
        every call is a local in-process read from NDU's on-disk cache,
        so the overhead is negligible compared to a yfinance HTTP round-trip.
        """
        if not tickers:
            return {}

        results: dict[str, list[BarRecord]] = {}
        for ticker in tickers:
            results[ticker] = self.fetch_bars(
                ticker, period=period, start=start, end=end,
            )
        return results

    # ------------------------------------------------------------------
    # Delisting / universe helpers (Phase A.2 will consume these)
    # ------------------------------------------------------------------

    def list_delisted_symbols(self) -> list[str]:
        """Return all symbols in the `US Equities Delisted` database."""
        try:
            import norgatedata as nd
            return list(nd.database_symbols(DB_DELISTED))
        except Exception as exc:  # noqa: BLE001
            logger.warning("cannot enumerate delisted symbols: %s", exc)
            return []

    def list_current_symbols(self) -> list[str]:
        """Return all symbols in the `US Equities` database."""
        try:
            import norgatedata as nd
            return list(nd.database_symbols(DB_CURRENT))
        except Exception as exc:  # noqa: BLE001
            logger.warning("cannot enumerate current symbols: %s", exc)
            return []

    def watchlist_symbols(self, watchlist_name: str) -> list[str]:
        """Return the member tickers of a Norgate watchlist.

        Key watchlist for us: "S&P 500 Current & Past" (survivorship-safe).
        """
        try:
            import norgatedata as nd
            return list(nd.watchlist_symbols(watchlist_name))
        except Exception as exc:  # noqa: BLE001
            logger.warning("cannot read watchlist '%s': %s", watchlist_name, exc)
            return []

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_date_range(
        self,
        period: str,
        start: dt.date | None,
        end: dt.date | None,
    ) -> tuple[dt.date | None, dt.date | None]:
        """Translate a yfinance-style `period` into (start, end) if not given."""
        if start is not None or end is not None:
            return start, end

        today = dt.date.today()
        if period == "ytd":
            return dt.date(today.year, 1, 1), today
        if period == "max":
            return None, today

        days = self._PERIOD_TO_DAYS.get(period)
        if days is None:
            # Unknown period — let Norgate return everything it has.
            return None, today
        return today - dt.timedelta(days=days), today

    def _normalise_df(self, ticker: str, df: pd.DataFrame) -> list[BarRecord]:
        """Map a raw Norgate DataFrame to a list of BarRecord.

        Norgate's DataFrame uses capitalised columns with an "Unadjusted Close"
        column alongside the split/dividend-adjusted "Close".  Map them to
        the adapter's BarRecord convention:

        - `close`          -> unadjusted close  (raw printed close)
        - `adjusted_close` -> adjusted close    (total-return / split adj.)

        This matches how the yfinance adapter populates the same fields when
        `auto_adjust=False` is used at fetch time.
        """
        records: list[BarRecord] = []

        # Normalise column access — Norgate returns CamelCase; lower-case
        # variants may appear if the package is upgraded.
        def col(row: pd.Series, *names: str) -> object:
            for name in names:
                if name in row.index:
                    return row[name]
            return None

        df = df.dropna(subset=[c for c in ("Close", "close") if c in df.columns])

        for idx, row in df.iterrows():
            try:
                trade_date = idx.date() if hasattr(idx, "date") else pd.Timestamp(idx).date()

                adj_close_val = col(row, "Close", "close")
                unadj_close_val = col(row, "Unadjusted Close", "unadjusted_close")
                # Fall back: if there's no unadjusted column, treat adj == raw
                if unadj_close_val is None:
                    unadj_close_val = adj_close_val

                records.append(
                    BarRecord(
                        ticker=ticker,
                        trade_date=trade_date,
                        open=_to_decimal(col(row, "Open", "open")),
                        high=_to_decimal(col(row, "High", "high")),
                        low=_to_decimal(col(row, "Low", "low")),
                        close=_to_decimal(unadj_close_val),
                        adjusted_close=_to_decimal(adj_close_val),
                        volume=_to_int(col(row, "Volume", "volume")),
                        source_key=SOURCE_KEY,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("Skipping malformed row for %s at %s: %s", ticker, idx, exc)

        records.sort(key=lambda b: b.trade_date)
        return records
