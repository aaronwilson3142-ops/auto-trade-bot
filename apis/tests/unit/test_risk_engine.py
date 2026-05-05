"""
Gate C — Risk Engine Tests.

Verifies:
  - kill_switch: blocks everything when active
  - max_positions: blocks new opens when portfolio is full
  - max_single_name_pct: sets adjusted_max_notional on oversized proposals
  - daily_loss_limit: blocks new opens when day's loss exceeds limit
  - drawdown: blocks new opens when drawdown exceeds weekly limit
  - monthly_drawdown: blocks new opens when MTD loss exceeds monthly cap
  - daily_position_cap: blocks new opens once the per-day open limit is reached
  - sector_concentration: blocks opens that breach max_sector_pct
  - thematic_concentration: blocks opens that breach max_thematic_pct
  - validate_action: aggregates all violations; CLOSE actions bypass position-count
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from config.settings import Settings
from services.portfolio_engine.models import (
    ActionType,
    PortfolioAction,
    PortfolioPosition,
    PortfolioState,
)
from services.risk_engine.models import RiskSeverity
from services.risk_engine.service import RiskEngineService

# ─────────────────────────── helpers ─────────────────────────────────────────

def _settings(**overrides) -> Settings:
    import os
    os.environ.setdefault("APIS_ENV", "development")
    os.environ.setdefault("APIS_OPERATING_MODE", "research")
    os.environ.setdefault("APIS_DB_URL", "postgresql+psycopg://test:test@localhost:5432/apis_test")
    s = Settings()
    for k, v in overrides.items():
        object.__setattr__(s, k, v)
    return s


def _pos(ticker: str) -> PortfolioPosition:
    return PortfolioPosition(
        ticker=ticker,
        quantity=Decimal("100"),
        avg_entry_price=Decimal("100"),
        current_price=Decimal("100"),
        opened_at=dt.datetime.utcnow(),
    )


def _open_action(
    ticker: str = "NVDA",
    notional: Decimal = Decimal("5000.00"),
) -> PortfolioAction:
    return PortfolioAction(
        action_type=ActionType.OPEN,
        ticker=ticker,
        reason="test_open",
        target_notional=notional,
    )


def _close_action(ticker: str = "AAPL") -> PortfolioAction:
    return PortfolioAction(
        action_type=ActionType.CLOSE,
        ticker=ticker,
        reason="test_close",
    )


def _full_state(n: int = 10) -> PortfolioState:
    """Portfolio with n positions each worth $10k, cash $100k."""
    state = PortfolioState(cash=Decimal("100000.00"))
    for i in range(n):
        ticker = f"T{i:03d}"
        state.positions[ticker] = _pos(ticker)
    return state


# ─────────────────────────────────────────────────────────────────────────────
# TestKillSwitch
# ─────────────────────────────────────────────────────────────────────────────

class TestKillSwitch:
    def test_kill_switch_active_blocks(self):
        svc = RiskEngineService(settings=_settings(kill_switch=True))
        result = svc.check_kill_switch()
        assert result.passed is False
        assert result.is_hard_blocked is True
        assert any(v.rule_name == "kill_switch" for v in result.violations)

    def test_kill_switch_inactive_passes(self):
        svc = RiskEngineService(settings=_settings(kill_switch=False))
        result = svc.check_kill_switch()
        assert result.passed is True
        assert result.violations == []

    def test_validate_action_blocks_when_kill_switch_active(self):
        svc = RiskEngineService(settings=_settings(kill_switch=True))
        state = PortfolioState(cash=Decimal("100000.00"))
        action = _open_action()
        result = svc.validate_action(action, state)
        assert result.passed is False
        assert action.risk_approved is False

    # ── Runtime kill_switch_fn tests ──────────────────────────────────────────

    def test_runtime_kill_switch_fn_blocks_when_true(self):
        """kill_switch_fn returning True blocks even when env kill_switch is False."""
        svc = RiskEngineService(
            settings=_settings(kill_switch=False),
            kill_switch_fn=lambda: True,
        )
        result = svc.check_kill_switch()
        assert result.passed is False
        assert result.is_hard_blocked is True
        assert any(v.rule_name == "kill_switch" for v in result.violations)
        # Source string reflects runtime flag
        assert "runtime" in result.violations[0].reason

    def test_runtime_kill_switch_fn_passes_when_false(self):
        """kill_switch_fn returning False + env False = passes."""
        svc = RiskEngineService(
            settings=_settings(kill_switch=False),
            kill_switch_fn=lambda: False,
        )
        result = svc.check_kill_switch()
        assert result.passed is True
        assert result.violations == []

    def test_runtime_kill_switch_fn_both_active(self):
        """Both env and runtime active = still blocks, source string shows both."""
        svc = RiskEngineService(
            settings=_settings(kill_switch=True),
            kill_switch_fn=lambda: True,
        )
        result = svc.check_kill_switch()
        assert result.passed is False
        assert "env+runtime" in result.violations[0].reason

    def test_no_kill_switch_fn_env_inactive_passes(self):
        """No kill_switch_fn and env kill_switch=False = passes (backward-compat)."""
        svc = RiskEngineService(settings=_settings(kill_switch=False))
        result = svc.check_kill_switch()
        assert result.passed is True

    def test_runtime_kill_switch_blocks_validate_action(self):
        """validate_action respects runtime kill_switch_fn."""
        svc = RiskEngineService(
            settings=_settings(kill_switch=False),
            kill_switch_fn=lambda: True,
        )
        state = PortfolioState(cash=Decimal("100000.00"))
        action = _open_action()
        result = svc.validate_action(action, state)
        assert result.passed is False
        assert action.risk_approved is False

    def test_runtime_kill_switch_blocks_evaluate_trims(self):
        """evaluate_trims returns empty list when runtime kill switch is active."""
        svc = RiskEngineService(
            settings=_settings(kill_switch=False),
            kill_switch_fn=lambda: True,
        )
        state = PortfolioState(cash=Decimal("100000.00"))
        assert svc.evaluate_trims(state) == []

    def test_mutable_runtime_kill_switch(self):
        """kill_switch_fn is re-evaluated on every call (reflects live state changes)."""
        state_flag = {"active": False}
        svc = RiskEngineService(
            settings=_settings(kill_switch=False),
            kill_switch_fn=lambda: state_flag["active"],
        )
        # Initially off — passes
        assert svc.check_kill_switch().passed is True
        # Flip on at runtime — now blocks
        state_flag["active"] = True
        result = svc.check_kill_switch()
        assert result.passed is False
        assert "runtime" in result.violations[0].reason


# ─────────────────────────────────────────────────────────────────────────────
# TestMaxPositions
# ─────────────────────────────────────────────────────────────────────────────

class TestMaxPositions:
    def test_blocks_open_at_max_positions(self):
        # Pin max_positions=10 explicitly — production .env raises it to 15
        # since 2026-04-15, so default-settings tests would be under-cap.
        svc = RiskEngineService(settings=_settings(max_positions=10))
        state = _full_state(10)
        result = svc.check_portfolio_limits(_open_action(), state)
        assert result.passed is False
        assert any(v.rule_name == "max_positions" for v in result.violations)

    def test_allows_open_below_max(self):
        svc = RiskEngineService(settings=_settings())
        state = _full_state(5)
        result = svc.check_portfolio_limits(_open_action(), state)
        # May have adjusted_max_notional warning but no hard block on position count
        hard_blocks = [v for v in result.violations if v.severity == RiskSeverity.HARD_BLOCK and v.rule_name == "max_positions"]
        assert len(hard_blocks) == 0

    def test_close_never_blocked_by_max_positions(self):
        svc = RiskEngineService(settings=_settings())
        state = _full_state(10)  # full
        result = svc.check_portfolio_limits(_close_action(), state)
        pos_blocks = [v for v in result.violations if v.rule_name == "max_positions"]
        assert len(pos_blocks) == 0


# ─────────────────────────────────────────────────────────────────────────────
# TestMaxSingleNamePct
# ─────────────────────────────────────────────────────────────────────────────

class TestMaxSingleNamePct:
    def test_oversized_notional_sets_adjusted_max(self):
        """Notional $30k on $100k equity exceeds 20% ceiling → adjusted_max_notional set."""
        svc = RiskEngineService(settings=_settings())
        state = PortfolioState(cash=Decimal("100000.00"))
        action = _open_action(notional=Decimal("30000.00"))
        result = svc.check_portfolio_limits(action, state)
        # Not a hard block — sizing recommendation returned instead
        assert result.adjusted_max_notional == Decimal("20000.00")
        assert len(result.warnings) > 0

    def test_within_limit_no_adjustment(self):
        svc = RiskEngineService(settings=_settings())
        state = PortfolioState(cash=Decimal("100000.00"))
        action = _open_action(notional=Decimal("15000.00"))
        result = svc.check_portfolio_limits(action, state)
        assert result.adjusted_max_notional is None

    def test_exact_at_ceiling_no_adjustment(self):
        svc = RiskEngineService(settings=_settings())
        state = PortfolioState(cash=Decimal("100000.00"))
        action = _open_action(notional=Decimal("20000.00"))
        result = svc.check_portfolio_limits(action, state)
        assert result.adjusted_max_notional is None


# ─────────────────────────────────────────────────────────────────────────────
# TestDailyLossLimit
# ─────────────────────────────────────────────────────────────────────────────

class TestDailyLossLimit:
    def test_blocks_when_daily_loss_exceeded(self):
        """Start equity $100k, current equity $97k → -3% loss > 2% limit."""
        svc = RiskEngineService(settings=_settings())  # daily_loss_limit_pct=0.02
        state = PortfolioState(
            cash=Decimal("97000.00"),
            start_of_day_equity=Decimal("100000.00"),
        )
        result = svc.check_daily_loss_limit(state)
        assert result.passed is False
        assert any(v.rule_name == "daily_loss_limit" for v in result.violations)

    def test_passes_when_loss_within_limit(self):
        """Start equity $100k, current equity $99k → -1% loss < 2% limit."""
        svc = RiskEngineService(settings=_settings())
        state = PortfolioState(
            cash=Decimal("99000.00"),
            start_of_day_equity=Decimal("100000.00"),
        )
        result = svc.check_daily_loss_limit(state)
        assert result.passed is True

    def test_passes_when_no_start_of_day_equity(self):
        """No start_of_day_equity → check skipped with warning."""
        svc = RiskEngineService(settings=_settings())
        state = PortfolioState(cash=Decimal("99000.00"))
        result = svc.check_daily_loss_limit(state)
        assert result.passed is True
        assert len(result.warnings) > 0

    def test_passes_when_at_break_even(self):
        svc = RiskEngineService(settings=_settings())
        state = PortfolioState(
            cash=Decimal("100000.00"),
            start_of_day_equity=Decimal("100000.00"),
        )
        result = svc.check_daily_loss_limit(state)
        assert result.passed is True


# ─────────────────────────────────────────────────────────────────────────────
# TestDrawdown
# ─────────────────────────────────────────────────────────────────────────────

class TestDrawdown:
    def test_blocks_when_drawdown_exceeded(self):
        """Equity $90k, HWM $100k → 10% drawdown > 5% weekly limit."""
        svc = RiskEngineService(settings=_settings())  # weekly_drawdown_limit_pct=0.05
        state = PortfolioState(
            cash=Decimal("90000.00"),
            high_water_mark=Decimal("100000.00"),
        )
        result = svc.check_drawdown(state)
        assert result.passed is False
        assert any(v.rule_name == "weekly_drawdown_limit" for v in result.violations)

    def test_passes_within_drawdown_limit(self):
        """Equity $97k, HWM $100k → 3% drawdown < 5% limit."""
        svc = RiskEngineService(settings=_settings())
        state = PortfolioState(
            cash=Decimal("97000.00"),
            high_water_mark=Decimal("100000.00"),
        )
        result = svc.check_drawdown(state)
        assert result.passed is True

    def test_passes_when_no_high_water_mark(self):
        svc = RiskEngineService(settings=_settings())
        state = PortfolioState(cash=Decimal("90000.00"))
        result = svc.check_drawdown(state)
        assert result.passed is True
        assert len(result.warnings) > 0

    def test_passes_at_high_water_mark(self):
        svc = RiskEngineService(settings=_settings())
        state = PortfolioState(
            cash=Decimal("100000.00"),
            high_water_mark=Decimal("100000.00"),
        )
        result = svc.check_drawdown(state)
        assert result.passed is True


# ─────────────────────────────────────────────────────────────────────────────
# TestMonthlyDrawdown
# ─────────────────────────────────────────────────────────────────────────────

class TestMonthlyDrawdown:
    def test_blocks_when_monthly_loss_exceeded(self):
        """Start-of-month equity $100k, current equity $88k → -12% MTD > 10% limit."""
        svc = RiskEngineService(settings=_settings())  # monthly_drawdown_limit_pct=0.10
        state = PortfolioState(
            cash=Decimal("88000.00"),
            start_of_month_equity=Decimal("100000.00"),
        )
        result = svc.check_monthly_drawdown(state)
        assert result.passed is False
        assert any(v.rule_name == "monthly_drawdown_limit" for v in result.violations)

    def test_passes_when_monthly_loss_within_limit(self):
        """Start-of-month equity $100k, current equity $95k → -5% MTD < 10% limit."""
        svc = RiskEngineService(settings=_settings())
        state = PortfolioState(
            cash=Decimal("95000.00"),
            start_of_month_equity=Decimal("100000.00"),
        )
        result = svc.check_monthly_drawdown(state)
        assert result.passed is True

    def test_passes_when_no_start_of_month_equity(self):
        """No start_of_month_equity → check skipped with warning."""
        svc = RiskEngineService(settings=_settings())
        state = PortfolioState(cash=Decimal("88000.00"))
        result = svc.check_monthly_drawdown(state)
        assert result.passed is True
        assert len(result.warnings) > 0

    def test_passes_at_breakeven(self):
        """No loss this month → passes."""
        svc = RiskEngineService(settings=_settings())
        state = PortfolioState(
            cash=Decimal("100000.00"),
            start_of_month_equity=Decimal("100000.00"),
        )
        result = svc.check_monthly_drawdown(state)
        assert result.passed is True

    def test_passes_when_month_is_positive(self):
        """MTD gain should never trigger the monthly drawdown check."""
        svc = RiskEngineService(settings=_settings())
        state = PortfolioState(
            cash=Decimal("110000.00"),
            start_of_month_equity=Decimal("100000.00"),
        )
        result = svc.check_monthly_drawdown(state)
        assert result.passed is True

    def test_blocks_at_exact_limit(self):
        """Loss of exactly limit+1bp should trigger the block."""
        svc = RiskEngineService(settings=_settings(monthly_drawdown_limit_pct=0.10))
        # Equity $89,990 → -10.01% MTD, just over the 10% cap
        state = PortfolioState(
            cash=Decimal("89990.00"),
            start_of_month_equity=Decimal("100000.00"),
        )
        result = svc.check_monthly_drawdown(state)
        assert result.passed is False

    def test_custom_monthly_limit_respected(self):
        """A tighter 5% monthly limit should block a 6% drawdown."""
        svc = RiskEngineService(settings=_settings(monthly_drawdown_limit_pct=0.05))
        state = PortfolioState(
            cash=Decimal("94000.00"),
            start_of_month_equity=Decimal("100000.00"),
        )
        result = svc.check_monthly_drawdown(state)
        assert result.passed is False
        assert any(v.rule_name == "monthly_drawdown_limit" for v in result.violations)

    def test_monthly_drawdown_wired_into_validate_action(self):
        """validate_action must include monthly_drawdown in its pipeline."""
        svc = RiskEngineService(settings=_settings())  # 10% monthly limit
        state = PortfolioState(
            cash=Decimal("85000.00"),              # -15% MTD
            start_of_month_equity=Decimal("100000.00"),
        )
        action = _open_action()
        result = svc.validate_action(action, state)
        assert result.passed is False
        assert any(v.rule_name == "monthly_drawdown_limit" for v in result.violations)


# ─────────────────────────────────────────────────────────────────────────────
# TestDailyPositionCap
# ─────────────────────────────────────────────────────────────────────────────

class TestDailyPositionCap:
    def test_blocks_open_when_daily_limit_reached(self):
        """daily_opens_count == limit → block the next OPEN."""
        svc = RiskEngineService(settings=_settings(max_new_positions_per_day=3))
        state = PortfolioState(cash=Decimal("100000.00"), daily_opens_count=3)
        action = _open_action()
        result = svc.check_daily_position_cap(action, state)
        assert result.passed is False
        assert any(v.rule_name == "max_new_positions_per_day" for v in result.violations)

    def test_passes_open_below_limit(self):
        """daily_opens_count < limit → OPEN is allowed."""
        svc = RiskEngineService(settings=_settings(max_new_positions_per_day=3))
        state = PortfolioState(cash=Decimal("100000.00"), daily_opens_count=2)
        action = _open_action()
        result = svc.check_daily_position_cap(action, state)
        assert result.passed is True

    def test_passes_when_zero_opens_today(self):
        """No opens yet today → always passes."""
        svc = RiskEngineService(settings=_settings())
        state = PortfolioState(cash=Decimal("100000.00"), daily_opens_count=0)
        action = _open_action()
        result = svc.check_daily_position_cap(action, state)
        assert result.passed is True

    def test_close_never_blocked_by_daily_cap(self):
        """CLOSE actions are never blocked regardless of daily_opens_count."""
        svc = RiskEngineService(settings=_settings(max_new_positions_per_day=1))
        state = PortfolioState(cash=Decimal("100000.00"), daily_opens_count=99)
        action = _close_action()
        result = svc.check_daily_position_cap(action, state)
        assert result.passed is True

    def test_blocks_strictly_at_limit_not_below(self):
        """Exactly at the limit blocks; one below passes."""
        svc = RiskEngineService(settings=_settings(max_new_positions_per_day=2))
        state_at = PortfolioState(cash=Decimal("100000.00"), daily_opens_count=2)
        state_below = PortfolioState(cash=Decimal("100000.00"), daily_opens_count=1)
        assert svc.check_daily_position_cap(_open_action(), state_at).passed is False
        assert svc.check_daily_position_cap(_open_action(), state_below).passed is True

    def test_custom_limit_respected(self):
        """A custom limit of 1 should block on the second open attempt."""
        svc = RiskEngineService(settings=_settings(max_new_positions_per_day=1))
        state = PortfolioState(cash=Decimal("100000.00"), daily_opens_count=1)
        result = svc.check_daily_position_cap(_open_action(), state)
        assert result.passed is False

    def test_daily_position_cap_wired_into_validate_action(self):
        """validate_action must include daily position cap in its pipeline."""
        svc = RiskEngineService(settings=_settings(max_new_positions_per_day=2))
        state = PortfolioState(cash=Decimal("100000.00"), daily_opens_count=2)
        action = _open_action()
        result = svc.validate_action(action, state)
        assert result.passed is False
        assert any(v.rule_name == "max_new_positions_per_day" for v in result.violations)

    def test_daily_opens_count_default_is_zero(self):
        """PortfolioState.daily_opens_count must default to 0 (no sentinel needed)."""
        state = PortfolioState(cash=Decimal("100000.00"))
        assert state.daily_opens_count == 0


# ─────────────────────────────────────────────────────────────────────────────
# TestSectorConcentration
# ─────────────────────────────────────────────────────────────────────────────

def _tech_state(notional_each: Decimal = Decimal("15000")) -> PortfolioState:
    """Portfolio with two technology positions worth notional_each each, equity=$100k.

    AAPL and MSFT both map to 'technology' sector in the universe registry.
    Combined sector MV = 2 * notional_each.
    """
    state = PortfolioState(cash=Decimal("100000") - 2 * notional_each)
    for ticker, price in (("AAPL", Decimal("175")), ("MSFT", Decimal("300"))):
        qty = (notional_each / price).quantize(Decimal("1"), rounding="ROUND_DOWN")
        state.positions[ticker] = PortfolioPosition(
            ticker=ticker,
            quantity=qty,
            avg_entry_price=price,
            current_price=price,
            opened_at=dt.datetime.utcnow(),
        )
    return state


class TestSectorConcentration:
    def test_blocks_open_that_breaches_sector_cap(self):
        """Portfolio already 30% tech; adding NVDA (tech) would exceed 40% cap."""
        # Two tech positions each $15k → $30k / $100k equity = 30% tech
        state = _tech_state(Decimal("15000"))
        # Action: add $15k of NVDA (tech) → projected tech = $45k / $100k = 45% > 40%
        svc = RiskEngineService(settings=_settings(max_sector_pct=0.40))
        action = PortfolioAction(
            action_type=ActionType.OPEN,
            ticker="NVDA",
            reason="test",
            target_notional=Decimal("15000"),
        )
        result = svc.check_sector_concentration(action, state)
        assert result.passed is False
        assert any(v.rule_name == "max_sector_pct" for v in result.violations)

    def test_passes_open_within_sector_cap(self):
        """Adding a small tech position that stays under 40% cap passes."""
        state = _tech_state(Decimal("10000"))  # 20k tech / 100k = 20%
        svc = RiskEngineService(settings=_settings(max_sector_pct=0.40))
        action = PortfolioAction(
            action_type=ActionType.OPEN,
            ticker="NVDA",
            reason="test",
            target_notional=Decimal("5000"),  # 15k / 100k = 15% — well under 40%
        )
        result = svc.check_sector_concentration(action, state)
        assert result.passed is True

    def test_close_never_blocked_by_sector_cap(self):
        """CLOSE actions must always pass the sector check."""
        state = _tech_state(Decimal("45000"))  # already > 40% tech
        svc = RiskEngineService(settings=_settings(max_sector_pct=0.40))
        action = PortfolioAction(
            action_type=ActionType.CLOSE,
            ticker="AAPL",
            reason="test",
        )
        result = svc.check_sector_concentration(action, state)
        assert result.passed is True

    def test_different_sector_never_blocked(self):
        """Opening a healthcare ticker does not trigger the tech sector cap."""
        state = _tech_state(Decimal("35000"))  # 70% tech, over limit
        svc = RiskEngineService(settings=_settings(max_sector_pct=0.40))
        # LLY → healthcare, completely separate sector
        action = PortfolioAction(
            action_type=ActionType.OPEN,
            ticker="LLY",
            reason="test",
            target_notional=Decimal("5000"),
        )
        result = svc.check_sector_concentration(action, state)
        assert result.passed is True

    def test_sector_check_wired_into_validate_action(self):
        """validate_action must include sector concentration in its pipeline."""
        state = _tech_state(Decimal("15000"))
        svc = RiskEngineService(settings=_settings(max_sector_pct=0.40))
        action = PortfolioAction(
            action_type=ActionType.OPEN,
            ticker="NVDA",
            reason="test",
            target_notional=Decimal("15000"),
        )
        result = svc.validate_action(action, state)
        assert result.passed is False
        assert any(v.rule_name == "max_sector_pct" for v in result.violations)


# ─────────────────────────────────────────────────────────────────────────────
# TestThematicConcentration
# ─────────────────────────────────────────────────────────────────────────────

def _ai_state(notional_each: Decimal = Decimal("15000")) -> PortfolioState:
    """Portfolio with two AI-infrastructure positions, equity=$100k.

    NVDA and AMD both map to 'ai_infrastructure' theme.
    """
    state = PortfolioState(cash=Decimal("100000") - 2 * notional_each)
    for ticker, price in (("NVDA", Decimal("800")), ("AMD", Decimal("150"))):
        qty = (notional_each / price).quantize(Decimal("1"), rounding="ROUND_DOWN")
        state.positions[ticker] = PortfolioPosition(
            ticker=ticker,
            quantity=qty,
            avg_entry_price=price,
            current_price=price,
            opened_at=dt.datetime.utcnow(),
        )
    return state


class TestThematicConcentration:
    def test_blocks_open_that_breaches_thematic_cap(self):
        """Portfolio already 30% AI-infra; adding ARM (ai_infra) exceeds 50% cap."""
        state = _ai_state(Decimal("15000"))  # 30k ai_infra / 100k = 30%
        svc = RiskEngineService(settings=_settings(max_thematic_pct=0.40))
        action = PortfolioAction(
            action_type=ActionType.OPEN,
            ticker="ARM",  # ai_infrastructure theme
            reason="test",
            target_notional=Decimal("15000"),  # → 45k / 100k = 45% > 40%
        )
        result = svc.check_thematic_concentration(action, state)
        assert result.passed is False
        assert any(v.rule_name == "max_thematic_pct" for v in result.violations)

    def test_passes_open_within_thematic_cap(self):
        """A modest addition to the theme that stays under the cap passes."""
        state = _ai_state(Decimal("10000"))  # 20% ai_infra
        svc = RiskEngineService(settings=_settings(max_thematic_pct=0.50))
        action = PortfolioAction(
            action_type=ActionType.OPEN,
            ticker="ARM",
            reason="test",
            target_notional=Decimal("5000"),  # 25k / 100k = 25% — under 50%
        )
        result = svc.check_thematic_concentration(action, state)
        assert result.passed is True

    def test_close_never_blocked_by_thematic_cap(self):
        """CLOSE actions must always pass the thematic check."""
        state = _ai_state(Decimal("40000"))  # way over 50% theme
        svc = RiskEngineService(settings=_settings(max_thematic_pct=0.50))
        action = PortfolioAction(
            action_type=ActionType.CLOSE,
            ticker="NVDA",
            reason="test",
        )
        result = svc.check_thematic_concentration(action, state)
        assert result.passed is True

    def test_different_theme_never_blocked(self):
        """Opening a healthcare ticker does not trigger the AI-infra theme cap."""
        state = _ai_state(Decimal("40000"))  # 80% ai_infra
        svc = RiskEngineService(settings=_settings(max_thematic_pct=0.50))
        action = PortfolioAction(
            action_type=ActionType.OPEN,
            ticker="LLY",  # healthcare theme
            reason="test",
            target_notional=Decimal("5000"),
        )
        result = svc.check_thematic_concentration(action, state)
        assert result.passed is True

    def test_thematic_check_wired_into_validate_action(self):
        """validate_action must include thematic concentration in its pipeline."""
        state = _ai_state(Decimal("15000"))
        svc = RiskEngineService(settings=_settings(max_thematic_pct=0.40))
        action = PortfolioAction(
            action_type=ActionType.OPEN,
            ticker="ARM",
            reason="test",
            target_notional=Decimal("15000"),
        )
        result = svc.validate_action(action, state)
        assert result.passed is False
        assert any(v.rule_name == "max_thematic_pct" for v in result.violations)


# ─────────────────────────────────────────────────────────────────────────────
# TestValidateAction (master gatekeeper)
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateAction:
    def test_all_clear_sets_risk_approved(self):
        svc = RiskEngineService(settings=_settings())
        state = PortfolioState(cash=Decimal("100000.00"))
        action = _open_action(notional=Decimal("5000.00"))
        result = svc.validate_action(action, state)
        assert result.passed is True
        assert action.risk_approved is True

    def test_single_violation_blocks_action(self):
        # Pin max_positions=10 explicitly — production .env raises it to 15
        # since 2026-04-15, so default-settings tests would be under-cap.
        svc = RiskEngineService(settings=_settings(max_positions=10))
        state = _full_state(10)   # max positions
        action = _open_action()
        result = svc.validate_action(action, state)
        assert result.passed is False
        assert action.risk_approved is False

    def test_multiple_violations_all_collected(self):
        """Kill switch + max_positions both fire — both violations present."""
        svc = RiskEngineService(settings=_settings(kill_switch=True))
        state = _full_state(10)
        action = _open_action()
        result = svc.validate_action(action, state)
        rule_names = {v.rule_name for v in result.violations}
        assert "kill_switch" in rule_names

    def test_close_action_passes_despite_full_portfolio(self):
        """CLOSE actions can always proceed past position-count check."""
        svc = RiskEngineService(settings=_settings())
        state = _full_state(10)
        action = _close_action()
        result = svc.validate_action(action, state)
        # close should not be blocked by position count
        pos_blocks = [
            v for v in result.violations if v.rule_name == "max_positions"
        ]
        assert len(pos_blocks) == 0

    def test_risk_approved_false_by_default(self):
        action = _open_action()
        assert action.risk_approved is False



# ──────────────────────────────────────────────────────────────────────────
# TestInactiveTicker — Phase 76 HOLX defence-in-depth
# ──────────────────────────────────────────────────────────────────────────

class TestInactiveTicker:
    """check_inactive_ticker: defence-in-depth against HOLX-class regression.

    Strategy candidate selector still leaks delisted/suspended tickers into
    proposal stream; risk engine is the defence-in-depth gate.
    """

    def test_inactive_open_is_hard_blocked(self):
        svc = RiskEngineService(
            settings=_settings(),
            is_active_fn=lambda t: False,  # everything inactive
        )
        result = svc.check_inactive_ticker(_open_action(ticker="HOLX"))
        assert result.passed is False
        assert result.is_hard_blocked is True
        assert any(v.rule_name == "inactive_ticker" for v in result.violations)

    def test_active_open_passes(self):
        svc = RiskEngineService(
            settings=_settings(),
            is_active_fn=lambda t: True,
        )
        result = svc.check_inactive_ticker(_open_action(ticker="NVDA"))
        assert result.passed is True
        assert result.violations == []

    def test_no_fn_skipped(self):
        """When is_active_fn is None the check is a no-op (backward compat)."""
        svc = RiskEngineService(settings=_settings(), is_active_fn=None)
        result = svc.check_inactive_ticker(_open_action(ticker="HOLX"))
        assert result.passed is True

    def test_close_on_inactive_ticker_is_allowed(self):
        """Must always allow CLOSE on a delisted ticker — never block our own exit."""
        svc = RiskEngineService(
            settings=_settings(),
            is_active_fn=lambda t: False,
        )
        result = svc.check_inactive_ticker(_close_action(ticker="HOLX"))
        assert result.passed is True
        assert not any(v.rule_name == "inactive_ticker" for v in result.violations)

    def test_callable_exception_skips_check(self):
        """Transient errors in the lookup don't stall the pipeline."""
        def _broken(_t: str) -> bool:
            raise RuntimeError("db down")

        svc = RiskEngineService(settings=_settings(), is_active_fn=_broken)
        result = svc.check_inactive_ticker(_open_action(ticker="HOLX"))
        assert result.passed is True
        assert any("inactive_ticker" in w for w in result.warnings)

    def test_validate_action_blocks_inactive_open(self):
        """End-to-end: validate_action surfaces the inactive_ticker violation."""
        svc = RiskEngineService(
            settings=_settings(),
            is_active_fn=lambda t: t != "HOLX",  # only HOLX is inactive
        )
        state = PortfolioState(cash=Decimal("100000.00"))
        action = _open_action(ticker="HOLX")
        result = svc.validate_action(action, state)
        assert result.passed is False
        assert any(v.rule_name == "inactive_ticker" for v in result.violations)
        # And the action must NOT be flagged risk_approved
        assert action.risk_approved is False

    def test_validate_action_passes_active_ticker(self):
        svc = RiskEngineService(
            settings=_settings(),
            is_active_fn=lambda t: True,
        )
        state = PortfolioState(cash=Decimal("100000.00"))
        action = _open_action(ticker="NVDA")
        result = svc.validate_action(action, state)
        assert result.passed is True
        assert action.risk_approved is True

    def test_inactive_set_lookup_pattern(self):
        """Mirror the production wiring: closure over a set of inactive tickers."""
        inactive = {"HOLX", "PXD", "ANSS"}
        svc = RiskEngineService(
            settings=_settings(),
            is_active_fn=lambda t: t not in inactive,
        )
        # HOLX should be blocked
        r1 = svc.check_inactive_ticker(_open_action(ticker="HOLX"))
        assert r1.passed is False
        # NVDA should be allowed
        r2 = svc.check_inactive_ticker(_open_action(ticker="NVDA"))
        assert r2.passed is True
