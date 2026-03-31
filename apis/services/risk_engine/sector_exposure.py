"""
Sector Exposure Limits — Phase 40.

SectorExposureService enforces sector-level concentration limits, preventing
the portfolio from accumulating too much exposure to a single sector (e.g.
technology) even when individual position sizes are within single-name limits.

Design rules
------------
- Stateless: all methods are pure (no side-effects, no DB access).
- Sector mapping sourced from config.universe.TICKER_SECTOR (curated static
  registry); tickers absent from that mapping fall into "other".
- filter_for_sector_limits() applies to OPEN actions only — CLOSE and TRIM
  actions are always passed through unchanged.
- Sector weight = sum(market_value of sector positions) / portfolio equity.
  Projected weight for a candidate OPEN includes both the new notional and
  the resulting equity increase to avoid overstating concentration.
- When equity is zero the projection uses gross_exposure as denominator
  (safe fallback — prevents divide-by-zero, returns 0.0 on true zero).
- Uses structlog only — no print() calls.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from config.settings import Settings
    from services.portfolio_engine.models import PortfolioAction, PortfolioState

log = structlog.get_logger(__name__)

# Sector label for tickers absent from the universe TICKER_SECTOR registry
_UNKNOWN_SECTOR = "other"


def _get_ticker_sector(ticker: str) -> str:
    """Return the primary sector tag for *ticker* from the universe config.

    Falls back to 'other' for tickers not in the static registry or when
    the universe module is unavailable.
    """
    try:
        from config.universe import TICKER_SECTOR  # noqa: PLC0415

        return TICKER_SECTOR.get(ticker, _UNKNOWN_SECTOR)
    except Exception:  # noqa: BLE001
        return _UNKNOWN_SECTOR


class SectorExposureService:
    """Enforce sector-level position concentration limits.

    All methods are stateless — caller passes portfolio data explicitly so
    the service remains fully testable without a running database or app state.
    """

    # ── Sector mapping ─────────────────────────────────────────────────────

    @staticmethod
    def get_sector(ticker: str) -> str:
        """Return the sector label for *ticker* (always a non-empty string)."""
        return _get_ticker_sector(ticker)

    # ── Portfolio sector weights ────────────────────────────────────────────

    @classmethod
    def compute_sector_weights(
        cls,
        positions: dict,  # dict[str, PortfolioPosition]
        equity: Decimal,
    ) -> dict[str, float]:
        """Compute current sector allocations as fractions of portfolio equity.

        Args:
            positions: Mapping of ticker → PortfolioPosition.
            equity:    Total portfolio equity (cash + gross exposure).

        Returns:
            Dict of sector → weight in [0.0, 1.0].
            Empty dict when equity is zero or positions is empty.
        """
        if not positions or equity <= Decimal("0"):
            return {}

        sector_mv: dict[str, Decimal] = {}
        for ticker, pos in positions.items():
            sector = cls.get_sector(ticker)
            mv = getattr(pos, "market_value", Decimal("0"))
            sector_mv[sector] = sector_mv.get(sector, Decimal("0")) + mv

        return {
            sector: float((mv / equity).quantize(Decimal("0.0001")))
            for sector, mv in sector_mv.items()
        }

    # ── Per-sector market value ─────────────────────────────────────────────

    @classmethod
    def compute_sector_market_values(
        cls,
        positions: dict,  # dict[str, PortfolioPosition]
    ) -> dict[str, Decimal]:
        """Compute gross market value per sector from current positions.

        Args:
            positions: Mapping of ticker → PortfolioPosition.

        Returns:
            Dict of sector → total market value (Decimal).
        """
        sector_mv: dict[str, Decimal] = {}
        for ticker, pos in positions.items():
            sector = cls.get_sector(ticker)
            mv = getattr(pos, "market_value", Decimal("0"))
            sector_mv[sector] = sector_mv.get(sector, Decimal("0")) + mv
        return sector_mv

    # ── Projected sector weight after a candidate OPEN ─────────────────────

    @classmethod
    def projected_sector_weight(
        cls,
        ticker: str,
        notional: Decimal,
        positions: dict,  # dict[str, PortfolioPosition]
        equity: Decimal,
    ) -> float:
        """Return the sector weight that would result if *ticker* were opened.

        Projects forward:
            new_sector_mv = current_sector_mv + notional
            new_equity    = equity + notional   (cash decreases, gross increases)

        Args:
            ticker:    Candidate ticker being considered for OPEN.
            notional:  Target notional of the proposed action.
            positions: Current portfolio positions.
            equity:    Current portfolio equity.

        Returns:
            Projected sector weight as float in [0.0, 1.0].
            Returns 0.0 when the projected equity is zero.
        """
        sector = cls.get_sector(ticker)

        # Current market value for the same sector
        current_sector_mv = Decimal("0")
        for t, pos in positions.items():
            if cls.get_sector(t) == sector:
                current_sector_mv += getattr(pos, "market_value", Decimal("0"))

        new_sector_mv = current_sector_mv + notional
        # Opening a position: cash decreases by notional, gross increases by
        # notional → net equity change is zero.  But for concentration math we
        # compare sector MV to total equity which stays the same.
        denom = equity if equity > Decimal("0") else (
            sum(
                getattr(p, "market_value", Decimal("0")) for p in positions.values()
            ) + notional
        )

        if denom <= Decimal("0"):
            return 0.0

        return float((new_sector_mv / denom).quantize(Decimal("0.0001")))

    # ── Action filter ──────────────────────────────────────────────────────

    @classmethod
    def filter_for_sector_limits(
        cls,
        actions: list,  # list[PortfolioAction]
        portfolio_state: "PortfolioState",
        settings: "Settings",
    ) -> list:
        """Remove OPEN actions that would breach the sector exposure limit.

        Non-OPEN actions (CLOSE, TRIM) are always passed through unchanged.

        Args:
            actions:         Proposed list of PortfolioAction objects.
            portfolio_state: Current PortfolioState.
            settings:        Settings instance with max_sector_pct field.

        Returns:
            Filtered list — same objects, never mutated.
        """
        from services.portfolio_engine.models import ActionType  # noqa: PLC0415

        max_pct: float = float(getattr(settings, "max_sector_pct", 0.40))
        equity: Decimal = getattr(portfolio_state, "equity", Decimal("0"))
        positions: dict = getattr(portfolio_state, "positions", {})

        allowed: list = []
        for action in actions:
            if action.action_type != ActionType.OPEN:
                allowed.append(action)
                continue

            projected = cls.projected_sector_weight(
                ticker=action.ticker,
                notional=action.target_notional,
                positions=positions,
                equity=equity,
            )

            if projected > max_pct:
                sector = cls.get_sector(action.ticker)
                log.info(
                    "sector_exposure_limit_breached",
                    ticker=action.ticker,
                    sector=sector,
                    projected_sector_pct=round(projected, 4),
                    max_sector_pct=round(max_pct, 4),
                )
            else:
                allowed.append(action)

        return allowed
