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
    from services.portfolio_engine.models import PortfolioState

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
        portfolio_state: PortfolioState,
        settings: Settings,
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

    # ── Sector rebalance trims ─────────────────────────────────────────────

    @classmethod
    def generate_sector_trim_actions(
        cls,
        portfolio_state: PortfolioState,
        settings: Settings,
        already_closing: set[str] | None = None,
    ) -> list:
        """Generate TRIM actions to reduce overweight sectors back under the limit.

        When a sector's current weight exceeds max_sector_pct, the lowest-ranked
        positions in that sector are trimmed (by market value descending, so the
        largest overweight positions are reduced first) until the projected sector
        weight drops to or below the limit.

        TRIM actions are pre-approved (risk_approved=True) — same pattern as
        overconcentration trims and rebalance trims.

        Args:
            portfolio_state: Current PortfolioState.
            settings:        Settings instance with max_sector_pct field.
            already_closing: Set of tickers already marked for CLOSE (skip these).

        Returns:
            List of PortfolioAction TRIM objects (may be empty).
        """
        from decimal import ROUND_DOWN  # noqa: PLC0415

        from services.portfolio_engine.models import ActionType, PortfolioAction  # noqa: PLC0415

        max_pct: float = float(getattr(settings, "max_sector_pct", 0.40))
        equity: Decimal = getattr(portfolio_state, "equity", Decimal("0"))
        positions: dict = getattr(portfolio_state, "positions", {})
        closing: set[str] = already_closing or set()

        if not positions or equity <= Decimal("0"):
            return []

        # Compute current sector weights
        sector_weights = cls.compute_sector_weights(positions, equity)
        overweight_sectors = {
            s: w for s, w in sector_weights.items() if w > max_pct
        }

        if not overweight_sectors:
            return []

        trim_actions: list = []

        for sector, current_weight in overweight_sectors.items():
            # Gather all open positions in this sector, sorted by market_value
            # descending (trim largest first to reduce exposure fastest).
            sector_positions = []
            for ticker, pos in positions.items():
                if ticker in closing:
                    continue
                if cls.get_sector(ticker) == sector:
                    mv = float(getattr(pos, "market_value", Decimal("0")))
                    sector_positions.append((ticker, pos, mv))
            sector_positions.sort(key=lambda x: x[2], reverse=True)

            if not sector_positions:
                continue

            # Target sector market value = max_pct × equity
            target_sector_mv = float(equity) * max_pct
            current_sector_mv = sum(mv for _, _, mv in sector_positions)
            excess_mv = current_sector_mv - target_sector_mv

            if excess_mv <= 0:
                continue

            remaining_excess = excess_mv

            for ticker, pos, mv in sector_positions:
                if remaining_excess <= 0:
                    break

                current_price = float(getattr(pos, "current_price", 0) or 0)
                quantity = float(getattr(pos, "quantity", 0) or 0)
                if current_price <= 0 or quantity <= 0:
                    continue

                # Trim enough to eliminate excess, but don't close entire position.
                # Leave at least 1 share.
                max_trim_value = min(remaining_excess, mv - current_price)
                if max_trim_value <= 0:
                    continue

                shares_to_sell = Decimal(str(max_trim_value / current_price)).quantize(
                    Decimal("1"), rounding=ROUND_DOWN
                )
                if shares_to_sell <= 0:
                    continue

                # Don't sell more than (quantity - 1) to keep position alive
                max_sellable = Decimal(str(int(quantity))) - Decimal("1")
                if max_sellable <= 0:
                    continue
                shares_to_sell = min(shares_to_sell, max_sellable)

                trim_actions.append(PortfolioAction(
                    ticker=ticker,
                    action_type=ActionType.TRIM,
                    reason=f"sector_rebalance: {sector} at {current_weight:.1%} > {max_pct:.0%}",
                    risk_approved=True,
                    target_quantity=shares_to_sell,
                ))

                remaining_excess -= float(shares_to_sell) * current_price
                closing.add(ticker)

                log.info(
                    "sector_rebalance_trim_generated",
                    ticker=ticker,
                    sector=sector,
                    shares_to_sell=int(shares_to_sell),
                    current_sector_pct=round(current_weight, 4),
                    max_sector_pct=round(max_pct, 4),
                )

        return trim_actions
