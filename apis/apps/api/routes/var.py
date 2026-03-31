"""
Portfolio VaR & CVaR API routes (Phase 43).

GET /api/v1/portfolio/var
    Returns the latest portfolio-level VaR summary (95%/99% VaR, CVaR,
    per-ticker standalone VaR) computed by run_var_refresh at 06:19 ET.

GET /api/v1/portfolio/var/{ticker}
    Returns standalone VaR contribution for a single position.

Both endpoints serve from in-memory app_state — no DB access on the request
path.  Data is populated by the run_var_refresh job at 06:19 ET.
"""
from __future__ import annotations

from fastapi import APIRouter

from apps.api.deps import AppStateDep, SettingsDep
from apps.api.schemas.var import (
    PortfolioVaRResponse,
    TickerVaRDetailResponse,
    TickerVaRSchema,
)

var_router = APIRouter(prefix="/portfolio", tags=["VaR"])


@var_router.get(
    "/var",
    response_model=PortfolioVaRResponse,
    summary="Portfolio-level VaR & CVaR summary",
    description=(
        "Returns the latest 1-day historical-simulation VaR (95%/99%) and CVaR "
        "(95%) for the current portfolio, plus per-position standalone VaR "
        "contributions.  Data is populated by the run_var_refresh job at 06:19 ET.  "
        "Returns an empty/zeroed response when no VaR computation has run yet."
    ),
)
def get_portfolio_var(
    state: AppStateDep,
    settings: SettingsDep,
) -> PortfolioVaRResponse:
    """Return portfolio VaR summary from in-memory app_state."""
    var_result = getattr(state, "latest_var_result", None)
    max_var_pct: float = float(getattr(settings, "max_portfolio_var_pct", 0.03))

    if var_result is None:
        return PortfolioVaRResponse(
            computed_at=None,
            equity=0.0,
            positions_count=0,
            lookback_days=0,
            insufficient_data=True,
            portfolio_var_95_pct=0.0,
            portfolio_var_99_pct=0.0,
            portfolio_cvar_95_pct=0.0,
            portfolio_var_95_dollar=0.0,
            portfolio_var_99_dollar=0.0,
            portfolio_cvar_95_dollar=0.0,
            max_portfolio_var_pct=max_var_pct * 100,
            var_limit_breached=False,
            tickers=[],
        )

    # Build per-ticker list
    portfolio_state = getattr(state, "portfolio_state", None)
    positions = getattr(portfolio_state, "positions", {}) if portfolio_state else {}
    equity: float = float(var_result.equity)

    ticker_rows: list[TickerVaRSchema] = []
    for ticker, standalone_var_pct in sorted(
        var_result.ticker_var_95.items(), key=lambda x: -x[1]
    ):
        pos = positions.get(ticker)
        mv = float(getattr(pos, "market_value", 0.0)) if pos else 0.0
        weight_pct = (mv / equity * 100) if equity > 0 else 0.0
        ticker_rows.append(
            TickerVaRSchema(
                ticker=ticker,
                weight_pct=round(weight_pct, 2),
                standalone_var_95_pct=round(standalone_var_pct * 100, 4),
                standalone_var_95_dollar=round(standalone_var_pct * equity, 2),
            )
        )

    var_limit_breached = (
        not var_result.insufficient_data
        and max_var_pct > 0.0
        and var_result.portfolio_var_95_pct > max_var_pct
    )

    return PortfolioVaRResponse(
        computed_at=var_result.computed_at,
        equity=equity,
        positions_count=var_result.positions_count,
        lookback_days=var_result.lookback_days,
        insufficient_data=var_result.insufficient_data,
        portfolio_var_95_pct=round(var_result.portfolio_var_95_pct * 100, 4),
        portfolio_var_99_pct=round(var_result.portfolio_var_99_pct * 100, 4),
        portfolio_cvar_95_pct=round(var_result.portfolio_cvar_95_pct * 100, 4),
        portfolio_var_95_dollar=round(var_result.portfolio_var_95_dollar, 2),
        portfolio_var_99_dollar=round(var_result.portfolio_var_99_dollar, 2),
        portfolio_cvar_95_dollar=round(var_result.portfolio_cvar_95_dollar, 2),
        max_portfolio_var_pct=round(max_var_pct * 100, 2),
        var_limit_breached=var_limit_breached,
        tickers=ticker_rows,
    )


@var_router.get(
    "/var/{ticker}",
    response_model=TickerVaRDetailResponse,
    summary="Single-ticker VaR contribution",
    description=(
        "Returns the standalone 1-day 95% VaR contribution for a single position.  "
        "A 200 response with data_available=False is returned when no VaR data "
        "exists for the ticker — 404 is NOT raised."
    ),
)
def get_ticker_var(
    ticker: str,
    state: AppStateDep,
    settings: SettingsDep,
) -> TickerVaRDetailResponse:
    """Return VaR detail for a single ticker."""
    ticker = ticker.upper()
    var_result = getattr(state, "latest_var_result", None)

    if var_result is None:
        return TickerVaRDetailResponse(
            ticker=ticker,
            data_available=False,
            computed_at=None,
        )

    standalone_var_pct = var_result.ticker_var_95.get(ticker)
    if standalone_var_pct is None:
        return TickerVaRDetailResponse(
            ticker=ticker,
            data_available=False,
            computed_at=var_result.computed_at,
            portfolio_var_95_pct=round(var_result.portfolio_var_95_pct * 100, 4),
            equity=var_result.equity,
        )

    equity: float = float(var_result.equity)
    portfolio_state = getattr(state, "portfolio_state", None)
    positions = getattr(portfolio_state, "positions", {}) if portfolio_state else {}
    pos = positions.get(ticker)
    mv = float(getattr(pos, "market_value", 0.0)) if pos else 0.0
    weight_pct = (mv / equity * 100) if equity > 0 else 0.0

    return TickerVaRDetailResponse(
        ticker=ticker,
        data_available=True,
        computed_at=var_result.computed_at,
        weight_pct=round(weight_pct, 2),
        standalone_var_95_pct=round(standalone_var_pct * 100, 4),
        standalone_var_95_dollar=round(standalone_var_pct * equity, 2),
        portfolio_var_95_pct=round(var_result.portfolio_var_95_pct * 100, 4),
        equity=equity,
    )
