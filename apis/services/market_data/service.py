"""MarketDataService — concrete normalized-price + liquidity snapshot provider.

Uses the existing YFinanceAdapter as the data back-end.  No DB required;
all state is fetched and computed in-memory on demand.

Spec reference: APIS_MASTER_SPEC.md §7.1
"""
from __future__ import annotations

import datetime as dt
import logging

from services.data_ingestion.adapters.yfinance_adapter import YFinanceAdapter
from services.market_data.config import MarketDataConfig
from services.market_data.models import LiquidityMetrics, MarketSnapshot, NormalizedBar
from services.market_data.utils import compute_liquidity_metrics

logger = logging.getLogger(__name__)


class MarketDataService:
    """Fetch normalized bars and liquidity metrics for equity securities.

    All data comes from Yahoo Finance (secondary_verified, delayed EOD).
    No database interaction — consumers are responsible for any persistence.

    Args:
        config:  MarketDataConfig with threshold and window parameters.
        adapter: YFinanceAdapter instance.  Defaults to a new instance.
    """

    def __init__(
        self,
        config: MarketDataConfig | None = None,
        adapter: YFinanceAdapter | None = None,
    ) -> None:
        self._config = config or MarketDataConfig()
        self._adapter = adapter or YFinanceAdapter()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_normalized_bars(
        self,
        ticker: str,
        period: str | None = None,
    ) -> list[NormalizedBar]:
        """Return a list of NormalizedBar objects for *ticker*.

        Args:
            ticker: Equity symbol, e.g. "AAPL".
            period: yfinance period string (default: config.default_period).

        Returns:
            List sorted ascending by trade_date.  Empty on any fetch error.
        """
        _period = period or self._config.default_period
        bars = self._adapter.fetch_bars(ticker, period=_period)
        if not bars:
            logger.warning("No bars returned for %s (period=%s)", ticker, _period)
            return []
        # Convert BarRecord objects from data_ingestion to NormalizedBar
        return [
            NormalizedBar(
                ticker=ticker,
                trade_date=b.trade_date,
                open=b.open or b.close,
                high=b.high or b.close,
                low=b.low or b.close,
                close=b.close,
                adjusted_close=b.adjusted_close or b.close,
                volume=b.volume or 0,
            )
            for b in bars
            if b.close is not None
        ]

    def get_snapshot(self, ticker: str) -> MarketSnapshot:
        """Return the complete MarketSnapshot for *ticker* including liquidity."""
        now = dt.datetime.now(dt.UTC)
        bars = self.get_normalized_bars(ticker)
        if not bars:
            logger.warning("Empty snapshot for %s — fetch returned no bars", ticker)
            return MarketSnapshot(ticker=ticker.upper(), as_of=now)
        liquidity = compute_liquidity_metrics(
            ticker,
            bars,
            short_window=self._config.liquidity_window_short,
            long_window=self._config.liquidity_window_long,
            high_threshold=self._config.high_liquidity_threshold,
            mid_threshold=self._config.mid_liquidity_threshold,
            low_threshold=self._config.low_liquidity_threshold,
        )
        return MarketSnapshot(
            ticker=ticker.upper(),
            as_of=now,
            latest_bar=bars[-1],
            liquidity=liquidity,
            bars_1y=bars[-252:],
        )

    def get_snapshots(
        self, tickers: list[str]
    ) -> dict[str, MarketSnapshot]:
        """Return MarketSnapshot objects for a list of tickers.

        Returns a dict of ticker → MarketSnapshot.  Failed tickers produce
        an empty snapshot rather than raising.
        """
        result: dict[str, MarketSnapshot] = {}
        for ticker in tickers:
            try:
                result[ticker.upper()] = self.get_snapshot(ticker)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to fetch snapshot for %s: %s", ticker, exc)
                result[ticker.upper()] = MarketSnapshot(
                    ticker=ticker.upper(),
                    as_of=dt.datetime.now(dt.UTC),
                )
        return result

    def compute_liquidity(
        self,
        ticker: str,
        bars: list[NormalizedBar] | None = None,
    ) -> LiquidityMetrics:
        """Compute liquidity metrics from pre-fetched bars or fetch fresh."""
        if bars is None:
            bars = self.get_normalized_bars(ticker)
        if not bars:
            return LiquidityMetrics(
                ticker=ticker.upper(),
                as_of=dt.date.today(),
                liquidity_tier="unknown",
            )
        return compute_liquidity_metrics(
            ticker,
            bars,
            short_window=self._config.liquidity_window_short,
            long_window=self._config.liquidity_window_long,
            high_threshold=self._config.high_liquidity_threshold,
            mid_threshold=self._config.mid_liquidity_threshold,
            low_threshold=self._config.low_liquidity_threshold,
        )

