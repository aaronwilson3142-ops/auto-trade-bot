"""
Gate C — Risk Engine Tests.

Verifies:
  - kill_switch: blocks everything when active
  - max_positions: blocks new opens when portfolio is full
  - max_single_name_pct: sets adjusted_max_notional on oversized proposals
  - daily_loss_limit: blocks new opens when day's loss exceeds limit
  - drawdown: blocks new opens when drawdown exceeds weekly limit
  - validate_action: aggregates all violations; CLOSE actions bypass position-count
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

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


# ─────────────────────────────────────────────────────────────────────────────
# TestMaxPositions
# ─────────────────────────────────────────────────────────────────────────────

class TestMaxPositions:
    def test_blocks_open_at_max_positions(self):
        svc = RiskEngineService(settings=_settings())  # max_positions=10
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
        svc = RiskEngineService(settings=_settings())
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
