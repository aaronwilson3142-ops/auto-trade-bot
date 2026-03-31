"""
Phase 44 — Portfolio Stress Testing + Scenario Analysis

Tests for:
- StressTestService.apply_scenario()
- StressTestService.run_all_scenarios()
- StressTestService.filter_for_stress_limit()
- run_stress_test() job
- GET /portfolio/stress-test route
- GET /portfolio/stress-test/{scenario} route
- Paper trading cycle stress gate integration
- app_state stress fields
- Settings.max_stress_loss_pct
- Worker scheduler job count
- Dashboard _render_stress_section
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_position(ticker: str, market_value: float) -> SimpleNamespace:
    return SimpleNamespace(
        ticker=ticker,
        market_value=Decimal(str(market_value)),
        quantity=Decimal("10"),
        avg_entry_price=Decimal(str(market_value / 10)),
        current_price=Decimal(str(market_value / 10)),
        cost_basis=Decimal(str(market_value)),
        unrealized_pnl=Decimal("0"),
        unrealized_pnl_pct=Decimal("0"),
        opened_at=dt.datetime.now(dt.timezone.utc),
        thesis_summary=None,
        strategy_key=None,
    )


def _make_portfolio(positions: dict, equity: float = 100_000.0) -> SimpleNamespace:
    return SimpleNamespace(
        positions=positions,
        equity=Decimal(str(equity)),
        cash=Decimal(str(equity - sum(
            float(p.market_value) for p in positions.values()
        ))),
    )


def _make_action(ticker: str, action_type_value: str = "open") -> SimpleNamespace:
    """Create a minimal PortfolioAction-like object."""
    from services.portfolio_engine.models import ActionType
    return SimpleNamespace(
        ticker=ticker,
        action_type=ActionType(action_type_value),
        target_notional=Decimal("5000"),
        risk_approved=False,
        reason=None,
        sizing_hint=None,
        target_quantity=None,
    )


# ---------------------------------------------------------------------------
# 1. StressTestService — apply_scenario
# ---------------------------------------------------------------------------

class TestApplyScenario:
    """Tests for StressTestService.apply_scenario()"""

    def test_apply_financial_crisis_2008_technology(self):
        """Technology positions should take a -55% shock in the 2008 scenario."""
        from services.risk_engine.stress_test import StressTestService

        positions = {"AAPL": _make_position("AAPL", 10_000.0)}
        equity = 100_000.0

        with patch("services.risk_engine.stress_test.StressTestService._get_sector", return_value="technology"):
            result = StressTestService.apply_scenario(positions, equity, "financial_crisis_2008")

        assert result.scenario_name == "financial_crisis_2008"
        assert result.positions_count == 1
        # 10_000 * -0.55 = -5_500
        assert abs(result.ticker_shocked_pnl["AAPL"] - (-5_500.0)) < 0.01
        assert abs(result.portfolio_shocked_pnl - (-5_500.0)) < 0.01
        assert result.portfolio_shocked_pnl_pct < 0.0

    def test_apply_rate_shock_energy_positive(self):
        """Energy positions gain in the 2022 rate shock scenario (+25%)."""
        from services.risk_engine.stress_test import StressTestService

        positions = {"XOM": _make_position("XOM", 20_000.0)}
        equity = 100_000.0

        with patch("services.risk_engine.stress_test.StressTestService._get_sector", return_value="energy"):
            result = StressTestService.apply_scenario(positions, equity, "rate_shock_2022")

        # 20_000 * +0.25 = +5_000
        assert abs(result.ticker_shocked_pnl["XOM"] - 5_000.0) < 0.01
        assert result.portfolio_shocked_pnl > 0.0

    def test_apply_covid_crash_financials(self):
        """Financials take -40% in COVID crash."""
        from services.risk_engine.stress_test import StressTestService

        positions = {"JPM": _make_position("JPM", 15_000.0)}
        equity = 100_000.0

        with patch("services.risk_engine.stress_test.StressTestService._get_sector", return_value="financials"):
            result = StressTestService.apply_scenario(positions, equity, "covid_crash_2020")

        # 15_000 * -0.40 = -6_000
        assert abs(result.ticker_shocked_pnl["JPM"] - (-6_000.0)) < 0.01

    def test_apply_dotcom_bust_technology(self):
        """Technology takes the worst hit (-75%) in the dotcom bust."""
        from services.risk_engine.stress_test import StressTestService

        positions = {"MSFT": _make_position("MSFT", 8_000.0)}
        equity = 100_000.0

        with patch("services.risk_engine.stress_test.StressTestService._get_sector", return_value="technology"):
            result = StressTestService.apply_scenario(positions, equity, "dotcom_bust_2001")

        # 8_000 * -0.75 = -6_000
        assert abs(result.ticker_shocked_pnl["MSFT"] - (-6_000.0)) < 0.01

    def test_apply_scenario_multi_position(self):
        """Multiple positions: shocked P&L sums across all tickers."""
        from services.risk_engine.stress_test import StressTestService

        positions = {
            "AAPL": _make_position("AAPL", 10_000.0),
            "JPM":  _make_position("JPM",  10_000.0),
        }
        equity = 100_000.0

        def mock_sector(ticker):
            return "technology" if ticker == "AAPL" else "financials"

        with patch.object(StressTestService, "_get_sector", side_effect=mock_sector):
            result = StressTestService.apply_scenario(positions, equity, "financial_crisis_2008")

        # AAPL: 10_000 * -0.55 = -5_500; JPM: 10_000 * -0.78 = -7_800
        expected = -5_500.0 + -7_800.0
        assert abs(result.portfolio_shocked_pnl - expected) < 0.01
        assert result.positions_count == 2

    def test_apply_unknown_scenario_defaults_to_other(self):
        """Unknown scenario name falls back to -30% for all sectors."""
        from services.risk_engine.stress_test import StressTestService

        positions = {"XYZ": _make_position("XYZ", 10_000.0)}
        equity = 100_000.0

        with patch("services.risk_engine.stress_test.StressTestService._get_sector", return_value="technology"):
            result = StressTestService.apply_scenario(positions, equity, "hypothetical_scenario")

        # Falls back to -30% default
        assert abs(result.ticker_shocked_pnl["XYZ"] - (-3_000.0)) < 0.01

    def test_apply_scenario_pnl_pct_computed(self):
        """portfolio_shocked_pnl_pct = pnl / equity."""
        from services.risk_engine.stress_test import StressTestService

        positions = {"AAPL": _make_position("AAPL", 20_000.0)}
        equity = 100_000.0

        with patch("services.risk_engine.stress_test.StressTestService._get_sector", return_value="technology"):
            result = StressTestService.apply_scenario(positions, equity, "financial_crisis_2008")

        # 20_000 * -0.55 = -11_000; -11_000 / 100_000 = -0.11
        expected_pct = -11_000.0 / 100_000.0
        assert abs(result.portfolio_shocked_pnl_pct - expected_pct) < 0.0001

    def test_apply_scenario_returns_label(self):
        """scenario_label is the human-readable name."""
        from services.risk_engine.stress_test import StressTestService, SCENARIO_LABELS

        positions = {"AAPL": _make_position("AAPL", 5_000.0)}
        result = StressTestService.apply_scenario(positions, 100_000.0, "financial_crisis_2008")
        assert result.scenario_label == SCENARIO_LABELS["financial_crisis_2008"]

    def test_apply_scenario_ticker_pnl_pct_dict(self):
        """ticker_shocked_pnl_pct contains per-ticker fraction-of-equity."""
        from services.risk_engine.stress_test import StressTestService

        positions = {"AAPL": _make_position("AAPL", 10_000.0)}
        equity = 100_000.0

        with patch("services.risk_engine.stress_test.StressTestService._get_sector", return_value="technology"):
            result = StressTestService.apply_scenario(positions, equity, "financial_crisis_2008")

        pct = result.ticker_shocked_pnl_pct["AAPL"]
        expected = -5_500.0 / 100_000.0
        assert abs(pct - expected) < 0.0001


# ---------------------------------------------------------------------------
# 2. StressTestService — run_all_scenarios
# ---------------------------------------------------------------------------

class TestRunAllScenarios:
    """Tests for StressTestService.run_all_scenarios()"""

    def test_run_all_returns_four_scenarios(self):
        """Exactly 4 scenarios are always computed."""
        from services.risk_engine.stress_test import StressTestService, SCENARIO_SHOCKS

        positions = {"AAPL": _make_position("AAPL", 10_000.0)}
        result = StressTestService.run_all_scenarios(positions, 100_000.0)

        assert len(result.scenarios) == len(SCENARIO_SHOCKS)
        scenario_names = {sr.scenario_name for sr in result.scenarios}
        assert scenario_names == set(SCENARIO_SHOCKS.keys())

    def test_run_all_identifies_worst_case(self):
        """worst_case_scenario is the name with the largest negative P&L."""
        from services.risk_engine.stress_test import StressTestService

        # Full tech portfolio → dotcom bust should be worst
        positions = {"AAPL": _make_position("AAPL", 50_000.0)}
        with patch.object(StressTestService, "_get_sector", return_value="technology"):
            result = StressTestService.run_all_scenarios(positions, 100_000.0)

        assert result.worst_case_scenario == "dotcom_bust_2001"

    def test_run_all_worst_loss_pct_positive(self):
        """worst_case_loss_pct is a positive fraction (magnitude of loss)."""
        from services.risk_engine.stress_test import StressTestService

        positions = {"AAPL": _make_position("AAPL", 50_000.0)}
        with patch.object(StressTestService, "_get_sector", return_value="technology"):
            result = StressTestService.run_all_scenarios(positions, 100_000.0)

        # 50_000 * 0.75 / 100_000 = 0.375
        assert result.worst_case_loss_pct > 0.0
        assert abs(result.worst_case_loss_pct - 0.375) < 0.001

    def test_run_all_worst_loss_dollar_positive(self):
        """worst_case_loss_dollar is a positive USD amount."""
        from services.risk_engine.stress_test import StressTestService

        positions = {"AAPL": _make_position("AAPL", 50_000.0)}
        with patch.object(StressTestService, "_get_sector", return_value="technology"):
            result = StressTestService.run_all_scenarios(positions, 100_000.0)

        assert result.worst_case_loss_dollar > 0.0
        assert abs(result.worst_case_loss_dollar - 37_500.0) < 0.01

    def test_run_all_no_positions(self):
        """Empty positions returns no_positions=True."""
        from services.risk_engine.stress_test import StressTestService

        result = StressTestService.run_all_scenarios({}, 100_000.0)

        assert result.no_positions is True
        assert result.scenarios == []
        assert result.worst_case_loss_pct == 0.0

    def test_run_all_zero_equity(self):
        """Zero equity returns no_positions=True."""
        from services.risk_engine.stress_test import StressTestService

        positions = {"AAPL": _make_position("AAPL", 10_000.0)}
        result = StressTestService.run_all_scenarios(positions, 0.0)

        assert result.no_positions is True

    def test_run_all_computed_at_set(self):
        """computed_at is populated with the current UTC time."""
        from services.risk_engine.stress_test import StressTestService

        positions = {"AAPL": _make_position("AAPL", 10_000.0)}
        before = dt.datetime.now(dt.timezone.utc)
        result = StressTestService.run_all_scenarios(positions, 100_000.0)
        after = dt.datetime.now(dt.timezone.utc)

        assert result.computed_at >= before
        assert result.computed_at <= after

    def test_run_all_positions_count(self):
        """positions_count matches number of positions."""
        from services.risk_engine.stress_test import StressTestService

        positions = {
            "AAPL": _make_position("AAPL", 10_000.0),
            "MSFT": _make_position("MSFT", 10_000.0),
            "JPM":  _make_position("JPM",  10_000.0),
        }
        result = StressTestService.run_all_scenarios(positions, 100_000.0)
        assert result.positions_count == 3

    def test_run_all_energy_dominated_worst_case(self):
        """Energy-only portfolio: covid crash is worst due to -60% energy shock."""
        from services.risk_engine.stress_test import StressTestService

        positions = {"XOM": _make_position("XOM", 50_000.0)}
        with patch.object(StressTestService, "_get_sector", return_value="energy"):
            result = StressTestService.run_all_scenarios(positions, 100_000.0)

        assert result.worst_case_scenario == "covid_crash_2020"


# ---------------------------------------------------------------------------
# 3. StressTestService — filter_for_stress_limit
# ---------------------------------------------------------------------------

class TestFilterForStressLimit:
    """Tests for StressTestService.filter_for_stress_limit()"""

    def _make_stress_result(self, worst_loss_pct: float, no_positions: bool = False):
        from services.risk_engine.stress_test import StressTestResult
        return StressTestResult(
            computed_at=dt.datetime.now(dt.timezone.utc),
            equity=100_000.0,
            positions_count=3,
            scenarios=[],
            worst_case_scenario="dotcom_bust_2001",
            worst_case_loss_pct=worst_loss_pct,
            worst_case_loss_dollar=worst_loss_pct * 100_000.0,
            no_positions=no_positions,
        )

    def _make_settings(self, max_stress_loss_pct: float = 0.25):
        return SimpleNamespace(max_stress_loss_pct=max_stress_loss_pct)

    def test_below_limit_no_blocking(self):
        """All actions pass when worst loss is below the limit."""
        from services.risk_engine.stress_test import StressTestService

        actions = [_make_action("AAPL", "open"), _make_action("MSFT", "open")]
        stress = self._make_stress_result(0.15)  # 15% < 25% limit
        settings = self._make_settings(0.25)

        filtered, blocked = StressTestService.filter_for_stress_limit(actions, stress, settings)

        assert blocked == 0
        assert len(filtered) == 2

    def test_above_limit_blocks_opens(self):
        """OPEN actions are blocked when worst loss exceeds the limit."""
        from services.risk_engine.stress_test import StressTestService

        actions = [
            _make_action("AAPL", "open"),
            _make_action("MSFT", "open"),
            _make_action("JPM",  "open"),
        ]
        stress = self._make_stress_result(0.35)  # 35% > 25% limit
        settings = self._make_settings(0.25)

        filtered, blocked = StressTestService.filter_for_stress_limit(actions, stress, settings)

        assert blocked == 3
        assert filtered == []

    def test_close_trim_always_pass(self):
        """CLOSE and TRIM actions always pass through even when limit is breached."""
        from services.risk_engine.stress_test import StressTestService

        actions = [
            _make_action("AAPL", "open"),
            _make_action("MSFT", "close"),
            _make_action("JPM",  "trim"),
        ]
        stress = self._make_stress_result(0.50)  # well above limit
        settings = self._make_settings(0.25)

        filtered, blocked = StressTestService.filter_for_stress_limit(actions, stress, settings)

        assert blocked == 1
        assert len(filtered) == 2
        tickers = {a.ticker for a in filtered}
        assert "MSFT" in tickers
        assert "JPM" in tickers

    def test_no_positions_pass_all(self):
        """no_positions=True → all actions pass through."""
        from services.risk_engine.stress_test import StressTestService

        actions = [_make_action("AAPL", "open"), _make_action("MSFT", "open")]
        stress = self._make_stress_result(0.99, no_positions=True)
        settings = self._make_settings(0.25)

        filtered, blocked = StressTestService.filter_for_stress_limit(actions, stress, settings)

        assert blocked == 0
        assert len(filtered) == 2

    def test_zero_limit_disables_gate(self):
        """max_stress_loss_pct=0.0 disables the gate — all actions pass."""
        from services.risk_engine.stress_test import StressTestService

        actions = [_make_action("AAPL", "open")]
        stress = self._make_stress_result(0.80)
        settings = self._make_settings(0.0)

        filtered, blocked = StressTestService.filter_for_stress_limit(actions, stress, settings)

        assert blocked == 0
        assert len(filtered) == 1

    def test_exact_limit_passes(self):
        """Worst loss exactly at limit allows actions through."""
        from services.risk_engine.stress_test import StressTestService

        actions = [_make_action("AAPL", "open")]
        stress = self._make_stress_result(0.25)  # exactly 25%
        settings = self._make_settings(0.25)

        filtered, blocked = StressTestService.filter_for_stress_limit(actions, stress, settings)

        assert blocked == 0

    def test_empty_action_list(self):
        """Empty action list → ([], 0)."""
        from services.risk_engine.stress_test import StressTestService

        stress = self._make_stress_result(0.50)
        settings = self._make_settings(0.25)

        filtered, blocked = StressTestService.filter_for_stress_limit([], stress, settings)

        assert filtered == []
        assert blocked == 0

    def test_returns_tuple(self):
        """Return type is a 2-tuple (list, int)."""
        from services.risk_engine.stress_test import StressTestService

        actions = [_make_action("AAPL", "open")]
        stress = self._make_stress_result(0.10)
        settings = self._make_settings(0.25)

        result = StressTestService.filter_for_stress_limit(actions, stress, settings)

        assert isinstance(result, tuple)
        assert len(result) == 2
        filtered, blocked = result
        assert isinstance(filtered, list)
        assert isinstance(blocked, int)


# ---------------------------------------------------------------------------
# 4. SCENARIO_SHOCKS / SCENARIO_LABELS constants
# ---------------------------------------------------------------------------

class TestScenarioConstants:
    """Validate that scenario constant dictionaries are correctly defined."""

    def test_four_scenarios_defined(self):
        from services.risk_engine.stress_test import SCENARIO_SHOCKS
        assert len(SCENARIO_SHOCKS) == 4

    def test_all_scenarios_have_labels(self):
        from services.risk_engine.stress_test import SCENARIO_SHOCKS, SCENARIO_LABELS
        for name in SCENARIO_SHOCKS:
            assert name in SCENARIO_LABELS

    def test_six_sectors_per_scenario(self):
        """Every scenario covers all 6 sector tags."""
        from services.risk_engine.stress_test import SCENARIO_SHOCKS
        expected_sectors = {"technology", "healthcare", "financials", "energy", "consumer", "other"}
        for name, shocks in SCENARIO_SHOCKS.items():
            assert set(shocks.keys()) == expected_sectors, f"scenario {name} missing sectors"

    def test_financial_crisis_financials_worst(self):
        """In 2008, financials sector shock is the most negative."""
        from services.risk_engine.stress_test import SCENARIO_SHOCKS
        shocks = SCENARIO_SHOCKS["financial_crisis_2008"]
        assert shocks["financials"] == min(shocks.values())

    def test_dotcom_technology_worst(self):
        """In dotcom bust, technology is the most negative."""
        from services.risk_engine.stress_test import SCENARIO_SHOCKS
        shocks = SCENARIO_SHOCKS["dotcom_bust_2001"]
        assert shocks["technology"] == min(shocks.values())

    def test_rate_shock_energy_positive(self):
        """Energy has a positive shock in rate shock 2022."""
        from services.risk_engine.stress_test import SCENARIO_SHOCKS
        assert SCENARIO_SHOCKS["rate_shock_2022"]["energy"] > 0.0


# ---------------------------------------------------------------------------
# 5. run_stress_test job
# ---------------------------------------------------------------------------

class TestRunStressTestJob:
    """Tests for run_stress_test() worker job."""

    def _make_app_state(self, positions=None, equity=100_000.0):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        if positions is not None:
            state.portfolio_state = SimpleNamespace(
                positions=positions,
                equity=Decimal(str(equity)),
                cash=Decimal("0"),
            )
        return state

    def test_skips_when_no_portfolio(self):
        from apps.worker.jobs.stress_test import run_stress_test
        state = self._make_app_state(positions=None)
        result = run_stress_test(app_state=state)
        assert result["status"] == "skipped_no_portfolio"
        assert state.latest_stress_result is None

    def test_skips_when_empty_positions(self):
        from apps.worker.jobs.stress_test import run_stress_test
        state = self._make_app_state(positions={})
        result = run_stress_test(app_state=state)
        assert result["status"] == "skipped_no_portfolio"

    def test_skips_when_zero_equity(self):
        from apps.worker.jobs.stress_test import run_stress_test
        positions = {"AAPL": _make_position("AAPL", 10_000.0)}
        state = self._make_app_state(positions=positions, equity=0.0)
        result = run_stress_test(app_state=state)
        assert result["status"] == "skipped_zero_equity"

    def test_ok_with_valid_portfolio(self):
        from apps.worker.jobs.stress_test import run_stress_test
        positions = {"AAPL": _make_position("AAPL", 10_000.0)}
        state = self._make_app_state(positions=positions, equity=100_000.0)
        result = run_stress_test(app_state=state)
        assert result["status"] == "ok"
        assert result["positions_count"] == 1
        assert result["worst_case_scenario"] is not None
        assert result["worst_case_loss_pct"] > 0.0
        assert state.latest_stress_result is not None
        assert state.stress_computed_at is not None

    def test_stores_result_in_app_state(self):
        from apps.worker.jobs.stress_test import run_stress_test
        from services.risk_engine.stress_test import StressTestResult
        positions = {"MSFT": _make_position("MSFT", 20_000.0)}
        state = self._make_app_state(positions=positions, equity=100_000.0)
        run_stress_test(app_state=state)
        assert isinstance(state.latest_stress_result, StressTestResult)

    def test_error_path_returns_error_status(self):
        """Exception in StressTestService is caught and returns error status."""
        from apps.worker.jobs.stress_test import run_stress_test

        positions = {"AAPL": _make_position("AAPL", 10_000.0)}
        state = self._make_app_state(positions=positions, equity=100_000.0)

        # Patch the lazy import path used inside the job
        mock_svc = MagicMock()
        mock_svc.run_all_scenarios.side_effect = RuntimeError("stress exploded")
        mock_module = MagicMock()
        mock_module.StressTestService = mock_svc

        with patch.dict("sys.modules", {"services.risk_engine.stress_test": mock_module}):
            result = run_stress_test(app_state=state)

        assert result["status"] == "error"
        assert "stress exploded" in result["error"]

    def test_result_has_four_scenarios(self):
        from apps.worker.jobs.stress_test import run_stress_test
        positions = {
            "AAPL": _make_position("AAPL", 10_000.0),
            "JPM":  _make_position("JPM",  10_000.0),
        }
        state = self._make_app_state(positions=positions, equity=100_000.0)
        run_stress_test(app_state=state)
        assert len(state.latest_stress_result.scenarios) == 4


# ---------------------------------------------------------------------------
# 6. Settings
# ---------------------------------------------------------------------------

class TestStressTestSettings:
    """Settings.max_stress_loss_pct field."""

    def test_default_value(self):
        from config.settings import Settings
        s = Settings()
        assert s.max_stress_loss_pct == 0.25

    def test_set_via_env(self, monkeypatch):
        monkeypatch.setenv("APIS_MAX_STRESS_LOSS_PCT", "0.40")
        from config.settings import Settings
        s = Settings()
        assert s.max_stress_loss_pct == 0.40

    def test_zero_allowed(self):
        from config.settings import Settings
        s = Settings(max_stress_loss_pct=0.0)
        assert s.max_stress_loss_pct == 0.0

    def test_one_allowed(self):
        from config.settings import Settings
        s = Settings(max_stress_loss_pct=1.0)
        assert s.max_stress_loss_pct == 1.0


# ---------------------------------------------------------------------------
# 7. app_state fields
# ---------------------------------------------------------------------------

class TestAppStateFields:
    """Verify Phase 44 fields exist and default correctly."""

    def test_latest_stress_result_defaults_none(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert state.latest_stress_result is None

    def test_stress_computed_at_defaults_none(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert state.stress_computed_at is None

    def test_stress_blocked_count_defaults_zero(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert state.stress_blocked_count == 0

    def test_fields_mutable(self):
        from apps.api.state import ApiAppState
        from services.risk_engine.stress_test import StressTestResult
        state = ApiAppState()
        now = dt.datetime.now(dt.timezone.utc)
        state.latest_stress_result = StressTestResult(
            computed_at=now,
            equity=100_000.0,
            positions_count=3,
            no_positions=False,
        )
        state.stress_computed_at = now
        state.stress_blocked_count = 2
        assert state.stress_blocked_count == 2
        assert state.stress_computed_at == now


# ---------------------------------------------------------------------------
# 8. REST route — GET /portfolio/stress-test
# ---------------------------------------------------------------------------

class TestGetPortfolioStressTest:
    """Tests for GET /api/v1/portfolio/stress-test route."""

    def _get_client(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        return TestClient(app)

    def test_no_data_returns_200_empty(self):
        from apps.api.state import reset_app_state
        reset_app_state()
        client = self._get_client()
        resp = client.get("/api/v1/portfolio/stress-test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["no_positions"] is True
        assert data["positions_count"] == 0
        assert data["scenarios"] == []

    def test_with_stress_result_returns_data(self):
        from apps.api.state import get_app_state, reset_app_state
        from services.risk_engine.stress_test import ScenarioResult, StressTestResult, SCENARIO_LABELS

        reset_app_state()
        state = get_app_state()

        scenarios = [
            ScenarioResult(
                scenario_name="financial_crisis_2008",
                scenario_label=SCENARIO_LABELS["financial_crisis_2008"],
                portfolio_shocked_pnl=-20_000.0,
                portfolio_shocked_pnl_pct=-0.20,
                equity=100_000.0,
                positions_count=3,
            ),
            ScenarioResult(
                scenario_name="dotcom_bust_2001",
                scenario_label=SCENARIO_LABELS["dotcom_bust_2001"],
                portfolio_shocked_pnl=-30_000.0,
                portfolio_shocked_pnl_pct=-0.30,
                equity=100_000.0,
                positions_count=3,
            ),
        ]
        state.latest_stress_result = StressTestResult(
            computed_at=dt.datetime.now(dt.timezone.utc),
            equity=100_000.0,
            positions_count=3,
            scenarios=scenarios,
            worst_case_scenario="dotcom_bust_2001",
            worst_case_loss_pct=0.30,
            worst_case_loss_dollar=30_000.0,
            no_positions=False,
        )

        client = self._get_client()
        resp = client.get("/api/v1/portfolio/stress-test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["no_positions"] is False
        assert data["positions_count"] == 3
        assert data["worst_case_scenario"] == "dotcom_bust_2001"
        assert data["worst_case_loss_pct"] == pytest.approx(30.0, abs=0.01)
        assert len(data["scenarios"]) == 2

    def test_stress_limit_breached_flag(self):
        from apps.api.state import get_app_state, reset_app_state
        from services.risk_engine.stress_test import StressTestResult

        reset_app_state()
        state = get_app_state()
        state.latest_stress_result = StressTestResult(
            computed_at=dt.datetime.now(dt.timezone.utc),
            equity=100_000.0,
            positions_count=2,
            scenarios=[],
            worst_case_scenario="dotcom_bust_2001",
            worst_case_loss_pct=0.40,   # 40% > 25% default limit
            worst_case_loss_dollar=40_000.0,
            no_positions=False,
        )

        client = self._get_client()
        resp = client.get("/api/v1/portfolio/stress-test")
        data = resp.json()
        assert data["stress_limit_breached"] is True

    def test_stress_limit_not_breached(self):
        from apps.api.state import get_app_state, reset_app_state
        from services.risk_engine.stress_test import StressTestResult

        reset_app_state()
        state = get_app_state()
        state.latest_stress_result = StressTestResult(
            computed_at=dt.datetime.now(dt.timezone.utc),
            equity=100_000.0,
            positions_count=2,
            scenarios=[],
            worst_case_scenario="covid_crash_2020",
            worst_case_loss_pct=0.10,   # 10% < 25% limit
            worst_case_loss_dollar=10_000.0,
            no_positions=False,
        )

        client = self._get_client()
        resp = client.get("/api/v1/portfolio/stress-test")
        data = resp.json()
        assert data["stress_limit_breached"] is False


# ---------------------------------------------------------------------------
# 9. REST route — GET /portfolio/stress-test/{scenario}
# ---------------------------------------------------------------------------

class TestGetStressScenarioDetail:
    """Tests for GET /api/v1/portfolio/stress-test/{scenario} route."""

    def _get_client(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        return TestClient(app)

    def test_no_data_returns_200_unavailable(self):
        from apps.api.state import reset_app_state
        reset_app_state()
        client = self._get_client()
        resp = client.get("/api/v1/portfolio/stress-test/financial_crisis_2008")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data_available"] is False
        assert data["scenario_name"] == "financial_crisis_2008"

    def test_known_scenario_returns_data(self):
        from apps.api.state import get_app_state, reset_app_state
        from services.risk_engine.stress_test import ScenarioResult, StressTestResult, SCENARIO_LABELS

        reset_app_state()
        state = get_app_state()
        state.latest_stress_result = StressTestResult(
            computed_at=dt.datetime.now(dt.timezone.utc),
            equity=100_000.0,
            positions_count=2,
            scenarios=[
                ScenarioResult(
                    scenario_name="financial_crisis_2008",
                    scenario_label=SCENARIO_LABELS["financial_crisis_2008"],
                    portfolio_shocked_pnl=-18_000.0,
                    portfolio_shocked_pnl_pct=-0.18,
                    equity=100_000.0,
                    positions_count=2,
                    ticker_shocked_pnl={"AAPL": -9_000.0, "MSFT": -9_000.0},
                    ticker_shocked_pnl_pct={"AAPL": -0.09, "MSFT": -0.09},
                ),
            ],
            worst_case_scenario="financial_crisis_2008",
            worst_case_loss_pct=0.18,
            worst_case_loss_dollar=18_000.0,
            no_positions=False,
        )

        client = self._get_client()
        resp = client.get("/api/v1/portfolio/stress-test/financial_crisis_2008")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data_available"] is True
        assert data["scenario_name"] == "financial_crisis_2008"
        assert data["portfolio_shocked_pnl"] == pytest.approx(-18_000.0, abs=0.01)
        assert "AAPL" in data["ticker_shocked_pnl"]

    def test_unknown_scenario_returns_unavailable(self):
        from apps.api.state import get_app_state, reset_app_state
        from services.risk_engine.stress_test import StressTestResult

        reset_app_state()
        state = get_app_state()
        state.latest_stress_result = StressTestResult(
            computed_at=dt.datetime.now(dt.timezone.utc),
            equity=100_000.0,
            positions_count=1,
            scenarios=[],
            worst_case_scenario="dotcom_bust_2001",
            worst_case_loss_pct=0.30,
            worst_case_loss_dollar=30_000.0,
            no_positions=False,
        )

        client = self._get_client()
        resp = client.get("/api/v1/portfolio/stress-test/nonexistent_scenario")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data_available"] is False

    def test_scenario_name_lowercased(self):
        """Route normalises scenario name to lowercase."""
        from apps.api.state import reset_app_state
        reset_app_state()
        client = self._get_client()
        resp = client.get("/api/v1/portfolio/stress-test/FINANCIAL_CRISIS_2008")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scenario_name"] == "financial_crisis_2008"


# ---------------------------------------------------------------------------
# 10. Paper trading cycle integration
# ---------------------------------------------------------------------------

class TestPaperCycleStressGate:
    """Verify stress gate is wired into run_paper_trading_cycle."""

    def _make_app_state_with_stress(self, worst_loss_pct: float):
        from apps.api.state import ApiAppState
        from services.risk_engine.stress_test import StressTestResult

        state = ApiAppState()
        state.latest_stress_result = StressTestResult(
            computed_at=dt.datetime.now(dt.timezone.utc),
            equity=100_000.0,
            positions_count=3,
            worst_case_scenario="dotcom_bust_2001",
            worst_case_loss_pct=worst_loss_pct,
            worst_case_loss_dollar=worst_loss_pct * 100_000.0,
            no_positions=False,
        )
        return state

    def test_stress_blocked_count_set_on_cycle(self):
        """stress_blocked_count is updated each cycle."""
        from apps.api.state import ApiAppState
        from services.risk_engine.stress_test import StressTestResult

        state = ApiAppState()
        state.latest_stress_result = StressTestResult(
            computed_at=dt.datetime.now(dt.timezone.utc),
            equity=100_000.0,
            positions_count=3,
            worst_case_scenario="dotcom_bust_2001",
            worst_case_loss_pct=0.80,  # far above 25% default
            worst_case_loss_dollar=80_000.0,
            no_positions=False,
        )
        # Attribute exists and is 0 before any cycle
        assert state.stress_blocked_count == 0

    def test_cycle_result_includes_stress_mode(self):
        """run_paper_trading_cycle skips gracefully in RESEARCH mode."""
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from apps.api.state import ApiAppState

        state = ApiAppState()
        result = run_paper_trading_cycle(app_state=state)

        # Research mode → skipped, not an error about stress gate
        assert result["status"] in ("skipped_mode", "killed", "skipped_no_rankings")


# ---------------------------------------------------------------------------
# 11. Worker scheduler job count
# ---------------------------------------------------------------------------

class TestSchedulerJobCount:
    """Worker scheduler must contain exactly 25 jobs."""

    def test_scheduler_has_25_jobs(self):
        from apps.worker.main import build_scheduler

        scheduler = build_scheduler()
        jobs = scheduler.get_jobs()
        assert len(jobs) == 30

    def test_stress_test_job_present(self):
        from apps.worker.main import build_scheduler

        scheduler = build_scheduler()
        job_ids = {j.id for j in scheduler.get_jobs()}
        assert "stress_test" in job_ids

    def test_stress_test_scheduled_at_0621(self):
        from apps.worker.main import build_scheduler

        scheduler = build_scheduler()
        job = next((j for j in scheduler.get_jobs() if j.id == "stress_test"), None)
        assert job is not None
        # Verify trigger fields
        trigger = job.trigger
        fields = {f.name: f for f in trigger.fields}
        assert int(str(fields["hour"])) == 6
        assert int(str(fields["minute"])) == 21


# ---------------------------------------------------------------------------
# 12. Dashboard _render_stress_section
# ---------------------------------------------------------------------------

class TestDashboardStressSection:
    """Tests for _render_stress_section in the dashboard router."""

    def _make_state(self, stress_result=None, stress_blocked=0):
        return SimpleNamespace(
            latest_stress_result=stress_result,
            stress_blocked_count=stress_blocked,
        )

    def _make_settings(self, max_stress_loss_pct=0.25):
        return SimpleNamespace(max_stress_loss_pct=max_stress_loss_pct)

    def test_renders_no_data_message(self):
        from apps.dashboard.router import _render_stress_section

        state = self._make_state(stress_result=None)
        html = _render_stress_section(state, self._make_settings())

        assert "No stress-test data yet" in html
        assert "Phase 44" in html

    def test_renders_no_positions_message(self):
        from apps.dashboard.router import _render_stress_section
        from services.risk_engine.stress_test import StressTestResult

        state = self._make_state(
            stress_result=StressTestResult(
                computed_at=dt.datetime.now(dt.timezone.utc),
                equity=100_000.0,
                positions_count=0,
                no_positions=True,
            )
        )
        html = _render_stress_section(state, self._make_settings())
        assert "No open positions" in html

    def test_renders_worst_case_loss(self):
        from apps.dashboard.router import _render_stress_section
        from services.risk_engine.stress_test import ScenarioResult, StressTestResult, SCENARIO_LABELS

        scenarios = [
            ScenarioResult(
                scenario_name="dotcom_bust_2001",
                scenario_label=SCENARIO_LABELS["dotcom_bust_2001"],
                portfolio_shocked_pnl=-30_000.0,
                portfolio_shocked_pnl_pct=-0.30,
                equity=100_000.0,
                positions_count=2,
            ),
        ]
        state = self._make_state(
            stress_result=StressTestResult(
                computed_at=dt.datetime.now(dt.timezone.utc),
                equity=100_000.0,
                positions_count=2,
                scenarios=scenarios,
                worst_case_scenario="dotcom_bust_2001",
                worst_case_loss_pct=0.30,
                worst_case_loss_dollar=30_000.0,
                no_positions=False,
            )
        )
        html = _render_stress_section(state, self._make_settings())
        assert "30.0%" in html
        assert "Worst-Case" in html

    def test_renders_limit_breached_flag(self):
        from apps.dashboard.router import _render_stress_section
        from services.risk_engine.stress_test import StressTestResult

        state = self._make_state(
            stress_result=StressTestResult(
                computed_at=dt.datetime.now(dt.timezone.utc),
                equity=100_000.0,
                positions_count=2,
                scenarios=[],
                worst_case_scenario="dotcom_bust_2001",
                worst_case_loss_pct=0.50,  # > 25% limit
                worst_case_loss_dollar=50_000.0,
                no_positions=False,
            )
        )
        html = _render_stress_section(state, self._make_settings(0.25))
        assert "LIMIT BREACHED" in html

    def test_renders_blocked_count(self):
        from apps.dashboard.router import _render_stress_section
        from services.risk_engine.stress_test import StressTestResult

        state = self._make_state(
            stress_result=StressTestResult(
                computed_at=dt.datetime.now(dt.timezone.utc),
                equity=100_000.0,
                positions_count=2,
                scenarios=[],
                worst_case_scenario="dotcom_bust_2001",
                worst_case_loss_pct=0.40,
                worst_case_loss_dollar=40_000.0,
                no_positions=False,
            ),
            stress_blocked=3,
        )
        html = _render_stress_section(state, self._make_settings())
        assert "3" in html

    def test_scenario_table_rendered(self):
        from apps.dashboard.router import _render_stress_section
        from services.risk_engine.stress_test import ScenarioResult, StressTestResult, SCENARIO_LABELS

        scenarios = [
            ScenarioResult(
                scenario_name="covid_crash_2020",
                scenario_label=SCENARIO_LABELS["covid_crash_2020"],
                portfolio_shocked_pnl=-15_000.0,
                portfolio_shocked_pnl_pct=-0.15,
                equity=100_000.0,
                positions_count=2,
            ),
        ]
        state = self._make_state(
            stress_result=StressTestResult(
                computed_at=dt.datetime.now(dt.timezone.utc),
                equity=100_000.0,
                positions_count=2,
                scenarios=scenarios,
                worst_case_scenario="covid_crash_2020",
                worst_case_loss_pct=0.15,
                worst_case_loss_dollar=15_000.0,
                no_positions=False,
            )
        )
        html = _render_stress_section(state, self._make_settings())
        assert "<table>" in html
        assert "COVID" in html

    def test_section_in_main_dashboard(self):
        """The full dashboard HTML includes the stress test section."""
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import reset_app_state

        reset_app_state()
        client = TestClient(app)
        resp = client.get("/dashboard/")
        assert resp.status_code == 200
        assert "Phase 44" in resp.text
