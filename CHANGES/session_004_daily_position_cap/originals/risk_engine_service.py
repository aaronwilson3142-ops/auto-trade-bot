"""
Risk Engine Service.

Acts as the hard gatekeeper between portfolio construction and execution.
Every proposed PortfolioAction must pass through validate_action() before
being handed to the ExecutionEngineService.

Rules enforced (in order inside validate_action):
  1. kill_switch              — blocks everything when active
  2. max_positions            — no more opens when portfolio is full
  3. max_single_name_pct      — no single-name overconcentration
  4. daily_loss_limit_pct     — halt new opens if today's loss limit is hit
  5. weekly_drawdown_limit    — halt new opens if drawdown exceeds weekly cap
  6. monthly_drawdown_limit   — halt new opens if MTD loss exceeds monthly cap

CLOSE actions are not blocked by position-count limits; they can always proceed
(subject to kill switch and drawdown limits).

Kill switch sources (both are checked):
  - settings.kill_switch      — env-var flag, set at process start
  - kill_switch_fn()          — optional callable injected at construction time
                                 that returns the runtime app_state.kill_switch_active
                                 flag (toggled via POST /api/v1/admin/kill-switch
                                 without requiring a process restart)

Spec references:
  - API_AND_SERVICE_BOUNDARIES_SPEC.md § 3.11
  - APIS_MASTER_SPEC.md § 4.1 (safety invariants)
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, ROUND_DOWN
from typing import Any, Callable, Optional

import structlog

from config.settings import Settings
from services.portfolio_engine.models import (
    ActionType,
    PortfolioAction,
    PortfolioPosition,
    PortfolioState,
)
from services.risk_engine.models import RiskCheckResult, RiskSeverity, RiskViolation

log = structlog.get_logger(__name__)


def update_position_peak_prices(
    positions: "dict[str, Any]",
    peak_prices: "dict[str, float]",
) -> "dict[str, float]":
    """Update the peak price dict from current position prices.

    For each open position, sets peak_prices[ticker] to max(current, existing_peak).
    New tickers (not yet in peak_prices) are initialized to current_price.

    Args:
        positions:   Open positions dict (ticker → PortfolioPosition).
        peak_prices: Mutable dict of ticker → historical peak price.

    Returns:
        Updated peak_prices dict (same object, mutated in place).
    """
    for ticker, position in positions.items():
        current = float(position.current_price)
        existing = peak_prices.get(ticker)
        if existing is None:
            peak_prices[ticker] = current
        elif current > existing:
            peak_prices[ticker] = current
    return peak_prices


class RiskEngineService:
    """
    Hard gatekeeper for all proposed portfolio actions.

    All checks return a RiskCheckResult.  If any check returns
    is_hard_blocked == True the action must not proceed to execution.
    """

    def __init__(
        self,
        settings: Settings,
        kill_switch_fn: Optional[Callable[[], bool]] = None,
    ) -> None:
        """Initialise the risk engine.

        Args:
            settings:       Application settings (provides env-var kill_switch and
                            all risk-limit thresholds).
            kill_switch_fn: Optional zero-argument callable that returns True when
                            the *runtime* kill switch is active (e.g.
                            ``lambda: app_state.kill_switch_active``).  When None,
                            only the env-var kill_switch is checked.  When provided,
                            the effective kill switch is
                            ``settings.kill_switch OR kill_switch_fn()``.
        """
        self._settings = settings
        self._kill_switch_fn = kill_switch_fn
        self._log = log.bind(service="risk_engine")

    # ── Master validator ──────────────────────────────────────────────────────

    def validate_action(
        self,
        action: PortfolioAction,
        portfolio_state: PortfolioState,
    ) -> RiskCheckResult:
        """Run all applicable risk checks and return a combined result.

        Collects violations from every check so the caller sees the full picture.
        Sets action.risk_approved = True if passed.
        """
        all_violations: list[RiskViolation] = []
        all_warnings: list[str] = []

        checks = [
            self.check_kill_switch(),
            self.check_portfolio_limits(action, portfolio_state),
            self.check_daily_loss_limit(portfolio_state),
            self.check_drawdown(portfolio_state),
            self.check_monthly_drawdown(portfolio_state),
        ]

        for result in checks:
            all_violations.extend(result.violations)
            all_warnings.extend(result.warnings)

        passed = not any(
            v.severity == RiskSeverity.HARD_BLOCK for v in all_violations
        )

        if passed:
            action.risk_approved = True

        combined = RiskCheckResult(
            passed=passed,
            violations=all_violations,
            warnings=all_warnings,
        )

        self._log.info(
            "risk_validate_action",
            ticker=action.ticker,
            action_type=action.action_type.value,
            passed=passed,
            violation_count=len(all_violations),
        )
        return combined

    # ── Individual checks ─────────────────────────────────────────────────────

    def check_kill_switch(self) -> RiskCheckResult:
        """Block all activity when the kill switch is active.

        Checks both the env-var kill_switch (settings.kill_switch) and the
        runtime kill_switch_fn (if provided at construction).  Either source
        being True is sufficient to hard-block the action.
        """
        runtime_active = self._kill_switch_fn() if self._kill_switch_fn is not None else False
        effective_kill = self._settings.kill_switch or runtime_active

        if effective_kill:
            source = "env+runtime" if (self._settings.kill_switch and runtime_active) \
                else ("runtime" if runtime_active else "env")
            return RiskCheckResult(
                passed=False,
                violations=[
                    RiskViolation(
                        rule_name="kill_switch",
                        reason=f"Kill switch is active ({source}) — no orders permitted.",
                        severity=RiskSeverity.HARD_BLOCK,
                    )
                ],
            )
        return RiskCheckResult(passed=True)

    def check_portfolio_limits(
        self,
        action: PortfolioAction,
        portfolio_state: PortfolioState,
    ) -> RiskCheckResult:
        """Enforce max_positions and max_single_name_pct.

        max_positions: only applied to OPEN actions.
        max_single_name_pct: applied to OPEN actions; sets adjusted_max_notional
            rather than outright blocking when downsizing would resolve the breach.
        """
        violations: list[RiskViolation] = []
        warnings: list[str] = []
        adjusted_max_notional: Decimal | None = None

        # ── max_positions (OPEN only) ───────────────────────────────────────
        if action.action_type == ActionType.OPEN:
            if portfolio_state.position_count >= self._settings.max_positions:
                violations.append(
                    RiskViolation(
                        rule_name="max_positions",
                        reason=(
                            f"Portfolio is at capacity: "
                            f"{portfolio_state.position_count}/{self._settings.max_positions} positions."
                        ),
                        severity=RiskSeverity.HARD_BLOCK,
                    )
                )

        # ── max_single_name_pct (OPEN only) ────────────────────────────────
        if action.action_type == ActionType.OPEN and portfolio_state.equity > Decimal("0"):
            max_notional = (
                portfolio_state.equity * Decimal(str(self._settings.max_single_name_pct))
            ).quantize(Decimal("0.01"))

            if action.target_notional > max_notional:
                # Provide adjusted ceiling rather than hard block (size reduction ok).
                adjusted_max_notional = max_notional
                warnings.append(
                    f"target_notional {action.target_notional:.2f} exceeds "
                    f"max_single_name_pct ceiling {max_notional:.2f}; "
                    f"adjusted_max_notional set."
                )

        passed = not any(v.severity == RiskSeverity.HARD_BLOCK for v in violations)
        return RiskCheckResult(
            passed=passed,
            violations=violations,
            warnings=warnings,
            adjusted_max_notional=adjusted_max_notional,
        )

    def check_daily_loss_limit(
        self,
        portfolio_state: PortfolioState,
    ) -> RiskCheckResult:
        """Block new OPEN actions when the daily loss limit is breached.

        If start_of_day_equity is not set, this check is skipped (insufficient data).
        Only fires when the day's P&L is a loss exceeding daily_loss_limit_pct.
        """
        if portfolio_state.start_of_day_equity is None:
            return RiskCheckResult(passed=True, warnings=["daily_loss_limit: no start_of_day_equity; check skipped."])

        daily_pnl = portfolio_state.daily_pnl_pct
        limit = Decimal(str(self._settings.daily_loss_limit_pct))

        # daily_pnl is negative when losing money
        if daily_pnl < -limit:
            return RiskCheckResult(
                passed=False,
                violations=[
                    RiskViolation(
                        rule_name="daily_loss_limit",
                        reason=(
                            f"Daily loss {abs(daily_pnl):.4%} exceeds limit "
                            f"{limit:.4%}. No new opens permitted today."
                        ),
                        severity=RiskSeverity.HARD_BLOCK,
                    )
                ],
            )
        return RiskCheckResult(passed=True)

    def check_drawdown(
        self,
        portfolio_state: PortfolioState,
    ) -> RiskCheckResult:
        """Block new OPEN actions when the weekly drawdown limit is breached.

        If high_water_mark is not set, this check is skipped.
        """
        if portfolio_state.high_water_mark is None:
            return RiskCheckResult(passed=True, warnings=["drawdown: no high_water_mark; check skipped."])

        drawdown = portfolio_state.drawdown_pct
        limit = Decimal(str(self._settings.weekly_drawdown_limit_pct))

        if drawdown > limit:
            return RiskCheckResult(
                passed=False,
                violations=[
                    RiskViolation(
                        rule_name="weekly_drawdown_limit",
                        reason=(
                            f"Drawdown {drawdown:.4%} exceeds weekly limit "
                            f"{limit:.4%}. No new opens permitted."
                        ),
                        severity=RiskSeverity.HARD_BLOCK,
                    )
                ],
            )
        return RiskCheckResult(passed=True)

    def check_monthly_drawdown(
        self,
        portfolio_state: PortfolioState,
    ) -> RiskCheckResult:
        """Block new OPEN actions when the month-to-date loss exceeds the monthly cap.

        If start_of_month_equity is not set, this check is skipped (insufficient data).
        Only fires when the month's P&L is a loss exceeding monthly_drawdown_limit_pct.
        """
        if portfolio_state.start_of_month_equity is None:
            return RiskCheckResult(
                passed=True,
                warnings=["monthly_drawdown: no start_of_month_equity; check skipped."],
            )

        monthly_pnl = portfolio_state.monthly_pnl_pct
        limit = Decimal(str(self._settings.monthly_drawdown_limit_pct))

        # monthly_pnl is negative when losing money
        if monthly_pnl < -limit:
            return RiskCheckResult(
                passed=False,
                violations=[
                    RiskViolation(
                        rule_name="monthly_drawdown_limit",
                        reason=(
                            f"Month-to-date loss {abs(monthly_pnl):.4%} exceeds monthly limit "
                            f"{limit:.4%}. No new opens permitted this month."
                        ),
                        severity=RiskSeverity.HARD_BLOCK,
                    )
                ],
            )
        return RiskCheckResult(passed=True)

    def evaluate_exits(
        self,
        positions: "dict[str, PortfolioPosition]",
        ranked_scores: "Optional[dict[str, Decimal]]" = None,
        reference_dt: "Optional[dt.datetime]" = None,
        peak_prices: "Optional[dict[str, float]]" = None,
    ) -> "list[PortfolioAction]":
        """Evaluate open positions against five exit triggers.

        Triggers checked in priority order (first match fires the exit):
          1. Stop-loss: unrealized_pnl_pct < -stop_loss_pct
          2. Take-profit: unrealized_pnl_pct >= take_profit_pct
          3. Trailing stop: current_price < peak * (1 - trailing_stop_pct)
          4. Age expiry: position held longer than max_position_age_days
          5. Thesis invalidation: ticker is in ranked_scores AND score < exit_score_threshold

        Exit actions are pre-approved (risk_approved=True) because reducing
        exposure never violates position-count or concentration limits.

        Args:
            positions:    Open positions dict (ticker → PortfolioPosition).
            ranked_scores: Mapping of ticker → latest composite_score.
                           Pass None to skip thesis invalidation checks.
            reference_dt: Reference datetime for age calculation (defaults to utcnow).
            peak_prices:  Dict of ticker → peak price since position opened.
                          Pass None to skip trailing stop checks.

        Returns:
            CLOSE PortfolioActions for all triggered positions.
        """
        now = reference_dt or dt.datetime.now(dt.timezone.utc)
        stop_loss = Decimal(str(self._settings.stop_loss_pct))
        max_age_days = self._settings.max_position_age_days
        score_threshold = Decimal(str(self._settings.exit_score_threshold))
        exit_actions: list[PortfolioAction] = []

        for ticker, position in positions.items():
            trigger_reason: Optional[str] = None

            # ── 1. Stop-loss ─────────────────────────────────────────────────
            if position.unrealized_pnl_pct < -stop_loss:
                trigger_reason = (
                    f"stop_loss: pnl={float(position.unrealized_pnl_pct):.2%}"
                    f" < -{float(stop_loss):.2%}"
                )

            # ── 2. Take-profit ───────────────────────────────────────────────
            take_profit = Decimal(str(self._settings.take_profit_pct))
            if trigger_reason is None and take_profit > Decimal("0"):
                if position.unrealized_pnl_pct >= take_profit:
                    trigger_reason = (
                        f"take_profit: pnl={float(position.unrealized_pnl_pct):.2%}"
                        f" >= target={float(take_profit):.2%}"
                    )

            # ── 3. Trailing stop ─────────────────────────────────────────────
            trailing_pct = Decimal(str(self._settings.trailing_stop_pct))
            activation_pct = Decimal(str(self._settings.trailing_stop_activation_pct))
            if trigger_reason is None and trailing_pct > Decimal("0") and peak_prices is not None:
                peak = peak_prices.get(ticker)
                if peak is not None and peak > 0:
                    peak_d = Decimal(str(peak))
                    trail_level = peak_d * (Decimal("1") - trailing_pct)
                    # Only fire if the position has activated (gained enough to arm the stop)
                    if (
                        position.unrealized_pnl_pct >= activation_pct
                        and position.current_price < trail_level
                    ):
                        trigger_reason = (
                            f"trailing_stop: price={float(position.current_price):.2f}"
                            f" < trail_level={float(trail_level):.2f}"
                            f" (peak={float(peak_d):.2f}, pct={float(trailing_pct):.2%})"
                        )

            # ── 4. Age expiry ────────────────────────────────────────────────
            if trigger_reason is None:
                opened_at = position.opened_at
                if opened_at.tzinfo is None and now.tzinfo is not None:
                    opened_at = opened_at.replace(tzinfo=dt.timezone.utc)
                age_days = (now - opened_at).days
                if age_days > max_age_days:
                    trigger_reason = (
                        f"age_expiry: held {age_days}d > max {max_age_days}d"
                    )

            # ── 5. Thesis invalidation ───────────────────────────────────────
            if trigger_reason is None and ranked_scores is not None:
                score = ranked_scores.get(ticker)
                if score is not None and score < score_threshold:
                    trigger_reason = (
                        f"thesis_invalidated: score={float(score):.4f}"
                        f" < threshold={float(score_threshold):.4f}"
                    )

            if trigger_reason is None:
                continue

            action = PortfolioAction(
                action_type=ActionType.CLOSE,
                ticker=ticker,
                reason=trigger_reason,
                target_quantity=position.quantity,
                thesis_summary=position.thesis_summary,
                sizing_rationale=f"exit_trigger: {trigger_reason}",
                risk_approved=True,  # reducing exposure is always safe
            )
            self._log.info(
                "exit_trigger_fired",
                ticker=ticker,
                trigger=trigger_reason,
            )
            exit_actions.append(action)

        return exit_actions

    # ── Phase 26: Overconcentration trim triggers ──────────────────────────────

    def evaluate_trims(
        self,
        portfolio_state: PortfolioState,
    ) -> "list[PortfolioAction]":
        """Generate TRIM actions for positions that exceed max_single_name_pct.

        Fires when a held position's market value has drifted above the single-name
        concentration limit (e.g. due to price appreciation after entry).  Calculates
        the number of shares to sell so that the remaining position equals exactly
        ``max_single_name_pct`` of current portfolio equity (after the sell).

        TRIM actions are pre-approved (``risk_approved=True``) because reducing
        exposure never violates position-count or concentration limits.

        Args:
            portfolio_state: Current portfolio state with positions and equity.

        Returns:
            Pre-approved TRIM PortfolioActions for all overconcentrated positions.
            Returns an empty list if the kill switch is active or equity is zero.
        """
        runtime_active = self._kill_switch_fn() if self._kill_switch_fn is not None else False
        if self._settings.kill_switch or runtime_active:
            return []

        if portfolio_state.equity <= Decimal("0"):
            return []

        max_pct = Decimal(str(self._settings.max_single_name_pct))
        max_value = (portfolio_state.equity * max_pct).quantize(Decimal("0.01"))
        trim_actions: list[PortfolioAction] = []

        for ticker, position in portfolio_state.positions.items():
            if position.market_value <= max_value:
                continue

            if position.current_price <= Decimal("0"):
                # Cannot calculate shares to sell without a valid price — skip.
                continue

            excess_value = position.market_value - max_value
            shares_to_sell = (excess_value / position.current_price).to_integral_value(
                rounding=ROUND_DOWN
            )

            if shares_to_sell <= Decimal("0"):
                continue

            concentration_pct = (
                position.market_value / portfolio_state.equity
            ).quantize(Decimal("0.0001"))

            action = PortfolioAction(
                action_type=ActionType.TRIM,
                ticker=ticker,
                reason=(
                    f"overconcentration: {float(concentration_pct):.1%} > "
                    f"max {float(max_pct):.1%}; sell {shares_to_sell} shares"
                ),
                target_quantity=shares_to_sell,
                thesis_summary=position.thesis_summary,
                sizing_rationale=(
                    f"trim_to_max_single_name_pct={float(max_pct):.1%}"
                ),
                risk_approved=True,  # reducing exposure is always safe
            )
            self._log.info(
                "overconcentration_trim_triggered",
                ticker=ticker,
                concentration_pct=str(concentration_pct),
                max_pct=str(max_pct),
                shares_to_sell=str(shares_to_sell),
            )
            trim_actions.append(action)

        return trim_actions
