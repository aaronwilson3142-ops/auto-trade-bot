"""Seeded daily policy events for the macro policy engine pipeline.

Provides PolicyEvent templates that reflect the current macroeconomic
backdrop for paper trading mode.  Templates are classified by event_type
so MacroPolicyEngineService computes realistic directional biases and
a non-neutral macro regime.

In production, swap PolicyEventSeedService for an adapter calling a real
policy/news API or an internal event bus.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from services.macro_policy_engine.models import PolicyEvent, PolicyEventType

_DEFAULT_SEEDS: list[dict] = [
    {
        "event_id": "seed_rates_hold_001",
        "headline": "Federal Reserve holds rates; no cuts expected before Q3",
        "event_type": PolicyEventType.INTEREST_RATE,
        "source": "Federal Reserve",
        "body_snippet": (
            "The FOMC voted to hold the target range steady. Meeting minutes "
            "emphasised patience and data-dependency. Market pricing for a June "
            "cut fell from 65% to 38%."
        ),
    },
    {
        "event_id": "seed_fiscal_001",
        "headline": "Infrastructure spending bill advances with bipartisan support",
        "event_type": PolicyEventType.FISCAL_POLICY,
        "source": "Reuters",
        "body_snippet": (
            "A $480bn infrastructure and clean-energy bill passed the Senate "
            "Commerce Committee with bipartisan backing.  Analysts expect a boost "
            "to industrials, utilities, and materials sectors."
        ),
    },
    {
        "event_id": "seed_tariff_001",
        "headline": "US considers 25% tariffs on selected electronics imports",
        "event_type": PolicyEventType.TARIFF,
        "source": "Wall Street Journal",
        "body_snippet": (
            "The administration is evaluating targeted tariffs up to 25% on "
            "consumer electronics imports.  Supply chains for semiconductors and "
            "hardware assemblers may be affected."
        ),
    },
    {
        "event_id": "seed_geo_001",
        "headline": "Geopolitical tensions ease following diplomatic talks",
        "event_type": PolicyEventType.GEOPOLITICAL,
        "source": "Bloomberg",
        "body_snippet": (
            "US and foreign envoys held productive discussions reducing near-term "
            "military escalation risk.  Semiconductor and technology supply chain "
            "stocks rallied on reduced disruption fears."
        ),
    },
    {
        "event_id": "seed_regulation_001",
        "headline": "SEC proposes clearer framework for AI-assisted investment advice",
        "event_type": PolicyEventType.REGULATION,
        "source": "SEC",
        "body_snippet": (
            "The Securities and Exchange Commission released a proposed rulemaking "
            "on AI disclosure requirements for registered investment advisers. "
            "Fintech firms broadly welcomed the regulatory clarity."
        ),
    },
]


class PolicyEventSeedService:
    """Provides a daily set of seeded PolicyEvent objects for the macro pipeline.

    In production these would be replaced by a real policy news feed adapter.
    For paper trading mode the static seed ensures MacroPolicyEngineService
    always has representative events to derive a non-neutral regime signal.

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

    def get_daily_events(
        self,
        reference_dt: Optional[dt.datetime] = None,
    ) -> list[PolicyEvent]:
        """Return a fresh list of PolicyEvent objects stamped to *today*.

        All events are published 3 hours before *reference_dt* so they pass
        the ``max_event_age_hours`` filter in MacroPolicyEngineService.

        Args:
            reference_dt: Optional reference datetime (UTC).

        Returns:
            list[PolicyEvent] ready for
            MacroPolicyEngineService.process_batch().
        """
        now = reference_dt or dt.datetime.now(dt.timezone.utc)
        published = now - dt.timedelta(hours=3)
        events: list[PolicyEvent] = []
        for tmpl in self._seeds:
            events.append(
                PolicyEvent(
                    event_id=tmpl["event_id"],
                    headline=tmpl["headline"],
                    event_type=tmpl["event_type"],
                    published_at=published,
                    source=tmpl.get("source", ""),
                    body_snippet=tmpl.get("body_snippet", ""),
                )
            )
        return events
