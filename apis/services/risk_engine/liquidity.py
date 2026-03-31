"""
Liquidity Filter + Dollar Volume Position Cap — Phase 41.

LiquidityService enforces two complementary liquidity rules:

1. **Minimum ADV gate** — OPEN actions for tickers whose 20-day average dollar
   volume (ADV) falls below ``min_liquidity_dollar_volume`` are dropped entirely.
   Illiquid positions cannot be exited cleanly under stress; better never to
   enter them.

2. **ADV-based notional cap** — For OPENs that pass the gate, target_notional
   is capped to ``max_position_as_pct_of_adv × dollar_volume_20d``.  Entering
   a notional larger than ~10% of daily volume creates adverse market impact and
   exit-liquidity risk even in nominally "liquid" names.

Design rules
------------
- Stateless: every method is pure (no side-effects, no DB access).
- dollar_volume_20d values are passed explicitly (populated by
  run_liquidity_refresh from the feature store DB at 06:17 ET).
- CLOSE and TRIM actions are always passed through unchanged — the filter
  must never block risk-reducing exits.
- Uses dataclasses.replace() to return adjusted PortfolioAction — never
  mutates the original object.
- Uses structlog only — no print() calls.
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

# Fallback ADV when no data is available for a ticker.  Using None (missing)
# rather than 0 lets callers decide the safe default (pass through vs. block).
_MISSING = None


class LiquidityService:
    """Enforce minimum liquidity and ADV-based position size caps.

    All methods are stateless — pass dollar_volumes explicitly so the service
    remains fully testable without a running database or app state.
    """

    # ── Liquidity gate ─────────────────────────────────────────────────────

    @staticmethod
    def is_liquid(
        dollar_volume_20d: float,
        settings: "Settings",
    ) -> bool:
        """Return True if dollar_volume_20d meets the minimum threshold.

        Args:
            dollar_volume_20d: 20-day average daily dollar volume for the ticker.
            settings:          Settings instance carrying min_liquidity_dollar_volume.

        Returns:
            True when dollar_volume_20d >= min_liquidity_dollar_volume.
        """
        min_dv: float = float(getattr(settings, "min_liquidity_dollar_volume", 1_000_000.0))
        return dollar_volume_20d >= min_dv

    # ── ADV notional cap ───────────────────────────────────────────────────

    @staticmethod
    def adv_capped_notional(
        target_notional: Decimal,
        dollar_volume_20d: float,
        settings: "Settings",
    ) -> Decimal:
        """Return target_notional capped to max_position_as_pct_of_adv × ADV.

        When target_notional already fits within the cap, it is returned
        unchanged.  A cap of $0 (degenerate settings) is ignored.

        Args:
            target_notional:   Proposed position notional (Decimal).
            dollar_volume_20d: 20-day average daily dollar volume.
            settings:          Settings instance carrying max_position_as_pct_of_adv.

        Returns:
            Capped notional (Decimal, 2 d.p.).
        """
        max_pct: float = float(getattr(settings, "max_position_as_pct_of_adv", 0.10))
        cap = Decimal(str(round(dollar_volume_20d * max_pct, 2)))
        if cap <= Decimal("0"):
            return target_notional
        return min(target_notional, cap)

    # ── Action filter + ADV cap ────────────────────────────────────────────

    @classmethod
    def filter_for_liquidity(
        cls,
        actions: list,  # list[PortfolioAction]
        dollar_volumes: dict[str, float],  # ticker → dollar_volume_20d
        settings: "Settings",
    ) -> list:
        """Drop illiquid OPENs and apply ADV caps to surviving OPEN actions.

        Processing order for each OPEN action:
          1. Lookup dollar_volume_20d; missing data → pass through (safe default).
          2. If dollar_volume < min_liquidity_dollar_volume → drop.
          3. Cap target_notional to max_pct_of_adv × ADV using dataclasses.replace().
             target_quantity is scaled proportionally (ROUND_DOWN, floor 1 share).
          4. CLOSE and TRIM actions always pass through unchanged.

        Args:
            actions:        Proposed list of PortfolioAction objects.
            dollar_volumes: Dict of ticker → 20-day avg dollar volume float.
            settings:       Settings instance.

        Returns:
            Filtered + adjusted list (same or fewer items, never mutated).
        """
        from services.portfolio_engine.models import ActionType  # noqa: PLC0415

        result: list = []
        for action in actions:
            if action.action_type != ActionType.OPEN:
                result.append(action)
                continue

            ticker = action.ticker
            dv: Optional[float] = dollar_volumes.get(ticker)

            # Missing ADV data → pass through (safe: don't block unknown tickers)
            if dv is None:
                result.append(action)
                continue

            # ── Gate: drop truly illiquid tickers ──────────────────────────
            if not cls.is_liquid(dv, settings):
                log.info(
                    "liquidity_gate_drop",
                    ticker=ticker,
                    dollar_volume_20d=dv,
                    min_threshold=getattr(settings, "min_liquidity_dollar_volume", 1_000_000.0),
                )
                continue  # drop this action

            # ── ADV cap: scale down oversized positions ─────────────────────
            original_notional = action.target_notional
            capped_notional = cls.adv_capped_notional(
                target_notional=original_notional,
                dollar_volume_20d=dv,
                settings=settings,
            ).quantize(Decimal("0.01"))

            if capped_notional < original_notional:
                # Scale target_quantity proportionally
                new_qty: Optional[Decimal] = None
                if action.target_quantity is not None and action.target_quantity > Decimal("0"):
                    scale = capped_notional / original_notional
                    new_qty = (
                        action.target_quantity * scale
                    ).to_integral_value(rounding=ROUND_DOWN)
                    new_qty = max(new_qty, Decimal("1"))

                updated_rationale = (
                    f"{action.sizing_rationale or ''} | "
                    f"adv_cap: dv={dv:.0f} cap={capped_notional}"
                ).strip(" |")

                log.info(
                    "liquidity_adv_cap_applied",
                    ticker=ticker,
                    dollar_volume_20d=round(dv, 0),
                    original_notional=str(original_notional),
                    capped_notional=str(capped_notional),
                )

                action = dataclasses.replace(
                    action,
                    target_notional=capped_notional,
                    target_quantity=new_qty if new_qty is not None else action.target_quantity,
                    sizing_rationale=updated_rationale,
                )

            result.append(action)

        return result

    # ── Per-ticker summary ─────────────────────────────────────────────────

    @classmethod
    def liquidity_summary(
        cls,
        dollar_volumes: dict[str, float],
        settings: "Settings",
    ) -> list[dict]:
        """Return per-ticker liquidity status dicts (sorted by ADV descending).

        Args:
            dollar_volumes: Dict of ticker → dollar_volume_20d float.
            settings:       Settings instance.

        Returns:
            List of dicts with keys: ticker, dollar_volume_20d, is_liquid,
            adv_notional_cap_usd, liquidity_tier.
        """
        min_dv: float = float(getattr(settings, "min_liquidity_dollar_volume", 1_000_000.0))
        max_pct: float = float(getattr(settings, "max_position_as_pct_of_adv", 0.10))

        rows: list[dict] = []
        for ticker, dv in dollar_volumes.items():
            liquid = dv >= min_dv
            cap_usd = round(dv * max_pct, 2)
            # Classify tier (mirrors market_data.utils thresholds)
            if dv >= 100_000_000:
                tier = "high"
            elif dv >= 10_000_000:
                tier = "mid"
            elif dv >= 1_000_000:
                tier = "low"
            else:
                tier = "micro"
            rows.append({
                "ticker": ticker,
                "dollar_volume_20d": dv,
                "is_liquid": liquid,
                "adv_notional_cap_usd": cap_usd,
                "liquidity_tier": tier,
            })

        rows.sort(key=lambda r: -r["dollar_volume_20d"])
        return rows
