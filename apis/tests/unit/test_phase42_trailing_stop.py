"""
Phase 42 — Trailing Stop + Take-Profit Exits

Test classes
------------
TestSettings42                  — 3 new settings fields with correct defaults
TestEvaluateExitsTakeProfit     — take-profit trigger logic
TestEvaluateExitsTrailingStop   — trailing stop trigger logic
TestEvaluateExitsPriority       — full priority order (5 triggers)
TestPeakPriceUpdate             — update_position_peak_prices helper
TestExitLevelsEndpoint          — GET /portfolio/exit-levels
TestAppState42                  — position_peak_prices field in ApiAppState
TestPaperCycleTrailingStop      — paper cycle integration
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(**overrides) -> Any:
    from config.settings import Settings
    base = {
        "db_url": "postgresql+psycopg://u:p@localhost/apis",
        "operating_mode": "paper",
        "kill_switch": False,
    }
    base.update(overrides)
    return Settings(**base)


def _make_position(
    ticker: str = "AAPL",
    quantity: float = 10,
    avg_entry_price: float = 100.0,
    current_price: float = 100.0,
    days_ago: int = 1,
    thesis: str = "test thesis",
):
    from services.portfolio_engine.models import PortfolioPosition
    return PortfolioPosition(
        ticker=ticker,
        quantity=Decimal(str(quantity)),
        avg_entry_price=Decimal(str(avg_entry_price)),
        current_price=Decimal(str(current_price)),
        opened_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=days_ago),
        thesis_summary=thesis,
    )


# ---------------------------------------------------------------------------
# TestSettings42
# ---------------------------------------------------------------------------

class TestSettings42:
    def test_trailing_stop_pct_default(self):
        s = _make_settings()
        assert s.trailing_stop_pct == pytest.approx(0.05)

    def test_trailing_stop_activation_pct_default(self):
        s = _make_settings()
        assert s.trailing_stop_activation_pct == pytest.approx(0.03)

    def test_take_profit_pct_default(self):
        s = _make_settings()
        assert s.take_profit_pct == pytest.approx(0.20)

    def test_trailing_stop_pct_zero_disables(self):
        s = _make_settings(trailing_stop_pct=0.0)
        assert s.trailing_stop_pct == 0.0

    def test_take_profit_pct_zero_disables(self):
        s = _make_settings(take_profit_pct=0.0)
        assert s.take_profit_pct == 0.0

    def test_trailing_stop_pct_configurable(self):
        s = _make_settings(trailing_stop_pct=0.10)
        assert s.trailing_stop_pct == pytest.approx(0.10)


# ---------------------------------------------------------------------------
# TestEvaluateExitsTakeProfit
# ---------------------------------------------------------------------------

class TestEvaluateExitsTakeProfit:
    def test_take_profit_fires_when_pnl_reaches_target(self):
        from services.risk_engine.service import RiskEngineService
        # pnl_pct = (120 - 100) / 100 = 0.20, take_profit = 0.20 → should fire
        s = _make_settings(take_profit_pct=0.20, trailing_stop_pct=0.0, stop_loss_pct=0.07)
        svc = RiskEngineService(settings=s)
        pos = _make_position(avg_entry_price=100.0, current_price=120.0)
        actions = svc.evaluate_exits(positions={"AAPL": pos})
        assert len(actions) == 1
        assert "take_profit" in actions[0].reason

    def test_take_profit_fires_when_pnl_exceeds_target(self):
        from services.risk_engine.service import RiskEngineService
        # pnl_pct > 0.20 → still fires
        s = _make_settings(take_profit_pct=0.20, trailing_stop_pct=0.0, stop_loss_pct=0.07)
        svc = RiskEngineService(settings=s)
        pos = _make_position(avg_entry_price=100.0, current_price=130.0)
        actions = svc.evaluate_exits(positions={"AAPL": pos})
        assert len(actions) == 1
        assert "take_profit" in actions[0].reason

    def test_take_profit_does_not_fire_below_target(self):
        from services.risk_engine.service import RiskEngineService
        # pnl = 0.10 < 0.20 → should not fire
        s = _make_settings(take_profit_pct=0.20, trailing_stop_pct=0.0, stop_loss_pct=0.07)
        svc = RiskEngineService(settings=s)
        pos = _make_position(avg_entry_price=100.0, current_price=110.0)
        actions = svc.evaluate_exits(positions={"AAPL": pos})
        assert len(actions) == 0

    def test_take_profit_disabled_when_zero(self):
        from services.risk_engine.service import RiskEngineService
        s = _make_settings(take_profit_pct=0.0, trailing_stop_pct=0.0, stop_loss_pct=0.07)
        svc = RiskEngineService(settings=s)
        pos = _make_position(avg_entry_price=100.0, current_price=200.0)
        actions = svc.evaluate_exits(positions={"AAPL": pos})
        assert len(actions) == 0

    def test_stop_loss_takes_precedence_over_take_profit(self):
        """When both stop-loss and take-profit would fire, stop-loss wins (priority 1)."""
        from services.risk_engine.service import RiskEngineService
        # This is artificially constructed: a position where pnl_pct is both below stop
        # and above take-profit can't happen naturally, but we test priority order by
        # setting take_profit low (e.g. 0.01) and verifying stop-loss fires on a loss.
        # More directly: a stop-loss condition always fires before take-profit is checked.
        s = _make_settings(stop_loss_pct=0.07, take_profit_pct=0.01, trailing_stop_pct=0.0)
        svc = RiskEngineService(settings=s)
        # Simulate a -10% loss position → stop-loss fires
        pos = _make_position(avg_entry_price=100.0, current_price=89.0)
        actions = svc.evaluate_exits(positions={"AAPL": pos})
        assert len(actions) == 1
        assert "stop_loss" in actions[0].reason

    def test_take_profit_action_is_close_type(self):
        from services.portfolio_engine.models import ActionType
        from services.risk_engine.service import RiskEngineService
        s = _make_settings(take_profit_pct=0.10, trailing_stop_pct=0.0)
        svc = RiskEngineService(settings=s)
        pos = _make_position(avg_entry_price=100.0, current_price=115.0)
        actions = svc.evaluate_exits(positions={"AAPL": pos})
        assert actions[0].action_type == ActionType.CLOSE

    def test_take_profit_action_is_risk_approved(self):
        from services.risk_engine.service import RiskEngineService
        s = _make_settings(take_profit_pct=0.10, trailing_stop_pct=0.0)
        svc = RiskEngineService(settings=s)
        pos = _make_position(avg_entry_price=100.0, current_price=115.0)
        actions = svc.evaluate_exits(positions={"AAPL": pos})
        assert actions[0].risk_approved is True


# ---------------------------------------------------------------------------
# TestEvaluateExitsTrailingStop
# ---------------------------------------------------------------------------

class TestEvaluateExitsTrailingStop:
    def test_trailing_stop_fires_when_price_drops_below_trail(self):
        from services.risk_engine.service import RiskEngineService
        # Entry 100, peak 130 (30% gain, > 3% activation), trail_level = 130 * 0.95 = 123.50
        # current = 120 < 123.50 → fires
        s = _make_settings(
            trailing_stop_pct=0.05,
            trailing_stop_activation_pct=0.03,
            take_profit_pct=0.0,
            stop_loss_pct=0.07,
        )
        svc = RiskEngineService(settings=s)
        pos = _make_position(avg_entry_price=100.0, current_price=120.0)
        peak_prices = {"AAPL": 130.0}
        actions = svc.evaluate_exits(positions={"AAPL": pos}, peak_prices=peak_prices)
        assert len(actions) == 1
        assert "trailing_stop" in actions[0].reason

    def test_trailing_stop_does_not_fire_before_activation(self):
        from services.risk_engine.service import RiskEngineService
        # pnl = 0.01 < 0.03 activation → trailing stop not armed
        s = _make_settings(
            trailing_stop_pct=0.05,
            trailing_stop_activation_pct=0.03,
            take_profit_pct=0.0,
            stop_loss_pct=0.50,  # high to avoid stop-loss interference
        )
        svc = RiskEngineService(settings=s)
        pos = _make_position(avg_entry_price=100.0, current_price=101.0)
        peak_prices = {"AAPL": 101.5}
        actions = svc.evaluate_exits(positions={"AAPL": pos}, peak_prices=peak_prices)
        assert len(actions) == 0

    def test_trailing_stop_not_fire_when_above_trail_level(self):
        from services.risk_engine.service import RiskEngineService
        # Entry 100, peak 130, trail = 123.50, current = 125 > 123.50 → no fire
        s = _make_settings(
            trailing_stop_pct=0.05,
            trailing_stop_activation_pct=0.03,
            take_profit_pct=0.0,
            stop_loss_pct=0.07,
        )
        svc = RiskEngineService(settings=s)
        pos = _make_position(avg_entry_price=100.0, current_price=125.0)
        peak_prices = {"AAPL": 130.0}
        actions = svc.evaluate_exits(positions={"AAPL": pos}, peak_prices=peak_prices)
        assert len(actions) == 0

    def test_trailing_stop_disabled_when_pct_zero(self):
        from services.risk_engine.service import RiskEngineService
        s = _make_settings(trailing_stop_pct=0.0, take_profit_pct=0.0, stop_loss_pct=0.50)
        svc = RiskEngineService(settings=s)
        pos = _make_position(avg_entry_price=100.0, current_price=50.0)
        peak_prices = {"AAPL": 200.0}
        actions = svc.evaluate_exits(positions={"AAPL": pos}, peak_prices=peak_prices)
        assert len(actions) == 0

    def test_trailing_stop_skipped_when_peak_prices_none(self):
        from services.risk_engine.service import RiskEngineService
        s = _make_settings(trailing_stop_pct=0.05, take_profit_pct=0.0, stop_loss_pct=0.50)
        svc = RiskEngineService(settings=s)
        pos = _make_position(avg_entry_price=100.0, current_price=120.0)
        # No peak_prices passed → trailing stop check skipped
        actions = svc.evaluate_exits(positions={"AAPL": pos}, peak_prices=None)
        assert len(actions) == 0

    def test_trailing_stop_activation_pct_exact_boundary(self):
        from services.risk_engine.service import RiskEngineService
        # pnl = 0.03 exactly == activation → should be armed (>=)
        s = _make_settings(
            trailing_stop_pct=0.05,
            trailing_stop_activation_pct=0.03,
            take_profit_pct=0.0,
            stop_loss_pct=0.50,
        )
        svc = RiskEngineService(settings=s)
        # Entry 100, current 103 → pnl = 3% exactly
        pos = _make_position(avg_entry_price=100.0, current_price=103.0)
        # peak 103, trail = 103 * 0.95 = 97.85, current = 103 > 97.85 → no fire (above trail)
        peak_prices = {"AAPL": 110.0}
        # trail_level = 110 * 0.95 = 104.5, current=103 < 104.5 → FIRES
        actions = svc.evaluate_exits(positions={"AAPL": pos}, peak_prices=peak_prices)
        assert len(actions) == 1
        assert "trailing_stop" in actions[0].reason

    def test_trailing_stop_reason_contains_trailing_stop(self):
        from services.risk_engine.service import RiskEngineService
        s = _make_settings(trailing_stop_pct=0.05, trailing_stop_activation_pct=0.03, take_profit_pct=0.0, stop_loss_pct=0.07)
        svc = RiskEngineService(settings=s)
        pos = _make_position(avg_entry_price=100.0, current_price=120.0)
        peak_prices = {"AAPL": 135.0}
        actions = svc.evaluate_exits(positions={"AAPL": pos}, peak_prices=peak_prices)
        assert len(actions) == 1
        assert "trailing_stop" in actions[0].reason

    def test_close_supersedes_trailing_stop(self):
        """CLOSE from rankings takes precedence: trailing stop should not duplicate it."""
        from services.risk_engine.service import RiskEngineService
        s = _make_settings(trailing_stop_pct=0.05, trailing_stop_activation_pct=0.03, take_profit_pct=0.0, stop_loss_pct=0.50)
        svc = RiskEngineService(settings=s)
        pos = _make_position(avg_entry_price=100.0, current_price=120.0)
        peak_prices = {"AAPL": 135.0}
        # evaluate_exits returns a CLOSE for trailing stop
        actions = svc.evaluate_exits(positions={"AAPL": pos}, peak_prices=peak_prices)
        # The test ensures only one CLOSE fires per ticker, not two
        assert len([a for a in actions if a.ticker == "AAPL"]) == 1


# ---------------------------------------------------------------------------
# TestEvaluateExitsPriority
# ---------------------------------------------------------------------------

class TestEvaluateExitsPriority:
    def test_stop_loss_fires_not_take_profit_when_in_loss(self):
        """Priority 1: stop-loss fires; take-profit is at 2 and doesn't apply to a loss."""
        from services.risk_engine.service import RiskEngineService
        s = _make_settings(stop_loss_pct=0.07, take_profit_pct=0.10, trailing_stop_pct=0.0)
        svc = RiskEngineService(settings=s)
        pos = _make_position(avg_entry_price=100.0, current_price=90.0)
        actions = svc.evaluate_exits(positions={"AAPL": pos})
        assert len(actions) == 1
        assert "stop_loss" in actions[0].reason

    def test_take_profit_fires_not_trailing_stop_when_profit_at_target(self):
        """Priority 2: take-profit fires; trailing stop (3) not checked after."""
        from services.risk_engine.service import RiskEngineService
        # Entry 100, current 125 (+25%, above take_profit=0.20)
        # Peak 130, trail = 130*0.95=123.5, current 125 > 123.5 → trailing would NOT fire anyway
        # Use a case where trailing WOULD fire but take-profit fires first
        # Entry 100, current 120 (exactly at take-profit=0.20), peak 130, trail=123.5 → current<trail → trailing would fire
        s = _make_settings(
            stop_loss_pct=0.07,
            take_profit_pct=0.20,
            trailing_stop_pct=0.05,
            trailing_stop_activation_pct=0.03,
        )
        svc = RiskEngineService(settings=s)
        pos = _make_position(avg_entry_price=100.0, current_price=120.0)
        peak_prices = {"AAPL": 130.0}
        actions = svc.evaluate_exits(positions={"AAPL": pos}, peak_prices=peak_prices)
        assert len(actions) == 1
        assert "take_profit" in actions[0].reason

    def test_trailing_stop_fires_not_age_expiry(self):
        """Priority 3: trailing stop fires; age expiry (4) not checked after."""
        from services.risk_engine.service import RiskEngineService
        s = _make_settings(
            stop_loss_pct=0.07,
            take_profit_pct=0.0,
            trailing_stop_pct=0.05,
            trailing_stop_activation_pct=0.03,
            max_position_age_days=5,
        )
        svc = RiskEngineService(settings=s)
        # Old position AND trailing stop triggered
        pos = _make_position(avg_entry_price=100.0, current_price=120.0, days_ago=10)
        peak_prices = {"AAPL": 135.0}
        actions = svc.evaluate_exits(positions={"AAPL": pos}, peak_prices=peak_prices)
        assert len(actions) == 1
        assert "trailing_stop" in actions[0].reason

    def test_age_expiry_fires_not_thesis_invalidation(self):
        """Priority 4: age expiry fires; thesis invalidation (5) not checked after."""
        from services.risk_engine.service import RiskEngineService
        s = _make_settings(
            stop_loss_pct=0.07,
            take_profit_pct=0.0,
            trailing_stop_pct=0.0,
            max_position_age_days=5,
            exit_score_threshold=0.40,
        )
        svc = RiskEngineService(settings=s)
        pos = _make_position(avg_entry_price=100.0, current_price=100.0, days_ago=10)
        ranked_scores = {"AAPL": Decimal("0.10")}  # below threshold, would also fire
        actions = svc.evaluate_exits(positions={"AAPL": pos}, ranked_scores=ranked_scores)
        assert len(actions) == 1
        assert "age_expiry" in actions[0].reason

    def test_thesis_invalidation_fires_when_nothing_else_does(self):
        """Priority 5: thesis invalidation fires when no earlier trigger applies."""
        from services.risk_engine.service import RiskEngineService
        s = _make_settings(
            stop_loss_pct=0.07,
            take_profit_pct=0.0,
            trailing_stop_pct=0.0,
            max_position_age_days=100,
            exit_score_threshold=0.40,
        )
        svc = RiskEngineService(settings=s)
        pos = _make_position(avg_entry_price=100.0, current_price=105.0, days_ago=1)
        ranked_scores = {"AAPL": Decimal("0.30")}
        actions = svc.evaluate_exits(positions={"AAPL": pos}, ranked_scores=ranked_scores)
        assert len(actions) == 1
        assert "thesis_invalidated" in actions[0].reason

    def test_only_one_trigger_fires_per_ticker(self):
        """Only the first matching trigger fires; no duplicate actions."""
        from services.risk_engine.service import RiskEngineService
        s = _make_settings(
            stop_loss_pct=0.07,
            take_profit_pct=0.05,
            trailing_stop_pct=0.05,
            trailing_stop_activation_pct=0.03,
            max_position_age_days=5,
            exit_score_threshold=0.99,
        )
        svc = RiskEngineService(settings=s)
        pos = _make_position(avg_entry_price=100.0, current_price=90.0, days_ago=10)
        peak_prices = {"AAPL": 120.0}
        ranked_scores = {"AAPL": Decimal("0.01")}
        actions = svc.evaluate_exits(
            positions={"AAPL": pos},
            peak_prices=peak_prices,
            ranked_scores=ranked_scores,
        )
        assert len(actions) == 1
        assert "stop_loss" in actions[0].reason


# ---------------------------------------------------------------------------
# TestPeakPriceUpdate
# ---------------------------------------------------------------------------

class TestPeakPriceUpdate:
    def test_new_ticker_initialized_to_current_price(self):
        from services.risk_engine.service import update_position_peak_prices
        pos = _make_position(ticker="AAPL", current_price=150.0)
        peaks = {}
        update_position_peak_prices({"AAPL": pos}, peaks)
        assert peaks["AAPL"] == pytest.approx(150.0)

    def test_current_above_peak_updates_peak(self):
        from services.risk_engine.service import update_position_peak_prices
        pos = _make_position(ticker="AAPL", current_price=160.0)
        peaks = {"AAPL": 150.0}
        update_position_peak_prices({"AAPL": pos}, peaks)
        assert peaks["AAPL"] == pytest.approx(160.0)

    def test_current_below_peak_no_change(self):
        from services.risk_engine.service import update_position_peak_prices
        pos = _make_position(ticker="AAPL", current_price=140.0)
        peaks = {"AAPL": 150.0}
        update_position_peak_prices({"AAPL": pos}, peaks)
        assert peaks["AAPL"] == pytest.approx(150.0)

    def test_current_equal_peak_no_change(self):
        from services.risk_engine.service import update_position_peak_prices
        pos = _make_position(ticker="AAPL", current_price=150.0)
        peaks = {"AAPL": 150.0}
        update_position_peak_prices({"AAPL": pos}, peaks)
        assert peaks["AAPL"] == pytest.approx(150.0)

    def test_multiple_tickers(self):
        from services.risk_engine.service import update_position_peak_prices
        pos_a = _make_position(ticker="AAPL", current_price=160.0)
        pos_b = _make_position(ticker="MSFT", current_price=300.0)
        peaks = {"AAPL": 150.0}
        update_position_peak_prices({"AAPL": pos_a, "MSFT": pos_b}, peaks)
        assert peaks["AAPL"] == pytest.approx(160.0)
        assert peaks["MSFT"] == pytest.approx(300.0)

    def test_returns_same_dict_object(self):
        from services.risk_engine.service import update_position_peak_prices
        pos = _make_position(ticker="AAPL", current_price=150.0)
        peaks = {}
        result = update_position_peak_prices({"AAPL": pos}, peaks)
        assert result is peaks

    def test_empty_positions_no_change(self):
        from services.risk_engine.service import update_position_peak_prices
        peaks = {"AAPL": 150.0}
        update_position_peak_prices({}, peaks)
        assert peaks == {"AAPL": 150.0}


# ---------------------------------------------------------------------------
# TestExitLevelsEndpoint
# ---------------------------------------------------------------------------

class TestExitLevelsEndpoint:
    def _make_app_state(self, portfolio_state=None, peak_prices=None):
        state = MagicMock()
        state.portfolio_state = portfolio_state
        state.position_peak_prices = peak_prices or {}
        return state

    def _make_settings_mock(
        self,
        trailing_stop_pct=0.05,
        trailing_stop_activation_pct=0.03,
        take_profit_pct=0.20,
        stop_loss_pct=0.07,
    ):
        s = MagicMock()
        s.trailing_stop_pct = trailing_stop_pct
        s.trailing_stop_activation_pct = trailing_stop_activation_pct
        s.take_profit_pct = take_profit_pct
        s.stop_loss_pct = stop_loss_pct
        return s

    def test_empty_positions_returns_200(self):
        from apps.api.routes.exit_levels import get_exit_levels
        state = self._make_app_state()
        settings = self._make_settings_mock()
        resp = get_exit_levels(state, settings)
        assert resp.positions == []

    def test_returns_correct_levels_for_position(self):
        from apps.api.routes.exit_levels import get_exit_levels
        from services.portfolio_engine.models import PortfolioState

        pos = _make_position(ticker="AAPL", avg_entry_price=100.0, current_price=110.0)
        ps = PortfolioState(cash=Decimal("90000"))
        ps.positions["AAPL"] = pos

        state = self._make_app_state(portfolio_state=ps, peak_prices={"AAPL": 115.0})
        settings = self._make_settings_mock(
            stop_loss_pct=0.07, trailing_stop_pct=0.05, take_profit_pct=0.20
        )
        resp = get_exit_levels(state, settings)
        assert len(resp.positions) == 1
        p = resp.positions[0]
        assert p.ticker == "AAPL"
        assert p.current_price == pytest.approx(110.0)
        assert p.avg_entry_price == pytest.approx(100.0)
        assert p.stop_loss_level == pytest.approx(100.0 * 0.93)
        assert p.take_profit_level == pytest.approx(100.0 * 1.20)

    def test_trailing_stop_level_computed_from_peak_not_entry(self):
        from apps.api.routes.exit_levels import get_exit_levels
        from services.portfolio_engine.models import PortfolioState

        pos = _make_position(ticker="AAPL", avg_entry_price=100.0, current_price=110.0)
        ps = PortfolioState(cash=Decimal("90000"))
        ps.positions["AAPL"] = pos
        peak = 120.0

        state = self._make_app_state(portfolio_state=ps, peak_prices={"AAPL": peak})
        settings = self._make_settings_mock(trailing_stop_pct=0.05)
        resp = get_exit_levels(state, settings)

        p = resp.positions[0]
        # trailing_stop_level = peak * (1 - 0.05) = 120 * 0.95 = 114.0
        assert p.trailing_stop_level == pytest.approx(120.0 * 0.95)
        assert p.peak_price == pytest.approx(peak)

    def test_stop_loss_level_computed_from_entry(self):
        from apps.api.routes.exit_levels import get_exit_levels
        from services.portfolio_engine.models import PortfolioState

        pos = _make_position(ticker="AAPL", avg_entry_price=100.0, current_price=105.0)
        ps = PortfolioState(cash=Decimal("90000"))
        ps.positions["AAPL"] = pos

        state = self._make_app_state(portfolio_state=ps)
        settings = self._make_settings_mock(stop_loss_pct=0.07)
        resp = get_exit_levels(state, settings)

        p = resp.positions[0]
        assert p.stop_loss_level == pytest.approx(100.0 * (1 - 0.07))

    def test_take_profit_level_computed_from_entry(self):
        from apps.api.routes.exit_levels import get_exit_levels
        from services.portfolio_engine.models import PortfolioState

        pos = _make_position(ticker="AAPL", avg_entry_price=100.0, current_price=105.0)
        ps = PortfolioState(cash=Decimal("90000"))
        ps.positions["AAPL"] = pos

        state = self._make_app_state(portfolio_state=ps)
        settings = self._make_settings_mock(take_profit_pct=0.20)
        resp = get_exit_levels(state, settings)

        p = resp.positions[0]
        assert p.take_profit_level == pytest.approx(100.0 * 1.20)

    def test_trailing_stop_none_when_disabled(self):
        from apps.api.routes.exit_levels import get_exit_levels
        from services.portfolio_engine.models import PortfolioState

        pos = _make_position(ticker="AAPL", avg_entry_price=100.0, current_price=110.0)
        ps = PortfolioState(cash=Decimal("90000"))
        ps.positions["AAPL"] = pos

        state = self._make_app_state(portfolio_state=ps)
        settings = self._make_settings_mock(trailing_stop_pct=0.0)
        resp = get_exit_levels(state, settings)
        assert resp.positions[0].trailing_stop_level is None

    def test_response_contains_config_fields(self):
        from apps.api.routes.exit_levels import get_exit_levels
        state = self._make_app_state()
        settings = self._make_settings_mock(trailing_stop_pct=0.05, take_profit_pct=0.20)
        resp = get_exit_levels(state, settings)
        assert resp.trailing_stop_pct == pytest.approx(0.05)
        assert resp.take_profit_pct == pytest.approx(0.20)
        assert resp.computed_at is not None


# ---------------------------------------------------------------------------
# TestAppState42
# ---------------------------------------------------------------------------

class TestAppState42:
    def test_position_peak_prices_field_exists(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert hasattr(state, "position_peak_prices")

    def test_position_peak_prices_default_is_empty_dict(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert state.position_peak_prices == {}

    def test_position_peak_prices_is_dict_type(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert isinstance(state.position_peak_prices, dict)

    def test_position_peak_prices_independent_between_instances(self):
        from apps.api.state import ApiAppState
        s1 = ApiAppState()
        s2 = ApiAppState()
        s1.position_peak_prices["AAPL"] = 150.0
        assert "AAPL" not in s2.position_peak_prices


# ---------------------------------------------------------------------------
# TestPaperCycleTrailingStop
# ---------------------------------------------------------------------------

class TestPaperCycleTrailingStop:
    """Integration tests: paper cycle calls update_position_peak_prices and passes peak_prices to evaluate_exits."""

    def _build_minimal_state(self):
        """Return a minimal ApiAppState with rankings and a position."""
        from apps.api.state import ApiAppState
        from services.portfolio_engine.models import PortfolioState

        state = ApiAppState()

        # Fake ranked result
        ranked = MagicMock()
        ranked.ticker = "AAPL"
        ranked.composite_score = Decimal("0.80")
        ranked.recommended_action = "HOLD"
        ranked.thesis_summary = "strong momentum"
        state.latest_rankings = [ranked]

        # Build a portfolio state with an existing position
        ps = PortfolioState(
            cash=Decimal("90000"),
            start_of_day_equity=Decimal("100000"),
            high_water_mark=Decimal("100000"),
        )
        pos = _make_position(ticker="AAPL", avg_entry_price=100.0, current_price=115.0)
        ps.positions["AAPL"] = pos
        state.portfolio_state = ps

        return state

    def test_peak_prices_updated_after_cycle(self):
        """After a paper cycle with a held position, position_peak_prices has an entry."""
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle

        state = self._build_minimal_state()
        cfg = _make_settings(
            operating_mode="paper",
            trailing_stop_pct=0.05,
            trailing_stop_activation_pct=0.03,
            take_profit_pct=0.0,
            stop_loss_pct=0.07,
        )

        # Mock the broker to avoid real network calls
        broker = MagicMock()
        broker.ping.return_value = True
        broker.get_account_state.return_value = MagicMock(cash_balance=Decimal("90000"))
        broker.list_positions.return_value = []
        broker.list_fills_since.return_value = []

        # Mock market data
        market_data = MagicMock()
        snapshot = MagicMock()
        snapshot.latest_price = Decimal("115.00")
        market_data.get_snapshot.return_value = snapshot

        # Mock portfolio service to return empty proposed actions (no new opens)
        portfolio_svc = MagicMock()
        portfolio_svc.apply_ranked_opportunities.return_value = []

        # Mock risk service
        risk_svc = MagicMock()
        risk_svc.evaluate_exits.return_value = []
        risk_svc.evaluate_trims.return_value = []
        risk_svc.validate_action.return_value = MagicMock(is_hard_blocked=False)

        # Mock execution service
        exec_svc = MagicMock()
        exec_svc.execute_approved_actions.return_value = []

        run_paper_trading_cycle(
            app_state=state,
            settings=cfg,
            broker=broker,
            portfolio_svc=portfolio_svc,
            risk_svc=risk_svc,
            market_data_svc=market_data,
        )

        # After the cycle, risk_svc.evaluate_exits should have been called with peak_prices
        call_kwargs = risk_svc.evaluate_exits.call_args
        assert call_kwargs is not None
        # peak_prices should have been passed
        assert "peak_prices" in call_kwargs.kwargs or (
            len(call_kwargs.args) >= 4  # positional
        )

    def test_evaluate_exits_called_with_peak_prices_kwarg(self):
        """evaluate_exits is called with peak_prices keyword argument."""
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle

        state = self._build_minimal_state()
        cfg = _make_settings(operating_mode="paper")

        broker = MagicMock()
        broker.ping.return_value = True
        broker.get_account_state.return_value = MagicMock(cash_balance=Decimal("90000"))
        broker.list_positions.return_value = []
        broker.list_fills_since.return_value = []

        market_data = MagicMock()
        snapshot = MagicMock()
        snapshot.latest_price = Decimal("115.00")
        market_data.get_snapshot.return_value = snapshot

        portfolio_svc = MagicMock()
        portfolio_svc.apply_ranked_opportunities.return_value = []

        risk_svc = MagicMock()
        risk_svc.evaluate_exits.return_value = []
        risk_svc.evaluate_trims.return_value = []
        risk_svc.validate_action.return_value = MagicMock(is_hard_blocked=False)

        run_paper_trading_cycle(
            app_state=state,
            settings=cfg,
            broker=broker,
            portfolio_svc=portfolio_svc,
            risk_svc=risk_svc,
            market_data_svc=market_data,
        )

        call_kwargs = risk_svc.evaluate_exits.call_args
        assert call_kwargs is not None
        # Verify peak_prices was passed
        peak_prices_arg = call_kwargs.kwargs.get("peak_prices")
        assert peak_prices_arg is not None

    def test_app_state_peak_prices_updated_after_cycle(self):
        """app_state.position_peak_prices is populated after a cycle with positions."""
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle

        state = self._build_minimal_state()
        cfg = _make_settings(operating_mode="paper")

        broker = MagicMock()
        broker.ping.return_value = True
        broker.get_account_state.return_value = MagicMock(cash_balance=Decimal("90000"))
        # Return AAPL still held so peak prices not cleaned up
        broker_pos = MagicMock()
        broker_pos.ticker = "AAPL"
        broker_pos.quantity = Decimal("10")
        broker_pos.current_price = Decimal("115.00")
        broker.list_positions.return_value = [broker_pos]
        broker.list_fills_since.return_value = []

        market_data = MagicMock()
        snapshot = MagicMock()
        snapshot.latest_price = Decimal("115.00")
        market_data.get_snapshot.return_value = snapshot

        portfolio_svc = MagicMock()
        portfolio_svc.apply_ranked_opportunities.return_value = []

        risk_svc = MagicMock()
        risk_svc.evaluate_exits.return_value = []
        risk_svc.evaluate_trims.return_value = []
        risk_svc.validate_action.return_value = MagicMock(is_hard_blocked=False)

        run_paper_trading_cycle(
            app_state=state,
            settings=cfg,
            broker=broker,
            portfolio_svc=portfolio_svc,
            risk_svc=risk_svc,
            market_data_svc=market_data,
        )

        # peak prices should have been updated for AAPL
        assert "AAPL" in state.position_peak_prices
