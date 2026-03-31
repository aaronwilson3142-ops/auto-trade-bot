"""
Portfolio-Level Value at Risk (VaR) & CVaR Service — Phase 43.

VaRService computes 1-day historical-simulation VaR and CVaR for the current
portfolio.  All methods are stateless and pure — no DB access, no side effects.

Definitions
-----------
- **VaR_95** (1-day, 95% confidence): the minimum loss exceeded with only 5%
  probability over a 1-day horizon.  Expressed both as a fraction of equity
  and as a dollar amount.
- **CVaR_95** (Conditional VaR / Expected Shortfall): the mean of losses that
  exceed VaR_95.  A more conservative and coherent risk measure.
- **VaR_99**: same as VaR_95 but at 99% confidence (stricter).
- **Standalone VaR per ticker**: VaR computed on (weight_i × returns_i) — the
  contribution that ticker i would have if its return alone drove the portfolio.
  Used for per-position risk attribution on the dashboard / API.

Historical simulation
---------------------
1. Obtain the daily close price series for each portfolio position from bar data
   (provided by the caller, typically loaded by run_var_refresh from the DB).
2. Convert prices → daily simple returns: r_t = (p_t - p_{t-1}) / p_{t-1}.
3. Compute weighted portfolio returns: r_port[t] = Σ w_i × r_i[t], where
   w_i = position.market_value / equity.  Dates are intersected so only trading
   days where ALL positions have data are used.
4. Sort portfolio returns ascending; apply percentile cut-offs.

Design rules
------------
- Stateless: every method is pure (no side-effects, no DB access).
- price_history values are passed explicitly (populated by run_var_refresh).
- CLOSE and TRIM actions always pass through filter_for_var_limit unchanged.
- Uses dataclasses.replace() when adjusting PortfolioAction objects.
- structlog only — no print() calls.
- insufficient_data=True when fewer than MIN_OBSERVATIONS return observations
  are available; callers treat this as "no VaR signal".
"""
from __future__ import annotations

import dataclasses
import datetime as dt
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

import structlog

if TYPE_CHECKING:
    from config.settings import Settings
    from services.portfolio_engine.models import PortfolioAction

log = structlog.get_logger(__name__)

# Minimum observations required for a statistically meaningful VaR estimate.
MIN_OBSERVATIONS: int = 30


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class VaRResult:
    """Result of a historical-simulation VaR computation.

    All ``pct`` fields are fractions of equity (e.g. 0.025 = 2.5%).
    All ``dollar`` fields are USD amounts (positive = potential loss).
    """

    computed_at: dt.datetime
    portfolio_var_95_pct: float     # 1-day 95% VaR as fraction of equity
    portfolio_var_99_pct: float     # 1-day 99% VaR as fraction of equity
    portfolio_cvar_95_pct: float    # 1-day 95% CVaR (ES) as fraction of equity
    portfolio_var_95_dollar: float  # 1-day 95% VaR in USD
    portfolio_var_99_dollar: float  # 1-day 99% VaR in USD
    portfolio_cvar_95_dollar: float # 1-day 95% CVaR in USD
    equity: float                   # portfolio equity used in the computation
    ticker_var_95: dict             # ticker → standalone 1-day 95% VaR pct
    lookback_days: int              # number of trading days included
    positions_count: int            # number of positions included
    insufficient_data: bool         # True when < MIN_OBSERVATIONS available


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class VaRService:
    """Compute historical-simulation VaR and CVaR for the portfolio.

    All methods are classmethods / staticmethods — no instance state.
    """

    # ── Return computation ─────────────────────────────────────────────────

    @staticmethod
    def compute_returns(prices: list[float]) -> list[float]:
        """Convert a price series to daily simple returns.

        Args:
            prices: List of daily close prices, oldest first.

        Returns:
            List of daily returns (len = len(prices) - 1).  Any period where
            the prior price is 0 is skipped (returns a shorter list).
        """
        if len(prices) < 2:
            return []
        returns: list[float] = []
        for i in range(1, len(prices)):
            prev = prices[i - 1]
            curr = prices[i]
            if prev > 0 and curr >= 0:
                returns.append((curr - prev) / prev)
        return returns

    @staticmethod
    def align_return_series(
        returns_by_ticker: dict[str, list[float]],
    ) -> dict[str, list[float]]:
        """Truncate all return series to the same length (shortest wins).

        Since all universe tickers trade on the same exchange, small length
        differences arise only from data availability.  Taking the minimum
        length gives a consistent set of overlapping trading days.

        Args:
            returns_by_ticker: Dict of ticker → return list (simple returns).

        Returns:
            Same dict with all lists truncated to the minimum length.
            Tickers with zero returns are excluded.
        """
        if not returns_by_ticker:
            return {}
        # Exclude any tickers with empty returns
        non_empty = {t: r for t, r in returns_by_ticker.items() if r}
        if not non_empty:
            return {}
        min_len = min(len(r) for r in non_empty.values())
        if min_len == 0:
            return {}
        return {t: r[-min_len:] for t, r in non_empty.items()}

    @staticmethod
    def compute_portfolio_returns(
        weights: dict[str, float],  # ticker → fraction of equity [0, 1]
        aligned_returns: dict[str, list[float]],
    ) -> list[float]:
        """Compute weighted-sum portfolio return series.

        Args:
            weights:         Dict of ticker → weight (market_value / equity).
            aligned_returns: Aligned return series per ticker (same length).

        Returns:
            List of portfolio returns (same length as each aligned series).
        """
        if not aligned_returns:
            return []

        # Find common tickers (in both weights and aligned_returns)
        common = [t for t in weights if t in aligned_returns]
        if not common:
            return []

        n = len(next(iter(aligned_returns.values())))
        portfolio_rets: list[float] = [0.0] * n
        for ticker in common:
            w = weights[ticker]
            rets = aligned_returns[ticker]
            for i in range(n):
                portfolio_rets[i] += w * rets[i]
        return portfolio_rets

    # ── VaR / CVaR formulas ────────────────────────────────────────────────

    @staticmethod
    def historical_var(returns: list[float], confidence: float = 0.95) -> float:
        """Return 1-day VaR as a positive fraction of capital (loss threshold).

        Uses the empirical percentile (historical simulation): sort losses
        ascending and take the (1 - confidence) quantile.

        Args:
            returns:    List of daily returns (may be negative).
            confidence: Confidence level (0.95 or 0.99 typical).

        Returns:
            VaR as a non-negative fraction (e.g. 0.025 = 2.5% of equity).
            Returns 0.0 when returns is empty.
        """
        if not returns:
            return 0.0
        sorted_r = sorted(returns)  # ascending: worst losses first
        n = len(sorted_r)
        # Index of the (1 - confidence) quantile
        idx = max(0, int((1.0 - confidence) * n) - 1)
        idx = min(idx, n - 1)
        return max(0.0, -sorted_r[idx])

    @staticmethod
    def historical_cvar(returns: list[float], confidence: float = 0.95) -> float:
        """Return 1-day CVaR (Expected Shortfall) as a positive fraction.

        CVaR = mean of losses strictly beyond VaR (the tail).

        Args:
            returns:    List of daily returns.
            confidence: Confidence level (must match the VaR confidence used).

        Returns:
            CVaR as a non-negative fraction.  Returns 0.0 when returns is empty
            or the tail is empty.
        """
        if not returns:
            return 0.0
        sorted_r = sorted(returns)  # ascending
        n = len(sorted_r)
        cutoff = max(1, int((1.0 - confidence) * n))
        tail = sorted_r[:cutoff]  # worst `cutoff` returns
        if not tail:
            return 0.0
        return max(0.0, -sum(tail) / len(tail))

    # ── Per-ticker standalone VaR ──────────────────────────────────────────

    @classmethod
    def compute_ticker_standalone_var(
        cls,
        ticker: str,
        weight: float,
        returns: list[float],
        confidence: float = 0.95,
    ) -> float:
        """Standalone 1-day VaR for a single position at the given weight.

        Standalone VaR = VaR of (weight × ticker_returns).  This measures
        what the position contributes to tail risk in isolation (ignoring
        diversification benefits with other positions).

        Args:
            ticker:     Ticker label (used for logging only).
            weight:     Position weight (market_value / equity).
            returns:    Daily return series for the ticker.
            confidence: Confidence level.

        Returns:
            Standalone VaR as a fraction of equity (positive = potential loss).
        """
        if not returns or weight <= 0.0:
            return 0.0
        weighted = [w * r for w, r in zip([weight] * len(returns), returns)]
        return cls.historical_var(weighted, confidence)

    # ── Main computation ───────────────────────────────────────────────────

    @classmethod
    def compute_var_result(
        cls,
        positions: dict,             # ticker → Position objects (need market_value attr)
        price_history: dict,         # ticker → list[float] closes (oldest first)
        equity: float,
    ) -> VaRResult:
        """Compute a full VaRResult for the portfolio.

        Args:
            positions:     Dict of ticker → position dataclass with market_value.
            price_history: Dict of ticker → list of daily close prices.
            equity:        Total portfolio equity (used for weights and dollar VaR).

        Returns:
            VaRResult with all VaR/CVaR metrics populated.  ``insufficient_data``
            is set True when fewer than MIN_OBSERVATIONS observations are available.
        """
        now = dt.datetime.now(dt.timezone.utc)

        if not positions or equity <= 0.0:
            return VaRResult(
                computed_at=now,
                portfolio_var_95_pct=0.0,
                portfolio_var_99_pct=0.0,
                portfolio_cvar_95_pct=0.0,
                portfolio_var_95_dollar=0.0,
                portfolio_var_99_dollar=0.0,
                portfolio_cvar_95_dollar=0.0,
                equity=equity,
                ticker_var_95={},
                lookback_days=0,
                positions_count=0,
                insufficient_data=True,
            )

        # Compute returns from price history for each position
        returns_by_ticker: dict[str, list[float]] = {}
        for ticker in positions:
            prices = price_history.get(ticker)
            if prices and len(prices) >= 2:
                r = cls.compute_returns(prices)
                if r:
                    returns_by_ticker[ticker] = r

        # Align series to same length
        aligned = cls.align_return_series(returns_by_ticker)

        lookback_days = len(next(iter(aligned.values()))) if aligned else 0

        insufficient = lookback_days < MIN_OBSERVATIONS

        # Compute position weights
        weights: dict[str, float] = {}
        for ticker, pos in positions.items():
            mv = float(getattr(pos, "market_value", 0.0))
            weights[ticker] = mv / equity if equity > 0 else 0.0

        # Portfolio returns
        portfolio_returns = cls.compute_portfolio_returns(weights, aligned)

        if not portfolio_returns or insufficient:
            var_95_pct = 0.0
            var_99_pct = 0.0
            cvar_95_pct = 0.0
        else:
            var_95_pct = cls.historical_var(portfolio_returns, 0.95)
            var_99_pct = cls.historical_var(portfolio_returns, 0.99)
            cvar_95_pct = cls.historical_cvar(portfolio_returns, 0.95)

        # Per-ticker standalone VaR
        ticker_var: dict[str, float] = {}
        for ticker in positions:
            if ticker in aligned and ticker in weights:
                ticker_var[ticker] = cls.compute_ticker_standalone_var(
                    ticker=ticker,
                    weight=weights[ticker],
                    returns=aligned[ticker],
                    confidence=0.95,
                )

        log.info(
            "var_computed",
            positions_count=len(positions),
            lookback_days=lookback_days,
            var_95_pct=round(var_95_pct * 100, 3),
            var_99_pct=round(var_99_pct * 100, 3),
            cvar_95_pct=round(cvar_95_pct * 100, 3),
            insufficient=insufficient,
        )

        return VaRResult(
            computed_at=now,
            portfolio_var_95_pct=var_95_pct,
            portfolio_var_99_pct=var_99_pct,
            portfolio_cvar_95_pct=cvar_95_pct,
            portfolio_var_95_dollar=var_95_pct * equity,
            portfolio_var_99_dollar=var_99_pct * equity,
            portfolio_cvar_95_dollar=cvar_95_pct * equity,
            equity=equity,
            ticker_var_95=ticker_var,
            lookback_days=lookback_days,
            positions_count=len(positions),
            insufficient_data=insufficient,
        )

    # ── Paper cycle gate ───────────────────────────────────────────────────

    @staticmethod
    def filter_for_var_limit(
        actions: list,              # list[PortfolioAction]
        var_result: "VaRResult",
        settings: "Settings",
    ) -> tuple[list, int]:
        """Drop OPEN actions when portfolio VaR exceeds the configured limit.

        CLOSE and TRIM actions always pass through — the gate must never block
        risk-reducing exits.  When VaR data is insufficient or the limit is not
        breached, all actions pass through unchanged.

        Args:
            actions:    Proposed list of PortfolioAction objects.
            var_result: Latest VaRResult from run_var_refresh.
            settings:   Settings instance carrying max_portfolio_var_pct.

        Returns:
            Tuple of (filtered_actions, blocked_count).
        """
        from services.portfolio_engine.models import ActionType  # noqa: PLC0415

        max_var: float = float(getattr(settings, "max_portfolio_var_pct", 0.03))

        # Insufficient data or limit not set → pass through all
        if var_result.insufficient_data or max_var <= 0.0:
            return actions, 0

        # Limit not breached → pass through all
        if var_result.portfolio_var_95_pct <= max_var:
            return actions, 0

        log.warning(
            "var_gate_applied",
            portfolio_var_95_pct=round(var_result.portfolio_var_95_pct * 100, 3),
            max_var_pct=round(max_var * 100, 3),
        )

        filtered: list = []
        blocked = 0
        for action in actions:
            if action.action_type == ActionType.OPEN:
                blocked += 1
                log.info(
                    "var_gate_open_blocked",
                    ticker=action.ticker,
                    portfolio_var_95_pct=round(var_result.portfolio_var_95_pct * 100, 3),
                )
            else:
                filtered.append(action)

        return filtered, blocked
