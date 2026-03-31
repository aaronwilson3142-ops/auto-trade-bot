"""
Phase 51 — Live Mode Promotion Gate Enhancement.

Tests for the three new gate checks added to LiveModeGateService:
  1. Sharpe gate     — annualised Sharpe from evaluation_history daily returns
  2. Drawdown state  — blocks promotion when portfolio is in RECOVERY mode
  3. Signal quality  — average strategy win rate from SignalQualityReport

Test classes
------------
  TestSharpeComputation          — _compute_sharpe_from_history static helper
  TestSharpeGatePaperToHA        — Sharpe gate in PAPER → HUMAN_APPROVED context
  TestSharpeGateHAToRL           — Sharpe gate in HUMAN_APPROVED → RESTRICTED_LIVE context
  TestDrawdownGatePaperToHA      — drawdown state gate in PAPER → HUMAN_APPROVED context
  TestDrawdownGateHAToRL         — drawdown state gate in HUMAN_APPROVED → RESTRICTED_LIVE context
  TestSignalQualityGatePaperToHA — signal quality gate in PAPER → HUMAN_APPROVED context
  TestSignalQualityGateHAToRL    — signal quality gate in HUMAN_APPROVED → RESTRICTED_LIVE context
  TestFullGateIntegration        — end-to-end check_prerequisites with new gates wired in
  TestNewGatesDoNotBreakExisting — existing gate tests still hold after Phase 51 additions
"""
from __future__ import annotations

import math
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest


# ── Reset shared state between tests ──────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_app_state():
    from apps.api.state import reset_app_state
    reset_app_state()
    yield
    reset_app_state()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_scorecard(daily_return_pct: float) -> MagicMock:
    sc = MagicMock()
    sc.daily_return_pct = Decimal(str(daily_return_pct))
    return sc


def _make_strategy_result(win_rate: float) -> MagicMock:
    sr = MagicMock()
    sr.win_rate = win_rate
    return sr


def _make_quality_report(win_rates: list[float]) -> MagicMock:
    report = MagicMock()
    report.strategy_results = [_make_strategy_result(wr) for wr in win_rates]
    return report


def _make_minimal_app_state(
    *,
    paper_cycle_count: int = 10,
    evaluation_history: list | None = None,
    portfolio_state: Any = object(),
    paper_cycle_results: list | None = None,
    latest_rankings: list | None = None,
    drawdown_state: str = "NORMAL",
    latest_signal_quality: Any = None,
    kill_switch_active: bool = False,
) -> MagicMock:
    """Build a minimal app_state mock suitable for gate testing."""
    state = MagicMock()
    state.paper_cycle_count = paper_cycle_count
    state.evaluation_history = evaluation_history if evaluation_history is not None else []
    state.portfolio_state = portfolio_state
    state.paper_cycle_results = paper_cycle_results if paper_cycle_results is not None else []
    state.latest_rankings = latest_rankings if latest_rankings is not None else [object()]
    state.drawdown_state = drawdown_state
    state.latest_signal_quality = latest_signal_quality
    state.kill_switch_active = kill_switch_active
    return state


def _make_settings(kill_switch: bool = False) -> MagicMock:
    s = MagicMock()
    s.kill_switch = kill_switch
    return s


# =============================================================================
# TestSharpeComputation
# =============================================================================

class TestSharpeComputation:
    """_compute_sharpe_from_history static helper."""

    def test_empty_history_returns_zero_sharpe_and_zero_obs(self):
        from services.live_mode_gate.service import LiveModeGateService
        sharpe, obs = LiveModeGateService._compute_sharpe_from_history([])
        assert sharpe == 0.0
        assert obs == 0

    def test_single_entry_returns_zero_sharpe_and_one_obs(self):
        from services.live_mode_gate.service import LiveModeGateService
        sharpe, obs = LiveModeGateService._compute_sharpe_from_history(
            [_make_scorecard(0.01)]
        )
        assert sharpe == 0.0
        assert obs == 1

    def test_two_identical_returns_zero_std_returns_zero_sharpe(self):
        from services.live_mode_gate.service import LiveModeGateService
        scorecards = [_make_scorecard(0.005)] * 2
        sharpe, obs = LiveModeGateService._compute_sharpe_from_history(scorecards)
        assert sharpe == 0.0
        assert obs == 2

    def test_positive_returns_produce_positive_sharpe(self):
        from services.live_mode_gate.service import LiveModeGateService
        # 10 returns: alternating +1% and +3% — mean=2%, positive Sharpe
        returns = [0.01, 0.03] * 5
        scorecards = [_make_scorecard(r) for r in returns]
        sharpe, obs = LiveModeGateService._compute_sharpe_from_history(scorecards)
        assert obs == 10
        assert sharpe > 0.0

    def test_negative_mean_returns_negative_sharpe(self):
        from services.live_mode_gate.service import LiveModeGateService
        returns = [-0.01, -0.02, -0.015, -0.025, -0.01,
                   -0.02, -0.01, -0.015, -0.02, -0.025]
        scorecards = [_make_scorecard(r) for r in returns]
        sharpe, obs = LiveModeGateService._compute_sharpe_from_history(scorecards)
        assert sharpe < 0.0

    def test_annualisation_factor_applied(self):
        from services.live_mode_gate.service import LiveModeGateService
        # Alternating [0.0, 0.02] → mean=0.01, sample std (Bessel n-1) ≈ 0.01026
        # Sharpe ≈ (0.01 / 0.01026) * sqrt(252) ≈ 15.47
        returns = [0.0, 0.02] * 10  # 20 observations
        scorecards = [_make_scorecard(r) for r in returns]
        sharpe, obs = LiveModeGateService._compute_sharpe_from_history(scorecards)
        n = 20
        mean_r = 0.01
        variance = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
        std_r = math.sqrt(variance)
        expected = round((mean_r / std_r) * math.sqrt(252), 4)
        assert sharpe == expected

    def test_handles_scorecard_with_no_daily_return_attr(self):
        from services.live_mode_gate.service import LiveModeGateService
        sc = MagicMock(spec=[])  # no daily_return_pct attribute
        sharpe, obs = LiveModeGateService._compute_sharpe_from_history([sc])
        assert obs == 0
        assert sharpe == 0.0

    def test_returns_rounded_to_four_decimal_places(self):
        from services.live_mode_gate.service import LiveModeGateService
        returns = [0.01 * i * 0.001 for i in range(1, 21)]
        scorecards = [_make_scorecard(r) for r in returns]
        sharpe, _ = LiveModeGateService._compute_sharpe_from_history(scorecards)
        # round to 4 places
        assert sharpe == round(sharpe, 4)


# =============================================================================
# TestSharpeGatePaperToHA
# =============================================================================

class TestSharpeGatePaperToHA:
    """Sharpe gate in PAPER → HUMAN_APPROVED (threshold = 0.5)."""

    def _run_gate(self, evaluation_history):
        from services.live_mode_gate.service import LiveModeGateService
        from services.live_mode_gate.models import LiveModeGateResult
        svc = LiveModeGateService()
        result = LiveModeGateResult(current_mode="paper", target_mode="human_approved")
        state = MagicMock()
        state.evaluation_history = evaluation_history
        state.drawdown_state = "NORMAL"
        state.latest_signal_quality = None
        svc._check_sharpe_gate(result, state, min_sharpe=0.5)
        return result

    def _get_sharpe_req(self, result):
        reqs = [r for r in result.requirements if r.name == "min_sharpe_estimate"]
        assert len(reqs) == 1
        return reqs[0]

    def test_warn_when_fewer_than_10_observations(self):
        from services.live_mode_gate.models import GateStatus
        history = [_make_scorecard(0.01)] * 5
        result = self._run_gate(history)
        req = self._get_sharpe_req(result)
        assert req.status == GateStatus.WARN

    def test_warn_still_counts_as_passed_not_blocked(self):
        from services.live_mode_gate.models import GateStatus
        history = [_make_scorecard(0.01)] * 9
        result = self._run_gate(history)
        req = self._get_sharpe_req(result)
        assert req.status == GateStatus.WARN
        assert req.passed is True

    def test_pass_when_sharpe_meets_threshold(self):
        from services.live_mode_gate.models import GateStatus
        # 10+ obs with strong positive returns → Sharpe > 0.5
        returns = [0.005, 0.010] * 10
        history = [_make_scorecard(r) for r in returns]
        result = self._run_gate(history)
        req = self._get_sharpe_req(result)
        assert req.status == GateStatus.PASS

    def test_fail_when_sharpe_below_threshold(self):
        from services.live_mode_gate.models import GateStatus
        # tiny mean vs large std → Sharpe < 0.5
        # [0.033, -0.031] * 6 → mean≈0.001, std≈0.032 → Sharpe≈0.5 (borderline low)
        # Use wider spread to ensure below 0.5
        returns = [0.04, -0.038] * 6  # mean≈0.001, std≈0.039 → Sharpe≈0.41
        history = [_make_scorecard(r) for r in returns]
        result = self._run_gate(history)
        req = self._get_sharpe_req(result)
        assert req.status == GateStatus.FAIL

    def test_warn_detail_mentions_observation_count(self):
        history = [_make_scorecard(0.01)] * 3
        result = self._run_gate(history)
        req = self._get_sharpe_req(result)
        assert "3" in req.detail

    def test_required_value_shows_threshold(self):
        history = []
        result = self._run_gate(history)
        req = self._get_sharpe_req(result)
        assert "0.50" in req.required_value

    def test_empty_history_produces_warn(self):
        from services.live_mode_gate.models import GateStatus
        result = self._run_gate([])
        req = self._get_sharpe_req(result)
        assert req.status == GateStatus.WARN


# =============================================================================
# TestSharpeGateHAToRL
# =============================================================================

class TestSharpeGateHAToRL:
    """Sharpe gate in HUMAN_APPROVED → RESTRICTED_LIVE (threshold = 1.0)."""

    def _run_gate(self, evaluation_history):
        from services.live_mode_gate.service import LiveModeGateService
        from services.live_mode_gate.models import LiveModeGateResult
        svc = LiveModeGateService()
        result = LiveModeGateResult(current_mode="human_approved", target_mode="restricted_live")
        state = MagicMock()
        state.evaluation_history = evaluation_history
        state.drawdown_state = "NORMAL"
        state.latest_signal_quality = None
        svc._check_sharpe_gate(result, state, min_sharpe=1.0)
        return result

    def _get_sharpe_req(self, result):
        reqs = [r for r in result.requirements if r.name == "min_sharpe_estimate"]
        assert len(reqs) == 1
        return reqs[0]

    def test_pass_with_high_sharpe(self):
        from services.live_mode_gate.models import GateStatus
        # consistent positive returns → Sharpe well above 1.0
        returns = [0.005, 0.006, 0.005, 0.006, 0.005,
                   0.006, 0.005, 0.006, 0.005, 0.006,
                   0.005, 0.006]
        history = [_make_scorecard(r) for r in returns]
        result = self._run_gate(history)
        req = self._get_sharpe_req(result)
        assert req.status == GateStatus.PASS

    def test_fail_when_sharpe_below_1(self):
        from services.live_mode_gate.models import GateStatus
        # tiny mean vs large std → Sharpe < 1.0
        # [0.033, -0.031] * 6 → mean≈0.001, std≈0.032 → Sharpe≈0.5 < 1.0
        returns = [0.033, -0.031] * 6
        history = [_make_scorecard(r) for r in returns]
        result = self._run_gate(history)
        req = self._get_sharpe_req(result)
        assert req.status == GateStatus.FAIL

    def test_required_value_shows_1_0_threshold(self):
        result = self._run_gate([])
        req = self._get_sharpe_req(result)
        assert "1.00" in req.required_value

    def test_warn_when_insufficient_observations(self):
        from services.live_mode_gate.models import GateStatus
        history = [_make_scorecard(0.02)] * 8
        result = self._run_gate(history)
        req = self._get_sharpe_req(result)
        assert req.status == GateStatus.WARN


# =============================================================================
# TestDrawdownGatePaperToHA
# =============================================================================

class TestDrawdownGatePaperToHA:
    """Drawdown state gate in PAPER → HUMAN_APPROVED context."""

    def _run_gate(self, drawdown_state: str):
        from services.live_mode_gate.service import LiveModeGateService
        from services.live_mode_gate.models import LiveModeGateResult
        svc = LiveModeGateService()
        result = LiveModeGateResult(current_mode="paper", target_mode="human_approved")
        state = MagicMock()
        state.drawdown_state = drawdown_state
        svc._check_drawdown_state_gate(result, state)
        return result

    def _get_req(self, result):
        reqs = [r for r in result.requirements if r.name == "drawdown_state_acceptable"]
        assert len(reqs) == 1
        return reqs[0]

    def test_normal_produces_pass(self):
        from services.live_mode_gate.models import GateStatus
        req = self._get_req(self._run_gate("NORMAL"))
        assert req.status == GateStatus.PASS

    def test_caution_produces_warn(self):
        from services.live_mode_gate.models import GateStatus
        req = self._get_req(self._run_gate("CAUTION"))
        assert req.status == GateStatus.WARN

    def test_caution_warn_counts_as_passed(self):
        req = self._get_req(self._run_gate("CAUTION"))
        assert req.passed is True

    def test_recovery_produces_fail(self):
        from services.live_mode_gate.models import GateStatus
        req = self._get_req(self._run_gate("RECOVERY"))
        assert req.status == GateStatus.FAIL

    def test_recovery_blocks_promotion(self):
        req = self._get_req(self._run_gate("RECOVERY"))
        assert req.passed is False

    def test_recovery_detail_mentions_recovery(self):
        req = self._get_req(self._run_gate("RECOVERY"))
        assert "RECOVERY" in req.detail

    def test_caution_detail_mentions_caution(self):
        req = self._get_req(self._run_gate("CAUTION"))
        assert "CAUTION" in req.detail

    def test_actual_value_reflects_state(self):
        for state_str in ("NORMAL", "CAUTION", "RECOVERY"):
            req = self._get_req(self._run_gate(state_str))
            assert req.actual_value == state_str


# =============================================================================
# TestDrawdownGateHAToRL
# =============================================================================

class TestDrawdownGateHAToRL:
    """Drawdown state gate in HUMAN_APPROVED → RESTRICTED_LIVE context.

    Same gate function — same behaviour regardless of target mode.
    """

    def _run_gate(self, drawdown_state: str):
        from services.live_mode_gate.service import LiveModeGateService
        from services.live_mode_gate.models import LiveModeGateResult
        svc = LiveModeGateService()
        result = LiveModeGateResult(current_mode="human_approved", target_mode="restricted_live")
        state = MagicMock()
        state.drawdown_state = drawdown_state
        svc._check_drawdown_state_gate(result, state)
        return result

    def _get_req(self, result):
        reqs = [r for r in result.requirements if r.name == "drawdown_state_acceptable"]
        assert len(reqs) == 1
        return reqs[0]

    def test_normal_passes_for_restricted_live(self):
        from services.live_mode_gate.models import GateStatus
        req = self._get_req(self._run_gate("NORMAL"))
        assert req.status == GateStatus.PASS

    def test_recovery_fails_for_restricted_live(self):
        from services.live_mode_gate.models import GateStatus
        req = self._get_req(self._run_gate("RECOVERY"))
        assert req.status == GateStatus.FAIL

    def test_caution_warns_for_restricted_live(self):
        from services.live_mode_gate.models import GateStatus
        req = self._get_req(self._run_gate("CAUTION"))
        assert req.status == GateStatus.WARN


# =============================================================================
# TestSignalQualityGatePaperToHA
# =============================================================================

class TestSignalQualityGatePaperToHA:
    """Signal quality gate in PAPER → HUMAN_APPROVED (threshold = 40%)."""

    def _run_gate(self, quality_report):
        from services.live_mode_gate.service import LiveModeGateService
        from services.live_mode_gate.models import LiveModeGateResult
        svc = LiveModeGateService()
        result = LiveModeGateResult(current_mode="paper", target_mode="human_approved")
        state = MagicMock()
        state.latest_signal_quality = quality_report
        svc._check_signal_quality_gate(result, state, min_win_rate=0.40)
        return result

    def _get_req(self, result):
        reqs = [r for r in result.requirements if r.name == "min_signal_quality_win_rate"]
        assert len(reqs) == 1
        return reqs[0]

    def test_warn_when_no_report(self):
        from services.live_mode_gate.models import GateStatus
        req = self._get_req(self._run_gate(None))
        assert req.status == GateStatus.WARN

    def test_no_report_counts_as_passed(self):
        req = self._get_req(self._run_gate(None))
        assert req.passed is True

    def test_warn_when_report_has_no_strategy_results(self):
        from services.live_mode_gate.models import GateStatus
        report = _make_quality_report([])
        req = self._get_req(self._run_gate(report))
        assert req.status == GateStatus.WARN

    def test_pass_when_avg_win_rate_meets_threshold(self):
        from services.live_mode_gate.models import GateStatus
        report = _make_quality_report([0.45, 0.50, 0.42])  # avg = 0.4567
        req = self._get_req(self._run_gate(report))
        assert req.status == GateStatus.PASS

    def test_pass_at_exact_threshold(self):
        from services.live_mode_gate.models import GateStatus
        report = _make_quality_report([0.40, 0.40])
        req = self._get_req(self._run_gate(report))
        assert req.status == GateStatus.PASS

    def test_fail_when_avg_win_rate_below_threshold(self):
        from services.live_mode_gate.models import GateStatus
        report = _make_quality_report([0.30, 0.35, 0.38])  # avg < 0.40
        req = self._get_req(self._run_gate(report))
        assert req.status == GateStatus.FAIL

    def test_actual_value_is_rounded_average(self):
        report = _make_quality_report([0.50, 0.60])  # avg = 0.55
        req = self._get_req(self._run_gate(report))
        assert abs(req.actual_value - 0.55) < 0.0001

    def test_required_value_shows_40_percent(self):
        req = self._get_req(self._run_gate(None))
        assert "40%" in req.required_value

    def test_single_strategy_uses_its_win_rate_directly(self):
        from services.live_mode_gate.models import GateStatus
        report = _make_quality_report([0.55])
        req = self._get_req(self._run_gate(report))
        assert req.status == GateStatus.PASS


# =============================================================================
# TestSignalQualityGateHAToRL
# =============================================================================

class TestSignalQualityGateHAToRL:
    """Signal quality gate in HUMAN_APPROVED → RESTRICTED_LIVE (threshold = 45%)."""

    def _run_gate(self, quality_report):
        from services.live_mode_gate.service import LiveModeGateService
        from services.live_mode_gate.models import LiveModeGateResult
        svc = LiveModeGateService()
        result = LiveModeGateResult(current_mode="human_approved", target_mode="restricted_live")
        state = MagicMock()
        state.latest_signal_quality = quality_report
        svc._check_signal_quality_gate(result, state, min_win_rate=0.45)
        return result

    def _get_req(self, result):
        reqs = [r for r in result.requirements if r.name == "min_signal_quality_win_rate"]
        assert len(reqs) == 1
        return reqs[0]

    def test_pass_at_45_percent(self):
        from services.live_mode_gate.models import GateStatus
        report = _make_quality_report([0.45, 0.50])  # avg = 0.475
        req = self._get_req(self._run_gate(report))
        assert req.status == GateStatus.PASS

    def test_fail_below_45_percent(self):
        from services.live_mode_gate.models import GateStatus
        report = _make_quality_report([0.40, 0.43])  # avg = 0.415 < 0.45
        req = self._get_req(self._run_gate(report))
        assert req.status == GateStatus.FAIL

    def test_required_value_shows_45_percent(self):
        req = self._get_req(self._run_gate(None))
        assert "45%" in req.required_value

    def test_warn_no_data_does_not_block(self):
        req = self._get_req(self._run_gate(None))
        assert req.passed is True


# =============================================================================
# TestFullGateIntegration
# =============================================================================

class TestFullGateIntegration:
    """End-to-end check_prerequisites with all three new gates wired in."""

    def _svc(self):
        from services.live_mode_gate.service import LiveModeGateService
        return LiveModeGateService()

    def _settings(self):
        from config.settings import Settings
        return Settings()

    def test_paper_to_ha_all_pass_when_conditions_ideal(self):
        """All gates pass: cycles, eval history, Sharpe, drawdown NORMAL, quality."""
        from config.settings import OperatingMode
        returns = [0.005, 0.007] * 8   # 16 obs, positive Sharpe > 0.5
        history = [_make_scorecard(r) for r in returns]
        quality = _make_quality_report([0.50, 0.55, 0.48])
        state = _make_minimal_app_state(
            paper_cycle_count=10,
            evaluation_history=history,
            portfolio_state=object(),
            drawdown_state="NORMAL",
            latest_signal_quality=quality,
        )
        result = self._svc().check_prerequisites(
            OperatingMode.PAPER, OperatingMode.HUMAN_APPROVED,
            state, self._settings(),
        )
        assert result.all_passed

    def test_paper_to_ha_fails_when_recovery_state(self):
        """RECOVERY drawdown state blocks PAPER → HUMAN_APPROVED."""
        from config.settings import OperatingMode
        returns = [0.005, 0.007] * 8
        history = [_make_scorecard(r) for r in returns]
        quality = _make_quality_report([0.50, 0.55])
        state = _make_minimal_app_state(
            paper_cycle_count=10,
            evaluation_history=history,
            drawdown_state="RECOVERY",
            latest_signal_quality=quality,
        )
        result = self._svc().check_prerequisites(
            OperatingMode.PAPER, OperatingMode.HUMAN_APPROVED,
            state, self._settings(),
        )
        assert not result.all_passed
        failed_names = [r.name for r in result.failed_requirements]
        assert "drawdown_state_acceptable" in failed_names

    def test_paper_to_ha_fails_when_sharpe_low(self):
        """Low Sharpe (with 10+ obs) blocks PAPER → HUMAN_APPROVED."""
        from config.settings import OperatingMode
        # 12 obs, tiny mean vs large std → Sharpe < 0.5
        returns = [0.04, -0.038] * 6
        history = [_make_scorecard(r) for r in returns]
        quality = _make_quality_report([0.50, 0.55])
        state = _make_minimal_app_state(
            paper_cycle_count=10,
            evaluation_history=history,
            drawdown_state="NORMAL",
            latest_signal_quality=quality,
        )
        result = self._svc().check_prerequisites(
            OperatingMode.PAPER, OperatingMode.HUMAN_APPROVED,
            state, self._settings(),
        )
        assert not result.all_passed
        failed_names = [r.name for r in result.failed_requirements]
        assert "min_sharpe_estimate" in failed_names

    def test_paper_to_ha_fails_when_win_rate_low(self):
        """Low signal quality win rate blocks PAPER → HUMAN_APPROVED."""
        from config.settings import OperatingMode
        returns = [0.005, 0.007] * 8
        history = [_make_scorecard(r) for r in returns]
        quality = _make_quality_report([0.25, 0.30])  # avg 0.275 < 0.40
        state = _make_minimal_app_state(
            paper_cycle_count=10,
            evaluation_history=history,
            drawdown_state="NORMAL",
            latest_signal_quality=quality,
        )
        result = self._svc().check_prerequisites(
            OperatingMode.PAPER, OperatingMode.HUMAN_APPROVED,
            state, self._settings(),
        )
        assert not result.all_passed
        failed_names = [r.name for r in result.failed_requirements]
        assert "min_signal_quality_win_rate" in failed_names

    def test_ha_to_rl_all_pass_when_conditions_ideal(self):
        """All gates pass for HUMAN_APPROVED → RESTRICTED_LIVE."""
        from config.settings import OperatingMode
        # consistent 0.006 daily returns → Sharpe well above 1.0
        returns = [0.006] * 2 + [0.005] * 10  # 12 obs, need variance
        returns = [0.004, 0.008] * 10  # mean=0.006, small std → high Sharpe
        history = [_make_scorecard(r) for r in returns]
        quality = _make_quality_report([0.50, 0.55, 0.48])
        state = _make_minimal_app_state(
            paper_cycle_count=25,
            evaluation_history=history,
            portfolio_state=object(),
            drawdown_state="NORMAL",
            latest_signal_quality=quality,
            latest_rankings=[object()],
        )
        result = self._svc().check_prerequisites(
            OperatingMode.HUMAN_APPROVED, OperatingMode.RESTRICTED_LIVE,
            state, self._settings(),
        )
        assert result.all_passed

    def test_ha_to_rl_fails_when_recovery_state(self):
        from config.settings import OperatingMode
        returns = [0.004, 0.008] * 10
        history = [_make_scorecard(r) for r in returns]
        quality = _make_quality_report([0.50, 0.55])
        state = _make_minimal_app_state(
            paper_cycle_count=25,
            evaluation_history=history,
            drawdown_state="RECOVERY",
            latest_signal_quality=quality,
            latest_rankings=[object()],
        )
        result = self._svc().check_prerequisites(
            OperatingMode.HUMAN_APPROVED, OperatingMode.RESTRICTED_LIVE,
            state, self._settings(),
        )
        assert not result.all_passed
        failed_names = [r.name for r in result.failed_requirements]
        assert "drawdown_state_acceptable" in failed_names

    def test_promotion_advisory_only_set_when_all_pass(self):
        from config.settings import OperatingMode
        # Fail by setting recovery mode
        state = _make_minimal_app_state(
            paper_cycle_count=10,
            drawdown_state="RECOVERY",
        )
        result = self._svc().check_prerequisites(
            OperatingMode.PAPER, OperatingMode.HUMAN_APPROVED,
            state, self._settings(),
        )
        assert result.promotion_advisory is None

    def test_caution_drawdown_does_not_block_promotion(self):
        """CAUTION drawdown state produces WARN (not FAIL) — promotion allowed."""
        from config.settings import OperatingMode
        returns = [0.005, 0.007] * 8
        history = [_make_scorecard(r) for r in returns]
        quality = _make_quality_report([0.50, 0.55])
        state = _make_minimal_app_state(
            paper_cycle_count=10,
            evaluation_history=history,
            drawdown_state="CAUTION",
            latest_signal_quality=quality,
        )
        result = self._svc().check_prerequisites(
            OperatingMode.PAPER, OperatingMode.HUMAN_APPROVED,
            state, self._settings(),
        )
        # All requirements either pass or warn — drawdown CAUTION is WARN not FAIL
        assert result.all_passed

    def test_no_quality_report_produces_warn_not_fail(self):
        """Missing signal quality report is advisory (WARN) not blocking."""
        from config.settings import OperatingMode
        returns = [0.005, 0.007] * 8
        history = [_make_scorecard(r) for r in returns]
        state = _make_minimal_app_state(
            paper_cycle_count=10,
            evaluation_history=history,
            drawdown_state="NORMAL",
            latest_signal_quality=None,
        )
        result = self._svc().check_prerequisites(
            OperatingMode.PAPER, OperatingMode.HUMAN_APPROVED,
            state, self._settings(),
        )
        # Should still pass overall (warn is not fail)
        assert result.all_passed


# =============================================================================
# TestNewGatesDoNotBreakExisting
# =============================================================================

class TestNewGatesDoNotBreakExisting:
    """Verify that adding Phase 51 gates does not break the pre-existing gate checks."""

    def _svc(self):
        from services.live_mode_gate.service import LiveModeGateService
        return LiveModeGateService()

    def _settings(self):
        from config.settings import Settings
        return Settings()

    def test_existing_requirements_still_present_paper_to_ha(self):
        from config.settings import OperatingMode
        state = _make_minimal_app_state(paper_cycle_count=0)
        result = self._svc().check_prerequisites(
            OperatingMode.PAPER, OperatingMode.HUMAN_APPROVED,
            state, self._settings(),
        )
        req_names = [r.name for r in result.requirements]
        # All original requirements should still be present
        assert "kill_switch_off" in req_names
        assert "min_paper_cycles" in req_names
        assert "min_evaluation_history" in req_names
        assert "acceptable_recent_error_rate" in req_names
        assert "portfolio_initialized" in req_names

    def test_new_requirements_added_to_paper_to_ha(self):
        from config.settings import OperatingMode
        state = _make_minimal_app_state()
        result = self._svc().check_prerequisites(
            OperatingMode.PAPER, OperatingMode.HUMAN_APPROVED,
            state, self._settings(),
        )
        req_names = [r.name for r in result.requirements]
        assert "min_sharpe_estimate" in req_names
        assert "drawdown_state_acceptable" in req_names
        assert "min_signal_quality_win_rate" in req_names

    def test_new_requirements_added_to_ha_to_rl(self):
        from config.settings import OperatingMode
        state = _make_minimal_app_state(latest_rankings=[object()])
        result = self._svc().check_prerequisites(
            OperatingMode.HUMAN_APPROVED, OperatingMode.RESTRICTED_LIVE,
            state, self._settings(),
        )
        req_names = [r.name for r in result.requirements]
        assert "min_sharpe_estimate" in req_names
        assert "drawdown_state_acceptable" in req_names
        assert "min_signal_quality_win_rate" in req_names

    def test_invalid_promotion_path_still_returns_early(self):
        from config.settings import OperatingMode
        state = _make_minimal_app_state()
        result = self._svc().check_prerequisites(
            OperatingMode.RESEARCH, OperatingMode.RESTRICTED_LIVE,
            state, self._settings(),
        )
        # Only the invalid_path requirement should be present
        assert len(result.requirements) == 1
        assert result.requirements[0].name == "valid_promotion_path"
        assert not result.all_passed

    def test_kill_switch_still_blocks_promotion(self):
        from config.settings import OperatingMode
        state = _make_minimal_app_state(kill_switch_active=True)
        result = self._svc().check_prerequisites(
            OperatingMode.PAPER, OperatingMode.HUMAN_APPROVED,
            state, self._settings(),
        )
        assert not result.all_passed
        failed_names = [r.name for r in result.failed_requirements]
        assert "kill_switch_off" in failed_names
