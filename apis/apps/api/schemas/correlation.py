"""
Pydantic schemas for the correlation API (Phase 39).
"""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field


class CorrelationPairSchema(BaseModel):
    """A single pairwise correlation entry."""

    ticker_a: str
    ticker_b: str
    correlation: float = Field(ge=-1.0, le=1.0)


class CorrelationMatrixResponse(BaseModel):
    """Response for GET /portfolio/correlation.

    Returns the full symmetric pairwise correlation matrix for all tickers
    present in the last correlation refresh job.
    """

    computed_at: dt.datetime | None = None
    ticker_count: int = 0
    pair_count: int = 0
    tickers: list[str] = Field(default_factory=list)
    pairs: list[CorrelationPairSchema] = Field(default_factory=list)
    max_correlation: float = Field(default=0.0, ge=0.0, le=1.0,
                                   description="Highest absolute pairwise correlation in the matrix")


class TickerCorrelationResponse(BaseModel):
    """Response for GET /portfolio/correlation/{ticker}.

    Returns this ticker's pairwise correlations with all other matrix tickers,
    plus the maximum absolute correlation with current portfolio positions.
    """

    ticker: str
    max_portfolio_correlation: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Max |correlation| of this ticker with any current portfolio position"
    )
    portfolio_tickers: list[str] = Field(default_factory=list)
    correlations: list[CorrelationPairSchema] = Field(default_factory=list)
    computed_at: dt.datetime | None = None
