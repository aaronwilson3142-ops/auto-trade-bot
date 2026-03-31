"""
Correlation-Aware Position Sizing — Phase 39.

CorrelationService computes pairwise Pearson correlations from daily return
series and provides size-adjustment factors so that highly correlated new
entries receive smaller allocations, limiting hidden cluster risk.

Design rules
------------
- Stateless: every method is pure (no side-effects, no DB access).
- Uses numpy for Pearson computation (already a project dependency).
- Requires ≥ MIN_OBSERVATIONS overlapping returns; falls back to 0.0 when
  data is insufficient rather than raising.
- Uses dataclasses.replace() to return adjusted PortfolioAction — never
  mutates the original object.
- Non-OPEN actions are returned unchanged by adjust_action_for_correlation().
- Size factor is 1.0 (no penalty) when max pairwise correlation ≤ 0.50;
  decays linearly to correlation_size_floor as correlation → 1.0.
"""
from __future__ import annotations

import dataclasses
from decimal import Decimal, ROUND_DOWN
from typing import TYPE_CHECKING, Optional

import structlog

if TYPE_CHECKING:
    from config.settings import Settings
    from services.portfolio_engine.models import PortfolioAction

log = structlog.get_logger(__name__)

# Minimum number of overlapping daily return observations needed to trust
# the Pearson estimate.  Below this threshold we return 0.0 (no penalty).
MIN_OBSERVATIONS = 20

# Correlation below this level carries no size penalty.
_PENALTY_ONSET = 0.50


class CorrelationService:
    """Compute and apply pairwise Pearson correlation adjustments.

    All methods are stateless — pass bar data / matrix explicitly so that
    the service remains easy to test without a running database.
    """

    # ── Matrix computation ─────────────────────────────────────────────────

    @staticmethod
    def compute_correlation_matrix(
        bars_by_ticker: dict[str, list[float]],
    ) -> dict[tuple[str, str], float]:
        """Compute symmetric Pearson correlation matrix from daily return series.

        Args:
            bars_by_ticker: Mapping of ticker → list of *daily return* floats
                            (not prices).  Lists need not be the same length;
                            only the overlapping tail is used.

        Returns:
            Dict keyed by ordered (ticker_a, ticker_b) and (ticker_b, ticker_a)
            pairs so look-up is O(1) regardless of argument order.
            Only pairs with ≥ MIN_OBSERVATIONS overlapping points are included.
        """
        try:
            import numpy as np  # noqa: PLC0415
        except ImportError:
            log.warning("numpy_not_available_correlation_matrix_empty")
            return {}

        matrix: dict[tuple[str, str], float] = {}
        tickers = list(bars_by_ticker.keys())

        for i, a in enumerate(tickers):
            for b in tickers[i + 1 :]:
                returns_a = bars_by_ticker[a]
                returns_b = bars_by_ticker[b]

                # Align on the shorter tail (most-recent N observations)
                n = min(len(returns_a), len(returns_b))
                if n < MIN_OBSERVATIONS:
                    continue

                arr_a = np.array(returns_a[-n:], dtype=float)
                arr_b = np.array(returns_b[-n:], dtype=float)

                # Drop positions where either series has NaN
                mask = np.isfinite(arr_a) & np.isfinite(arr_b)
                if mask.sum() < MIN_OBSERVATIONS:
                    continue

                try:
                    corr = float(np.corrcoef(arr_a[mask], arr_b[mask])[0, 1])
                except Exception:  # noqa: BLE001
                    continue

                if not (-1.0 <= corr <= 1.0):
                    continue

                # Store both orderings for symmetric look-up
                matrix[(a, b)] = corr
                matrix[(b, a)] = corr

        return matrix

    # ── Pair look-up ──────────────────────────────────────────────────────

    @staticmethod
    def get_pairwise(
        ticker_a: str,
        ticker_b: str,
        matrix: dict[tuple[str, str], float],
    ) -> Optional[float]:
        """Return the pairwise correlation between two tickers, or None.

        Tries both orderings so callers need not worry about key direction.
        """
        val = matrix.get((ticker_a, ticker_b))
        if val is not None:
            return val
        return matrix.get((ticker_b, ticker_a))

    # ── Portfolio-level max correlation ───────────────────────────────────

    @classmethod
    def max_pairwise_with_portfolio(
        cls,
        existing_tickers: list[str],
        candidate: str,
        matrix: dict[tuple[str, str], float],
    ) -> float:
        """Return the maximum pairwise |correlation| of candidate vs portfolio.

        Uses absolute value so strongly *negative* correlations (rare for
        equities but possible) also reduce sizing — both types indicate that
        the candidate is not truly independent of the existing basket.

        Returns 0.0 when the portfolio is empty or no matrix data exists.
        """
        if not existing_tickers or not matrix:
            return 0.0

        max_corr = 0.0
        for ticker in existing_tickers:
            if ticker == candidate:
                continue
            val = cls.get_pairwise(candidate, ticker, matrix)
            if val is not None:
                max_corr = max(max_corr, abs(val))

        return max_corr

    # ── Size factor ───────────────────────────────────────────────────────

    @staticmethod
    def correlation_size_factor(max_corr: float, settings: "Settings") -> float:
        """Map maximum pairwise correlation to a position size multiplier.

        No penalty below _PENALTY_ONSET (0.50).  Linear decay from 1.0 to
        ``settings.correlation_size_floor`` as max_corr rises from 0.50 → 1.0.

        Args:
            max_corr: Maximum absolute pairwise correlation [0.0, 1.0].
            settings: Settings instance carrying correlation_size_floor.

        Returns:
            Multiplier in [correlation_size_floor, 1.0].
        """
        floor = getattr(settings, "correlation_size_floor", 0.25)
        if max_corr <= _PENALTY_ONSET:
            return 1.0

        # Linear interpolation: factor = 1.0 at onset → floor at 1.0
        slope = (1.0 - floor) / (1.0 - _PENALTY_ONSET)
        factor = 1.0 - slope * (max_corr - _PENALTY_ONSET)
        return max(floor, min(1.0, factor))

    # ── Action adjustment ─────────────────────────────────────────────────

    @classmethod
    def adjust_action_for_correlation(
        cls,
        action: "PortfolioAction",
        existing_tickers: list[str],
        matrix: dict[tuple[str, str], float],
        settings: "Settings",
    ) -> "PortfolioAction":
        """Return a correlation-adjusted OPEN action (or the original unchanged).

        Non-OPEN actions are returned as-is.  Empty portfolio or missing matrix
        data also return the action unchanged.

        Applies correlation_size_factor to target_notional and target_quantity.
        Uses dataclasses.replace() — never mutates the original.

        Args:
            action:           Proposed PortfolioAction.
            existing_tickers: Tickers of currently open positions.
            matrix:           Precomputed correlation matrix (may be empty dict).
            settings:         Settings instance.

        Returns:
            Adjusted PortfolioAction (or original when no adjustment needed).
        """
        from services.portfolio_engine.models import ActionType  # noqa: PLC0415

        if action.action_type != ActionType.OPEN:
            return action

        if not existing_tickers or not matrix:
            return action

        max_corr = cls.max_pairwise_with_portfolio(
            existing_tickers=existing_tickers,
            candidate=action.ticker,
            matrix=matrix,
        )

        factor = cls.correlation_size_factor(max_corr, settings)

        if factor >= 1.0:
            return action

        # Scale down target_notional and target_quantity
        new_notional = (action.target_notional * Decimal(str(round(factor, 6)))).quantize(
            Decimal("0.01")
        )

        new_qty: Optional[Decimal] = None
        if action.target_quantity is not None and action.target_quantity > Decimal("0"):
            new_qty = (
                action.target_quantity * Decimal(str(round(factor, 6)))
            ).to_integral_value(rounding=ROUND_DOWN)
            # Never reduce below 1 share
            new_qty = max(new_qty, Decimal("1"))

        updated_rationale = (
            f"{action.sizing_rationale or ''} | "
            f"correlation_adj: max_corr={max_corr:.3f} factor={factor:.3f}"
        ).strip(" |")

        log.info(
            "correlation_size_adjustment",
            ticker=action.ticker,
            max_pairwise_corr=round(max_corr, 4),
            size_factor=round(factor, 4),
            original_notional=str(action.target_notional),
            adjusted_notional=str(new_notional),
        )

        return dataclasses.replace(
            action,
            target_notional=new_notional,
            target_quantity=new_qty if new_qty is not None else action.target_quantity,
            sizing_rationale=updated_rationale,
        )
