"""
APIS trading universe configuration.

Defines the default paper-trading universe: 50 US equities spanning large-cap
technology, healthcare, financials, energy, and consumer sectors plus a set of
thematic plays aligned with APIS signal families.

Any service that needs the ticker list should import `get_universe_tickers()`.
"""
from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Sector / segment buckets (used by signal_engine + ranking_engine weighting)
# ---------------------------------------------------------------------------
MEGA_CAP_TECH: Final[list[str]] = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO",
]

AI_INFRASTRUCTURE: Final[list[str]] = [
    "NVDA", "AMD", "INTC", "ARM", "MRVL", "SMCI", "DELL", "HPE",
]

SEMICONDUCTORS: Final[list[str]] = [
    "TSM", "ASML", "QCOM", "TXN", "MU", "NXPI", "ON",
]

CLOUD_SOFTWARE: Final[list[str]] = [
    "MSFT", "AMZN", "GOOGL", "CRM", "NOW", "SNOW", "DDOG", "MDB",
]

HEALTHCARE: Final[list[str]] = [
    "LLY", "UNH", "JNJ", "ABBV", "MRK", "PFE", "TMO",
]

FINANCIALS: Final[list[str]] = [
    "JPM", "BAC", "GS", "MS", "V", "MA", "BRK-B",
]

ENERGY: Final[list[str]] = [
    "XOM", "CVX", "COP", "SLB",
]

CONSUMER: Final[list[str]] = [
    "WMT", "COST", "HD", "NKE", "SBUX",
]

# ---------------------------------------------------------------------------
# Full universe — deduplicated, preserving order of first appearance
# ---------------------------------------------------------------------------
def _build_universe() -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for segment in [
        MEGA_CAP_TECH,
        AI_INFRASTRUCTURE,
        SEMICONDUCTORS,
        CLOUD_SOFTWARE,
        HEALTHCARE,
        FINANCIALS,
        ENERGY,
        CONSUMER,
    ]:
        for ticker in segment:
            if ticker not in seen:
                seen.add(ticker)
                result.append(ticker)
    return result


UNIVERSE_TICKERS: Final[list[str]] = _build_universe()

# Map ticker → primary sector tag (used for ranking source reliability tags)
TICKER_SECTOR: Final[dict[str, str]] = dict.fromkeys(MEGA_CAP_TECH + AI_INFRASTRUCTURE + SEMICONDUCTORS + CLOUD_SOFTWARE, "technology") | dict.fromkeys(HEALTHCARE, "healthcare") | dict.fromkeys(FINANCIALS, "financials") | dict.fromkeys(ENERGY, "energy") | dict.fromkeys(CONSUMER, "consumer")


# Map ticker → primary investment theme (used for thematic concentration checks).
# Where a ticker belongs to multiple themes, the most *specific* theme wins
# (e.g. NVDA → "ai_infrastructure" rather than the broader "mega_cap_tech").
# Tickers absent from this mapping fall into the "other" bucket at runtime.
TICKER_THEME: Final[dict[str, str]] = {
    # AI / compute infrastructure — most specific theme for these names
    **dict.fromkeys(AI_INFRASTRUCTURE, "ai_infrastructure"),
    # Semiconductors (non-AI-infra overlap)
    **dict.fromkeys(SEMICONDUCTORS, "semiconductors"),
    # Cloud software
    **dict.fromkeys(CLOUD_SOFTWARE, "cloud_software"),
    # Mega-cap tech not already captured by a more specific theme
    **{t: "mega_cap_tech" for t in MEGA_CAP_TECH
       if t not in AI_INFRASTRUCTURE and t not in CLOUD_SOFTWARE},
    # Other sectors map to their sector name as theme (no overlap)
    **dict.fromkeys(HEALTHCARE, "healthcare"),
    **dict.fromkeys(FINANCIALS, "financials"),
    **dict.fromkeys(ENERGY, "energy"),
    **dict.fromkeys(CONSUMER, "consumer"),
}


def get_universe_tickers(segment: str | None = None) -> list[str]:
    """Return the full universe ticker list, or a named segment subset.

    Args:
        segment: One of "mega_cap_tech", "ai_infrastructure", "semiconductors",
                 "cloud_software", "healthcare", "financials", "energy",
                 "consumer", or None for the full universe.
    """
    segments: dict[str, list[str]] = {
        "mega_cap_tech": MEGA_CAP_TECH,
        "ai_infrastructure": AI_INFRASTRUCTURE,
        "semiconductors": SEMICONDUCTORS,
        "cloud_software": CLOUD_SOFTWARE,
        "healthcare": HEALTHCARE,
        "financials": FINANCIALS,
        "energy": ENERGY,
        "consumer": CONSUMER,
    }
    if segment is not None:
        return list(segments[segment])
    return list(UNIVERSE_TICKERS)
