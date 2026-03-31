"""
Correlation API routes (Phase 39).

GET /api/v1/portfolio/correlation
    Returns the full pairwise Pearson correlation matrix from the last
    run_correlation_refresh job.

GET /api/v1/portfolio/correlation/{ticker}
    Returns the target ticker's correlations with all matrix tickers, plus
    the maximum absolute correlation with currently open portfolio positions.

Both endpoints read from app_state (in-memory cache) — no DB access.
They return empty/zero responses when the correlation job has not yet run.
"""
from __future__ import annotations

from fastapi import APIRouter

from apps.api.deps import AppStateDep, SettingsDep
from apps.api.schemas.correlation import (
    CorrelationMatrixResponse,
    CorrelationPairSchema,
    TickerCorrelationResponse,
)
from services.risk_engine.correlation import CorrelationService

correlation_router = APIRouter(prefix="/portfolio", tags=["Correlation"])


@correlation_router.get(
    "/correlation",
    response_model=CorrelationMatrixResponse,
    summary="Full pairwise correlation matrix",
    description=(
        "Returns the full symmetric Pearson correlation matrix computed by "
        "run_correlation_refresh (06:16 ET job).  Returns empty when the job "
        "has not yet run."
    ),
)
def get_correlation_matrix(state: AppStateDep, settings: SettingsDep) -> CorrelationMatrixResponse:
    """Return cached correlation matrix."""
    matrix: dict = getattr(state, "correlation_matrix", {})
    tickers: list[str] = getattr(state, "correlation_tickers", [])
    computed_at = getattr(state, "correlation_computed_at", None)

    if not matrix:
        return CorrelationMatrixResponse(
            computed_at=computed_at,
            ticker_count=len(tickers),
            pair_count=0,
            tickers=tickers,
            pairs=[],
            max_correlation=0.0,
        )

    # Deduplicate — matrix stores both (a,b) and (b,a); keep lexicographic order
    seen: set[tuple[str, str]] = set()
    pairs: list[CorrelationPairSchema] = []
    max_corr = 0.0

    for (a, b), corr in matrix.items():
        key = (min(a, b), max(a, b))
        if key in seen:
            continue
        seen.add(key)
        pairs.append(CorrelationPairSchema(ticker_a=a, ticker_b=b, correlation=round(corr, 6)))
        max_corr = max(max_corr, abs(corr))

    # Sort for deterministic output
    pairs.sort(key=lambda p: (p.ticker_a, p.ticker_b))

    return CorrelationMatrixResponse(
        computed_at=computed_at,
        ticker_count=len(tickers),
        pair_count=len(pairs),
        tickers=sorted(tickers),
        pairs=pairs,
        max_correlation=round(max_corr, 6),
    )


@correlation_router.get(
    "/correlation/{ticker}",
    response_model=TickerCorrelationResponse,
    summary="Ticker correlation with portfolio",
    description=(
        "Returns the target ticker's pairwise correlations with all matrix "
        "tickers, and the maximum absolute correlation with currently open "
        "portfolio positions.  404 is NOT raised when the ticker is absent "
        "from the matrix — an empty response is returned instead."
    ),
)
def get_ticker_correlation(
    ticker: str,
    state: AppStateDep,
    settings: SettingsDep,
) -> TickerCorrelationResponse:
    """Return this ticker's correlation profile."""
    ticker = ticker.upper()
    matrix: dict = getattr(state, "correlation_matrix", {})
    computed_at = getattr(state, "correlation_computed_at", None)

    # Current portfolio tickers
    ps = getattr(state, "portfolio_state", None)
    portfolio_tickers: list[str] = (
        list(ps.positions.keys()) if ps and getattr(ps, "positions", None) else []
    )

    if not matrix:
        return TickerCorrelationResponse(
            ticker=ticker,
            max_portfolio_correlation=0.0,
            portfolio_tickers=portfolio_tickers,
            correlations=[],
            computed_at=computed_at,
        )

    # All correlations for this ticker
    corr_pairs: list[CorrelationPairSchema] = []
    for (a, b), corr in matrix.items():
        if a == ticker:
            corr_pairs.append(
                CorrelationPairSchema(ticker_a=ticker, ticker_b=b, correlation=round(corr, 6))
            )

    corr_pairs.sort(key=lambda p: -abs(p.correlation))

    max_portfolio_corr = CorrelationService.max_pairwise_with_portfolio(
        existing_tickers=portfolio_tickers,
        candidate=ticker,
        matrix=matrix,
    )

    return TickerCorrelationResponse(
        ticker=ticker,
        max_portfolio_correlation=round(max_portfolio_corr, 6),
        portfolio_tickers=portfolio_tickers,
        correlations=corr_pairs,
        computed_at=computed_at,
    )
