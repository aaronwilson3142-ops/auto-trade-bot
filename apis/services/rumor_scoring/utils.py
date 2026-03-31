"""rumor_scoring utilities.

Helper for extracting ticker symbols from raw rumor text.  Uses the same
pattern-based approach as the NLP layer (no external deps).
"""
from __future__ import annotations

import re
from typing import Optional

_TICKER_RE = re.compile(r"\b([A-Z]{1,5})\b")


def extract_tickers_from_rumor(
    text: str, known_tickers: Optional[frozenset[str]] = None
) -> list[str]:
    """Extract ticker symbols appearing in a rumor text string.

    Filters to known universe tickers when a set is provided.
    Falls back to returning any 1-5 uppercase letter sequence.
    """
    if known_tickers is None:
        from config.universe import UNIVERSE_TICKERS
        known_tickers = frozenset(UNIVERSE_TICKERS)
    found = _TICKER_RE.findall(text)
    in_universe = [t for t in found if t in known_tickers]
    # If nothing matched the universe, return all-caps words of length 2-5
    if not in_universe:
        return list(dict.fromkeys(t for t in found if 2 <= len(t) <= 5))
    return list(dict.fromkeys(in_universe))


def normalize_source_text(text: str) -> str:
    """Basic text normalization: strip excessive whitespace and truncate."""
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned[:500]  # cap at 500 chars for performance

