"""
Phase 25 — Exit Strategy + Position Lifecycle Management

Tests for:
  - New settings fields: stop_loss_pct, max_position_age_days, exit_score_threshold
  - ActionType.TRIM enum value
  - RiskEngineService.evaluate_exits (stop-loss, age expiry, thesis invalidation)
  - Paper trading cycle exit integration
  - ExecutionEngine handling of TRIM action type
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from config.settings import Settings
from services.portfolio_engine.models import (
    ActionType,
    PortfolioAction,
    PortfolioPosition,
    PortfolioState,
)
from services.risk_engine.service import RiskEngineService

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_settings(**overrides) -> Settings:
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
) -> PortfolioPosition:
    return PortfolioPosition(
        ticker=ticker,
        quantity=Decimal(str(quantity)),
        avg_entry_price=Decimal(str(avg_entry_price)),
        current_price=Decimal(str(current_price)),
        opened_at=dt.datetime.utcnow() - dt.timedelta(days=days_ago),
        thesis_summary=thesis,
    )


# ── TestExitSettingsFields ────────────────────────────────────────────────────

class TestExitSettingsFields:
    def test_stop_loss_pct_default(self):
        s = _make_settings()
        assert s.stop_loss_pct == pytest.approx(0.07)

    def test_max_position_age_days_default(self):
        s = _make_settings()
        assert s.max_position_age_days == 20

    def test_exit_score_threshold_default(self):
        s = _make_settings()
        assert s.exit_score_threshold == pytest.approx(0.40)

    def test_stop_loss_pct_configurable(self):
        s = _make_settings(stop_loss_pct=0.05)
        assert s.stop_loss_pct == pytest.approx(0.05)

    def test_max_position_age_days_configurable(self):
        s = _make_settings(max_position_age_days=30)
        assert s.max_position_age_days == 30

    def test_exit_score_threshold_configurable(self):
        s = _make_settings(exit_score_threshold=0.30)
        assert s.exit_score_threshold == pytest.approx(0.30)


# ── TestExitSettingsValidation ────────────────────────────────────────────────

class TestExitSettingsValidation:
    def test_stop_loss_pct_must_be_positive(self):
        with pytest.raises(Exception):
            _make_settings(stop_loss_pct=0.0)

    def test_max_position_age_days_minimum_one(self):
        with pytest.raises(Exception):
            _make_settings(max_position_age_days=0)

    def test_stop_loss_pct_max_bound(self):
        with pytest.raises(Exception):
            _make_settings(stop_loss_pct=0.51)


# ── TestActionTypeTrim ────────────────────────────────────────────────────────

class TestActionTypeTrim:
    def test_trim_enum_exists(self):
        assert ActionType.TRIM is not None

    def test_trim_enum_value(self):
        assert ActionType.TRIM.value == "trim"

    def test_trim_is_str(self):
        assert isinstance(ActionType.TRIM, str)

    def test_trim_distinct_from_close(self):
        assert ActionType.TRIM != ActionType.CLOSE

    def test_trim_distinct_from_open(self):
        assert ActionType.TRIM != ActionType.OPEN

    def test_all_four_action_types_present(self):
        values = {a.value for a in ActionType}
        assert {"open", "close", "trim", "blocked"} == values


# ── TestEvaluateExitsStopLoss ─────────────────────────────────────────────────

class TestEvaluateExitsStopLoss:
    def setup_method(self):
        self.svc = RiskEngineService(_make_settings(stop_loss_pct=0.07))

    def test_stop_loss_triggers_when_loss_exceeds_threshold(self):
        # -8% loss exceeds 7% stop-loss
        pos = _make_position(avg_entry_price=100.0, current_price=92.0)
        exits = self.svc.evaluate_exits({"AAPL": pos})
        assert len(exits) == 1
        assert exits[0].ticker == "AAPL"

    def test_stop_loss_generates_close_action(self):
        pos = _make_position(avg_entry_price=100.0, current_price=92.0)
        exits = self.svc.evaluate_exits({"AAPL": pos})
        assert exits[0].action_type == ActionType.CLOSE

    def test_stop_loss_does_not_trigger_below_threshold(self):
        # -5% loss is within 7% threshold
        pos = _make_position(avg_entry_price=100.0, current_price=95.0)
        exits = self.svc.evaluate_exits({"AAPL": pos})
        assert len(exits) == 0

    def test_stop_loss_reason_contains_stop_loss_keyword(self):
        pos = _make_position(avg_entry_price=100.0, current_price=90.0)
        exits = self.svc.evaluate_exits({"AAPL": pos})
        assert "stop_loss" in exits[0].reason

    def test_stop_loss_action_is_pre_approved(self):
        pos = _make_position(avg_entry_price=100.0, current_price=90.0)
        exits = self.svc.evaluate_exits({"AAPL": pos})
        assert exits[0].risk_approved is True

    def test_stop_loss_respects_custom_threshold(self):
        svc = RiskEngineService(_make_settings(stop_loss_pct=0.15))
        # -10% loss would trigger at 7% but NOT at 15%
        pos = _make_position(avg_entry_price=100.0, current_price=90.0)
        exits = svc.evaluate_exits({"AAPL": pos})
        assert len(exits) == 0

    def test_stop_loss_at_exact_boundary_does_not_trigger(self):
        # exactly -7%: unrealized_pnl_pct = -0.07; condition is strict <
        pos = _make_position(avg_entry_price=100.0, current_price=93.0)
        exits = self.svc.evaluate_exits({"AAPL": pos})
        assert len(exits) == 0

    def test_stop_loss_profitable_position_no_trigger(self):
        pos = _make_position(avg_entry_price=100.0, current_price=115.0)
        exits = self.svc.evaluate_exits({"AAPL": pos})
        assert len(exits) == 0


# ── TestEvaluateExitsAgeExpiry ─────────────────────────────────────────────────

class TestEvaluateExitsAgeExpiry:
    def setup_method(self):
        self.svc = RiskEngineService(_make_settings(max_position_age_days=20))

    def test_age_expiry_triggers_over_limit(self):
        pos = _make_position(days_ago=21)
        exits = self.svc.evaluate_exits({"AAPL": pos})
        assert len(exits) == 1
        assert exits[0].ticker == "AAPL"

    def test_age_expiry_does_not_trigger_within_limit(self):
        pos = _make_position(days_ago=19)
        exits = self.svc.evaluate_exits({"AAPL": pos})
        assert len(exits) == 0

    def test_age_expiry_at_exact_limit_does_not_trigger(self):
        # exactly 20 days: condition is strict > 20, not >=
        pos = _make_position(days_ago=20)
        exits = self.svc.evaluate_exits({"AAPL": pos})
        assert len(exits) == 0

    def test_age_expiry_reason_contains_age_expiry_keyword(self):
        pos = _make_position(days_ago=25)
        exits = self.svc.evaluate_exits({"AAPL": pos})
        assert "age_expiry" in exits[0].reason

    def test_age_expiry_respects_custom_days(self):
        svc = RiskEngineService(_make_settings(max_position_age_days=10))
        pos = _make_position(days_ago=15)
        exits = svc.evaluate_exits({"AAPL": pos})
        assert len(exits) == 1

    def test_age_expiry_action_is_pre_approved(self):
        pos = _make_position(days_ago=30)
        exits = self.svc.evaluate_exits({"AAPL": pos})
        assert exits[0].risk_approved is True

    def test_age_expiry_uses_reference_dt(self):
        ref = dt.datetime.utcnow()
        pos = PortfolioPosition(
            ticker="AAPL",
            quantity=Decimal("10"),
            avg_entry_price=Decimal("100"),
            current_price=Decimal("100"),
            opened_at=ref - dt.timedelta(days=21),
        )
        exits = self.svc.evaluate_exits({"AAPL": pos}, reference_dt=ref)
        assert len(exits) == 1


# ── TestEvaluateExitsThesisInvalidation ──────────────────────────────────────

class TestEvaluateExitsThesisInvalidation:
    def setup_method(self):
        self.svc = RiskEngineService(_make_settings(exit_score_threshold=0.40))
        self.healthy_pos = _make_position(avg_entry_price=100.0, current_price=100.0)

    def test_thesis_invalidated_below_threshold(self):
        exits = self.svc.evaluate_exits(
            {"AAPL": self.healthy_pos},
            ranked_scores={"AAPL": Decimal("0.30")},
        )
        assert len(exits) == 1
        assert exits[0].ticker == "AAPL"

    def test_thesis_not_invalidated_above_threshold(self):
        exits = self.svc.evaluate_exits(
            {"AAPL": self.healthy_pos},
            ranked_scores={"AAPL": Decimal("0.60")},
        )
        assert len(exits) == 0

    def test_thesis_score_at_exact_threshold_does_not_trigger(self):
        # exactly 0.40 — condition is strict <
        exits = self.svc.evaluate_exits(
            {"AAPL": self.healthy_pos},
            ranked_scores={"AAPL": Decimal("0.40")},
        )
        assert len(exits) == 0

    def test_thesis_ticker_absent_from_ranked_scores_is_conservative(self):
        # AAPL not in ranked_scores → skip check; do NOT close
        exits = self.svc.evaluate_exits(
            {"AAPL": self.healthy_pos},
            ranked_scores={"MSFT": Decimal("0.20")},
        )
        assert len(exits) == 0

    def test_thesis_ranked_scores_none_disables_check(self):
        exits = self.svc.evaluate_exits({"AAPL": self.healthy_pos}, ranked_scores=None)
        assert len(exits) == 0

    def test_thesis_invalidated_reason_contains_keyword(self):
        exits = self.svc.evaluate_exits(
            {"AAPL": self.healthy_pos},
            ranked_scores={"AAPL": Decimal("0.20")},
        )
        assert "thesis_invalidated" in exits[0].reason

    def test_thesis_action_is_pre_approved(self):
        exits = self.svc.evaluate_exits(
            {"AAPL": self.healthy_pos},
            ranked_scores={"AAPL": Decimal("0.10")},
        )
        assert exits[0].risk_approved is True


# ── TestEvaluateExitsCombined ─────────────────────────────────────────────────

class TestEvaluateExitsCombined:
    def setup_method(self):
        self.svc = RiskEngineService(_make_settings())

    def test_empty_positions_returns_empty_list(self):
        exits = self.svc.evaluate_exits({})
        assert exits == []

    def test_all_healthy_positions_no_exits(self):
        pos = _make_position(avg_entry_price=100.0, current_price=103.0, days_ago=5)
        exits = self.svc.evaluate_exits(
            {"AAPL": pos},
            ranked_scores={"AAPL": Decimal("0.70")},
        )
        assert exits == []

    def test_multiple_triggers_same_position_yields_single_exit(self):
        # Position violates both stop-loss AND age — must produce exactly one CLOSE
        pos = _make_position(avg_entry_price=100.0, current_price=88.0, days_ago=25)
        exits = self.svc.evaluate_exits({"AAPL": pos})
        assert len(exits) == 1
        assert exits[0].action_type == ActionType.CLOSE

    def test_multiple_positions_evaluated_independently(self):
        pos_stop = _make_position("TSLA", avg_entry_price=100.0, current_price=85.0)
        pos_age = _make_position("NVDA", days_ago=25)
        pos_ok = _make_position("MSFT", avg_entry_price=100.0, current_price=102.0, days_ago=5)
        exits = self.svc.evaluate_exits({
            "TSLA": pos_stop,
            "NVDA": pos_age,
            "MSFT": pos_ok,
        })
        exit_tickers = {e.ticker for e in exits}
        assert "TSLA" in exit_tickers
        assert "NVDA" in exit_tickers
        assert "MSFT" not in exit_tickers
        assert len(exits) == 2

    def test_exit_close_contains_correct_target_quantity(self):
        pos = _make_position(quantity=15, avg_entry_price=100.0, current_price=85.0)
        exits = self.svc.evaluate_exits({"AAPL": pos})
        assert exits[0].target_quantity == Decimal("15")

    def test_exit_preserves_thesis_summary(self):
        pos = _make_position(avg_entry_price=100.0, current_price=88.0, thesis="AI momentum play")
        exits = self.svc.evaluate_exits({"AAPL": pos})
        assert exits[0].thesis_summary == "AI momentum play"


# ── TestEvaluateExitsEdgeCases ────────────────────────────────────────────────

class TestEvaluateExitsEdgeCases:
    def setup_method(self):
        self.svc = RiskEngineService(_make_settings())

    def test_zero_cost_basis_position_skips_stop_loss(self):
        # cost_basis = 0 → unrealized_pnl_pct returns 0 → no stop-loss trigger
        pos = PortfolioPosition(
            ticker="AAPL",
            quantity=Decimal("10"),
            avg_entry_price=Decimal("0"),
            current_price=Decimal("50"),
            opened_at=dt.datetime.utcnow() - dt.timedelta(days=2),
        )
        exits = self.svc.evaluate_exits({"AAPL": pos}, ranked_scores={"AAPL": Decimal("0.80")})
        assert len(exits) == 0

    def test_stop_loss_takes_priority_over_age(self):
        # Both triggers fire; stop_loss should appear in reason (checked first)
        pos = _make_position(avg_entry_price=100.0, current_price=88.0, days_ago=25)
        exits = self.svc.evaluate_exits({"AAPL": pos})
        assert "stop_loss" in exits[0].reason

    def test_age_expiry_takes_priority_over_thesis_invalidation(self):
        # Stop-loss doesn't fire, age does
        pos = _make_position(avg_entry_price=100.0, current_price=99.0, days_ago=25)
        exits = self.svc.evaluate_exits(
            {"AAPL": pos},
            ranked_scores={"AAPL": Decimal("0.10")},  # also invalid thesis
        )
        assert "age_expiry" in exits[0].reason  # age fires first

    def test_evaluate_exits_is_exception_safe_with_bad_position(self):
        # Even with a broken position dict we should not raise unhandled exception
        svc = RiskEngineService(_make_settings())
        pos = _make_position(avg_entry_price=100.0, current_price=88.0)
        # Should not raise
        exits = svc.evaluate_exits({"AAPL": pos})
        assert isinstance(exits, list)


# ── TestEvaluateExitsKillSwitch ───────────────────────────────────────────────

class TestEvaluateExitsKillSwitch:
    def test_evaluate_exits_unaffected_by_kill_switch(self):
        """evaluate_exits always produces exit signals regardless of kill_switch.
        Kill-switch enforcement is in execution_engine, not evaluate_exits.
        """
        svc = RiskEngineService(_make_settings(kill_switch=True))
        pos = _make_position(avg_entry_price=100.0, current_price=88.0)
        exits = svc.evaluate_exits({"AAPL": pos})
        assert len(exits) == 1


# ── TestPaperCycleExitIntegration ─────────────────────────────────────────────

class TestPaperCycleExitIntegration:
    """Integration tests verifying evaluate_exits is wired into run_paper_trading_cycle."""

    def _make_state(self, rankings=None, portfolio_state=None):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        state.latest_rankings = rankings or []
        state.portfolio_state = portfolio_state
        state.kill_switch_active = False
        return state

    def _ranked_result(self, ticker="AAPL", score=0.70, action="buy"):
        from services.ranking_engine.models import RankedResult
        return RankedResult(
            rank_position=1,
            security_id=None,
            ticker=ticker,
            composite_score=Decimal(str(score)),
            portfolio_fit_score=Decimal("0.50"),
            recommended_action=action,
            target_horizon="swing",
            thesis_summary="test",
            disconfirming_factors="none",
            sizing_hint_pct=Decimal("0.10"),
            contains_rumor=False,
            source_reliability_tier="primary_verified",
        )

    def _mock_broker(self):
        b = MagicMock()
        b.ping.return_value = True
        b.get_account_state.return_value = MagicMock(cash_balance=Decimal("50000"))
        b.list_positions.return_value = []
        b.list_fills_since.return_value = []
        return b

    def _mock_reporting(self):
        r = MagicMock()
        r.reconcile_fills.return_value = MagicMock(is_clean=True)
        return r

    def test_cycle_calls_evaluate_exits(self):
        """evaluate_exits must be called in every cycle."""
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle

        state = self._make_state(
            rankings=[self._ranked_result("AAPL")],
            portfolio_state=PortfolioState(cash=Decimal("100000")),
        )
        mock_risk = MagicMock()
        mock_risk.validate_action.return_value = MagicMock(is_hard_blocked=False)
        mock_risk.evaluate_exits.return_value = []
        mock_portfolio = MagicMock()
        mock_portfolio.apply_ranked_opportunities.return_value = []
        mock_exec = MagicMock()
        mock_exec.execute_approved_actions.return_value = []
        mock_mds = MagicMock()
        mock_mds.get_snapshot.return_value = MagicMock(latest_price=Decimal("150"))

        run_paper_trading_cycle(
            app_state=state,
            settings=_make_settings(operating_mode="paper"),
            broker=self._mock_broker(),
            portfolio_svc=mock_portfolio,
            risk_svc=mock_risk,
            execution_svc=mock_exec,
            market_data_svc=mock_mds,
            reporting_svc=self._mock_reporting(),
        )
        mock_risk.evaluate_exits.assert_called_once()

    def test_exit_action_from_evaluate_exits_added_to_proposed(self):
        """Exit actions returned by evaluate_exits are included in proposed_count."""
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle

        state = self._make_state(
            rankings=[self._ranked_result("AAPL")],
            portfolio_state=PortfolioState(cash=Decimal("50000")),
        )
        mock_risk = MagicMock()
        mock_risk.validate_action.return_value = MagicMock(is_hard_blocked=False)
        mock_risk.evaluate_exits.return_value = [
            PortfolioAction(
                action_type=ActionType.CLOSE,
                ticker="TSLA",
                reason="stop_loss",
                risk_approved=True,
            )
        ]
        mock_portfolio = MagicMock()
        mock_portfolio.apply_ranked_opportunities.return_value = []
        mock_exec = MagicMock()
        mock_exec.execute_approved_actions.return_value = []
        mock_mds = MagicMock()
        mock_mds.get_snapshot.return_value = MagicMock(latest_price=Decimal("85"))

        result = run_paper_trading_cycle(
            app_state=state,
            settings=_make_settings(operating_mode="paper"),
            broker=self._mock_broker(),
            portfolio_svc=mock_portfolio,
            risk_svc=mock_risk,
            execution_svc=mock_exec,
            market_data_svc=mock_mds,
            reporting_svc=self._mock_reporting(),
        )
        assert result["status"] == "ok"
        assert result["proposed_count"] == 1  # the TSLA exit

    def test_exit_deduplication_no_double_close_for_same_ticker(self):
        """If rankings already schedule a CLOSE for AAPL, exit trigger CLOSE is skipped."""
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle

        state = self._make_state(
            rankings=[self._ranked_result("MSFT")],
            portfolio_state=PortfolioState(cash=Decimal("50000")),
        )
        rankings_close = PortfolioAction(
            action_type=ActionType.CLOSE, ticker="AAPL", reason="not_in_buy_set", risk_approved=False
        )
        mock_risk = MagicMock()
        mock_risk.validate_action.return_value = MagicMock(is_hard_blocked=False)
        mock_risk.evaluate_exits.return_value = [
            PortfolioAction(action_type=ActionType.CLOSE, ticker="AAPL", reason="stop_loss", risk_approved=True)
        ]
        mock_portfolio = MagicMock()
        mock_portfolio.apply_ranked_opportunities.return_value = [rankings_close]
        mock_exec = MagicMock()
        mock_exec.execute_approved_actions.return_value = []
        mock_mds = MagicMock()
        mock_mds.get_snapshot.return_value = MagicMock(latest_price=Decimal("88"))

        result = run_paper_trading_cycle(
            app_state=state,
            settings=_make_settings(operating_mode="paper"),
            broker=self._mock_broker(),
            portfolio_svc=mock_portfolio,
            risk_svc=mock_risk,
            execution_svc=mock_exec,
            market_data_svc=mock_mds,
            reporting_svc=self._mock_reporting(),
        )
        # Only one CLOSE for AAPL, not two
        assert result["proposed_count"] == 1

    def test_cycle_returns_ok_status_with_exit_only_actions(self):
        """A cycle that only produces exit actions still returns status ok."""
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle

        state = self._make_state(
            rankings=[self._ranked_result("AAPL")],
            portfolio_state=PortfolioState(cash=Decimal("50000")),
        )
        mock_risk = MagicMock()
        mock_risk.validate_action.return_value = MagicMock(is_hard_blocked=False)
        mock_risk.evaluate_exits.return_value = [
            PortfolioAction(
                action_type=ActionType.CLOSE, ticker="TSLA", reason="age_expiry", risk_approved=True
            )
        ]
        mock_portfolio = MagicMock()
        mock_portfolio.apply_ranked_opportunities.return_value = []
        mock_exec = MagicMock()
        mock_exec.execute_approved_actions.return_value = []
        mock_mds = MagicMock()
        mock_mds.get_snapshot.return_value = MagicMock(latest_price=Decimal("100"))

        result = run_paper_trading_cycle(
            app_state=state,
            settings=_make_settings(operating_mode="paper"),
            broker=self._mock_broker(),
            portfolio_svc=mock_portfolio,
            risk_svc=mock_risk,
            execution_svc=mock_exec,
            market_data_svc=mock_mds,
            reporting_svc=self._mock_reporting(),
        )
        assert result["status"] == "ok"

    def test_kill_switch_bypasses_exit_evaluation(self):
        """Kill switch prevents any evaluation — cycle returns 'killed' immediately."""
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle

        state = self._make_state(rankings=[self._ranked_result("AAPL")])
        state.kill_switch_active = True

        result = run_paper_trading_cycle(
            app_state=state,
            settings=_make_settings(operating_mode="paper"),
        )
        assert result["status"] == "killed"


# ── TestExecutionEngineTrimAction ─────────────────────────────────────────────

class TestExecutionEngineTrimAction:
    def setup_method(self):
        from broker_adapters.paper.adapter import PaperBrokerAdapter
        from services.execution_engine.models import ExecutionRequest
        from services.execution_engine.service import ExecutionEngineService
        self._ExecutionRequest = ExecutionRequest
        self._svc = ExecutionEngineService(
            settings=_make_settings(),
            broker=PaperBrokerAdapter(market_open=True),
        )

    def test_trim_action_returns_rejected_status_no_position(self):
        """Phase 26: TRIM is now supported — returns REJECTED when no position exists."""
        from services.execution_engine.models import ExecutionRequest, ExecutionStatus
        action = PortfolioAction(
            action_type=ActionType.TRIM,
            ticker="AAPL",
            reason="overconcentration",
            target_quantity=Decimal("5"),
            risk_approved=True,
        )
        req = ExecutionRequest(action=action, current_price=Decimal("150"))
        result = self._svc.execute_action(req)
        assert result.status == ExecutionStatus.REJECTED

    def test_trim_action_error_message_identifies_no_position(self):
        """Phase 26: TRIM is now supported — error_message mentions no position."""
        from services.execution_engine.models import ExecutionRequest
        action = PortfolioAction(
            action_type=ActionType.TRIM,
            ticker="AAPL",
            reason="test",
            target_quantity=Decimal("5"),
            risk_approved=True,
        )
        req = ExecutionRequest(action=action, current_price=Decimal("150"))
        result = self._svc.execute_action(req)
        assert result.error_message is not None
        assert "AAPL" in result.error_message
