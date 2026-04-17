"""
Insider / smart-money flow adapter (Phase 57 scaffold).

Responsibility: pull congressional disclosures (STOCK Act filings), 13F
holdings changes, and (optionally) unusual options flow from an external
provider, normalise them into ``InsiderFlowEvent`` objects, and aggregate
them per-ticker into an ``InsiderFlowOverlay`` the enrichment pipeline
can attach to a ``FeatureSet``.

Provider strategy
-----------------
Phase 57 ships only the abstract interface plus a ``NullInsiderFlowAdapter``
that returns empty data.  Candidate concrete providers to evaluate before
wiring for real (in priority order):

    1. QuiverQuant — REST API, congressional + insider + 13F, paid tiers
    2. Finnhub      — /stock/congressional-trading, free tier + paid
    3. CapitalTrades (via scraping) — used in the reference video, no
       documented API; scraping is fragile and potentially ToS-violating
    4. SEC EDGAR FULL-TEXT SEARCH — free but requires parsing Form 4 / 13F

The chosen provider must satisfy:
    - documented terms of service that permit programmatic access
    - a stable REST contract (not page-scraping) OR a first-party feed
    - a response field that lets us distinguish buys vs sells and
      compute a dollar-weighted net flow
    - a ``filing_date`` separate from ``trade_date`` so the strategy
      can decay correctly (filings are lagged up to 45 days)

Reliability tier is always ``secondary_verified``.  SEC filings are
public record but they are lagged and insider motives are not always
alpha-driven, so they never qualify as ``primary_verified``.

IMPORTANT — do not promote any concrete provider to production until:
    - a multi-year walk-forward backtest through BacktestEngine shows
      positive risk-adjusted edge after realistic transaction costs
    - the LiveModeGateService readiness report passes with the new
      signal weight in place
    - an entry is added to ``state/DECISION_LOG.md`` recording the
      provider choice and its ToS review
"""
from __future__ import annotations

import datetime as dt
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal

logger = logging.getLogger(__name__)

SOURCE_KEY = "insider_flow"
RELIABILITY_TIER = "secondary_verified"


@dataclass(frozen=True)
class InsiderFlowEvent:
    """A single disclosed trade or holdings change from a smart-money source.

    Fields
    ------
    ticker          : normalised upper-case ticker
    actor_type      : 'congress' | 'hedge_fund_13f' | 'insider_form4' | 'unusual_options'
    actor_name      : free-text identifier of the filer / actor
    side            : 'BUY' | 'SELL' | 'BUY_CALL' | 'SELL_CALL' | etc.
    notional_usd    : absolute dollar size of the trade or position change
    trade_date      : date the trade actually happened (may be weeks ago)
    filing_date     : date the filing was disclosed (what we actually see)
    source_key      : provider identifier (e.g. 'quiverquant', 'finnhub', 'edgar')
    confidence      : [0, 1] provider-specific confidence; 1.0 for SEC filings,
                      lower for inferred options flow
    raw             : opaque provider payload retained for audit
    """
    ticker: str
    actor_type: str
    actor_name: str
    side: str
    notional_usd: Decimal
    trade_date: dt.date
    filing_date: dt.date
    source_key: str
    confidence: float = 1.0
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class InsiderFlowOverlay:
    """Aggregated overlay produced by the adapter for one ticker as of a date.

    This is what the enrichment pipeline attaches to a ``FeatureSet`` via the
    ``insider_flow_*`` overlay fields.

    net_flow_score     : dollar-weighted net buy/sell bias in [-1, +1]
    aggregate_confidence: [0, 1] — mean provider confidence across constituents
    most_recent_age_days: age in days of the newest contributing filing_date
    event_count        : number of raw events aggregated into this overlay
    contributors       : list of the events used (audit trail)
    """
    ticker: str
    as_of: dt.date
    net_flow_score: float
    aggregate_confidence: float
    most_recent_age_days: float | None
    event_count: int
    contributors: list[InsiderFlowEvent] = field(default_factory=list)


class InsiderFlowAdapter(ABC):
    """Abstract base: every concrete provider must implement fetch_events."""

    SOURCE_KEY: str = SOURCE_KEY
    RELIABILITY_TIER: str = RELIABILITY_TIER

    @abstractmethod
    def fetch_events(
        self,
        tickers: list[str],
        lookback_days: int = 90,
        as_of: dt.date | None = None,
    ) -> list[InsiderFlowEvent]:
        """Return raw events for the given tickers within the lookback window.

        Implementations MUST:
            - never raise on empty result sets (return [])
            - never raise on individual row parse failures (log + skip)
            - apply the adapter's own rate-limiting / backoff
            - return events with filing_date <= as_of (default: today UTC)
        """

    # ------------------------------------------------------------------
    # Aggregation — shared by all concrete subclasses
    # ------------------------------------------------------------------

    def aggregate(
        self,
        ticker: str,
        events: list[InsiderFlowEvent],
        as_of: dt.date | None = None,
    ) -> InsiderFlowOverlay:
        """Collapse raw events into one overlay for one ticker."""
        as_of = as_of or dt.date.today()
        rel = [e for e in events if e.ticker.upper() == ticker.upper()]

        if not rel:
            return InsiderFlowOverlay(
                ticker=ticker.upper(),
                as_of=as_of,
                net_flow_score=0.0,
                aggregate_confidence=0.0,
                most_recent_age_days=None,
                event_count=0,
                contributors=[],
            )

        buy_usd = Decimal("0")
        sell_usd = Decimal("0")
        conf_sum = 0.0
        for e in rel:
            side = e.side.upper()
            if side.startswith("BUY"):
                buy_usd += e.notional_usd
            elif side.startswith("SELL"):
                sell_usd += e.notional_usd
            conf_sum += e.confidence

        total = buy_usd + sell_usd
        net = 0.0 if total == 0 else float((buy_usd - sell_usd) / total)
        # Clamp to [-1, +1] defensively
        net = max(-1.0, min(1.0, net))
        agg_conf = conf_sum / len(rel) if rel else 0.0
        newest = max(rel, key=lambda e: e.filing_date).filing_date
        age_days = float((as_of - newest).days)

        return InsiderFlowOverlay(
            ticker=ticker.upper(),
            as_of=as_of,
            net_flow_score=net,
            aggregate_confidence=agg_conf,
            most_recent_age_days=age_days,
            event_count=len(rel),
            contributors=list(rel),
        )


class NullInsiderFlowAdapter(InsiderFlowAdapter):
    """No-op adapter used in tests and as the production default until a
    concrete provider is wired and validated.

    Always returns an empty list; the strategy will produce a neutral
    0.5 signal with zero confidence, which is exactly what we want until
    Phase 57 graduates past scaffold.
    """

    SOURCE_KEY: str = "insider_flow_null"

    def fetch_events(
        self,
        tickers: list[str],
        lookback_days: int = 90,
        as_of: dt.date | None = None,
    ) -> list[InsiderFlowEvent]:
        logger.debug(
            "NullInsiderFlowAdapter.fetch_events called: %d tickers, "
            "lookback=%d (returning empty list — Phase 57 scaffold)",
            len(tickers), lookback_days,
        )
        return []
