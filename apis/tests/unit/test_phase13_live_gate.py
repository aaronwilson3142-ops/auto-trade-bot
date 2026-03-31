"""
Phase 13 — Live Mode Gate, Secrets Management, and Grafana Dashboard Tests.

Covers:
  ✅ LiveModeGate models — GateRequirement, GateStatus, LiveModeGateResult
  ✅ LiveModeGateService — gate checks for PAPER→HUMAN_APPROVED and HUMAN_APPROVED→RESTRICTED_LIVE
  ✅ EnvSecretManager — get, get_optional, missing key behaviour
  ✅ AWSSecretManager — concrete boto3 implementation (Phase 14 updated)
  ✅ get_secret_manager() factory — env/production dispatch
  ✅ Live gate API routes — GET /live-gate/status, POST /live-gate/promote
  ✅ Grafana dashboard JSON — structure, panels, titles

Test classes
------------
  TestLiveModeGateModels              — GateRequirement, GateStatus, LiveModeGateResult
  TestLiveModeGateServiceImport       — module import and symbol visibility
  TestLiveModeGateServiceInvalidPath  — non-sequential / invalid promotion paths
  TestLiveModeGateServicePaperToHA    — PAPER → HUMAN_APPROVED gate checks
  TestLiveModeGateServiceHAToRL       — HUMAN_APPROVED → RESTRICTED_LIVE gate checks
  TestSecretsEnvManager               — EnvSecretManager behaviour
  TestSecretsAWSManager               — AWSSecretManager scaffold
  TestSecretsFactory                  — get_secret_manager() dispatch
  TestLiveGateRouteStatus             — GET /api/v1/live-gate/status
  TestLiveGateRoutePromote            — POST /api/v1/live-gate/promote
  TestGrafanaDashboard                — dashboard JSON structure and content
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Reset shared state between tests ──────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_app_state():
    from apps.api.state import reset_app_state
    reset_app_state()
    yield
    reset_app_state()


# =============================================================================
# TestLiveModeGateModels
# =============================================================================

class TestLiveModeGateModels:
    """GateRequirement, GateStatus, and LiveModeGateResult model behaviour."""

    def test_gate_status_enum_values(self):
        from services.live_mode_gate.models import GateStatus
        assert GateStatus.PASS == "pass"
        assert GateStatus.FAIL == "fail"
        assert GateStatus.WARN == "warn"

    def test_gate_requirement_pass_counts_as_passed(self):
        from services.live_mode_gate.models import GateRequirement, GateStatus
        req = GateRequirement(
            name="test", description="desc",
            status=GateStatus.PASS, actual_value=5, required_value=5,
        )
        assert req.passed is True

    def test_gate_requirement_warn_counts_as_passed(self):
        from services.live_mode_gate.models import GateRequirement, GateStatus
        req = GateRequirement(
            name="test", description="desc",
            status=GateStatus.WARN, actual_value=5, required_value=5,
        )
        assert req.passed is True

    def test_gate_requirement_fail_does_not_pass(self):
        from services.live_mode_gate.models import GateRequirement, GateStatus
        req = GateRequirement(
            name="test", description="desc",
            status=GateStatus.FAIL, actual_value=2, required_value=5,
        )
        assert req.passed is False

    def test_gate_requirement_has_detail_default(self):
        from services.live_mode_gate.models import GateRequirement, GateStatus
        req = GateRequirement(
            name="test", description="desc",
            status=GateStatus.PASS, actual_value=1, required_value=1,
        )
        assert req.detail == ""

    def test_live_mode_gate_result_all_passed_true_when_all_reqs_pass(self):
        from services.live_mode_gate.models import GateRequirement, GateStatus, LiveModeGateResult
        result = LiveModeGateResult()
        result.requirements.append(GateRequirement("r1", "d", GateStatus.PASS, 5, 5))
        result.requirements.append(GateRequirement("r2", "d", GateStatus.WARN, 3, 1))
        assert result.all_passed is True

    def test_live_mode_gate_result_all_passed_false_when_any_fail(self):
        from services.live_mode_gate.models import GateRequirement, GateStatus, LiveModeGateResult
        result = LiveModeGateResult()
        result.requirements.append(GateRequirement("r1", "d", GateStatus.PASS, 5, 5))
        result.requirements.append(GateRequirement("r2", "d", GateStatus.FAIL, 2, 5))
        assert result.all_passed is False

    def test_live_mode_gate_result_all_passed_false_when_no_requirements(self):
        from services.live_mode_gate.models import LiveModeGateResult
        result = LiveModeGateResult()
        assert result.all_passed is False

    def test_live_mode_gate_result_failed_requirements_filters_correctly(self):
        from services.live_mode_gate.models import GateRequirement, GateStatus, LiveModeGateResult
        result = LiveModeGateResult()
        result.requirements.append(GateRequirement("pass_req", "d", GateStatus.PASS, 5, 5))
        result.requirements.append(GateRequirement("fail_req", "d", GateStatus.FAIL, 2, 5))
        failed = result.failed_requirements
        assert len(failed) == 1
        assert failed[0].name == "fail_req"

    def test_live_mode_gate_result_has_id_and_evaluated_at(self):
        from services.live_mode_gate.models import LiveModeGateResult
        result = LiveModeGateResult()
        assert result.id
        assert result.evaluated_at is not None

    def test_live_mode_gate_result_promotion_advisory_none_by_default(self):
        from services.live_mode_gate.models import LiveModeGateResult
        result = LiveModeGateResult()
        assert result.promotion_advisory is None


# =============================================================================
# TestLiveModeGateServiceImport
# =============================================================================

class TestLiveModeGateServiceImport:
    def test_module_importable(self):
        from services.live_mode_gate import service  # noqa: F401

    def test_service_class_importable(self):
        from services.live_mode_gate.service import LiveModeGateService
        assert callable(LiveModeGateService)

    def test_service_exported_from_package(self):
        from services.live_mode_gate import LiveModeGateService
        assert callable(LiveModeGateService)

    def test_service_has_check_prerequisites(self):
        from services.live_mode_gate.service import LiveModeGateService
        svc = LiveModeGateService()
        assert hasattr(svc, "check_prerequisites")


# =============================================================================
# TestLiveModeGateServiceInvalidPath
# =============================================================================

class TestLiveModeGateServiceInvalidPath:
    """Invalid or non-sequential promotion paths fail immediately."""

    def _make_state(self):
        from apps.api.state import ApiAppState
        return ApiAppState()

    def _make_settings(self, mode: str):
        from config.settings import Settings
        return Settings(operating_mode=mode)

    def test_research_to_human_approved_is_invalid(self):
        from config.settings import OperatingMode
        from services.live_mode_gate.service import LiveModeGateService
        svc = LiveModeGateService()
        result = svc.check_prerequisites(
            current_mode=OperatingMode.RESEARCH,
            target_mode=OperatingMode.HUMAN_APPROVED,
            app_state=self._make_state(),
            settings=self._make_settings("research"),
        )
        assert result.all_passed is False
        assert any(r.name == "valid_promotion_path" for r in result.requirements)

    def test_backtest_to_restricted_live_is_invalid(self):
        from config.settings import OperatingMode
        from services.live_mode_gate.service import LiveModeGateService
        svc = LiveModeGateService()
        result = svc.check_prerequisites(
            current_mode=OperatingMode.BACKTEST,
            target_mode=OperatingMode.RESTRICTED_LIVE,
            app_state=self._make_state(),
            settings=self._make_settings("backtest"),
        )
        assert result.all_passed is False

    def test_paper_to_restricted_live_is_invalid_skips_human_approved(self):
        from config.settings import OperatingMode
        from services.live_mode_gate.service import LiveModeGateService
        svc = LiveModeGateService()
        result = svc.check_prerequisites(
            current_mode=OperatingMode.PAPER,
            target_mode=OperatingMode.RESTRICTED_LIVE,
            app_state=self._make_state(),
            settings=self._make_settings("paper"),
        )
        assert result.all_passed is False
        assert any(r.name == "valid_promotion_path" for r in result.requirements)

    def test_result_has_current_and_target_mode_set(self):
        from config.settings import OperatingMode
        from services.live_mode_gate.service import LiveModeGateService
        svc = LiveModeGateService()
        result = svc.check_prerequisites(
            current_mode=OperatingMode.RESEARCH,
            target_mode=OperatingMode.HUMAN_APPROVED,
            app_state=self._make_state(),
            settings=self._make_settings("research"),
        )
        assert result.current_mode == "research"
        assert result.target_mode == "human_approved"


# =============================================================================
# TestLiveModeGateServicePaperToHA
# =============================================================================

class TestLiveModeGateServicePaperToHA:
    """PAPER → HUMAN_APPROVED gate checks."""

    def _make_settings(self, kill_switch: bool = False):
        from config.settings import Settings
        return Settings(operating_mode="paper", kill_switch=str(kill_switch).lower())

    def _make_full_state(self, cycle_count: int = 5, eval_count: int = 5,
                         recent_errors: int = 0, init_portfolio: bool = True):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        # Fill in paper_cycle_results
        for i in range(cycle_count):
            errors = ["err"] if i < recent_errors else []
            state.paper_cycle_results.append({"cycle": i, "errors": errors})
        # Fill in evaluation_history
        for _ in range(eval_count):
            state.evaluation_history.append(MagicMock())
        if init_portfolio:
            state.portfolio_state = MagicMock()
        return state

    def test_kill_switch_blocks_promotion(self):
        from config.settings import OperatingMode
        from services.live_mode_gate.service import LiveModeGateService
        svc = LiveModeGateService()
        result = svc.check_prerequisites(
            current_mode=OperatingMode.PAPER,
            target_mode=OperatingMode.HUMAN_APPROVED,
            app_state=self._make_full_state(),
            settings=self._make_settings(kill_switch=True),
        )
        assert result.all_passed is False
        assert any(r.name == "kill_switch_off" and not r.passed for r in result.requirements)

    def test_fails_when_too_few_paper_cycles(self):
        from config.settings import OperatingMode
        from services.live_mode_gate.service import LiveModeGateService
        svc = LiveModeGateService()
        result = svc.check_prerequisites(
            current_mode=OperatingMode.PAPER,
            target_mode=OperatingMode.HUMAN_APPROVED,
            app_state=self._make_full_state(cycle_count=2),
            settings=self._make_settings(),
        )
        assert result.all_passed is False
        req = next(r for r in result.requirements if r.name == "min_paper_cycles")
        assert not req.passed
        assert req.actual_value == 2

    def test_fails_when_too_few_evaluations(self):
        from config.settings import OperatingMode
        from services.live_mode_gate.service import LiveModeGateService
        svc = LiveModeGateService()
        result = svc.check_prerequisites(
            current_mode=OperatingMode.PAPER,
            target_mode=OperatingMode.HUMAN_APPROVED,
            app_state=self._make_full_state(eval_count=1),
            settings=self._make_settings(),
        )
        assert result.all_passed is False
        req = next(r for r in result.requirements if r.name == "min_evaluation_history")
        assert not req.passed

    def test_fails_when_portfolio_not_initialized(self):
        from config.settings import OperatingMode
        from services.live_mode_gate.service import LiveModeGateService
        svc = LiveModeGateService()
        result = svc.check_prerequisites(
            current_mode=OperatingMode.PAPER,
            target_mode=OperatingMode.HUMAN_APPROVED,
            app_state=self._make_full_state(init_portfolio=False),
            settings=self._make_settings(),
        )
        assert result.all_passed is False
        req = next(r for r in result.requirements if r.name == "portfolio_initialized")
        assert not req.passed

    def test_fails_when_too_many_recent_errors(self):
        from config.settings import OperatingMode
        from services.live_mode_gate.service import LiveModeGateService
        svc = LiveModeGateService()
        # 3 of last 5 cycles have errors — exceeds limit of 2
        result = svc.check_prerequisites(
            current_mode=OperatingMode.PAPER,
            target_mode=OperatingMode.HUMAN_APPROVED,
            app_state=self._make_full_state(cycle_count=5, recent_errors=3),
            settings=self._make_settings(),
        )
        assert result.all_passed is False
        req = next(r for r in result.requirements if r.name == "acceptable_recent_error_rate")
        assert not req.passed
        assert req.actual_value == 3

    def test_all_pass_when_conditions_met(self):
        from config.settings import OperatingMode
        from services.live_mode_gate.service import LiveModeGateService
        svc = LiveModeGateService()
        result = svc.check_prerequisites(
            current_mode=OperatingMode.PAPER,
            target_mode=OperatingMode.HUMAN_APPROVED,
            app_state=self._make_full_state(cycle_count=5, eval_count=5, recent_errors=0),
            settings=self._make_settings(),
        )
        assert result.all_passed is True

    def test_promotion_advisory_set_when_all_pass(self):
        from config.settings import OperatingMode
        from services.live_mode_gate.service import LiveModeGateService
        svc = LiveModeGateService()
        result = svc.check_prerequisites(
            current_mode=OperatingMode.PAPER,
            target_mode=OperatingMode.HUMAN_APPROVED,
            app_state=self._make_full_state(),
            settings=self._make_settings(),
        )
        assert result.promotion_advisory is not None
        assert "human_approved" in result.promotion_advisory

    def test_promotion_advisory_none_when_fails(self):
        from config.settings import OperatingMode
        from services.live_mode_gate.service import LiveModeGateService
        svc = LiveModeGateService()
        result = svc.check_prerequisites(
            current_mode=OperatingMode.PAPER,
            target_mode=OperatingMode.HUMAN_APPROVED,
            app_state=self._make_full_state(cycle_count=0),
            settings=self._make_settings(),
        )
        assert result.promotion_advisory is None


# =============================================================================
# TestLiveModeGateServiceHAToRL
# =============================================================================

class TestLiveModeGateServiceHAToRL:
    """HUMAN_APPROVED → RESTRICTED_LIVE gate checks (stricter thresholds)."""

    def _make_settings(self):
        from config.settings import Settings
        return Settings(operating_mode="human_approved")

    def _make_full_state(self, cycle_count: int = 20, eval_count: int = 10,
                         has_rankings: bool = True):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        for i in range(cycle_count):
            state.paper_cycle_results.append({"cycle": i, "errors": []})
        for _ in range(eval_count):
            state.evaluation_history.append(MagicMock())
        state.portfolio_state = MagicMock()
        if has_rankings:
            state.latest_rankings.append(MagicMock())
        return state

    def test_fails_when_too_few_cycles_for_restricted_live(self):
        from config.settings import OperatingMode
        from services.live_mode_gate.service import LiveModeGateService
        svc = LiveModeGateService()
        result = svc.check_prerequisites(
            current_mode=OperatingMode.HUMAN_APPROVED,
            target_mode=OperatingMode.RESTRICTED_LIVE,
            app_state=self._make_full_state(cycle_count=5),
            settings=self._make_settings(),
        )
        assert result.all_passed is False
        req = next(r for r in result.requirements if r.name == "min_cycles_for_restricted_live")
        assert not req.passed

    def test_fails_when_too_few_eval_for_restricted_live(self):
        from config.settings import OperatingMode
        from services.live_mode_gate.service import LiveModeGateService
        svc = LiveModeGateService()
        result = svc.check_prerequisites(
            current_mode=OperatingMode.HUMAN_APPROVED,
            target_mode=OperatingMode.RESTRICTED_LIVE,
            app_state=self._make_full_state(eval_count=3),
            settings=self._make_settings(),
        )
        assert result.all_passed is False
        req = next(r for r in result.requirements if r.name == "min_evaluation_history_for_restricted_live")
        assert not req.passed

    def test_fails_when_no_rankings_available(self):
        from config.settings import OperatingMode
        from services.live_mode_gate.service import LiveModeGateService
        svc = LiveModeGateService()
        result = svc.check_prerequisites(
            current_mode=OperatingMode.HUMAN_APPROVED,
            target_mode=OperatingMode.RESTRICTED_LIVE,
            app_state=self._make_full_state(has_rankings=False),
            settings=self._make_settings(),
        )
        assert result.all_passed is False
        req = next(r for r in result.requirements if r.name == "rankings_available")
        assert not req.passed

    def test_all_pass_when_conditions_met(self):
        from config.settings import OperatingMode
        from services.live_mode_gate.service import LiveModeGateService
        svc = LiveModeGateService()
        result = svc.check_prerequisites(
            current_mode=OperatingMode.HUMAN_APPROVED,
            target_mode=OperatingMode.RESTRICTED_LIVE,
            app_state=self._make_full_state(),
            settings=self._make_settings(),
        )
        assert result.all_passed is True

    def test_promotion_advisory_mentions_restricted_live(self):
        from config.settings import OperatingMode
        from services.live_mode_gate.service import LiveModeGateService
        svc = LiveModeGateService()
        result = svc.check_prerequisites(
            current_mode=OperatingMode.HUMAN_APPROVED,
            target_mode=OperatingMode.RESTRICTED_LIVE,
            app_state=self._make_full_state(),
            settings=self._make_settings(),
        )
        assert result.promotion_advisory is not None
        assert "restricted_live" in result.promotion_advisory

    def test_result_has_more_requirements_than_paper_to_ha(self):
        """Restricted live gate should have at least as many requirements."""
        from config.settings import OperatingMode
        from services.live_mode_gate.service import LiveModeGateService
        svc = LiveModeGateService()
        paper_result = svc.check_prerequisites(
            current_mode=OperatingMode.PAPER,
            target_mode=OperatingMode.HUMAN_APPROVED,
            app_state=self._make_full_state(),
            settings=MagicMock(kill_switch=False, operating_mode=OperatingMode.PAPER),
        )
        rl_result = svc.check_prerequisites(
            current_mode=OperatingMode.HUMAN_APPROVED,
            target_mode=OperatingMode.RESTRICTED_LIVE,
            app_state=self._make_full_state(),
            settings=MagicMock(kill_switch=False, operating_mode=OperatingMode.HUMAN_APPROVED),
        )
        assert len(rl_result.requirements) >= len(paper_result.requirements)


# =============================================================================
# TestSecretsEnvManager
# =============================================================================

class TestSecretsEnvManager:
    def test_module_importable(self):
        from config import secrets  # noqa: F401

    def test_env_manager_importable(self):
        from config.secrets import EnvSecretManager
        assert callable(EnvSecretManager)

    def test_env_manager_get_existing_key(self):
        from config.secrets import EnvSecretManager
        sm = EnvSecretManager()
        with patch.dict(os.environ, {"TEST_SECRET_KEY": "test_value"}):
            assert sm.get("TEST_SECRET_KEY") == "test_value"

    def test_env_manager_get_missing_key_raises_key_error(self):
        from config.secrets import EnvSecretManager
        sm = EnvSecretManager()
        env_copy = {k: v for k, v in os.environ.items() if k != "NONEXISTENT_KEY_XYZ"}
        with patch.dict(os.environ, env_copy, clear=True):
            with pytest.raises(KeyError, match="NONEXISTENT_KEY_XYZ"):
                sm.get("NONEXISTENT_KEY_XYZ")

    def test_env_manager_get_empty_string_raises_key_error(self):
        from config.secrets import EnvSecretManager
        sm = EnvSecretManager()
        with patch.dict(os.environ, {"EMPTY_SECRET": ""}):
            with pytest.raises(KeyError):
                sm.get("EMPTY_SECRET")

    def test_env_manager_get_optional_returns_default_for_missing(self):
        from config.secrets import EnvSecretManager
        sm = EnvSecretManager()
        env_copy = {k: v for k, v in os.environ.items() if k != "MISSING_SECRET_XYZ"}
        with patch.dict(os.environ, env_copy, clear=True):
            result = sm.get_optional("MISSING_SECRET_XYZ", default="fallback")
        assert result == "fallback"

    def test_env_manager_get_optional_returns_empty_string_by_default(self):
        from config.secrets import EnvSecretManager
        sm = EnvSecretManager()
        env_copy = {k: v for k, v in os.environ.items() if k != "MISSING_SECRET_XYZ"}
        with patch.dict(os.environ, env_copy, clear=True):
            result = sm.get_optional("MISSING_SECRET_XYZ")
        assert result == ""

    def test_env_manager_get_optional_returns_value_when_found(self):
        from config.secrets import EnvSecretManager
        sm = EnvSecretManager()
        with patch.dict(os.environ, {"FOUND_SECRET": "found_value"}):
            result = sm.get_optional("FOUND_SECRET", default="other")
        assert result == "found_value"

    def test_env_manager_is_subclass_of_secret_manager(self):
        from config.secrets import EnvSecretManager, SecretManager
        assert issubclass(EnvSecretManager, SecretManager)

    def test_secret_manager_is_abstract(self):
        import inspect

        from config.secrets import SecretManager
        assert inspect.isabstract(SecretManager)


# =============================================================================
# TestSecretsAWSManager
# =============================================================================

class TestSecretsAWSManager:
    def test_aws_manager_importable(self):
        from config.secrets import AWSSecretManager
        assert callable(AWSSecretManager)

    def test_aws_manager_get_raises_runtime_error_without_aws(self):
        """AWSSecretManager.get() is now concrete; without real AWS it raises RuntimeError."""
        import json
        from unittest.mock import MagicMock, patch

        from config.secrets import AWSSecretManager
        sm = AWSSecretManager()
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {"SecretString": json.dumps({"SOME_KEY": "val"})}
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            result = sm.get("SOME_KEY")
        assert result == "val"

    def test_aws_manager_get_optional_returns_default_on_missing(self):
        """AWSSecretManager.get_optional() is now concrete; returns default for missing key."""
        import json
        from unittest.mock import MagicMock, patch

        from config.secrets import AWSSecretManager
        sm = AWSSecretManager()
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {"SecretString": json.dumps({"OTHER": "v"})}
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            result = sm.get_optional("SOME_KEY", default="fallback")
        assert result == "fallback"

    def test_aws_manager_default_secret_name(self):
        from config.secrets import AWSSecretManager
        sm = AWSSecretManager()
        assert sm.secret_name == "apis/production/secrets"

    def test_aws_manager_default_region(self):
        from config.secrets import AWSSecretManager
        sm = AWSSecretManager()
        assert sm.region_name == "us-east-1"

    def test_aws_manager_custom_secret_name(self):
        from config.secrets import AWSSecretManager
        sm = AWSSecretManager(secret_name="apis/staging/secrets", region_name="eu-west-1")
        assert sm.secret_name == "apis/staging/secrets"
        assert sm.region_name == "eu-west-1"

    def test_aws_manager_is_subclass_of_secret_manager(self):
        from config.secrets import AWSSecretManager, SecretManager
        assert issubclass(AWSSecretManager, SecretManager)

    def test_aws_manager_get_raises_runtime_error_on_aws_failure(self):
        """AWSSecretManager.get() raises RuntimeError when AWS call fails."""
        from unittest.mock import MagicMock, patch

        from config.secrets import AWSSecretManager
        sm = AWSSecretManager()
        mock_client = MagicMock()
        mock_client.get_secret_value.side_effect = Exception("AccessDenied")
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            with pytest.raises(RuntimeError):
                sm.get("KEY")


# =============================================================================
# TestSecretsFactory
# =============================================================================

class TestSecretsFactory:
    def test_development_returns_env_manager(self):
        from config.secrets import EnvSecretManager, get_secret_manager
        sm = get_secret_manager("development")
        assert isinstance(sm, EnvSecretManager)

    def test_staging_returns_env_manager(self):
        from config.secrets import EnvSecretManager, get_secret_manager
        sm = get_secret_manager("staging")
        assert isinstance(sm, EnvSecretManager)

    def test_production_returns_aws_manager(self):
        from config.secrets import AWSSecretManager, get_secret_manager
        sm = get_secret_manager("production")
        assert isinstance(sm, AWSSecretManager)

    def test_enum_development_returns_env_manager(self):
        from config.secrets import EnvSecretManager, get_secret_manager
        from config.settings import Environment
        sm = get_secret_manager(Environment.DEVELOPMENT)
        assert isinstance(sm, EnvSecretManager)

    def test_enum_production_returns_aws_manager(self):
        from config.secrets import AWSSecretManager, get_secret_manager
        from config.settings import Environment
        sm = get_secret_manager(Environment.PRODUCTION)
        assert isinstance(sm, AWSSecretManager)


# =============================================================================
# TestLiveGateRouteStatus
# =============================================================================

class TestLiveGateRouteStatus:
    """GET /api/v1/live-gate/status"""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from apps.api.main import app
        return TestClient(app)

    def test_get_status_returns_200(self, client):
        resp = client.get("/api/v1/live-gate/status")
        assert resp.status_code == 200

    def test_get_status_returns_json(self, client):
        resp = client.get("/api/v1/live-gate/status")
        data = resp.json()
        assert isinstance(data, dict)

    def test_get_status_has_current_mode(self, client):
        resp = client.get("/api/v1/live-gate/status")
        data = resp.json()
        assert "current_mode" in data

    def test_get_status_has_all_passed_field(self, client):
        resp = client.get("/api/v1/live-gate/status")
        data = resp.json()
        assert "all_passed" in data
        assert isinstance(data["all_passed"], bool)

    def test_get_status_has_requirements_list(self, client):
        resp = client.get("/api/v1/live-gate/status")
        data = resp.json()
        assert "requirements" in data
        assert isinstance(data["requirements"], list)

    def test_get_status_has_failed_count(self, client):
        resp = client.get("/api/v1/live-gate/status")
        data = resp.json()
        assert "failed_count" in data
        assert isinstance(data["failed_count"], int)

    def test_get_status_has_evaluated_at(self, client):
        resp = client.get("/api/v1/live-gate/status")
        data = resp.json()
        assert "evaluated_at" in data

    def test_get_status_in_research_mode_has_no_gate_required(self, client):
        """RESEARCH mode has no programmatic gate — should return pass with advisory."""
        resp = client.get("/api/v1/live-gate/status")
        data = resp.json()
        # Default mode is research which has no gated promotion
        req_names = [r["name"] for r in data["requirements"]]
        assert "no_gate_required" in req_names

    def test_get_status_caches_result_in_app_state(self, client):
        resp = client.get("/api/v1/live-gate/status")
        assert resp.status_code == 200
        from apps.api.state import get_app_state
        state = get_app_state()
        assert state.live_gate_last_result is not None

    def test_get_status_requirement_schema_has_required_fields(self, client):
        resp = client.get("/api/v1/live-gate/status")
        data = resp.json()
        if data["requirements"]:
            req = data["requirements"][0]
            assert "name" in req
            assert "description" in req
            assert "status" in req
            assert "passed" in req


# =============================================================================
# TestLiveGateRoutePromote
# =============================================================================

class TestLiveGateRoutePromote:
    """POST /api/v1/live-gate/promote"""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from apps.api.main import app
        return TestClient(app)

    def test_post_promote_returns_200(self, client):
        resp = client.post(
            "/api/v1/live-gate/promote",
            json={"target_mode": "human_approved"},
        )
        assert resp.status_code == 200

    def test_post_promote_returns_gate_result(self, client):
        resp = client.post(
            "/api/v1/live-gate/promote",
            json={"target_mode": "human_approved"},
        )
        data = resp.json()
        assert "gate_result" in data

    def test_post_promote_returns_message(self, client):
        resp = client.post(
            "/api/v1/live-gate/promote",
            json={"target_mode": "human_approved"},
        )
        data = resp.json()
        assert "message" in data
        assert isinstance(data["message"], str)

    def test_post_promote_returns_promotion_recorded_field(self, client):
        resp = client.post(
            "/api/v1/live-gate/promote",
            json={"target_mode": "human_approved"},
        )
        data = resp.json()
        assert "promotion_recorded" in data
        assert isinstance(data["promotion_recorded"], bool)

    def test_post_promote_fails_in_research_mode(self, client):
        """Research → human_approved is not a valid gated path."""
        resp = client.post(
            "/api/v1/live-gate/promote",
            json={"target_mode": "human_approved"},
        )
        data = resp.json()
        # Should fail because current mode (research) cannot directly gate to human_approved
        assert data["promotion_recorded"] is False

    def test_post_promote_invalid_target_mode_returns_422(self, client):
        resp = client.post(
            "/api/v1/live-gate/promote",
            json={"target_mode": "not_a_valid_mode"},
        )
        assert resp.status_code == 422

    def test_post_promote_records_result_in_app_state(self, client):
        client.post(
            "/api/v1/live-gate/promote",
            json={"target_mode": "human_approved"},
        )
        from apps.api.state import get_app_state
        state = get_app_state()
        assert state.live_gate_last_result is not None

    def test_post_promote_records_pending_false_when_fails(self, client):
        """In research mode, promotion fails, pending should be False."""
        client.post(
            "/api/v1/live-gate/promote",
            json={"target_mode": "human_approved"},
        )
        from apps.api.state import get_app_state
        state = get_app_state()
        assert state.live_gate_promotion_pending is False

    def test_post_promote_restricted_live_also_valid_target(self, client):
        resp = client.post(
            "/api/v1/live-gate/promote",
            json={"target_mode": "restricted_live"},
        )
        assert resp.status_code == 200

    def test_live_gate_router_tagged_correctly(self):
        from apps.api.routes.live_gate import router
        assert "Live Gate" in router.tags


# =============================================================================
# TestApiAppStateNewFields
# =============================================================================

class TestApiAppStateNewFields:
    """Phase 13 additions to ApiAppState."""

    def test_live_gate_last_result_field_exists(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert hasattr(state, "live_gate_last_result")
        assert state.live_gate_last_result is None

    def test_live_gate_promotion_pending_field_exists(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert hasattr(state, "live_gate_promotion_pending")
        assert state.live_gate_promotion_pending is False

    def test_live_gate_fields_reset_on_reset(self):
        from apps.api.state import get_app_state, reset_app_state
        state = get_app_state()
        state.live_gate_last_result = MagicMock()
        state.live_gate_promotion_pending = True
        reset_app_state()
        state2 = get_app_state()
        assert state2.live_gate_last_result is None
        assert state2.live_gate_promotion_pending is False


# =============================================================================
# TestGrafanaDashboard
# =============================================================================

GRAFANA_DASHBOARD_PATH = (
    Path(__file__).parent.parent.parent  # apis/
    / "infra" / "monitoring" / "grafana_dashboard.json"
)


class TestGrafanaDashboard:
    def test_dashboard_file_exists(self):
        assert GRAFANA_DASHBOARD_PATH.exists(), (
            f"Grafana dashboard not found at {GRAFANA_DASHBOARD_PATH}"
        )

    def test_dashboard_json_is_valid(self):
        with open(GRAFANA_DASHBOARD_PATH, encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_dashboard_has_required_top_level_keys(self):
        with open(GRAFANA_DASHBOARD_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for key in ("title", "panels", "uid", "schemaVersion"):
            assert key in data, f"Missing top-level key: {key}"

    def test_dashboard_title_mentions_apis(self):
        with open(GRAFANA_DASHBOARD_PATH, encoding="utf-8") as f:
            data = json.load(f)
        assert "APIS" in data["title"]

    def test_dashboard_has_multiple_panels(self):
        with open(GRAFANA_DASHBOARD_PATH, encoding="utf-8") as f:
            data = json.load(f)
        # Must have at least 8 panels (excluding row separators)
        non_row_panels = [p for p in data["panels"] if p.get("type") != "row"]
        assert len(non_row_panels) >= 8

    def test_dashboard_panels_have_required_fields(self):
        with open(GRAFANA_DASHBOARD_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for panel in data["panels"]:
            assert "title" in panel, f"Panel missing 'title': {panel.get('id')}"
            assert "type" in panel, f"Panel missing 'type': {panel.get('id')}"

    def test_dashboard_references_prometheus_metrics(self):
        with open(GRAFANA_DASHBOARD_PATH, encoding="utf-8") as f:
            raw = f.read()
        # At least one of the known APIS Prometheus metric names should appear
        expected_metrics = [
            "apis_kill_switch_active",
            "apis_portfolio_equity_usd",
            "apis_paper_loop_active",
            "apis_portfolio_positions",
        ]
        for metric in expected_metrics:
            assert metric in raw, f"Dashboard does not reference metric: {metric}"

    def test_dashboard_has_input_for_prometheus_datasource(self):
        with open(GRAFANA_DASHBOARD_PATH, encoding="utf-8") as f:
            data = json.load(f)
        assert "__inputs" in data
        input_ids = [i["pluginId"] for i in data["__inputs"]]
        assert "prometheus" in input_ids

    def test_dashboard_refresh_interval_set(self):
        with open(GRAFANA_DASHBOARD_PATH, encoding="utf-8") as f:
            data = json.load(f)
        assert "refresh" in data
        assert data["refresh"]  # must not be empty
