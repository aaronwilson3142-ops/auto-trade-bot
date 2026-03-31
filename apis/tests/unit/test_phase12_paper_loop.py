"""
Phase 12 — Live Paper Trading Loop Tests.

Covers:
  ✅ Paper trading cycle job — mode guards, skip paths, full cycle
  ✅ ApiAppState — new paper-loop fields
  ✅ Worker scheduler — paper trading jobs registered
  ✅ Schwab adapter scaffold — import, identity, construction, method stubs
  ✅ Prometheus metrics endpoint — content, keys, format
  ✅ Worker jobs __init__ — run_paper_trading_cycle exported

Test classes
------------
  TestPaperTradingCycleImport         — module-level import and symbol visibility
  TestPaperTradingCycleModeGuard      — skips in RESEARCH / BACKTEST modes
  TestPaperTradingCycleNoRankings     — skips when latest_rankings is empty
  TestPaperTradingCycleFullCycle      — end-to-end with mocked services
  TestPaperTradingCycleBrokerConnect  — broker connect / ping path
  TestPaperTradingCycleFatalError     — top-level exception captured
  TestApiAppStateNewFields            — paper_loop_active / last_paper_cycle_at etc.
  TestWorkerSchedulerPaperJobs        — scheduler has paper trading jobs
  TestWorkerJobsExports               — run_paper_trading_cycle in __init__
  TestSchwabAdapterImport             — module import and symbol export
  TestSchwabAdapterConstruction       — identity, construction, auth guards
  TestSchwabAdapterMethodStubs        — all methods raise BrokerConnectionError when not connected (Phase 14: concrete impl)
  TestSchwabAdapterDuplicateGuard     — place_order duplicate key guard
  TestMetricsRoute                    — /metrics returns Prometheus text payload
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ── Reset shared state between tests ─────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_app_state():
    from apps.api.state import reset_app_state
    reset_app_state()
    yield
    reset_app_state()


# =============================================================================
# TestPaperTradingCycleImport
# =============================================================================

class TestPaperTradingCycleImport:
    def test_module_importable(self):
        from apps.worker.jobs import paper_trading  # noqa: F401

    def test_function_importable(self):
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        assert callable(run_paper_trading_cycle)

    def test_exported_from_jobs_package(self):
        from apps.worker.jobs import run_paper_trading_cycle
        assert callable(run_paper_trading_cycle)


# =============================================================================
# TestPaperTradingCycleModeGuard
# =============================================================================

class TestPaperTradingCycleModeGuard:
    """skip_mode is returned for modes that do not permit execution."""

    def _run_with_mode(self, mode_str: str) -> dict:
        from apps.api.state import ApiAppState
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from config.settings import Settings

        state = ApiAppState()
        settings = Settings(operating_mode=mode_str)
        return run_paper_trading_cycle(app_state=state, settings=settings)

    def test_research_mode_skipped(self):
        result = self._run_with_mode("research")
        assert result["status"] == "skipped_mode"
        assert result["proposed_count"] == 0
        assert result["executed_count"] == 0

    def test_backtest_mode_skipped(self):
        result = self._run_with_mode("backtest")
        assert result["status"] == "skipped_mode"

    def test_paper_mode_not_skipped_by_mode_guard(self):
        """Paper mode passes the mode guard (may be skipped for other reasons)."""
        from apps.api.state import ApiAppState
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from config.settings import Settings

        state = ApiAppState()
        settings = Settings(operating_mode="paper")
        result = run_paper_trading_cycle(app_state=state, settings=settings)
        # Not skipped_mode — should be skipped_no_rankings or ok
        assert result["status"] != "skipped_mode"

    def test_human_approved_mode_not_skipped_by_mode_guard(self):
        from apps.api.state import ApiAppState
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from config.settings import Settings

        state = ApiAppState()
        settings = Settings(operating_mode="human_approved")
        result = run_paper_trading_cycle(app_state=state, settings=settings)
        assert result["status"] != "skipped_mode"

    def test_skip_result_has_expected_keys(self):
        result = self._run_with_mode("research")
        for key in ("status", "mode", "run_at", "proposed_count", "approved_count",
                    "executed_count", "reconciliation_clean", "errors"):
            assert key in result

    def test_skip_result_mode_value(self):
        result = self._run_with_mode("research")
        assert result["mode"] == "research"


# =============================================================================
# TestPaperTradingCycleNoRankings
# =============================================================================

class TestPaperTradingCycleNoRankings:
    def _run_paper_empty(self) -> dict:
        from apps.api.state import ApiAppState
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from config.settings import Settings

        state = ApiAppState()
        settings = Settings(operating_mode="paper")
        return run_paper_trading_cycle(app_state=state, settings=settings)

    def test_skipped_no_rankings(self):
        result = self._run_paper_empty()
        assert result["status"] == "skipped_no_rankings"

    def test_no_rankings_zero_counts(self):
        result = self._run_paper_empty()
        assert result["proposed_count"] == 0
        assert result["executed_count"] == 0

    def test_no_rankings_has_mode(self):
        result = self._run_paper_empty()
        assert result["mode"] == "paper"


# =============================================================================
# TestPaperTradingCycleFullCycle
# =============================================================================

class TestPaperTradingCycleFullCycle:
    """Full cycle with all services mocked."""

    def _make_ranked_result(self, ticker: str = "AAPL") -> Any:
        import uuid
        from services.ranking_engine.models import RankedResult
        return RankedResult(
            rank_position=1,
            security_id=uuid.uuid4(),
            ticker=ticker,
            composite_score=Decimal("0.85"),
            portfolio_fit_score=Decimal("0.80"),
            recommended_action="buy",
            target_horizon="swing",
            thesis_summary="Strong momentum",
            disconfirming_factors="None identified",
            sizing_hint_pct=Decimal("0.10"),
            source_reliability_tier="secondary_verified",
            contains_rumor=False,
        )

    def _make_portfolio_state(self) -> Any:
        from services.portfolio_engine.models import PortfolioState
        return PortfolioState(
            cash=Decimal("100000.00"),
            start_of_day_equity=Decimal("100000.00"),
            high_water_mark=Decimal("100000.00"),
        )

    def _make_portfolio_action(self, ticker: str = "AAPL") -> Any:
        from services.portfolio_engine.models import ActionType, PortfolioAction
        action = PortfolioAction(
            action_type=ActionType.OPEN,
            ticker=ticker,
            reason="Strong momentum signal",
            target_notional=Decimal("10000.00"),
            thesis_summary="Strong momentum",
        )
        action.risk_approved = True
        return action

    def test_full_cycle_ok_status(self):
        from apps.api.state import ApiAppState
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from config.settings import Settings
        from services.execution_engine.models import ExecutionResult, ExecutionStatus
        from services.reporting.models import FillReconciliationSummary

        state = ApiAppState()
        state.latest_rankings = [self._make_ranked_result()]
        state.portfolio_state = self._make_portfolio_state()

        settings = Settings(operating_mode="paper")

        # Mock portfolio service
        mock_portfolio = MagicMock()
        mock_portfolio.apply_ranked_opportunities.return_value = [
            self._make_portfolio_action()
        ]

        # Mock risk service — no hard blocks
        from services.risk_engine.models import RiskCheckResult
        mock_risk = MagicMock()
        mock_risk.validate_action.return_value = RiskCheckResult(
            passed=True, violations=[], warnings=[], adjusted_max_notional=None
        )

        # Mock market data
        mock_md = MagicMock()
        mock_snapshot = MagicMock()
        mock_snapshot.latest_price = Decimal("150.00")
        mock_md.get_snapshot.return_value = mock_snapshot

        # Mock execution service
        from services.execution_engine.models import ExecutionResult, ExecutionStatus
        action = self._make_portfolio_action()
        mock_exec = MagicMock()
        mock_exec.execute_approved_actions.return_value = [
            ExecutionResult(status=ExecutionStatus.FILLED, action=action)
        ]

        # Mock broker
        from broker_adapters.base.models import AccountState
        mock_broker = MagicMock()
        mock_broker.ping.return_value = True
        mock_broker.get_account_state.return_value = AccountState(
            account_id="paper-001",
            cash_balance=Decimal("90000.00"),
            buying_power=Decimal("90000.00"),
            equity_value=Decimal("100000.00"),
            gross_exposure=Decimal("10000.00"),
        )
        mock_broker.list_positions.return_value = []
        mock_broker.list_fills_since.return_value = []

        # Mock reporting
        mock_reporting = MagicMock()
        mock_summary = MagicMock()
        mock_summary.is_clean = True
        mock_reporting.reconcile_fills.return_value = mock_summary

        result = run_paper_trading_cycle(
            app_state=state,
            settings=settings,
            broker=mock_broker,
            portfolio_svc=mock_portfolio,
            risk_svc=mock_risk,
            execution_svc=mock_exec,
            market_data_svc=mock_md,
            reporting_svc=mock_reporting,
        )

        assert result["status"] == "ok"

    def test_full_cycle_proposed_count(self):
        from apps.api.state import ApiAppState
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from config.settings import Settings
        from services.risk_engine.models import RiskCheckResult

        state = ApiAppState()
        state.latest_rankings = [self._make_ranked_result()]
        state.portfolio_state = self._make_portfolio_state()
        settings = Settings(operating_mode="paper")

        mock_portfolio = MagicMock()
        mock_portfolio.apply_ranked_opportunities.return_value = [
            self._make_portfolio_action("AAPL"),
            self._make_portfolio_action("MSFT"),
        ]
        mock_risk = MagicMock()
        mock_risk.validate_action.return_value = RiskCheckResult(
            passed=True, violations=[], warnings=[], adjusted_max_notional=None
        )
        mock_md = MagicMock()
        mock_md.get_snapshot.return_value = MagicMock(latest_price=Decimal("200.00"))
        mock_exec = MagicMock()
        mock_exec.execute_approved_actions.return_value = []
        mock_broker = MagicMock()
        mock_broker.ping.return_value = True
        mock_broker.get_account_state.return_value = MagicMock(
            cash_balance=Decimal("100000"), positions=[]
        )
        mock_broker.list_positions.return_value = []
        mock_broker.list_fills_since.return_value = []
        mock_reporting = MagicMock()
        mock_reporting.reconcile_fills.return_value = MagicMock(is_clean=True)

        result = run_paper_trading_cycle(
            app_state=state, settings=settings,
            broker=mock_broker, portfolio_svc=mock_portfolio,
            risk_svc=mock_risk, execution_svc=mock_exec,
            market_data_svc=mock_md, reporting_svc=mock_reporting,
        )

        assert result["proposed_count"] == 2

    def test_full_cycle_updates_app_state_portfolio(self):
        from apps.api.state import ApiAppState
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from config.settings import Settings
        from services.risk_engine.models import RiskCheckResult

        state = ApiAppState()
        state.latest_rankings = [self._make_ranked_result()]
        state.portfolio_state = self._make_portfolio_state()
        settings = Settings(operating_mode="paper")

        mock_portfolio = MagicMock()
        mock_portfolio.apply_ranked_opportunities.return_value = []
        mock_risk = MagicMock()
        mock_risk.validate_action.return_value = RiskCheckResult(True, [], [], None)
        mock_exec = MagicMock()
        mock_exec.execute_approved_actions.return_value = []
        mock_broker = MagicMock()
        mock_broker.ping.return_value = True
        new_cash = Decimal("95000.00")
        mock_broker.get_account_state.return_value = MagicMock(
            cash_balance=new_cash, positions=[]
        )
        mock_broker.list_positions.return_value = []
        mock_broker.list_fills_since.return_value = []
        mock_reporting = MagicMock()
        mock_reporting.reconcile_fills.return_value = MagicMock(is_clean=True)

        run_paper_trading_cycle(
            app_state=state, settings=settings,
            broker=mock_broker, portfolio_svc=mock_portfolio,
            risk_svc=mock_risk, execution_svc=mock_exec,
            reporting_svc=mock_reporting,
        )

        assert state.portfolio_state is not None
        assert state.portfolio_state.cash == new_cash

    def test_full_cycle_updates_paper_loop_active(self):
        from apps.api.state import ApiAppState
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from config.settings import Settings
        from services.risk_engine.models import RiskCheckResult

        state = ApiAppState()
        state.latest_rankings = [self._make_ranked_result()]
        state.portfolio_state = self._make_portfolio_state()
        settings = Settings(operating_mode="paper")

        mock_portfolio = MagicMock()
        mock_portfolio.apply_ranked_opportunities.return_value = []
        mock_risk = MagicMock()
        mock_risk.validate_action.return_value = RiskCheckResult(True, [], [], None)
        mock_exec = MagicMock()
        mock_exec.execute_approved_actions.return_value = []
        mock_broker = MagicMock()
        mock_broker.ping.return_value = True
        mock_broker.get_account_state.return_value = MagicMock(
            cash_balance=Decimal("100000"), positions=[]
        )
        mock_broker.list_positions.return_value = []
        mock_broker.list_fills_since.return_value = []
        mock_reporting = MagicMock()
        mock_reporting.reconcile_fills.return_value = MagicMock(is_clean=True)

        run_paper_trading_cycle(
            app_state=state, settings=settings,
            broker=mock_broker, portfolio_svc=mock_portfolio,
            risk_svc=mock_risk, execution_svc=mock_exec,
            reporting_svc=mock_reporting,
        )

        assert state.paper_loop_active is True
        assert state.last_paper_cycle_at is not None

    def test_blocked_actions_not_executed(self):
        """Actions blocked by risk engine do not reach execution service."""
        from apps.api.state import ApiAppState
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from config.settings import Settings
        from services.risk_engine.models import RiskCheckResult, RiskSeverity, RiskViolation

        state = ApiAppState()
        state.latest_rankings = [self._make_ranked_result()]
        state.portfolio_state = self._make_portfolio_state()
        settings = Settings(operating_mode="paper")

        mock_portfolio = MagicMock()
        mock_portfolio.apply_ranked_opportunities.return_value = [
            self._make_portfolio_action()
        ]
        mock_risk = MagicMock()
        # Return a hard block via kill switch
        mock_risk.validate_action.return_value = RiskCheckResult(
            passed=False,
            violations=[
                RiskViolation(rule_name="kill_switch", reason="kill switch active", severity=RiskSeverity.HARD_BLOCK)
            ],
            warnings=[],
            adjusted_max_notional=None,
        )
        mock_exec = MagicMock()
        mock_exec.execute_approved_actions.return_value = []
        mock_broker = MagicMock()
        mock_broker.ping.return_value = True
        mock_broker.get_account_state.return_value = MagicMock(
            cash_balance=Decimal("100000"), positions=[]
        )
        mock_broker.list_positions.return_value = []
        mock_broker.list_fills_since.return_value = []
        mock_reporting = MagicMock()
        mock_reporting.reconcile_fills.return_value = MagicMock(is_clean=True)

        result = run_paper_trading_cycle(
            app_state=state, settings=settings,
            broker=mock_broker, portfolio_svc=mock_portfolio,
            risk_svc=mock_risk, execution_svc=mock_exec,
            reporting_svc=mock_reporting,
        )

        assert result["approved_count"] == 0
        # execute_approved_actions called with empty list
        mock_exec.execute_approved_actions.assert_called_once_with([])

    def test_result_has_all_keys(self):
        from apps.api.state import ApiAppState
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from config.settings import Settings

        state = ApiAppState()
        state.latest_rankings = [self._make_ranked_result()]
        state.portfolio_state = self._make_portfolio_state()
        settings = Settings(operating_mode="paper")

        mock_portfolio = MagicMock()
        mock_portfolio.apply_ranked_opportunities.return_value = []
        mock_risk = MagicMock()
        mock_exec = MagicMock()
        mock_exec.execute_approved_actions.return_value = []
        mock_broker = MagicMock()
        mock_broker.ping.return_value = True
        mock_broker.get_account_state.return_value = MagicMock(
            cash_balance=Decimal("100000"), positions=[]
        )
        mock_broker.list_positions.return_value = []
        mock_broker.list_fills_since.return_value = []
        mock_reporting = MagicMock()
        mock_reporting.reconcile_fills.return_value = MagicMock(is_clean=True)

        result = run_paper_trading_cycle(
            app_state=state, settings=settings,
            broker=mock_broker, portfolio_svc=mock_portfolio,
            risk_svc=mock_risk, execution_svc=mock_exec,
            reporting_svc=mock_reporting,
        )

        for key in ("status", "mode", "run_at", "proposed_count",
                    "approved_count", "executed_count", "reconciliation_clean", "errors"):
            assert key in result


# =============================================================================
# TestPaperTradingCycleBrokerConnect
# =============================================================================

class TestPaperTradingCycleBrokerConnect:
    def test_broker_connected_when_not_pinged(self):
        """connect() is called when ping() returns False."""
        from apps.api.state import ApiAppState
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from config.settings import Settings
        from services.risk_engine.models import RiskCheckResult

        state = ApiAppState()
        state.latest_rankings = [MagicMock(recommended_action="buy", ticker="AAPL")]
        state.portfolio_state = MagicMock(
            positions={}, position_count=0, cash=Decimal("100000"),
            equity=Decimal("100000"), gross_exposure=Decimal("0"),
            start_of_day_equity=Decimal("100000"), high_water_mark=Decimal("100000"),
        )
        settings = Settings(operating_mode="paper")

        mock_broker = MagicMock()
        mock_broker.ping.return_value = False   # not connected → connect() called
        mock_broker.get_account_state.return_value = MagicMock(
            cash_balance=Decimal("100000"), positions=[]
        )
        mock_broker.list_positions.return_value = []
        mock_broker.list_fills_since.return_value = []
        mock_portfolio = MagicMock()
        mock_portfolio.apply_ranked_opportunities.return_value = []
        mock_risk = MagicMock()
        mock_exec = MagicMock()
        mock_exec.execute_approved_actions.return_value = []
        mock_reporting = MagicMock()
        mock_reporting.reconcile_fills.return_value = MagicMock(is_clean=True)

        run_paper_trading_cycle(
            app_state=state, settings=settings, broker=mock_broker,
            portfolio_svc=mock_portfolio, risk_svc=mock_risk,
            execution_svc=mock_exec, reporting_svc=mock_reporting,
        )

        mock_broker.connect.assert_called_once()

    def test_broker_not_reconnected_when_already_connected(self):
        from apps.api.state import ApiAppState
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from config.settings import Settings

        state = ApiAppState()
        state.latest_rankings = []
        settings = Settings(operating_mode="paper")

        mock_broker = MagicMock()
        mock_broker.ping.return_value = True

        run_paper_trading_cycle(
            app_state=state, settings=settings, broker=mock_broker,
        )
        # With no rankings the cycle exits early before reaching connect logic
        mock_broker.connect.assert_not_called()


# =============================================================================
# TestPaperTradingCycleFatalError
# =============================================================================

class TestPaperTradingCycleFatalError:
    def test_fatal_exception_captured(self):
        """Top-level exception is caught and returned in error result."""
        from apps.api.state import ApiAppState
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from config.settings import Settings

        state = ApiAppState()
        state.latest_rankings = [MagicMock()]
        state.portfolio_state = None
        settings = Settings(operating_mode="paper")

        # portfolio_svc.apply_ranked_opportunities raises unexpectedly
        mock_portfolio = MagicMock()
        mock_portfolio.apply_ranked_opportunities.side_effect = RuntimeError("boom")
        mock_broker = MagicMock()
        mock_broker.ping.return_value = True

        result = run_paper_trading_cycle(
            app_state=state, settings=settings, broker=mock_broker,
            portfolio_svc=mock_portfolio,
        )

        assert result["status"] == "error"
        assert any("fatal" in e for e in result["errors"])


# =============================================================================
# TestApiAppStateNewFields
# =============================================================================

class TestApiAppStateNewFields:
    def test_broker_adapter_defaults_none(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert state.broker_adapter is None

    def test_paper_loop_active_defaults_false(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert state.paper_loop_active is False

    def test_last_paper_cycle_at_defaults_none(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert state.last_paper_cycle_at is None

    def test_paper_cycle_results_defaults_empty(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert state.paper_cycle_results == []

    def test_can_set_broker_adapter(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        mock = MagicMock()
        state.broker_adapter = mock
        assert state.broker_adapter is mock

    def test_can_set_paper_loop_active(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        state.paper_loop_active = True
        assert state.paper_loop_active is True

    def test_can_set_last_paper_cycle_at(self):
        from apps.api.state import ApiAppState
        now = dt.datetime.now(dt.timezone.utc)
        state = ApiAppState()
        state.last_paper_cycle_at = now
        assert state.last_paper_cycle_at == now


# =============================================================================
# TestWorkerSchedulerPaperJobs
# =============================================================================

class TestWorkerSchedulerPaperJobs:
    def test_paper_trading_morning_job_registered(self):
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        job_ids = [j.id for j in scheduler.get_jobs()]
        assert "paper_trading_cycle_morning" in job_ids

    def test_paper_trading_midday_job_registered(self):
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        job_ids = [j.id for j in scheduler.get_jobs()]
        assert "paper_trading_cycle_midday" in job_ids

    def test_total_job_count_increased(self):
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        # Phase 9 had 9 jobs; Phase 12 adds 2 more → at least 11
        assert len(scheduler.get_jobs()) >= 11


# =============================================================================
# TestWorkerJobsExports
# =============================================================================

class TestWorkerJobsExports:
    def test_paper_trading_cycle_exported(self):
        from apps.worker.jobs import run_paper_trading_cycle
        assert callable(run_paper_trading_cycle)

    def test_all_original_jobs_still_exported(self):
        from apps.worker import jobs
        expected = [
            "run_market_data_ingestion", "run_feature_refresh",
            "run_signal_generation", "run_ranking_generation",
            "run_daily_evaluation", "run_attribution_analysis",
            "run_generate_daily_report", "run_publish_operator_summary",
            "run_generate_improvement_proposals", "run_paper_trading_cycle",
        ]
        for name in expected:
            assert hasattr(jobs, name), f"Missing export: {name}"


# =============================================================================
# TestSchwabAdapterImport
# =============================================================================

class TestSchwabAdapterImport:
    def test_module_importable(self):
        from broker_adapters.schwab import adapter  # noqa: F401

    def test_class_importable(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        assert SchwabBrokerAdapter is not None

    def test_package_exports_class(self):
        from broker_adapters.schwab import SchwabBrokerAdapter
        assert SchwabBrokerAdapter is not None

    def test_inherits_base_adapter(self):
        from broker_adapters.base.adapter import BaseBrokerAdapter
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        assert issubclass(SchwabBrokerAdapter, BaseBrokerAdapter)


# =============================================================================
# TestSchwabAdapterConstruction
# =============================================================================

class TestSchwabAdapterConstruction:
    def _adapter(self, **kwargs) -> Any:
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        defaults = dict(api_key="test-key", app_secret="test-secret")
        defaults.update(kwargs)
        return SchwabBrokerAdapter(**defaults)

    def test_adapter_name_paper(self):
        adapter = self._adapter(paper=True)
        assert adapter.adapter_name == "schwab_paper"

    def test_adapter_name_live(self):
        adapter = self._adapter(paper=False)
        assert adapter.adapter_name == "schwab"

    def test_paper_default_true(self):
        adapter = self._adapter()
        assert adapter._paper is True

    def test_empty_api_key_raises(self):
        from broker_adapters.base.exceptions import BrokerAuthenticationError
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        with pytest.raises(BrokerAuthenticationError):
            SchwabBrokerAdapter(api_key="", app_secret="secret")

    def test_whitespace_api_key_raises(self):
        from broker_adapters.base.exceptions import BrokerAuthenticationError
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        with pytest.raises(BrokerAuthenticationError):
            SchwabBrokerAdapter(api_key="   ", app_secret="secret")

    def test_empty_app_secret_raises(self):
        from broker_adapters.base.exceptions import BrokerAuthenticationError
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        with pytest.raises(BrokerAuthenticationError):
            SchwabBrokerAdapter(api_key="key", app_secret="")

    def test_connected_defaults_false(self):
        adapter = self._adapter()
        assert adapter._connected is False

    def test_idempotency_set_starts_empty(self):
        adapter = self._adapter()
        assert len(adapter._idempotency_keys) == 0

    def test_token_path_configurable(self):
        adapter = self._adapter(token_path="my_token.json")
        assert adapter._token_path == "my_token.json"

    def test_account_hash_optional(self):
        adapter = self._adapter(account_hash="ABC123")
        assert adapter._account_hash == "ABC123"


# =============================================================================
# TestSchwabAdapterMethodStubs
# =============================================================================

class TestSchwabAdapterMethodStubs:
    """Phase 14 update: methods are now concrete; they raise BrokerConnectionError
    when called without first connecting (not NotImplementedError)."""

    def _adapter(self) -> Any:
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        return SchwabBrokerAdapter(api_key="key", app_secret="secret")

    def test_connect_raises_auth_error_on_missing_token_file(self):
        from broker_adapters.base.exceptions import BrokerAuthenticationError
        with pytest.raises(BrokerAuthenticationError):
            with patch("schwab.auth.client_from_token_file", side_effect=FileNotFoundError("missing")):
                self._adapter().connect()

    def test_disconnect_is_safe_when_not_connected(self):
        """disconnect() on an unconnected adapter must not raise."""
        self._adapter().disconnect()  # should be a no-op

    def test_ping_returns_false_when_not_connected(self):
        assert self._adapter().ping() is False

    def test_get_account_state_raises_connection_error(self):
        from broker_adapters.base.exceptions import BrokerConnectionError
        with pytest.raises(BrokerConnectionError):
            self._adapter().get_account_state()

    def test_cancel_order_raises_connection_error(self):
        from broker_adapters.base.exceptions import BrokerConnectionError
        with pytest.raises(BrokerConnectionError):
            self._adapter().cancel_order("ord-123")

    def test_get_order_raises_connection_error(self):
        from broker_adapters.base.exceptions import BrokerConnectionError
        with pytest.raises(BrokerConnectionError):
            self._adapter().get_order("ord-123")

    def test_list_open_orders_raises_connection_error(self):
        from broker_adapters.base.exceptions import BrokerConnectionError
        with pytest.raises(BrokerConnectionError):
            self._adapter().list_open_orders()

    def test_get_position_raises_connection_error(self):
        from broker_adapters.base.exceptions import BrokerConnectionError
        with pytest.raises(BrokerConnectionError):
            self._adapter().get_position("AAPL")

    def test_list_positions_raises_connection_error(self):
        from broker_adapters.base.exceptions import BrokerConnectionError
        with pytest.raises(BrokerConnectionError):
            self._adapter().list_positions()

    def test_get_fills_for_order_raises_connection_error(self):
        from broker_adapters.base.exceptions import BrokerConnectionError
        with pytest.raises(BrokerConnectionError):
            self._adapter().get_fills_for_order("ord-123")

    def test_list_fills_since_raises_connection_error(self):
        from broker_adapters.base.exceptions import BrokerConnectionError
        with pytest.raises(BrokerConnectionError):
            self._adapter().list_fills_since(dt.datetime.now(dt.timezone.utc))

    def test_is_market_open_raises_connection_error(self):
        from broker_adapters.base.exceptions import BrokerConnectionError
        with pytest.raises(BrokerConnectionError):
            self._adapter().is_market_open()

    def test_next_market_open_raises_connection_error(self):
        from broker_adapters.base.exceptions import BrokerConnectionError
        with pytest.raises(BrokerConnectionError):
            self._adapter().next_market_open()


# =============================================================================
# TestSchwabAdapterDuplicateGuard
# =============================================================================

class TestSchwabAdapterDuplicateGuard:
    def test_place_order_duplicate_key_raises(self):
        from broker_adapters.base.exceptions import DuplicateOrderError
        from broker_adapters.base.models import OrderRequest, OrderSide, OrderType
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter

        adapter = SchwabBrokerAdapter(api_key="k", app_secret="s", account_hash="H")
        # Must be connected so _require_connected() passes before duplicate check
        adapter._connected = True
        adapter._client = MagicMock()
        # Pre-seed idempotency key as if the order was already placed
        adapter._idempotency_keys.add("key-001")

        req = OrderRequest(
            idempotency_key="key-001",
            ticker="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("10"),
        )
        with pytest.raises(DuplicateOrderError):
            adapter.place_order(req)

    def test_place_order_new_key_raises_connection_error(self):
        """A new key passes the duplicate guard but raises BrokerConnectionError when not connected."""
        from broker_adapters.base.exceptions import BrokerConnectionError
        from broker_adapters.base.models import OrderRequest, OrderSide, OrderType
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter

        adapter = SchwabBrokerAdapter(api_key="k", app_secret="s")
        req = OrderRequest(
            idempotency_key="key-new",
            ticker="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("10"),
        )
        with pytest.raises(BrokerConnectionError):
            adapter.place_order(req)


# =============================================================================
# TestMetricsRoute
# =============================================================================

class TestMetricsRoute:
    def _client(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        return TestClient(app)

    def test_metrics_returns_200(self):
        client = self._client()
        resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_metrics_content_type_text(self):
        client = self._client()
        resp = client.get("/metrics")
        assert "text/plain" in resp.headers["content-type"]

    def test_metrics_contains_kill_switch(self):
        client = self._client()
        resp = client.get("/metrics")
        assert "apis_kill_switch_active" in resp.text

    def test_metrics_contains_operating_mode(self):
        client = self._client()
        resp = client.get("/metrics")
        assert "apis_operating_mode" in resp.text

    def test_metrics_contains_portfolio_positions(self):
        client = self._client()
        resp = client.get("/metrics")
        assert "apis_portfolio_positions" in resp.text

    def test_metrics_contains_portfolio_equity(self):
        client = self._client()
        resp = client.get("/metrics")
        assert "apis_portfolio_equity_usd" in resp.text

    def test_metrics_contains_portfolio_cash(self):
        client = self._client()
        resp = client.get("/metrics")
        assert "apis_portfolio_cash_usd" in resp.text

    def test_metrics_contains_ranking_count(self):
        client = self._client()
        resp = client.get("/metrics")
        assert "apis_latest_ranking_count" in resp.text

    def test_metrics_contains_paper_loop_active(self):
        client = self._client()
        resp = client.get("/metrics")
        assert "apis_paper_loop_active" in resp.text

    def test_metrics_contains_improvement_proposals(self):
        client = self._client()
        resp = client.get("/metrics")
        assert "apis_improvement_proposal_count" in resp.text

    def test_metrics_contains_evaluation_history(self):
        client = self._client()
        resp = client.get("/metrics")
        assert "apis_evaluation_history_count" in resp.text

    def test_metrics_has_help_lines(self):
        client = self._client()
        resp = client.get("/metrics")
        assert "# HELP" in resp.text

    def test_metrics_has_type_lines(self):
        client = self._client()
        resp = client.get("/metrics")
        assert "# TYPE" in resp.text

    def test_metrics_kill_switch_zero_when_off(self):
        client = self._client()
        resp = client.get("/metrics")
        # Default kill_switch is False → should see 0
        lines = resp.text.splitlines()
        for line in lines:
            if line.startswith("apis_kill_switch_active "):
                value = line.split()[-2]  # value is second-to-last (after timestamp)
                assert value == "0"
                break
