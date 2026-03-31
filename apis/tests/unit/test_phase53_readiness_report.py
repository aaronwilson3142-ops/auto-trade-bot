"""
Phase 53 — Automated Live-Mode Readiness Report

Tests cover:
  1. ReadinessGateRow + ReadinessReport models
  2. ReadinessReportService — PASS / WARN / FAIL / NO_GATE scenarios
  3. ReadinessReportService — graceful degradation (gate error)
  4. run_readiness_report_update job — ok / error / empty-mode paths
  5. GET /system/readiness-report route — 200 / 503 (no data)
  6. Dashboard readiness section rendering
  7. Scheduler job count assertion (30 total)
"""
from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# 1. Model tests
# ---------------------------------------------------------------------------

class TestReadinessGateRowModel:
    def test_default_detail_empty(self):
        from services.readiness.models import ReadinessGateRow
        row = ReadinessGateRow(
            gate_name="test_gate",
            description="A test gate",
            status="PASS",
            actual_value="5",
            required_value=">= 5",
        )
        assert row.detail == ""

    def test_all_fields_set(self):
        from services.readiness.models import ReadinessGateRow
        row = ReadinessGateRow(
            gate_name="kill_switch_off",
            description="Kill switch must be off",
            status="FAIL",
            actual_value="True",
            required_value="False",
            detail="Disable kill switch first.",
        )
        assert row.gate_name == "kill_switch_off"
        assert row.status == "FAIL"
        assert "Disable" in row.detail

    def test_status_pass(self):
        from services.readiness.models import ReadinessGateRow
        row = ReadinessGateRow("g", "d", "PASS", "ok", "ok")
        assert row.status == "PASS"

    def test_status_warn(self):
        from services.readiness.models import ReadinessGateRow
        row = ReadinessGateRow("g", "d", "WARN", "3", ">= 10")
        assert row.status == "WARN"


class TestReadinessReportModel:
    def _make(self, **kwargs):
        from services.readiness.models import ReadinessReport
        defaults = dict(
            generated_at=dt.datetime(2026, 3, 21, 18, 45, tzinfo=dt.UTC),
            current_mode="paper",
            target_mode="human_approved",
            overall_status="PASS",
        )
        defaults.update(kwargs)
        return ReadinessReport(**defaults)

    def test_is_ready_pass(self):
        r = self._make(overall_status="PASS")
        assert r.is_ready is True

    def test_is_ready_fail(self):
        r = self._make(overall_status="FAIL")
        assert r.is_ready is False

    def test_is_ready_warn(self):
        r = self._make(overall_status="WARN")
        assert r.is_ready is False

    def test_is_ready_no_gate(self):
        r = self._make(overall_status="NO_GATE")
        assert r.is_ready is False

    def test_gate_count_empty(self):
        r = self._make()
        assert r.gate_count == 0

    def test_gate_count_with_rows(self):
        from services.readiness.models import ReadinessGateRow, ReadinessReport
        rows = [ReadinessGateRow(f"g{i}", "d", "PASS", "v", "r") for i in range(3)]
        r = ReadinessReport(
            generated_at=dt.datetime.now(dt.UTC),
            current_mode="paper",
            target_mode="human_approved",
            overall_status="PASS",
            gate_rows=rows,
        )
        assert r.gate_count == 3

    def test_defaults(self):
        r = self._make()
        assert r.pass_count == 0
        assert r.warn_count == 0
        assert r.fail_count == 0
        assert r.recommendation == ""
        assert r.gate_rows == []


# ---------------------------------------------------------------------------
# 2. ReadinessReportService — PASS scenario
# ---------------------------------------------------------------------------

class TestReadinessReportServicePass:
    def _make_app_state(self, **overrides):
        from apps.api.state import ApiAppState
        s = ApiAppState()
        for k, v in overrides.items():
            setattr(s, k, v)
        return s

    def _make_settings(self, mode="paper"):
        from config.settings import OperatingMode, Settings
        s = Settings()
        s.operating_mode = OperatingMode(mode)
        s.kill_switch = False
        return s

    def test_returns_readiness_report(self):
        from services.readiness.service import ReadinessReportService
        svc = ReadinessReportService()
        state = self._make_app_state(
            paper_cycle_count=10,
            evaluation_history=[MagicMock(daily_return_pct=0.01)] * 10,
            portfolio_state=MagicMock(),
        )
        settings = self._make_settings("paper")
        report = svc.generate_report(app_state=state, settings=settings)
        from services.readiness.models import ReadinessReport
        assert isinstance(report, ReadinessReport)

    def test_current_mode_in_report(self):
        from services.readiness.service import ReadinessReportService
        svc = ReadinessReportService()
        state = self._make_app_state()
        settings = self._make_settings("paper")
        report = svc.generate_report(app_state=state, settings=settings)
        assert report.current_mode == "paper"
        assert report.target_mode == "human_approved"

    def test_generated_at_is_utc(self):
        from services.readiness.service import ReadinessReportService
        svc = ReadinessReportService()
        state = self._make_app_state()
        settings = self._make_settings("paper")
        report = svc.generate_report(app_state=state, settings=settings)
        assert report.generated_at.tzinfo is not None

    def test_gate_rows_populated(self):
        from services.readiness.service import ReadinessReportService
        svc = ReadinessReportService()
        state = self._make_app_state(
            paper_cycle_count=10,
            evaluation_history=[MagicMock(daily_return_pct=0.01)] * 10,
            portfolio_state=MagicMock(),
        )
        settings = self._make_settings("paper")
        report = svc.generate_report(app_state=state, settings=settings)
        assert len(report.gate_rows) > 0

    def test_overall_counts_consistent(self):
        from services.readiness.service import ReadinessReportService
        svc = ReadinessReportService()
        state = self._make_app_state()
        settings = self._make_settings("paper")
        report = svc.generate_report(app_state=state, settings=settings)
        total = report.pass_count + report.warn_count + report.fail_count
        assert total == report.gate_count


# ---------------------------------------------------------------------------
# 3. ReadinessReportService — FAIL scenario
# ---------------------------------------------------------------------------

class TestReadinessReportServiceFail:
    def _make_app_state(self, **overrides):
        from apps.api.state import ApiAppState
        s = ApiAppState()
        for k, v in overrides.items():
            setattr(s, k, v)
        return s

    def _make_settings(self, mode="paper"):
        from config.settings import OperatingMode, Settings
        s = Settings()
        s.operating_mode = OperatingMode(mode)
        s.kill_switch = True  # force a fail
        return s

    def test_fail_overall_status_when_kill_switch(self):
        from services.readiness.service import ReadinessReportService
        svc = ReadinessReportService()
        state = self._make_app_state()
        settings = self._make_settings("paper")
        report = svc.generate_report(app_state=state, settings=settings)
        assert report.overall_status == "FAIL"
        assert report.fail_count >= 1

    def test_fail_recommendation_mentions_gate_name(self):
        from services.readiness.service import ReadinessReportService
        svc = ReadinessReportService()
        state = self._make_app_state()
        settings = self._make_settings("paper")
        report = svc.generate_report(app_state=state, settings=settings)
        assert "fail" in report.recommendation.lower() or "kill" in report.recommendation.lower()

    def test_fail_rows_have_fail_status(self):
        from services.readiness.service import ReadinessReportService
        svc = ReadinessReportService()
        state = self._make_app_state()
        settings = self._make_settings("paper")
        report = svc.generate_report(app_state=state, settings=settings)
        fail_rows = [r for r in report.gate_rows if r.status == "FAIL"]
        assert len(fail_rows) >= 1

    def test_is_ready_false_on_fail(self):
        from services.readiness.service import ReadinessReportService
        svc = ReadinessReportService()
        state = self._make_app_state()
        settings = self._make_settings("paper")
        report = svc.generate_report(app_state=state, settings=settings)
        assert report.is_ready is False


# ---------------------------------------------------------------------------
# 4. ReadinessReportService — NO_GATE scenario
# ---------------------------------------------------------------------------

class TestReadinessReportServiceNoGate:
    def _make_settings(self, mode):
        from config.settings import OperatingMode, Settings
        s = Settings()
        s.operating_mode = OperatingMode(mode)
        return s

    def _make_state(self):
        from apps.api.state import ApiAppState
        return ApiAppState()

    def test_research_mode_no_gate(self):
        from services.readiness.service import ReadinessReportService
        svc = ReadinessReportService()
        report = svc.generate_report(
            app_state=self._make_state(),
            settings=self._make_settings("research"),
        )
        assert report.overall_status == "NO_GATE"
        assert report.target_mode == "n/a"

    def test_backtest_mode_no_gate(self):
        from services.readiness.service import ReadinessReportService
        svc = ReadinessReportService()
        report = svc.generate_report(
            app_state=self._make_state(),
            settings=self._make_settings("backtest"),
        )
        assert report.overall_status == "NO_GATE"

    def test_no_gate_recommendation(self):
        from services.readiness.service import ReadinessReportService
        svc = ReadinessReportService()
        report = svc.generate_report(
            app_state=self._make_state(),
            settings=self._make_settings("research"),
        )
        assert "No gated promotion" in report.recommendation

    def test_no_gate_empty_rows(self):
        from services.readiness.service import ReadinessReportService
        svc = ReadinessReportService()
        report = svc.generate_report(
            app_state=self._make_state(),
            settings=self._make_settings("research"),
        )
        assert report.gate_rows == []
        assert report.gate_count == 0


# ---------------------------------------------------------------------------
# 5. ReadinessReportService — WARN scenario
# ---------------------------------------------------------------------------

class TestReadinessReportServiceWarn:
    def test_warn_when_insufficient_sharpe_obs(self):
        """WARN produced when eval_history has <10 observations."""
        from apps.api.state import ApiAppState
        from config.settings import OperatingMode, Settings
        from services.readiness.service import ReadinessReportService

        svc = ReadinessReportService()
        state = ApiAppState()
        # Give enough cycles + eval entries but few Sharpe observations
        state.paper_cycle_count = 10
        # 3 eval entries → Sharpe gate WARNs (< 10 obs)
        state.evaluation_history = [MagicMock(daily_return_pct=0.01)] * 3
        state.portfolio_state = MagicMock()
        state.kill_switch_active = False

        settings = Settings()
        settings.operating_mode = OperatingMode.PAPER
        settings.kill_switch = False

        report = svc.generate_report(app_state=state, settings=settings)
        warn_rows = [r for r in report.gate_rows if r.status == "WARN"]
        # At least Sharpe gate should WARN with only 3 observations
        assert len(warn_rows) >= 1

    def test_warn_overall_status(self):
        from services.readiness.models import ReadinessGateRow
        from services.readiness.service import ReadinessReportService

        # Build a WARN report directly via _build_recommendation
        rows = [
            ReadinessGateRow("g1", "d", "PASS", "v", "r"),
            ReadinessGateRow("g2", "d", "WARN", "v", "r"),
        ]
        rec = ReadinessReportService._build_recommendation(
            overall_status="WARN",
            current_mode="paper",
            target_mode="human_approved",
            pass_count=1,
            warn_count=1,
            fail_count=0,
            gate_rows=rows,
        )
        assert "warning" in rec.lower() or "warn" in rec.lower()


# ---------------------------------------------------------------------------
# 6. run_readiness_report_update job
# ---------------------------------------------------------------------------

class TestRunReadinessReportUpdateJob:
    def _make_state(self):
        from apps.api.state import ApiAppState
        return ApiAppState()

    def _make_settings(self, mode="paper"):
        from config.settings import OperatingMode, Settings
        s = Settings()
        s.operating_mode = OperatingMode(mode)
        s.kill_switch = False
        return s

    def test_job_returns_dict(self):
        from apps.worker.jobs.readiness import run_readiness_report_update
        state = self._make_state()
        result = run_readiness_report_update(app_state=state, settings=self._make_settings())
        assert isinstance(result, dict)

    def test_job_writes_report_to_state(self):
        from apps.worker.jobs.readiness import run_readiness_report_update
        state = self._make_state()
        run_readiness_report_update(app_state=state, settings=self._make_settings())
        assert state.latest_readiness_report is not None

    def test_job_writes_computed_at(self):
        from apps.worker.jobs.readiness import run_readiness_report_update
        state = self._make_state()
        run_readiness_report_update(app_state=state, settings=self._make_settings())
        assert state.readiness_report_computed_at is not None

    def test_job_ok_status(self):
        from apps.worker.jobs.readiness import run_readiness_report_update
        state = self._make_state()
        result = run_readiness_report_update(app_state=state, settings=self._make_settings())
        assert result["status"] == "ok"

    def test_job_returns_overall_status(self):
        from apps.worker.jobs.readiness import run_readiness_report_update
        state = self._make_state()
        result = run_readiness_report_update(app_state=state, settings=self._make_settings())
        assert result["overall_status"] in ("PASS", "WARN", "FAIL", "NO_GATE")

    def test_job_returns_gate_count(self):
        from apps.worker.jobs.readiness import run_readiness_report_update
        state = self._make_state()
        result = run_readiness_report_update(app_state=state, settings=self._make_settings())
        assert isinstance(result["gate_count"], int)

    def test_job_returns_computed_at_iso(self):
        from apps.worker.jobs.readiness import run_readiness_report_update
        state = self._make_state()
        result = run_readiness_report_update(app_state=state, settings=self._make_settings())
        # Should be an ISO datetime string
        dt.datetime.fromisoformat(result["computed_at"])

    def test_job_error_path_returns_error_status(self):
        from apps.api.state import ApiAppState
        from apps.worker.jobs.readiness import run_readiness_report_update

        state = ApiAppState()
        # Patch the service class at its source module so the lazy import picks it up
        with patch(
            "services.readiness.service.ReadinessReportService.generate_report",
            side_effect=Exception("boom"),
        ):
            result = run_readiness_report_update(app_state=state)
        assert result["status"] == "error"
        assert result["error"] is not None

    def test_job_error_path_does_not_raise(self):
        from apps.api.state import ApiAppState
        from apps.worker.jobs.readiness import run_readiness_report_update

        state = ApiAppState()
        with patch(
            "services.readiness.service.ReadinessReportService.generate_report",
            side_effect=RuntimeError("test_error"),
        ):
            result = run_readiness_report_update(app_state=state)
        # Must not raise; returns error dict
        assert isinstance(result, dict)

    def test_job_no_gate_mode(self):
        from apps.worker.jobs.readiness import run_readiness_report_update
        state = self._make_state()
        result = run_readiness_report_update(
            app_state=state,
            settings=self._make_settings("research"),
        )
        assert result["status"] == "ok"
        assert result["overall_status"] == "NO_GATE"

    def test_job_uses_get_settings_fallback(self):
        from apps.worker.jobs.readiness import run_readiness_report_update
        state = self._make_state()
        # No settings arg — should fall back to get_settings()
        result = run_readiness_report_update(app_state=state)
        assert "status" in result


# ---------------------------------------------------------------------------
# 7. GET /system/readiness-report route
# ---------------------------------------------------------------------------

class TestReadinessReportRoute:
    def _make_state(self):
        from apps.api.state import ApiAppState
        return ApiAppState()

    def _make_report(self):
        from services.readiness.models import ReadinessGateRow, ReadinessReport
        rows = [
            ReadinessGateRow("kill_switch_off", "Kill switch off", "PASS", "False", "False"),
            ReadinessGateRow("min_paper_cycles", "Min cycles", "PASS", "10", ">= 5"),
        ]
        return ReadinessReport(
            generated_at=dt.datetime(2026, 3, 21, 18, 45, tzinfo=dt.UTC),
            current_mode="paper",
            target_mode="human_approved",
            overall_status="PASS",
            gate_rows=rows,
            pass_count=2,
            warn_count=0,
            fail_count=0,
            recommendation="All gates satisfied.",
        )

    def test_503_when_no_report(self):
        from fastapi.testclient import TestClient

        from apps.api.main import app
        from apps.api.state import reset_app_state

        reset_app_state()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/system/readiness-report")
        assert resp.status_code == 503

    def test_200_when_report_available(self):
        from fastapi.testclient import TestClient

        from apps.api.main import app
        from apps.api.state import get_app_state, reset_app_state

        reset_app_state()
        state = get_app_state()
        state.latest_readiness_report = self._make_report()

        client = TestClient(app)
        resp = client.get("/api/v1/system/readiness-report")
        assert resp.status_code == 200

    def test_response_has_overall_status(self):
        from fastapi.testclient import TestClient

        from apps.api.main import app
        from apps.api.state import get_app_state, reset_app_state

        reset_app_state()
        state = get_app_state()
        state.latest_readiness_report = self._make_report()

        client = TestClient(app)
        resp = client.get("/api/v1/system/readiness-report")
        data = resp.json()
        assert "overall_status" in data
        assert data["overall_status"] == "PASS"

    def test_response_has_gate_rows(self):
        from fastapi.testclient import TestClient

        from apps.api.main import app
        from apps.api.state import get_app_state, reset_app_state

        reset_app_state()
        state = get_app_state()
        state.latest_readiness_report = self._make_report()

        client = TestClient(app)
        resp = client.get("/api/v1/system/readiness-report")
        data = resp.json()
        assert isinstance(data["gate_rows"], list)
        assert len(data["gate_rows"]) == 2

    def test_response_is_ready_true(self):
        from fastapi.testclient import TestClient

        from apps.api.main import app
        from apps.api.state import get_app_state, reset_app_state

        reset_app_state()
        state = get_app_state()
        state.latest_readiness_report = self._make_report()

        client = TestClient(app)
        resp = client.get("/api/v1/system/readiness-report")
        assert resp.json()["is_ready"] is True

    def test_response_recommendation_present(self):
        from fastapi.testclient import TestClient

        from apps.api.main import app
        from apps.api.state import get_app_state, reset_app_state

        reset_app_state()
        state = get_app_state()
        state.latest_readiness_report = self._make_report()

        client = TestClient(app)
        resp = client.get("/api/v1/system/readiness-report")
        assert "recommendation" in resp.json()


# ---------------------------------------------------------------------------
# 8. Dashboard section rendering
# ---------------------------------------------------------------------------

class TestDashboardReadinessSection:
    def _make_state_no_report(self):
        from apps.api.state import ApiAppState
        return ApiAppState()

    def _make_state_with_report(self, overall_status="PASS"):
        from apps.api.state import ApiAppState
        from services.readiness.models import ReadinessGateRow, ReadinessReport
        state = ApiAppState()
        rows = [
            ReadinessGateRow("kill_switch_off", "Kill switch", "PASS", "False", "False"),
        ]
        state.latest_readiness_report = ReadinessReport(
            generated_at=dt.datetime(2026, 3, 21, 18, 45, tzinfo=dt.UTC),
            current_mode="paper",
            target_mode="human_approved",
            overall_status=overall_status,
            gate_rows=rows,
            pass_count=1 if overall_status == "PASS" else 0,
            warn_count=1 if overall_status == "WARN" else 0,
            fail_count=1 if overall_status == "FAIL" else 0,
            recommendation="Test recommendation.",
        )
        state.readiness_report_computed_at = dt.datetime(2026, 3, 21, 18, 45, tzinfo=dt.UTC)
        return state

    def test_no_report_shows_placeholder(self):
        from apps.dashboard.router import _render_readiness_section
        html = _render_readiness_section(self._make_state_no_report())
        assert "No readiness report yet" in html

    def test_report_shows_overall_status_pass(self):
        from apps.dashboard.router import _render_readiness_section
        html = _render_readiness_section(self._make_state_with_report("PASS"))
        assert "PASS" in html

    def test_report_shows_overall_status_fail(self):
        from apps.dashboard.router import _render_readiness_section
        html = _render_readiness_section(self._make_state_with_report("FAIL"))
        assert "FAIL" in html

    def test_report_shows_overall_status_warn(self):
        from apps.dashboard.router import _render_readiness_section
        html = _render_readiness_section(self._make_state_with_report("WARN"))
        assert "WARN" in html

    def test_report_shows_gate_table(self):
        from apps.dashboard.router import _render_readiness_section
        html = _render_readiness_section(self._make_state_with_report("PASS"))
        assert "kill_switch_off" in html

    def test_report_shows_recommendation(self):
        from apps.dashboard.router import _render_readiness_section
        html = _render_readiness_section(self._make_state_with_report("PASS"))
        assert "Test recommendation" in html

    def test_section_rendered_in_full_page(self):
        from fastapi.testclient import TestClient

        from apps.api.main import app
        from apps.api.state import get_app_state, reset_app_state

        reset_app_state()
        state = get_app_state()
        state.latest_readiness_report = self._make_state_with_report("PASS").latest_readiness_report

        client = TestClient(app)
        resp = client.get("/dashboard/")
        assert resp.status_code == 200
        assert "Readiness" in resp.text


# ---------------------------------------------------------------------------
# 9. AppState field defaults
# ---------------------------------------------------------------------------

class TestAppStateReadinessFields:
    def test_latest_readiness_report_default_none(self):
        from apps.api.state import ApiAppState
        s = ApiAppState()
        assert s.latest_readiness_report is None

    def test_readiness_report_computed_at_default_none(self):
        from apps.api.state import ApiAppState
        s = ApiAppState()
        assert s.readiness_report_computed_at is None

    def test_reset_app_state_clears_report(self):
        from apps.api.state import get_app_state, reset_app_state
        from services.readiness.models import ReadinessReport

        reset_app_state()
        state = get_app_state()
        state.latest_readiness_report = ReadinessReport(
            generated_at=dt.datetime.now(dt.UTC),
            current_mode="paper",
            target_mode="human_approved",
            overall_status="PASS",
        )
        reset_app_state()
        assert get_app_state().latest_readiness_report is None


# ---------------------------------------------------------------------------
# 10. Scheduler job count assertion (30 total)
# ---------------------------------------------------------------------------

class TestSchedulerJobCount:
    def test_scheduler_has_29_jobs(self):
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        jobs = scheduler.get_jobs()
        assert len(jobs) == 30, (
            f"Expected 30 scheduler jobs, got {len(jobs)}: "
            f"{[j.id for j in jobs]}"
        )

    def test_readiness_report_update_job_registered(self):
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        job_ids = {j.id for j in scheduler.get_jobs()}
        assert "readiness_report_update" in job_ids

    def test_readiness_job_scheduled_at_18_45(self):
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        job = next((j for j in scheduler.get_jobs() if j.id == "readiness_report_update"), None)
        assert job is not None
        trigger = job.trigger
        # CronTrigger — inspect fields
        fields = {f.name: f for f in trigger.fields}
        assert str(fields["hour"]) == "18"
        assert str(fields["minute"]) == "45"
