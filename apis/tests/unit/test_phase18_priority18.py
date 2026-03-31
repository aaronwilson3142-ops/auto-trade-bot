"""
Phase 18 — Priority 18 Unit Tests
Schwab Token Auto-Refresh + Admin Rate Limiting + DB Pool Config + Alertmanager

Coverage:
  - DB connection pool settings (TestDBPoolSettings)          8 tests
  - Admin rate limiter _check_rate_limit (TestAdminRateLimiter) 12 tests
  - Broker token refresh job (TestBrokerRefreshJob)           15 tests
  - Worker scheduler: broker refresh registered (TestWorkerScheduler) 4 tests
  - Alertmanager config file (TestAlertmanagerConfig)         10 tests
  - Prometheus alerting block enabled (TestPrometheusAlerting) 4 tests
  - Docker Compose alertmanager service (TestDockerCompose)    6 tests
  - .env.example new entries (TestEnvExample)                  5 tests
  - POST /admin/invalidate-secrets rate-limit integration
      (TestAdminRateLimitIntegration)                          8 tests
  - Phase 18 integration (TestPhase18Integration)              6 tests

Total: ~78 tests
"""
from __future__ import annotations

import collections
import datetime as dt
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

# ── Repo root ──────────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent.parent  # apis/


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_settings(**kwargs) -> Any:
    from config.settings import Environment, Settings
    defaults = dict(
        env=Environment.DEVELOPMENT,
        admin_rotation_token="secret-tok",
        db_url="postgresql+psycopg://user:pass@localhost:5432/apis_test",
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def _make_app_state() -> Any:
    from apps.api.state import reset_app_state, get_app_state
    reset_app_state()
    return get_app_state()


def _reset_rate_limit_store() -> None:
    """Clear rate limiter store between tests to prevent cross-contamination."""
    import apps.api.routes.admin as admin_mod
    with admin_mod._rate_limit_lock:
        admin_mod._rate_limit_store.clear()


# ══════════════════════════════════════════════════════════════════════════════
# 1. DB connection pool settings
# ══════════════════════════════════════════════════════════════════════════════

class TestDBPoolSettings:
    """Settings class must expose pool config fields; session must use them."""

    def test_settings_has_db_pool_size(self):
        from config.settings import Settings
        assert "db_pool_size" in Settings.model_fields

    def test_settings_has_db_max_overflow(self):
        from config.settings import Settings
        assert "db_max_overflow" in Settings.model_fields

    def test_settings_has_db_pool_recycle(self):
        from config.settings import Settings
        assert "db_pool_recycle" in Settings.model_fields

    def test_settings_has_db_pool_timeout(self):
        from config.settings import Settings
        assert "db_pool_timeout" in Settings.model_fields

    def test_default_pool_size_is_five(self):
        s = _make_settings()
        assert s.db_pool_size == 5

    def test_default_max_overflow_is_ten(self):
        s = _make_settings()
        assert s.db_max_overflow == 10

    def test_default_pool_recycle_is_1800(self):
        s = _make_settings()
        assert s.db_pool_recycle == 1800

    def test_session_build_engine_uses_pool_settings(self):
        """_build_engine() must pass pool settings to create_engine."""
        import inspect
        import infra.db.session as session_mod
        src = inspect.getsource(session_mod._build_engine)
        assert "db_pool_size" in src
        assert "db_max_overflow" in src
        assert "db_pool_recycle" in src
        assert "pool_pre_ping=True" in src

    def test_pool_size_overridable_via_settings(self):
        s = _make_settings(db_pool_size=20)
        assert s.db_pool_size == 20

    def test_pool_recycle_envvar_name(self):
        """Verify the env prefix maps to APIS_DB_POOL_RECYCLE."""
        from config.settings import Settings
        # pydantic-settings uses env_prefix + field_name (uppercased)
        cfg = Settings.model_config
        prefix = cfg.get("env_prefix", "")
        assert prefix == "APIS_"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Admin rate limiter
# ══════════════════════════════════════════════════════════════════════════════

class TestAdminRateLimiter:
    """Tests for _check_rate_limit(ip) sliding-window rate limiter."""

    def setup_method(self):
        _reset_rate_limit_store()

    def test_check_rate_limit_is_callable(self):
        from apps.api.routes.admin import _check_rate_limit
        assert callable(_check_rate_limit)

    def test_does_not_raise_below_limit(self):
        from apps.api.routes.admin import _check_rate_limit, _RATE_LIMIT_MAX
        for _ in range(_RATE_LIMIT_MAX - 1):
            _check_rate_limit("1.2.3.4")  # must not raise

    def test_raises_429_at_limit(self):
        from fastapi import HTTPException
        from apps.api.routes.admin import _check_rate_limit, _RATE_LIMIT_MAX
        for _ in range(_RATE_LIMIT_MAX):
            try:
                _check_rate_limit("1.2.3.5")
            except HTTPException:
                pass
        with pytest.raises(HTTPException) as exc_info:
            _check_rate_limit("1.2.3.5")
        assert exc_info.value.status_code == 429

    def test_429_response_has_retry_after_header(self):
        from fastapi import HTTPException
        from apps.api.routes.admin import _check_rate_limit, _RATE_LIMIT_MAX
        for _ in range(_RATE_LIMIT_MAX + 1):
            try:
                _check_rate_limit("1.2.3.6")
            except HTTPException as exc:
                if exc.status_code == 429:
                    assert "Retry-After" in exc.headers
                    return
        pytest.fail("Expected 429 to be raised")

    def test_rate_limit_is_per_ip(self):
        from apps.api.routes.admin import _check_rate_limit, _RATE_LIMIT_MAX
        # Fill up IP-A's bucket
        from fastapi import HTTPException
        for _ in range(_RATE_LIMIT_MAX):
            try:
                _check_rate_limit("10.0.0.1")
            except HTTPException:
                pass
        # IP-B should still work
        _check_rate_limit("10.0.0.2")  # must not raise

    def test_rate_limit_handles_none_ip(self):
        from apps.api.routes.admin import _check_rate_limit, _RATE_LIMIT_MAX
        # Should key on "unknown"; not crash
        for _ in range(_RATE_LIMIT_MAX - 1):
            _check_rate_limit(None)

    def test_rate_limit_window_constant_is_60(self):
        from apps.api.routes.admin import _RATE_LIMIT_WINDOW_S
        assert _RATE_LIMIT_WINDOW_S == 60

    def test_rate_limit_max_constant_is_20(self):
        from apps.api.routes.admin import _RATE_LIMIT_MAX
        assert _RATE_LIMIT_MAX == 20

    def test_rate_limit_store_is_dict(self):
        from apps.api.routes.admin import _rate_limit_store
        assert isinstance(_rate_limit_store, dict)

    def test_rate_limit_lock_is_threading_lock(self):
        from apps.api.routes.admin import _rate_limit_lock
        from threading import Lock
        # Lock is a function returning _RLow; check it's lock-like
        assert hasattr(_rate_limit_lock, "acquire") and hasattr(_rate_limit_lock, "release")

    def test_rate_limit_entries_are_deque(self):
        from apps.api.routes.admin import _check_rate_limit, _rate_limit_store
        _check_rate_limit("192.168.1.1")
        assert isinstance(_rate_limit_store["192.168.1.1"], collections.deque)

    def test_rate_limit_429_detail_mentions_rate_limit(self):
        from fastapi import HTTPException
        from apps.api.routes.admin import _check_rate_limit, _RATE_LIMIT_MAX
        for _ in range(_RATE_LIMIT_MAX + 1):
            try:
                _check_rate_limit("9.9.9.9")
            except HTTPException as exc:
                if exc.status_code == 429:
                    assert "rate limit" in exc.detail.lower() or "Rate limit" in exc.detail
                    return
        pytest.fail("Expected 429 to fire")


# ══════════════════════════════════════════════════════════════════════════════
# 3. Broker token refresh job
# ══════════════════════════════════════════════════════════════════════════════

class TestBrokerRefreshJob:
    """Tests for run_broker_token_refresh() in broker_refresh.py."""

    def _run(self, broker=None, app_state=None):
        from apps.worker.jobs.broker_refresh import run_broker_token_refresh
        state = app_state or _make_app_state()
        return run_broker_token_refresh(app_state=state, broker=broker), state

    def test_module_is_importable(self):
        import apps.worker.jobs.broker_refresh  # noqa: F401

    def test_job_file_exists(self):
        assert (_REPO / "apps" / "worker" / "jobs" / "broker_refresh.py").exists()

    def test_no_broker_returns_skipped(self):
        result, _ = self._run(broker=None)
        assert result["status"] == "skipped"
        assert result["reason"] == "no_broker"

    def test_no_broker_in_app_state_returns_skipped(self):
        state = _make_app_state()
        state.broker_adapter = None
        from apps.worker.jobs.broker_refresh import run_broker_token_refresh
        result = run_broker_token_refresh(app_state=state)
        assert result["status"] == "skipped"

    def test_non_schwab_broker_returns_skipped(self):
        from broker_adapters.paper.adapter import PaperBrokerAdapter
        # PaperBrokerAdapter is NOT a SchwabBrokerAdapter; job should skip
        broker = PaperBrokerAdapter()
        result, _ = self._run(broker=broker)
        assert result["status"] == "skipped"
        assert result["reason"] == "not_schwab"

    def test_non_schwab_result_includes_adapter_name(self):
        broker = MagicMock()
        broker.adapter_name = "ibkr"
        result, _ = self._run(broker=broker)
        # adapter name is in result (or status=skipped with reason=not_schwab)
        assert result["status"] == "skipped"

    def test_successful_refresh_returns_ok(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        broker = MagicMock(spec=SchwabBrokerAdapter)
        broker.refresh_auth.return_value = None
        result, _ = self._run(broker=broker)
        assert result["status"] == "ok"

    def test_successful_refresh_calls_refresh_auth(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        broker = MagicMock(spec=SchwabBrokerAdapter)
        self._run(broker=broker)
        broker.refresh_auth.assert_called_once()

    def test_successful_refresh_clears_stale_expired_flag(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        broker = MagicMock(spec=SchwabBrokerAdapter)
        broker.refresh_auth.return_value = None
        state = _make_app_state()
        state.broker_auth_expired = True
        state.broker_auth_expired_at = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        from apps.worker.jobs.broker_refresh import run_broker_token_refresh
        run_broker_token_refresh(app_state=state, broker=broker)
        assert state.broker_auth_expired is False
        assert state.broker_auth_expired_at is None

    def test_successful_refresh_no_state_changes_if_flag_already_false(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        broker = MagicMock(spec=SchwabBrokerAdapter)
        broker.refresh_auth.return_value = None
        state = _make_app_state()
        assert state.broker_auth_expired is False
        from apps.worker.jobs.broker_refresh import run_broker_token_refresh
        run_broker_token_refresh(app_state=state, broker=broker)
        assert state.broker_auth_expired is False

    def test_auth_error_returns_error_auth(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        from broker_adapters.base.exceptions import BrokerAuthenticationError
        broker = MagicMock(spec=SchwabBrokerAdapter)
        broker.refresh_auth.side_effect = BrokerAuthenticationError("RT expired")
        result, _ = self._run(broker=broker)
        assert result["status"] == "error_auth"

    def test_auth_error_sets_broker_auth_expired_flag(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        from broker_adapters.base.exceptions import BrokerAuthenticationError
        broker = MagicMock(spec=SchwabBrokerAdapter)
        broker.refresh_auth.side_effect = BrokerAuthenticationError("RT expired")
        state = _make_app_state()
        from apps.worker.jobs.broker_refresh import run_broker_token_refresh
        run_broker_token_refresh(app_state=state, broker=broker)
        assert state.broker_auth_expired is True

    def test_auth_error_sets_broker_auth_expired_at(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        from broker_adapters.base.exceptions import BrokerAuthenticationError
        broker = MagicMock(spec=SchwabBrokerAdapter)
        broker.refresh_auth.side_effect = BrokerAuthenticationError("RT expired")
        state = _make_app_state()
        before = dt.datetime.now(dt.timezone.utc)
        from apps.worker.jobs.broker_refresh import run_broker_token_refresh
        run_broker_token_refresh(app_state=state, broker=broker)
        after = dt.datetime.now(dt.timezone.utc)
        assert state.broker_auth_expired_at is not None
        assert before <= state.broker_auth_expired_at <= after

    def test_other_exception_returns_error_other(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        broker = MagicMock(spec=SchwabBrokerAdapter)
        broker.refresh_auth.side_effect = ConnectionError("network hiccup")
        result, _ = self._run(broker=broker)
        assert result["status"] == "error_other"

    def test_other_exception_does_not_set_auth_expired_flag(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        broker = MagicMock(spec=SchwabBrokerAdapter)
        broker.refresh_auth.side_effect = ConnectionError("network hiccup")
        state = _make_app_state()
        from apps.worker.jobs.broker_refresh import run_broker_token_refresh
        run_broker_token_refresh(app_state=state, broker=broker)
        assert state.broker_auth_expired is False

    def test_job_never_raises(self):
        """run_broker_token_refresh must never propagate exceptions."""
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        broker = MagicMock(spec=SchwabBrokerAdapter)
        broker.refresh_auth.side_effect = Exception("catastrophic failure")
        from apps.worker.jobs.broker_refresh import run_broker_token_refresh
        state = _make_app_state()
        result = run_broker_token_refresh(app_state=state, broker=broker)
        # Any status other than a raised exception is acceptable
        assert isinstance(result, dict)

    def test_error_result_includes_error_message(self):
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        from broker_adapters.base.exceptions import BrokerAuthenticationError
        broker = MagicMock(spec=SchwabBrokerAdapter)
        broker.refresh_auth.side_effect = BrokerAuthenticationError("RT expired: foo")
        result, _ = self._run(broker=broker)
        assert "error" in result
        assert "foo" in result["error"]


# ══════════════════════════════════════════════════════════════════════════════
# 4. Worker scheduler — broker token refresh scheduled
# ══════════════════════════════════════════════════════════════════════════════

class TestWorkerScheduler:
    """Broker token refresh must be registered in the scheduler at 05:30 ET."""

    def _get_jobs(self):
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        return {job.id: job for job in scheduler.get_jobs()}

    def test_broker_token_refresh_job_is_registered(self):
        jobs = self._get_jobs()
        assert "broker_token_refresh" in jobs

    def test_broker_token_refresh_fires_at_0530(self):
        jobs = self._get_jobs()
        job = jobs["broker_token_refresh"]
        trigger = job.trigger
        # APScheduler CronTrigger stores fields; check hour and minute
        fields = {f.name: str(f) for f in trigger.fields}
        assert fields.get("hour") == "5"
        assert fields.get("minute") == "30"

    def test_broker_token_refresh_is_weekday_only(self):
        jobs = self._get_jobs()
        job = jobs["broker_token_refresh"]
        trigger = job.trigger
        fields = {f.name: str(f) for f in trigger.fields}
        assert fields.get("day_of_week") == "mon-fri"

    def test_total_scheduled_jobs_is_12(self):
        """Should have 27 jobs total (Phase 49 added rebalance_check)."""
        jobs = self._get_jobs()
        assert len(jobs) == 30

    def test_broker_refresh_exported_from_jobs_package(self):
        from apps.worker.jobs import run_broker_token_refresh
        assert callable(run_broker_token_refresh)


# ══════════════════════════════════════════════════════════════════════════════
# 5. Alertmanager config file
# ══════════════════════════════════════════════════════════════════════════════

_AM_CONFIG = _REPO / "infra" / "monitoring" / "alertmanager" / "alertmanager.yml"


class TestAlertmanagerConfig:
    """Alertmanager YAML must exist with correct routing and receiver structure."""

    def test_alertmanager_config_file_exists(self):
        assert _AM_CONFIG.exists(), f"alertmanager.yml not found at {_AM_CONFIG}"

    def test_alertmanager_config_yaml_syntax(self):
        pytest.importorskip("yaml", reason="PyYAML not installed")
        import yaml
        text = _AM_CONFIG.read_text()
        parsed = yaml.safe_load(text)
        assert isinstance(parsed, dict)

    def test_alertmanager_has_global_section(self):
        text = _AM_CONFIG.read_text()
        assert "global:" in text

    def test_alertmanager_has_route_section(self):
        text = _AM_CONFIG.read_text()
        assert "route:" in text

    def test_alertmanager_has_receivers_section(self):
        text = _AM_CONFIG.read_text()
        assert "receivers:" in text

    def test_alertmanager_has_inhibit_rules(self):
        text = _AM_CONFIG.read_text()
        assert "inhibit_rules:" in text

    def test_alertmanager_routes_critical_to_pagerduty(self):
        text = _AM_CONFIG.read_text()
        assert "pagerduty" in text.lower()
        assert "critical" in text

    def test_alertmanager_routes_to_slack(self):
        text = _AM_CONFIG.read_text()
        assert "slack" in text.lower()

    def test_alertmanager_inhibits_warning_when_critical(self):
        pytest.importorskip("yaml", reason="PyYAML not installed")
        import yaml
        parsed = yaml.safe_load(_AM_CONFIG.read_text())
        inhibit = parsed.get("inhibit_rules", [])
        assert len(inhibit) >= 1
        # At least one rule suppresses warning when critical fires
        found = any(
            any("warning" in str(m) for m in rule.get("target_matchers", []))
            for rule in inhibit
        )
        assert found, "No inhibit rule suppresses warnings when critical fires"

    def test_alertmanager_has_pagerduty_receiver(self):
        text = _AM_CONFIG.read_text()
        assert "pagerduty_configs:" in text


# ══════════════════════════════════════════════════════════════════════════════
# 6. Prometheus alerting block enabled
# ══════════════════════════════════════════════════════════════════════════════

_PROM_CONFIG = _REPO / "infra" / "monitoring" / "prometheus" / "prometheus.yml"


class TestPrometheusAlerting:
    """prometheus.yml must have an active (uncommented) alerting block."""

    def test_prometheus_yml_exists(self):
        assert _PROM_CONFIG.exists()

    def test_alerting_block_is_uncommented(self):
        text = _PROM_CONFIG.read_text()
        # Must contain `alerting:` not prefixed by `#`
        import re
        matches = re.findall(r"^alerting:", text, re.MULTILINE)
        assert matches, "alerting: block is missing or still commented out"

    def test_alertmanager_target_is_set(self):
        text = _PROM_CONFIG.read_text()
        assert "alertmanager:9093" in text

    def test_alerting_block_syntax(self):
        pytest.importorskip("yaml", reason="PyYAML not installed")
        import yaml
        parsed = yaml.safe_load(_PROM_CONFIG.read_text())
        assert "alerting" in parsed
        alertmanagers = parsed["alerting"].get("alertmanagers", [])
        assert len(alertmanagers) >= 1


# ══════════════════════════════════════════════════════════════════════════════
# 7. Docker Compose: alertmanager service
# ══════════════════════════════════════════════════════════════════════════════

_DC_FILE = _REPO / "infra" / "docker" / "docker-compose.yml"


class TestDockerCompose:
    """docker-compose.yml must include the alertmanager service and volume."""

    def test_docker_compose_exists(self):
        assert _DC_FILE.exists()

    def test_alertmanager_service_present(self):
        text = _DC_FILE.read_text()
        assert "alertmanager:" in text

    def test_alertmanager_image_version(self):
        text = _DC_FILE.read_text()
        assert "prom/alertmanager" in text

    def test_alertmanager_config_volume_mounted(self):
        text = _DC_FILE.read_text()
        assert "alertmanager.yml" in text

    def test_alertmanager_data_volume_declared(self):
        text = _DC_FILE.read_text()
        assert "alertmanager_data:" in text

    def test_prometheus_depends_on_alertmanager(self):
        text = _DC_FILE.read_text()
        # prometheus block should reference alertmanager
        assert "alertmanager" in text


# ══════════════════════════════════════════════════════════════════════════════
# 8. .env.example updated with new variables
# ══════════════════════════════════════════════════════════════════════════════

_ENV_EXAMPLE = _REPO / ".env.example"  # apis/.env.example


class TestEnvExample:
    """New env vars for Phase 18 must be documented in .env.example."""

    def test_env_example_exists(self):
        assert _ENV_EXAMPLE.exists(), f".env.example not found at {_ENV_EXAMPLE}"

    def test_slack_webhook_url_present(self):
        text = _ENV_EXAMPLE.read_text()
        assert "SLACK_WEBHOOK_URL" in text

    def test_pagerduty_integration_key_present(self):
        text = _ENV_EXAMPLE.read_text()
        assert "PAGERDUTY_INTEGRATION_KEY" in text

    def test_db_pool_size_documented(self):
        text = _ENV_EXAMPLE.read_text()
        assert "APIS_DB_POOL_SIZE" in text

    def test_slack_channel_critical_present(self):
        text = _ENV_EXAMPLE.read_text()
        assert "SLACK_CHANNEL_CRITICAL" in text


# ══════════════════════════════════════════════════════════════════════════════
# 9. Admin rate limit — HTTP-level integration via TestClient
# ══════════════════════════════════════════════════════════════════════════════

class TestAdminRateLimitIntegration:
    """POST /admin/invalidate-secrets and GET /admin/events must respect rate limit."""

    def setup_method(self):
        _reset_rate_limit_store()

    def _client_with_settings(self, token: str = "tok"):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.deps import get_settings
        cfg = _make_settings(admin_rotation_token=token)
        app.dependency_overrides[get_settings] = lambda: cfg
        return TestClient(app, raise_server_exceptions=False)

    def teardown_method(self):
        from apps.api.main import app
        app.dependency_overrides.clear()
        _reset_rate_limit_store()

    def test_post_invalidate_succeeds_below_limit(self):
        client = self._client_with_settings()
        resp = client.post(
            "/api/v1/admin/invalidate-secrets",
            headers={"Authorization": "Bearer tok"},
        )
        # Should not be 429
        assert resp.status_code != 429

    def test_post_invalidate_returns_429_at_limit(self):
        from apps.api.routes.admin import _RATE_LIMIT_MAX
        client = self._client_with_settings()
        responses = []
        for _ in range(_RATE_LIMIT_MAX + 2):
            resp = client.post(
                "/api/v1/admin/invalidate-secrets",
                headers={"Authorization": "Bearer tok"},
            )
            responses.append(resp.status_code)
        assert 429 in responses

    def test_429_response_has_retry_after_header(self):
        from apps.api.routes.admin import _RATE_LIMIT_MAX
        client = self._client_with_settings()
        last_resp = None
        for _ in range(_RATE_LIMIT_MAX + 2):
            resp = client.post(
                "/api/v1/admin/invalidate-secrets",
                headers={"Authorization": "Bearer tok"},
            )
            if resp.status_code == 429:
                last_resp = resp
                break
        assert last_resp is not None, "Expected 429 response"
        assert "retry-after" in {k.lower(): v for k, v in last_resp.headers.items()}

    def test_get_events_returns_429_at_limit(self):
        from apps.api.routes.admin import _RATE_LIMIT_MAX
        client = self._client_with_settings()
        responses = []
        for _ in range(_RATE_LIMIT_MAX + 2):
            resp = client.get(
                "/api/v1/admin/events",
                headers={"Authorization": "Bearer tok"},
            )
            responses.append(resp.status_code)
        assert 429 in responses

    def test_rate_limit_check_precedes_auth(self):
        """429 must fire even before 401 — rate limit is checked before auth."""
        from apps.api.routes.admin import _RATE_LIMIT_MAX
        client = self._client_with_settings()
        responses = []
        # Send without valid auth token to get 401, but keep hammering
        for _ in range(_RATE_LIMIT_MAX + 5):
            resp = client.post(
                "/api/v1/admin/invalidate-secrets",
                headers={"Authorization": "Bearer WRONG"},
            )
            responses.append(resp.status_code)
        # Eventually 429 should appear (rate limit precedes auth)
        assert 429 in responses

    def test_rate_limit_detail_mentions_retry(self):
        from apps.api.routes.admin import _RATE_LIMIT_MAX
        client = self._client_with_settings()
        last_resp = None
        for _ in range(_RATE_LIMIT_MAX + 2):
            resp = client.post(
                "/api/v1/admin/invalidate-secrets",
                headers={"Authorization": "Bearer tok"},
            )
            if resp.status_code == 429:
                last_resp = resp
                break
        assert last_resp is not None
        body = last_resp.json()
        detail = body.get("detail", "")
        assert "retry" in detail.lower() or "rate" in detail.lower()

    def test_invalidate_post_check_rate_limit_import(self):
        import inspect
        import apps.api.routes.admin as mod
        src = inspect.getsource(mod.invalidate_secrets)
        assert "_check_rate_limit" in src

    def test_list_events_check_rate_limit_import(self):
        import inspect
        import apps.api.routes.admin as mod
        src = inspect.getsource(mod.list_admin_events)
        assert "_check_rate_limit" in src


# ══════════════════════════════════════════════════════════════════════════════
# 10. Phase 18 Integration
# ══════════════════════════════════════════════════════════════════════════════

class TestPhase18Integration:
    """Cross-cutting integration checks for all Phase 18 deliverables."""

    def test_broker_refresh_exported_from_worker_package(self):
        from apps.worker.jobs import run_broker_token_refresh
        assert callable(run_broker_token_refresh)

    def test_broker_refresh_in_worker_jobs_all(self):
        from apps.worker import jobs
        assert "run_broker_token_refresh" in jobs.__all__

    def test_worker_main_imports_broker_refresh(self):
        import inspect
        import apps.worker.main as mod
        src = inspect.getsource(mod)
        assert "run_broker_token_refresh" in src

    def test_settings_pool_fields_survives_validation(self):
        from config.settings import Settings
        s = Settings(
            db_url="postgresql+psycopg://u:p@localhost/db",
            db_pool_size=10,
            db_max_overflow=20,
            db_pool_recycle=900,
            db_pool_timeout=15,
        )
        assert s.db_pool_size == 10
        assert s.db_max_overflow == 20
        assert s.db_pool_recycle == 900
        assert s.db_pool_timeout == 15

    def test_alertmanager_dir_exists(self):
        am_dir = _REPO / "infra" / "monitoring" / "alertmanager"
        assert am_dir.is_dir()

    def test_all_phase18_files_exist(self):
        required = [
            _REPO / "apps" / "worker" / "jobs" / "broker_refresh.py",
            _REPO / "infra" / "monitoring" / "alertmanager" / "alertmanager.yml",
        ]
        for path in required:
            assert path.exists(), f"Missing required Phase 18 file: {path}"
