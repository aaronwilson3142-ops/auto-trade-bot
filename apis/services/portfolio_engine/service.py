"""
Portfolio Engine Service.

Owns portfolio state models, candidate sizing proposals, and add/trim/exit
proposal generation.  Does NOT enforce risk limits and does NOT submit orders.
Risk checks happen in risk_engine.  Order submission happens in execution_engine.

Spec references:
  - API_AND_SERVICE_BOUNDARIES_SPEC.md § 3.10
  - APIS_MASTER_SPEC.md § 4.1 (long-only, max 10 positions, no leverage)
"""
from __future__ import annotations

import datetime as dt
from decimal import ROUND_DOWN, Decimal

import structlog

from config.settings import Settings
from services.portfolio_engine.models import (
    ActionType,
    PortfolioAction,
    PortfolioSnapshot,
    PortfolioState,
    SizingResult,
)
from services.ranking_engine.models import RankedResult

log = structlog.get_logger(__name__)

# Minimum position size in dollars — below this, skip opening
_MIN_NOTIONAL = Decimal("100.00")


class PortfolioEngineService:
    """
    Converts ranked opportunities into proposed portfolio actions.

    Thread-safety: not thread-safe; callers must coordinate access.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._log = log.bind(service="portfolio_engine")

    # ── Public API ────────────────────────────────────────────────────────────

    def apply_ranked_opportunities(
        self,
        ranked_results: list[RankedResult],
        portfolio_state: PortfolioState,
    ) -> list[PortfolioAction]:
        """Generate portfolio actions from a ranked opportunity list.

        Logic:
        1. Select the top 'buy'-recommended results that are NOT already held.
        2. For each new opportunity (while position_count + opens < max_positions),
           generate an OPEN action sized by compute_sizing().
        3. For each currently-held ticker NOT in the top buy set, generate a CLOSE.

        Returns a list of actions: opens first, then closes.
        """
        buy_results = [r for r in ranked_results if r.recommended_action == "buy"]
        buy_tickers: set[str] = {r.ticker for r in buy_results}
        held_tickers: set[str] = set(portfolio_state.positions.keys())

        actions: list[PortfolioAction] = []

        # ── Open new positions ──────────────────────────────────────────────
        available_slots = self._settings.max_positions - portfolio_state.position_count
        opened = 0

        for result in buy_results:
            if opened >= available_slots:
                break
            if result.ticker in held_tickers:
                self._log.debug(
                    "skipping_already_held",
                    ticker=result.ticker,
                )
                continue

            action = self.open_position(result, portfolio_state)
            if action.target_notional >= _MIN_NOTIONAL:
                actions.append(action)
                opened += 1

        # ── Close stale positions ───────────────────────────────────────────
        for ticker in held_tickers:
            if ticker not in buy_tickers:
                actions.append(
                    self.close_position(ticker, portfolio_state, reason="not_in_buy_set")
                )

        self._log.info(
            "apply_ranked_opportunities_complete",
            opens=sum(1 for a in actions if a.action_type == ActionType.OPEN),
            closes=sum(1 for a in actions if a.action_type == ActionType.CLOSE),
        )
        return actions

    def open_position(
        self,
        ranked_result: RankedResult,
        portfolio_state: PortfolioState,
    ) -> PortfolioAction:
        """Generate an OPEN action with Kelly-based sizing for a ranked opportunity."""
        sizing = self.compute_sizing(ranked_result, portfolio_state)

        self._log.debug(
            "open_position_proposed",
            ticker=ranked_result.ticker,
            target_notional=str(sizing.target_notional),
            sizing_rationale=sizing.rationale,
        )

        return PortfolioAction(
            action_type=ActionType.OPEN,
            ticker=ranked_result.ticker,
            reason="ranked_buy_signal",
            target_notional=sizing.target_notional,
            thesis_summary=ranked_result.thesis_summary,
            sizing_rationale=sizing.rationale,
            risk_approved=False,
            security_id=ranked_result.security_id,
            ranked_result=ranked_result,
        )

    def close_position(
        self,
        ticker: str,
        portfolio_state: PortfolioState,
        reason: str = "position_exit",
    ) -> PortfolioAction:
        """Generate a CLOSE action for a currently held position.

        The explanation is derived from the existing position's thesis so that
        gate-C's "exits are explainable" requirement is satisfied.
        """
        position = portfolio_state.positions.get(ticker)
        thesis = position.thesis_summary if position else ""
        quantity = position.quantity if position else None

        self._log.debug("close_position_proposed", ticker=ticker, reason=reason)

        return PortfolioAction(
            action_type=ActionType.CLOSE,
            ticker=ticker,
            reason=reason,
            target_quantity=quantity,
            thesis_summary=thesis,
            sizing_rationale=f"full exit: {reason}",
            risk_approved=False,
        )

    def snapshot(self, portfolio_state: PortfolioState) -> PortfolioSnapshot:
        """Create a PortfolioSnapshot from the current in-memory state."""
        snap = PortfolioSnapshot(
            snapshot_at=dt.datetime.utcnow(),
            cash=portfolio_state.cash,
            equity=portfolio_state.equity,
            gross_exposure=portfolio_state.gross_exposure,
            position_count=portfolio_state.position_count,
            drawdown_pct=portfolio_state.drawdown_pct,
            daily_pnl_pct=portfolio_state.daily_pnl_pct,
            positions=list(portfolio_state.positions.values()),
            mode=self._settings.operating_mode.value,
        )
        self._log.info(
            "portfolio_snapshot",
            equity=str(snap.equity),
            positions=snap.position_count,
            drawdown_pct=str(snap.drawdown_pct),
        )
        return snap

    def compute_sizing(
        self,
        ranked_result: RankedResult,
        portfolio_state: PortfolioState,
    ) -> SizingResult:
        """Compute a half-Kelly position size capped at configured limits.

        Formula (half-Kelly for binary outcome):
            f* = 0.5 × max(0, 2p − 1)
          where p = composite_score ∈ [0, 1].
          Interpretation: 0 edge at p=0.5, 20% at p=0.7, 40% at p=0.9.

        Ceiling ordering (tightest wins):
            min(half_kelly, sizing_hint_pct, max_single_name_pct)

        Also enforces a floor of 0 (no negative notional).
        """
        p = float(ranked_result.composite_score or Decimal("0.5"))
        p = max(0.0, min(1.0, p))

        half_kelly_pct = 0.5 * max(0.0, 2.0 * p - 1.0)
        # -- Deep-Dive Plan Step 5 Rec 5 -- portfolio_fit promotion ------------
        # Flag OFF => untouched half-Kelly (byte-for-byte legacy).
        # Flag ON => multiply by portfolio_fit_score when the ranking engine
        # produced one; missing fit score leaves Kelly alone.  The downstream
        # min() with max_single_name_pct still binds, so this can only REDUCE
        # a size, never inflate past the risk-engine cap.
        fit_on = bool(getattr(self._settings, "portfolio_fit_sizing_enabled", False))
        fit_score = ranked_result.portfolio_fit_score
        if fit_on and fit_score is not None:
            try:
                fit_f = max(0.0, min(1.0, float(fit_score)))
            except (TypeError, ValueError):
                fit_f = 1.0
            half_kelly_pct = half_kelly_pct * fit_f
        half_kelly_decimal = Decimal(str(round(half_kelly_pct, 6)))

        ceilings = [self._settings.max_single_name_pct]
        rationale_parts = [f"half_kelly={half_kelly_decimal:.4f}"]
        if fit_on and fit_score is not None:
            rationale_parts.append(f"fit_score={float(fit_score):.4f}")

        if ranked_result.sizing_hint_pct is not None:
            ceilings.append(float(ranked_result.sizing_hint_pct))
            rationale_parts.append(
                f"sizing_hint={ranked_result.sizing_hint_pct:.4f}"
            )

        effective_ceiling = Decimal(str(min(ceilings)))
        effective_ceiling_str = f"ceiling={effective_ceiling:.4f} "
        effective_ceiling_str += f"(max_single_name={self._settings.max_single_name_pct:.4f})"

        capped = half_kelly_decimal > effective_ceiling
        final_pct = min(half_kelly_decimal, effective_ceiling)
        final_pct = max(Decimal("0"), final_pct)

        equity = portfolio_state.equity
        target_notional = (final_pct * equity).quantize(Decimal("0.01"), rounding=ROUND_DOWN)

        rationale = (
            f"composite_score={p:.4f}; "
            + "; ".join(rationale_parts)
            + f"; {effective_ceiling_str}"
            + ("; CAPPED" if capped else "")
            + f" → {final_pct:.4f} × equity({equity:.2f}) = {target_notional:.2f}"
        )

        return SizingResult(
            target_notional=target_notional,
            target_pct=final_pct,
            half_kelly_pct=half_kelly_decimal,
            capped=capped,
            rationale=rationale,
        )

