"""theme_engine configuration."""
from __future__ import annotations

from dataclasses import dataclass, field

# Canonical themes tracked by APIS
_DEFAULT_THEMES = [
    "ai_infrastructure",
    "ai_applications",
    "cloud_computing",
    "semiconductor",
    "cybersecurity",
    "power_infrastructure",   # second-order AI beneficiary
    "data_centres",           # second-order AI beneficiary
    "networking",             # second-order AI beneficiary
    "fintech",
    "clean_energy",
    "defence",
    "biotech",
]


@dataclass
class ThemeEngineConfig:
    """Tunable parameters for the theme mapping service."""
    known_themes: list[str] = field(default_factory=lambda: list(_DEFAULT_THEMES))
    # Minimum score for a mapping to be retained
    min_thematic_score: float = 0.1
    # Maximum themes returned per ticker
    max_themes_per_ticker: int = 3
