"""
Phase 49 — Portfolio Rebalancing Engine.

RebalancingService
------------------
Stateless service that computes target weights from the current ranking list,
measures drift vs. held positions, and generates rebalance TRIM / OPEN actions
when drift exceeds the configured threshold.

Design rules
------------
- Stateless: no DB writes, no I/O.
- TRIM rebalance actions are pre-approved (risk_approved=True) — same pattern
  as evaluate_exits / evaluate_trims.
- OPEN rebalance suggestions are NOT pre-approved — they enter the normal
  risk-gate pipeline so VaR, stress, sector, liquidity, earnings, and drawdown
  checks all apply.
- CLOSE actions in proposed_actions always supersede rebalance TRIMs (dedup
  by ticker, same pattern as overconcentration trims).
- Minimum trade size filter (rebalance_min_trade_usd) prevents thrashing on
  tiny drift amounts.
- If enable_rebalancing=False all methods return empty results immediately.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class DriftEntry:
    """Per-ticker drift information."""

    ticker: str
    current_weight: float       # fraction of equity currently allocated
    target_weight: float        # fraction of equity at target allocation
    drift_pct: float            # current_weight - target_weight (signed)
    drift_usd: float            # drift_pct × equity (signed, + = over-allocated)
    action_suggested: str       # "TRIM", "OPEN", or "HOLD"


@dataclass
class RebalanceSummary:
    """Snapshot of portfolio rebalance status."""

    computed_at: str                    # ISO UTC string
    rebalance_enabled: bool
    target_n_positions: int
    total_equity: float
    drift_entries: list[DriftEntry]
    trim_count: int                     # positions over-allocated beyond threshold
    open_count: int                     # positions under-allocated beyond threshold
    hold_count: int                     # within threshold — no action needed
    threshold_pct: float
    min_trade_usd: float


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class RebalancingService:
    """Stateless portfolio rebalancing service."""

    # ------------------------------------------------------------------
    # Target weight computation
    # ------------------------------------------------------------------

    @staticmethod
    def compute_target_weights(
        ranked_tickers: list[str],
        n_positions: int,
    ) -> dict[str, float]:
        """Compute equal-weight target allocation for the top N ranked tickers.

        Args:
            ranked_tickers: ordered list of tickers (best first) from ranking engine.
            n_positions: maximum number of positions (from settings.max_positions).

        Returns:
            Dict mapping ticker → target weight fraction (sums to 1.0).
            Empty dict when ranked_tickers is empty or n_positions < 1.
        """
        if not ranked_tickers or n_positions < 1:
            return {}
        top = ranked_tickers[:n_positions]
        weight = 1.0 / len(top)
        return dict.fromkeys(top, weight)

    # ------------------------------------------------------------------
    # Drift computation
    # ------------------------------------------------------------------

    @staticmethod
    def compute_drift(
        positions: dict[str, Any],
        target_weights: dict[str, float],
        equity: float,
        threshold_pct: float,
        min_trade_usd: float,
    ) -> list[DriftEntry]:
        """Compute per-ticker drift between current allocation and target weights.

        Covers:
        - Tickers in positions that also have a target weight (may need TRIM or OPEN).
        - Tickers in positions with NO target weight (over-allocated — suggest TRIM).
        - Tickers with a target weight but NOT in positions (under-allocated — suggest OPEN).

        Args:
            positions: dict of ticker → Position (must have market_value attribute).
            target_weights: dict of ticker → target fraction.
            equity: current total portfolio equity (USD).
            threshold_pct: minimum |drift_pct| to flag as TRIM or OPEN.
            min_trade_usd: minimum |drift_usd| to flag as actionable.

        Returns:
            List of DriftEntry objects, one per relevant ticker.
        """
        if equity <= 0:
            return []

        entries: list[DriftEntry] = []
        seen: set[str] = set()

        # Tickers currently held
        for ticker, pos in positions.items():
            mv = float(getattr(pos, "market_value", 0) or 0)
            current_w = mv / equity if equity > 0 else 0.0
            target_w = target_weights.get(ticker, 0.0)
            drift_pct = current_w - target_w
            drift_usd = drift_pct * equity

            if drift_pct > threshold_pct and abs(drift_usd) >= min_trade_usd:
                action = "TRIM"
            elif drift_pct < -threshold_pct and abs(drift_usd) >= min_trade_usd:
                action = "OPEN"
            else:
                action = "HOLD"

            entries.append(DriftEntry(
                ticker=ticker,
                current_weight=round(current_w, 6),
                target_weight=round(target_w, 6),
                drift_pct=round(drift_pct, 6),
                drift_usd=round(drift_usd, 2),
                action_suggested=action,
            ))
            seen.add(ticker)

        # Tickers targeted but not yet held
        for ticker, target_w in target_weights.items():
            if ticker in seen:
                continue
            drift_pct = -target_w          # 0% current, target% target → negative drift
            drift_usd = drift_pct * equity

            if abs(drift_pct) > threshold_pct and abs(drift_usd) >= min_trade_usd:
                action = "OPEN"
            else:
                action = "HOLD"

            entries.append(DriftEntry(
                ticker=ticker,
                current_weight=0.0,
                target_weight=round(target_w, 6),
                drift_pct=round(drift_pct, 6),
                drift_usd=round(drift_usd, 2),
                action_suggested=action,
            ))

        return entries

    # ------------------------------------------------------------------
    # Action generation
    # ------------------------------------------------------------------

    @staticmethod
    def generate_rebalance_actions(
        positions: dict[str, Any],
        target_weights: dict[str, float],
        equity: float,
        settings: Any,
    ) -> list[Any]:
        """Generate TRIM and OPEN PortfolioActions to restore target allocation.

        TRIM actions:
        - Pre-approved (risk_approved=True) — same pattern as evaluate_trims.
        - Computed quantity = shares to sell to bring position to target weight.

        OPEN actions:
        - NOT pre-approved — enter normal risk pipeline.
        - target_quantity = shares to buy to reach target weight from current.

        Args:
            positions: dict of ticker → Position.
            target_weights: dict of ticker → target fraction.
            equity: current total portfolio equity (USD).
            settings: Settings instance (reads enable_rebalancing,
                      rebalance_threshold_pct, rebalance_min_trade_usd).

        Returns:
            List of PortfolioAction objects (may be empty).
        """
        if not getattr(settings, "enable_rebalancing", True):
            return []

        threshold_pct: float = float(getattr(settings, "rebalance_threshold_pct", 0.05))
        min_trade_usd: float = float(getattr(settings, "rebalance_min_trade_usd", 500.0))

        if equity <= 0:
            return []

        drift_entries = RebalancingService.compute_drift(
            positions=positions,
            target_weights=target_weights,
            equity=equity,
            threshold_pct=threshold_pct,
            min_trade_usd=min_trade_usd,
        )

        try:
            from services.portfolio_engine.models import ActionType, PortfolioAction
        except ImportError:
            return []

        actions: list[Any] = []

        for entry in drift_entries:
            if entry.action_suggested == "TRIM" and entry.ticker in positions:
                pos = positions[entry.ticker]
                current_price = float(getattr(pos, "current_price", 0) or 0)
                if current_price <= 0:
                    continue

                # Shares to sell = excess USD / price, floored to whole shares
                excess_usd = entry.drift_usd  # positive means over-allocated
                shares_to_sell = Decimal(str(excess_usd / current_price)).quantize(
                    Decimal("1"), rounding=ROUND_DOWN
                )
                if shares_to_sell <= 0:
                    continue

                actions.append(PortfolioAction(
                    ticker=entry.ticker,
                    action_type=ActionType.TRIM,
                    reason=f"rebalance_trim: drift={entry.drift_pct:+.2%}",
                    risk_approved=True,
                    target_quantity=shares_to_sell,
                ))

            elif entry.action_suggested == "OPEN":
                current_price = 0.0
                if entry.ticker in positions:
                    current_price = float(
                        getattr(positions[entry.ticker], "current_price", 0) or 0
                    )
                # For open suggestions we don't have price here — leave target_quantity=None
                # The paper cycle will fetch prices for OPEN actions as normal.
                target_usd = abs(entry.drift_usd)
                if target_usd < min_trade_usd:
                    continue

                qty: Decimal | None = None
                if current_price > 0:
                    qty = Decimal(str(target_usd / current_price)).quantize(
                        Decimal("1"), rounding=ROUND_DOWN
                    )
                    if qty <= 0:
                        continue

                actions.append(PortfolioAction(
                    ticker=entry.ticker,
                    action_type=ActionType.OPEN,
                    reason=f"rebalance_open: drift={entry.drift_pct:+.2%}",
                    risk_approved=False,
                    target_quantity=qty,
                    target_notional=Decimal(str(round(target_usd, 2))),
                ))

        return actions

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    @staticmethod
    def compute_rebalance_summary(
        positions: dict[str, Any],
        target_weights: dict[str, float],
        equity: float,
        settings: Any,
        computed_at: str = "",
    ) -> RebalanceSummary:
        """Build a RebalanceSummary for the API endpoint / dashboard.

        Args:
            positions: dict of ticker → Position.
            target_weights: dict of ticker → target fraction.
            equity: current portfolio equity (USD).
            settings: Settings instance.
            computed_at: ISO UTC timestamp string (optional).

        Returns:
            RebalanceSummary dataclass.
        """
        enabled: bool = bool(getattr(settings, "enable_rebalancing", True))
        threshold_pct: float = float(getattr(settings, "rebalance_threshold_pct", 0.05))
        min_trade_usd: float = float(getattr(settings, "rebalance_min_trade_usd", 500.0))
        max_positions: int = int(getattr(settings, "max_positions", 10))

        if not enabled or equity <= 0:
            return RebalanceSummary(
                computed_at=computed_at,
                rebalance_enabled=enabled,
                target_n_positions=max_positions,
                total_equity=equity,
                drift_entries=[],
                trim_count=0,
                open_count=0,
                hold_count=0,
                threshold_pct=threshold_pct,
                min_trade_usd=min_trade_usd,
            )

        drift_entries = RebalancingService.compute_drift(
            positions=positions,
            target_weights=target_weights,
            equity=equity,
            threshold_pct=threshold_pct,
            min_trade_usd=min_trade_usd,
        )

        trim_count = sum(1 for e in drift_entries if e.action_suggested == "TRIM")
        open_count = sum(1 for e in drift_entries if e.action_suggested == "OPEN")
        hold_count = sum(1 for e in drift_entries if e.action_suggested == "HOLD")

        return RebalanceSummary(
            computed_at=computed_at,
            rebalance_enabled=enabled,
            target_n_positions=max_positions,
            total_equity=equity,
            drift_entries=drift_entries,
            trim_count=trim_count,
            open_count=open_count,
            hold_count=hold_count,
            threshold_pct=threshold_pct,
            min_trade_usd=min_trade_usd,
        )
