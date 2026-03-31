"""FundamentalsService — fetch and apply valuation / earnings fundamentals.

Wraps yfinance `Ticker.info` to extract the fundamental metrics used by the
ValuationStrategy signal family.  Design mirrors MarketDataService: all
network calls are isolated here; the rest of the pipeline consumes the
FundamentalsData dataclass.

Design rules
------------
- `fetch()` catches all yfinance exceptions and returns a FundamentalsData
  with None fields rather than raising — a missing data point must never
  break the signal pipeline.
- `fetch_batch()` calls `fetch()` per-ticker; individual failures are silently
  isolated so one bad ticker doesn't cancel the whole batch.
- `apply_to_feature_set()` uses dataclasses.replace() to return a new
  FeatureSet with fundamentals overlay fields populated.
- All numeric values are sanity-checked: negative P/E ratios are replaced
  with None (loss-making companies; not meaningful for valuation scoring).
- Source reliability tier: "secondary_verified" (yfinance provides
  consensus/reported data, not raw analyst modelling).

Spec references
---------------
- APIS_MASTER_SPEC.md § 7.2 (Fundamentals data domain)
- APIS_BUILD_RUNBOOK.md § Step 2 (Research Engine fundamentals)
- API_AND_SERVICE_BOUNDARIES_SPEC.md § 3.5 (feature_store)
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, replace

from services.feature_store.models import FeatureSet

logger = logging.getLogger(__name__)


@dataclass
class FundamentalsData:
    """Fundamental metrics for a single security at one point in time."""

    ticker: str
    pe_ratio: float | None              # trailing 12-month P/E (None if negative / unavailable)
    forward_pe: float | None            # forward P/E from consensus estimate
    peg_ratio: float | None             # price/earnings-to-growth ratio
    price_to_sales: float | None        # trailing 12-month P/S
    eps_growth: float | None            # YoY EPS growth as decimal (0.15 = +15%)
    revenue_growth: float | None        # YoY revenue growth as decimal
    earnings_surprise_pct: float | None # latest quarterly EPS surprise %
    fetched_at: dt.datetime = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.fetched_at is None:
            self.fetched_at = dt.datetime.now(dt.UTC)


def _safe_positive_float(info: dict, key: str) -> float | None:
    """Extract a positive float from the yfinance info dict.

    Returns None if absent, non-numeric, or <= 0 (e.g. negative P/E for
    loss-making companies is not meaningful for valuation scoring).
    """
    val = info.get(key)
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _safe_float(info: dict, key: str) -> float | None:
    """Extract any float (positive or negative) from the yfinance info dict."""
    val = info.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


class FundamentalsService:
    """Fetches fundamental metrics for universe tickers via yfinance.

    Designed to be injected in tests; the real implementation uses
    `yfinance.Ticker.info` which makes live network calls.
    """

    # yfinance .info key → our field mapping
    _FIELD_MAP: dict[str, tuple[str, bool]] = {
        # key, (field_name, positive_only)
        "trailingPE":      ("pe_ratio",              True),
        "forwardPE":       ("forward_pe",             True),
        "pegRatio":        ("peg_ratio",              True),
        "priceToSalesTrailing12Months": ("price_to_sales", True),
        "earningsGrowth":  ("eps_growth",             False),
        "revenueGrowth":   ("revenue_growth",         False),
        # earnings_surprise_pct is derived from earningsSurprise* fields below
    }

    def fetch(self, ticker: str) -> FundamentalsData:
        """Fetch fundamentals for a single ticker.

        Network failures and missing data are silently handled; all fields
        default to None rather than raising.

        Args:
            ticker: Ticker symbol (e.g. "AAPL").

        Returns:
            FundamentalsData with available fields populated.
        """
        try:
            import yfinance as yf
            info = yf.Ticker(ticker).info or {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("fundamentals_fetch_failed ticker=%s error=%s", ticker, exc)
            info = {}

        return self._parse_info(ticker, info)

    def fetch_batch(self, tickers: list[str]) -> dict[str, FundamentalsData]:
        """Fetch fundamentals for a list of tickers.

        Args:
            tickers: List of ticker symbols.

        Returns:
            Dict mapping ticker → FundamentalsData.  Every input ticker is
            guaranteed to have an entry (with None fields if fetching failed).
        """
        result: dict[str, FundamentalsData] = {}
        for ticker in tickers:
            result[ticker] = self.fetch(ticker)
        return result

    def apply_to_feature_set(
        self, feature_set: FeatureSet, data: FundamentalsData
    ) -> FeatureSet:
        """Return a new FeatureSet with fundamentals overlay fields populated.

        Uses dataclasses.replace() — never mutates the input.

        Args:
            feature_set: Baseline FeatureSet to enrich.
            data:        FundamentalsData for the same ticker.

        Returns:
            New FeatureSet with fundamentals fields set.
        """
        return replace(
            feature_set,
            pe_ratio=data.pe_ratio,
            forward_pe=data.forward_pe,
            peg_ratio=data.peg_ratio,
            price_to_sales=data.price_to_sales,
            eps_growth=data.eps_growth,
            revenue_growth=data.revenue_growth,
            earnings_surprise_pct=data.earnings_surprise_pct,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_info(self, ticker: str, info: dict) -> FundamentalsData:
        """Parse a yfinance info dict into FundamentalsData."""
        pe_ratio = _safe_positive_float(info, "trailingPE")
        forward_pe = _safe_positive_float(info, "forwardPE")
        peg_ratio = _safe_positive_float(info, "pegRatio")
        price_to_sales = _safe_positive_float(info, "priceToSalesTrailing12Months")
        eps_growth = _safe_float(info, "earningsGrowth")
        revenue_growth = _safe_float(info, "revenueGrowth")

        # Earnings surprise: yfinance exposes earningsHistory list or individual
        # surprise fields.  We try the shorthand first.
        earnings_surprise_pct = self._extract_earnings_surprise(info)

        return FundamentalsData(
            ticker=ticker,
            pe_ratio=pe_ratio,
            forward_pe=forward_pe,
            peg_ratio=peg_ratio,
            price_to_sales=price_to_sales,
            eps_growth=eps_growth,
            revenue_growth=revenue_growth,
            earnings_surprise_pct=earnings_surprise_pct,
        )

    @staticmethod
    def _extract_earnings_surprise(info: dict) -> float | None:
        """Return the most recent quarterly EPS surprise as a decimal fraction.

        yfinance 0.2+ sometimes provides ``earningsSurprise`` directly;
        otherwise we compute from ``epsActual`` and ``epsEstimate`` on the
        most recent earnings history entry.

        Returns None when insufficient data is available.
        """
        # Direct key (present in some yfinance versions)
        direct = _safe_float(info, "earningsSurprise")
        if direct is not None:
            return direct

        # Fallback: derive from epsActual / epsEstimate
        history = info.get("earningsHistory")
        if not isinstance(history, list) or not history:
            return None
        # Take the most recent entry
        latest = history[-1] if history else {}
        if not isinstance(latest, dict):
            return None
        eps_actual = _safe_float(latest, "epsActual")
        eps_estimate = _safe_float(latest, "epsEstimate")
        if eps_actual is None or eps_estimate is None or eps_estimate == 0:
            return None
        return (eps_actual - eps_estimate) / abs(eps_estimate)
