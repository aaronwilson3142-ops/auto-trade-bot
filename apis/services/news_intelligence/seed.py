"""Seeded daily news items for the intel feed pipeline.

Every morning the worker ingests these templates (with today's timestamps)
through NewsIntelligenceService.process_batch() so the enrichment pipeline
has non-trivial sentiment overlays to work with in paper trading mode.

Templates cover the major investment themes in the 50-ticker APIS universe.
In production, swap NewsSeedService for an adapter that calls a real news API.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from services.news_intelligence.models import CredibilityTier, NewsItem

_DEFAULT_SEEDS: list[dict] = [
    {
        "source_id": "seed_tech_ai_001",
        "headline": "Cloud AI spending accelerates as hyperscalers raise capex guidance",
        "body_snippet": (
            "Microsoft, Amazon, and Alphabet each raised data-centre capex outlooks "
            "for the year, pointing to sustained AI infrastructure investment. "
            "NVIDIA GPU allocations remain tight."
        ),
        "credibility_tier": CredibilityTier.SECONDARY_VERIFIED,
        "tickers_mentioned": ["MSFT", "AMZN", "GOOGL", "NVDA"],
    },
    {
        "source_id": "seed_rates_001",
        "headline": "Federal Reserve holds rates steady; signals patience on cuts",
        "body_snippet": (
            "The FOMC voted unanimously to keep the federal funds rate at current "
            "levels. Chair comments indicated no urgency to cut rates, weighing on "
            "rate-sensitive sectors including utilities and REITs."
        ),
        "credibility_tier": CredibilityTier.PRIMARY_VERIFIED,
        "tickers_mentioned": [],
    },
    {
        "source_id": "seed_energy_001",
        "headline": "Oil prices rally on OPEC supply restraint and improving demand outlook",
        "body_snippet": (
            "Brent crude rose 2.4% as OPEC+ reaffirmed production cuts. Energy "
            "sector equities advanced broadly with exploration and production names "
            "leading gains."
        ),
        "credibility_tier": CredibilityTier.SECONDARY_VERIFIED,
        "tickers_mentioned": ["XOM", "CVX"],
    },
    {
        "source_id": "seed_semis_001",
        "headline": "Semiconductor equipment orders rebound as chip upcycle resumes",
        "body_snippet": (
            "ASML and Applied Materials reported stronger-than-expected orders "
            "pointing to the start of a new upcycle. Memory and logic spending both "
            "accelerating through the second half."
        ),
        "credibility_tier": CredibilityTier.SECONDARY_VERIFIED,
        "tickers_mentioned": ["NVDA", "AMD", "INTC", "MU"],
    },
    {
        "source_id": "seed_pharma_001",
        "headline": "Drug pricing reform proposal faces Senate opposition",
        "body_snippet": (
            "A revised drug pricing bill lost key votes in the Senate. Analysts "
            "view the setback as mildly positive for large-cap pharmaceuticals "
            "and biotech near-term."
        ),
        "credibility_tier": CredibilityTier.SECONDARY_VERIFIED,
        "tickers_mentioned": ["JNJ", "MRK", "PFE", "ABBV"],
    },
    {
        "source_id": "seed_fintech_001",
        "headline": "Online brokerage volumes surge on retail investor return",
        "body_snippet": (
            "Retail trading activity rose sharply last week according to exchange "
            "volume data. Fintech and brokerage equities benefit from higher revenue."
        ),
        "credibility_tier": CredibilityTier.SECONDARY_VERIFIED,
        "tickers_mentioned": ["GS", "MS", "JPM"],
    },
    {
        "source_id": "seed_ev_001",
        "headline": "EV subsidy phase-out risk weighs on automaker sentiment",
        "body_snippet": (
            "Congressional proposals to reduce EV tax credits weighed on electric "
            "vehicle manufacturer stocks. Tesla fell on uncertainty about demand."
        ),
        "credibility_tier": CredibilityTier.UNVERIFIED,
        "tickers_mentioned": ["TSLA"],
    },
    {
        "source_id": "seed_consumer_001",
        "headline": "Consumer confidence hits 18-month high on strong labour market",
        "body_snippet": (
            "The Conference Board consumer confidence index rose to its highest "
            "level since late 2024 driven by job availability and rising wages, "
            "supporting the consumer discretionary sector outlook."
        ),
        "credibility_tier": CredibilityTier.PRIMARY_VERIFIED,
        "tickers_mentioned": ["AMZN", "META", "HD"],
    },
]


class NewsSeedService:
    """Provides a daily set of seeded NewsItem objects for the intel pipeline.

    In production these would be replaced by a real news feed adapter.
    For paper trading mode, the static seed ensures the enrichment pipeline
    always has representative sentiment coverage across the universe.

    Args:
        seeds: Override the default seed templates.  Pass ``None`` (default)
               to use the built-in APIS seed set.
    """

    def __init__(self, seeds: Optional[list[dict]] = None) -> None:
        self._seeds = seeds if seeds is not None else _DEFAULT_SEEDS

    @property
    def seed_count(self) -> int:
        """Number of seed templates configured."""
        return len(self._seeds)

    def get_daily_items(
        self,
        reference_dt: Optional[dt.datetime] = None,
    ) -> list[NewsItem]:
        """Return a fresh list of NewsItem objects stamped to *today*.

        All items are published 2 hours before *reference_dt* (or 2 hours
        before now if not provided) so they pass the ``max_item_age_hours``
        filter in NewsIntelligenceService.

        Args:
            reference_dt: Optional reference datetime (UTC).  Defaults to
                          ``datetime.now(UTC)``.

        Returns:
            list[NewsItem] ready to feed into
            NewsIntelligenceService.process_batch().
        """
        now = reference_dt or dt.datetime.now(dt.timezone.utc)
        published = now - dt.timedelta(hours=2)
        items: list[NewsItem] = []
        for tmpl in self._seeds:
            items.append(
                NewsItem(
                    source_id=tmpl["source_id"],
                    headline=tmpl["headline"],
                    published_at=published,
                    body_snippet=tmpl.get("body_snippet", ""),
                    credibility_tier=tmpl.get(
                        "credibility_tier", CredibilityTier.UNVERIFIED
                    ),
                    tickers_mentioned=list(tmpl.get("tickers_mentioned", [])),
                )
            )
        return items
