"""
Thematic Exposure Limits.

ThematicExposureService enforces theme-level concentration limits, preventing
the portfolio from accumulating too much exposure to a single investment theme
(e.g. "ai_infrastructure") even when individual position sizes and sector weights
are within their respective limits.

Design mirrors SectorExposureService (Phase 40) intentionally:
- Stateless: all methods are pure (no side-effects, no DB access).
- Theme mapping sourced from config.universe.TICKER_THEME (curated static
  registry); tickers absent from that mapping fall into "other".
- Only OPEN actions are affected — CLOSE and TRIM always pass through.
- Projected weight for a candidate OPEN is computed against current equity
  (same denominator logic as SectorExposureService).
- Uses structlog only — no print() calls.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from config.settings import Settings
    from services.portfolio_engine.models import PortfolioState

log = structlog.get_logger(__name__)

_UNKNOWN_THEME = "other"


def _get_ticker_theme(ticker: str) -> str:
    """Return the primary investment theme for *ticker* from the universe config.

    Falls back to 'other' for tickers not in the static registry or when
    the universe module is unavailable.
    """
    try:
        from config.universe import TICKER_THEME  # noqa: PLC0415

        return TICKER_THEME.get(ticker, _UNKNOWN_THEME)
    except Exception:  # noqa: BLE001
        return _UNKNOWN_THEME


class ThematicExposureService:
    """Enforce theme-level position concentration limits.

    All methods are stateless — caller passes portfolio data explicitly so
    the service remains fully testable without a running database or app state.
    """

    # ── Theme mapping ───────────────────────────────────────────────────────

    @staticmethod
    def get_theme(ticker: str) -> str:
        """Return the investment theme label for *ticker* (always a non-empty string)."""
        return _get_ticker_theme(ticker)

    # ── Portfolio thematic weights ──────────────────────────────────────────

    @classmethod
    def compute_thematic_weights(
        cls,
        positions: dict,  # dict[str, PortfolioPosition]
        equity: Decimal,
    ) -> dict[str, float]:
        """Compute current theme allocations as fractions of portfolio equity.

        Args:
            positions: Mapping of ticker → PortfolioPosition.
            equity:    Total portfolio equity (cash + gross exposure).

        Returns:
            Dict of theme → weight in [0.0, 1.0].
            Empty dict when equity is zero or positions is empty.
        """
        if not positions or equity <= Decimal("0"):
            return {}

        theme_mv: dict[str, Decimal] = {}
        for ticker, pos in positions.items():
            theme = cls.get_theme(ticker)
            mv = getattr(pos, "market_value", Decimal("0"))
            theme_mv[theme] = theme_mv.get(theme, Decimal("0")) + mv

        return {
            theme: float((mv / equity).quantize(Decimal("0.0001")))
            for theme, mv in theme_mv.items()
        }

    # ── Projected thematic weight after a candidate OPEN ───────────────────

    @classmethod
    def projected_thematic_weight(
        cls,
        ticker: str,
        notional: Decimal,
        positions: dict,  # dict[str, PortfolioPosition]
        equity: Decimal,
    ) -> float:
        """Return the theme weight that would result if *ticker* were opened.

        Projects forward:
            new_theme_mv = current_theme_mv + notional
            denominator  = equity (unchanged — cash decreases, gross increases by equal amount)

        Args:
            ticker:    Candidate ticker being considered for OPEN.
            notional:  Target notional of the proposed action.
            positions: Current portfolio positions.
            equity:    Current portfolio equity.

        Returns:
            Projected theme weight as float in [0.0, 1.0].
            Returns 0.0 when the projected equity is zero.
        """
        theme = cls.get_theme(ticker)

        current_theme_mv = Decimal("0")
        for t, pos in positions.items():
            if cls.get_theme(t) == theme:
                current_theme_mv += getattr(pos, "market_value", Decimal("0"))

        new_theme_mv = current_theme_mv + notional
        denom = equity if equity > Decimal("0") else (
            sum(
                getattr(p, "market_value", Decimal("0")) for p in positions.values()
            ) + notional
        )

        if denom <= Decimal("0"):
            return 0.0

        return float((new_theme_mv / denom).quantize(Decimal("0.0001")))

    # ── Action filter ───────────────────────────────────────────────────────

    @classmethod
    def filter_for_thematic_limits(
        cls,
        actions: list,  # list[PortfolioAction]
        portfolio_state: PortfolioState,
        settings: Settings,
    ) -> list:
        """Remove OPEN actions that would breach the thematic exposure limit.

        Non-OPEN actions (CLOSE, TRIM) are always passed through unchanged.

        Args:
            actions:         Proposed list of PortfolioAction objects.
            portfolio_state: Current PortfolioState.
            settings:        Settings instance with max_thematic_pct field.

        Returns:
            Filtered list — same objects, never mutated.
        """
        from services.portfolio_engine.models import ActionType  # noqa: PLC0415

        max_pct: float = float(getattr(settings, "max_thematic_pct", 0.50))
        equity: Decimal = getattr(portfolio_state, "equity", Decimal("0"))
        positions: dict = getattr(portfolio_state, "positions", {})

        allowed: list = []
        for action in actions:
            if action.action_type != ActionType.OPEN:
                allowed.append(action)
                continue

            projected = cls.projected_thematic_weight(
                ticker=action.ticker,
                notional=action.target_notional,
                positions=positions,
                equity=equity,
            )

            if projected > max_pct:
                theme = cls.get_theme(action.ticker)
                log.info(
                    "thematic_exposure_limit_breached",
                    ticker=action.ticker,
                    theme=theme,
                    projected_thematic_pct=round(projected, 4),
                    max_thematic_pct=round(max_pct, 4),
                )
            else:
                allowed.append(action)

        return allowed
