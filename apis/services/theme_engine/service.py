"""theme_engine service — concrete static-registry ticker-to-theme mapping.

Loads theme assignments from the curated TICKER_THEME_REGISTRY and returns
ThematicExposure objects for any requested ticker.  No DB or LLM needed.
"""
from __future__ import annotations

from typing import Optional

import structlog

from services.theme_engine.config import ThemeEngineConfig
from services.theme_engine.models import BeneficiaryOrder, ThematicExposure, ThemeMapping
from services.theme_engine.utils import (
    TICKER_THEME_REGISTRY,
    get_theme_members_from_registry,
    get_ticker_mappings,
)

log = structlog.get_logger(__name__)


class ThemeEngineService:
    """Maps securities to investment themes and scores thematic exposure.

    Uses a curated static registry covering the 50-ticker APIS universe.
    Unknown tickers return an empty ThematicExposure rather than raising.
    """

    def __init__(self, config: Optional[ThemeEngineConfig] = None) -> None:
        self._config = config or ThemeEngineConfig()
        self._log = log.bind(service="theme_engine")

    def get_exposure(self, ticker: str) -> ThematicExposure:
        """Return thematic exposure for a single ticker from the registry.

        Applies min_thematic_score and max_themes_per_ticker filters from
        config before returning.  Unknown tickers return an empty exposure.
        """
        mappings = get_ticker_mappings(ticker.upper())
        # Apply filters: minimum score and configuration cap
        filtered = [
            m for m in mappings
            if m.thematic_score >= self._config.min_thematic_score
        ]
        # Sort by score descending and cap to max
        filtered.sort(key=lambda m: m.thematic_score, reverse=True)
        filtered = filtered[: self._config.max_themes_per_ticker]
        return ThematicExposure(ticker=ticker.upper(), mappings=filtered)

    def get_bulk_exposure(
        self, tickers: list[str]
    ) -> dict[str, ThematicExposure]:
        """Return thematic exposures for a list of tickers."""
        return {t.upper(): self.get_exposure(t) for t in tickers}

    def get_theme_members(
        self, theme: str, min_score: float = 0.0
    ) -> list[ThemeMapping]:
        """Return all securities mapped to a given theme above min_score."""
        if theme not in self._config.known_themes:
            self._log.warning("unknown_theme_requested", theme=theme)
            return []
        return get_theme_members_from_registry(theme, min_score=min_score)
