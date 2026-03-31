"""theme_engine domain models."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class BeneficiaryOrder(str, Enum):
    """How directly a security benefits from a theme."""
    DIRECT = "direct"           # primary beneficiary (e.g. NVIDIA for AI compute)
    SECOND_ORDER = "second_order"  # downstream (e.g. power utilities for AI data centres)
    INDIRECT = "indirect"       # loosely correlated


@dataclass
class ThemeMapping:
    """Maps a security to one investment theme."""
    ticker: str
    theme: str                                  # e.g. "ai_infrastructure"
    beneficiary_order: BeneficiaryOrder = BeneficiaryOrder.DIRECT
    thematic_score: float = 0.0                 # [0.0, 1.0] — theme relevance strength
    rationale: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class ThematicExposure:
    """Aggregated thematic exposure for a ticker across all themes."""
    ticker: str
    mappings: list[ThemeMapping] = field(default_factory=list)

    @property
    def primary_theme(self) -> str | None:
        """The theme with the highest thematic_score, or None."""
        if not self.mappings:
            return None
        return max(self.mappings, key=lambda m: m.thematic_score).theme

    @property
    def max_score(self) -> float:
        if not self.mappings:
            return 0.0
        return max(m.thematic_score for m in self.mappings)
