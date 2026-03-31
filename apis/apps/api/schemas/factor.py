"""Phase 50 — Factor Exposure API schemas."""
from __future__ import annotations

from pydantic import BaseModel


class TickerFactorScoresSchema(BaseModel):
    """Per-ticker factor scores."""
    ticker: str
    momentum: float
    value: float
    growth: float
    quality: float
    low_vol: float
    market_value: float
    dominant_factor: str


class FactorExposureResponse(BaseModel):
    """Portfolio-level factor exposure summary.

    ``portfolio_factor_weights`` is the market-value-weighted mean of all
    per-ticker factor scores, one entry per factor.
    """
    computed_at: str | None
    position_count: int
    total_market_value: float
    dominant_factor: str
    momentum: float
    value: float
    growth: float
    quality: float
    low_vol: float
    ticker_scores: list[TickerFactorScoresSchema]


class FactorTopBottomEntry(BaseModel):
    """Single entry in a factor top/bottom ranking."""
    ticker: str
    score: float
    market_value: float


class FactorDetailResponse(BaseModel):
    """Detailed view of a single factor across all portfolio positions."""
    factor: str
    portfolio_weight: float
    top_tickers: list[FactorTopBottomEntry]
    bottom_tickers: list[FactorTopBottomEntry]
    computed_at: str | None
