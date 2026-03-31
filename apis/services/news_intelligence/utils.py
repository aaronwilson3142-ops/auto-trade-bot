"""news_intelligence NLP utilities.

Keyword-based sentiment scoring, ticker mention extraction, and theme
tagging.  No external NLP dependencies — pure Python rule-based approach.
All functions are stateless and fully testable in isolation.
"""
from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Sentiment lexicons
# ---------------------------------------------------------------------------

POSITIVE_WORDS: frozenset[str] = frozenset({
    "beat", "beats", "surpass", "surge", "soar", "jump", "rally", "rise",
    "gain", "gains", "profit", "profits", "growth", "grow", "strong",
    "upgrade", "upgraded", "outperform", "buy", "overweight", "positive",
    "record", "high", "breakout", "expand", "expansion", "contract", "win",
    "award", "approved", "approval", "launch", "partner", "partnership",
    "deal", "acquisition", "merger", "revenue", "earnings", "exceed",
    "exceeds", "raise", "raised", "guidance", "dividend", "buyback",
    "bullish", "momentum", "accelerate", "boom", "robust", "recover",
    "recovery", "breakthrough", "opportunity", "favorable", "upside",
})

NEGATIVE_WORDS: frozenset[str] = frozenset({
    "miss", "misses", "cut", "cuts", "drop", "drops", "fall", "falls",
    "decline", "declines", "loss", "losses", "weak", "weakness", "warn",
    "warning", "downgrade", "downgraded", "underperform", "sell", "underweight",
    "negative", "low", "breakdown", "contract", "contraction", "delay",
    "delayed", "layoff", "layoffs", "recall", "fine", "penalty", "lawsuit",
    "sued", "investigation", "probe", "scandal", "fraud", "bankrupt",
    "bankruptcy", "restructure", "restructuring", "tariff", "sanction",
    "sanctions", "concern", "concerns", "uncertainty", "volatile",
    "volatility", "recession", "recessionary", "bearish", "headwind",
    "headwinds", "risk", "risks", "shortage", "supply", "inflation",
    "downside", "depreciate", "depreciation", "halt", "halted", "suspend",
})

# ---------------------------------------------------------------------------
# Theme keywords
# ---------------------------------------------------------------------------

THEME_KEYWORDS: dict[str, frozenset[str]] = {
    "ai_infrastructure": frozenset({
        "ai", "artificial intelligence", "gpu", "nvidia", "data center",
        "data centre", "inference", "training", "accelerator", "ai chip",
        "ai server", "generative ai", "large language model", "llm",
    }),
    "semiconductor": frozenset({
        "semiconductor", "chip", "chips", "wafer", "fab", "foundry",
        "tsmc", "asml", "lithography", "memory", "dram", "nand", "hbm",
        "integrated circuit", "packaging",
    }),
    "cloud_computing": frozenset({
        "cloud", "aws", "azure", "gcp", "saas", "paas", "subscription",
        "software as a service", "cloud computing", "multi-cloud",
    }),
    "cybersecurity": frozenset({
        "cybersecurity", "cyber", "security breach", "hack", "hacked",
        "ransomware", "zero-day", "firewall", "endpoint security",
        "identity management",
    }),
    "power_infrastructure": frozenset({
        "power grid", "electricity", "utility", "utilities", "energy demand",
        "transmission", "nuclear", "grid expansion", "electrification",
        "data center power", "load growth",
    }),
    "data_centres": frozenset({
        "data center", "data centre", "colocation", "colo", "hyperscaler",
        "server farm", "cloud campus", "building data",
    }),
    "networking": frozenset({
        "networking", "ethernet", "infiniband", "optical", "bandwidth",
        "switch", "router", "interconnect", "broadband", "fiber",
    }),
    "defence": frozenset({
        "defense", "defence", "military", "pentagon", "nato", "weapon",
        "missile", "drone", "contract defense", "government contract",
        "geopolit",
    }),
    "biotech": frozenset({
        "fda", "drug approval", "clinical trial", "phase 3", "phase 2",
        "biotech", "pharmaceutical", "therapy", "oncology", "vaccine",
        "genomics", "gene editing", "crispr",
    }),
    "clean_energy": frozenset({
        "solar", "wind", "renewable", "clean energy", "lng", "natural gas",
        "battery", "ev", "electric vehicle", "carbon", "emissions",
        "green energy",
    }),
    "fintech": frozenset({
        "payment", "payments", "fintech", "digital wallet", "crypto",
        "blockchain", "lending", "credit card", "banking app",
    }),
    "ai_applications": frozenset({
        "copilot", "chatgpt", "openai", "gemini", "ai assistant",
        "ai integration", "ai feature", "ai model", "foundation model",
        "ai adoption",
    }),
}

# ---------------------------------------------------------------------------
# Known universe tickers (loaded lazily)
# ---------------------------------------------------------------------------

_TICKER_PATTERN = re.compile(r"\b([A-Z]{1,5})(?:\.[A-Z])?\b")


def extract_tickers_from_text(
    text: str, known_tickers: Optional[frozenset[str]] = None
) -> list[str]:
    """Extract ticker symbols from free text.

    Finds uppercase 1-5 letter sequences that match the known universe.
    Falls back to all-caps 2-5 letter words if no known_tickers set supplied.
    """
    if known_tickers is None:
        from config.universe import UNIVERSE_TICKERS
        known_tickers = frozenset(UNIVERSE_TICKERS)
    found = _TICKER_PATTERN.findall(text)
    # Filter to only known tickers to avoid stopwords like "I", "A", "THE"
    return list(dict.fromkeys(t for t in found if t in known_tickers))


def score_sentiment(text: str) -> float:
    """Return a sentiment score in [-1.0, 1.0] using keyword matching.

    Strategy:
    - Tokenise text into lowercase words
    - Count positive and negative signal words
    - Score = (positive - negative) / (positive + negative + 1)
    """
    words = re.findall(r"[a-z]+", text.lower())
    pos = sum(1 for w in words if w in POSITIVE_WORDS)
    neg = sum(1 for w in words if w in NEGATIVE_WORDS)
    total = pos + neg
    if total == 0:
        return 0.0
    return round((pos - neg) / (total + 1), 4)


def detect_themes(text: str) -> list[str]:
    """Return list of themes whose keywords appear in *text*."""
    text_lower = text.lower()
    matched: list[str] = []
    for theme, keywords in THEME_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            matched.append(theme)
    return matched


def generate_market_implication(
    sentiment_score: float,
    affected_tickers: list[str],
    affected_themes: list[str],
) -> str:
    """Produce a concise market implication string from extracted signals."""
    direction = "bullish" if sentiment_score > 0.1 else ("bearish" if sentiment_score < -0.1 else "neutral")
    tickers_str = ", ".join(affected_tickers[:3]) if affected_tickers else "market"
    themes_str = ", ".join(affected_themes[:2]) if affected_themes else ""
    if themes_str:
        return f"{direction.capitalize()} for {tickers_str} (themes: {themes_str})"
    return f"{direction.capitalize()} for {tickers_str}"

