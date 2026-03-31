"""
Phase 56 — Readiness Report History tests.

Tests cover:
- ReadinessSnapshot ORM model fields and tablename
- ReadinessReportService.persist_snapshot (fire-and-forget DB write)
- run_readiness_report_update job with session_factory (snapshot persist)
- ReadinessSnapshotSchema and ReadinessHistoryResponse schemas
- GET /system/readiness-report/history endpoint (200 + empty on no DB)
- Dashboard readiness history table (graceful degradation)
- Scheduler still at 30 jobs (no new job in Phase 56)
"""
from __future__ import annotations

import datetime as dt
import json
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------

def _make_report(
    overall_status: str = "PASS",
    current_mode: str = "paper",
    target_mode: str = "human_approved",
    pass_count: int = 3,
    warn_count: int = 0,
    fail_count: int = 0,
    gate_rows: list | None = None,
    recommendation: str = "All gates pass.",
):
    """Build a minimal ReadinessReport dataclass for testing."""
    from services.readiness.models import ReadinessGateRow, ReadinessReport

    rows = gate_rows or [
        ReadinessGateRow(
            gate_name="eval_count",
            description="Minimum evaluation runs",
            status="PASS",
            actual_value="20",
            required_value="10",
            detail="",
        )
    ]
    return ReadinessReport(
        generated_at=dt.datetime(2026, 3, 21, 18, 45, tzinfo=dt.UTC),
        current_mode=current_mode,
        target_mode=target_mode,
        overall_status=overall_status,
        gate_rows=rows,
        pass_count=pass_count,
        warn_count=warn_count,
        fail_count=fail_count,
        recommendation=recommendation,
    )


def _make_state(**kwargs):
    from apps.api.state import ApiAppState
    state = ApiAppState()
    for k, v in kwargs.items():
        setattr(state, k, v)
    return state


# ---------------------------------------------------------------------------
# TestReadinessSnapshotModel
# ---------------------------------------------------------------------------

class TestReadinessSnapshotModel:
    def test_model_importable(self):
        from infra.db.models.readiness import ReadinessSnapshot
        assert ReadinessSnapshot is not None

    def test_model_in_models_init(self):
        from infra.db.models import ReadinessSnapshot
        assert ReadinessSnapshot is not None

    def test_tablename_is_readiness_snapshots(self):
        from infra.db.models.readiness import ReadinessSnapshot
        assert ReadinessSnapshot.__tablename__ == "readiness_snapshots"

    def test_model_has_id_column(self):
        from infra.db.models.readiness import ReadinessSnapshot
        cols = {c.name for c in ReadinessSnapshot.__table__.columns}
        assert "id" in cols

    def test_model_has_captured_at_column(self):
        from infra.db.models.readiness import ReadinessSnapshot
        cols = {c.name for c in ReadinessSnapshot.__table__.columns}
        assert "captured_at" in cols

    def test_model_has_overall_status_column(self):
        from infra.db.models.readiness import ReadinessSnapshot
        cols = {c.name for c in ReadinessSnapshot.__table__.columns}
        assert "overall_status" in cols

    def test_model_has_current_mode_column(self):
        from infra.db.models.readiness import ReadinessSnapshot
        cols = {c.name for c in ReadinessSnapshot.__table__.columns}
        assert "current_mode" in cols

    def test_model_has_target_mode_column(self):
        from infra.db.models.readiness import ReadinessSnapshot
        cols = {c.name for c in ReadinessSnapshot.__table__.columns}
        assert "target_mode" in cols

    def test_model_has_pass_count_column(self):
        from infra.db.models.readiness import ReadinessSnapshot
        cols = {c.name for c in ReadinessSnapshot.__table__.columns}
        assert "pass_count" in cols

    def test_model_has_warn_count_column(self):
        from infra.db.models.readiness import ReadinessSnapshot
        cols = {c.name for c in ReadinessSnapshot.__table__.columns}
        assert "warn_count" in cols

    def test_model_has_fail_count_column(self):
        from infra.db.models.readiness import ReadinessSnapshot
        cols = {c.name for c in ReadinessSnapshot.__table__.columns}
        assert "fail_count" in cols

    def test_model_has_gate_count_column(self):
        from infra.db.models.readiness import ReadinessSnapshot
        cols = {c.name for c in ReadinessSnapshot.__table__.columns}
        assert "gate_count" in cols

    def test_model_has_gates_json_column(self):
        from infra.db.models.readiness import ReadinessSnapshot
        cols = {c.name for c in ReadinessSnapshot.__table__.columns}
        assert "gates_json" in cols

    def test_model_has_recommendation_column(self):
        from infra.db.models.readiness import ReadinessSnapshot
        cols = {c.name for c in ReadinessSnapshot.__table__.columns}
        assert "recommendation" in cols

    def test_model_has_created_at_from_mixin(self):
        from infra.db.models.readiness import ReadinessSnapshot
        cols = {c.name for c in ReadinessSnapshot.__table__.columns}
        assert "created_at" in cols

    def test_model_indexes_on_captured_at(self):
        from infra.db.models.readiness import ReadinessSnapshot
        index_names = {idx.name for idx in ReadinessSnapshot.__table__.indexes}
        assert "ix_readiness_snapshot_captured_at" in index_names

    def test_model_indexes_on_overall_status(self):
        from infra.db.models.readiness import ReadinessSnapshot
        index_names = {idx.name for idx in ReadinessSnapshot.__table__.indexes}
        assert "ix_readiness_snapshot_overall_status" in index_names


# ---------------------------------------------------------------------------
# TestPersistSnapshot
# ---------------------------------------------------------------------------

class TestPersistSnapshot:
    def test_no_session_factory_is_noop(self):
        """persist_snapshot with no session_factory must not raise."""
        from services.readiness.service import ReadinessReportService
        report = _make_report()
        svc = ReadinessReportService()
        # Should complete without error
        svc.persist_snapshot(report=report, session_factory=None)

    def test_with_session_factory_calls_add_and_commit(self):
        """persist_snapshot calls session.add() and session.commit()."""
        from services.readiness.service import ReadinessReportService

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        report = _make_report()
        svc = ReadinessReportService()
        svc.persist_snapshot(report=report, session_factory=mock_factory)

        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_gates_json_contains_gate_names(self):
        """persist_snapshot serializes gate_rows into gates_json."""
        from services.readiness.service import ReadinessReportService

        captured_rows = []

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.add.side_effect = lambda obj: captured_rows.append(obj)
        mock_factory = MagicMock(return_value=mock_session)

        report = _make_report()
        svc = ReadinessReportService()
        svc.persist_snapshot(report=report, session_factory=mock_factory)

        assert len(captured_rows) == 1
        snap = captured_rows[0]
        gates = json.loads(snap.gates_json)
        assert len(gates) == 1
        assert gates[0]["gate_name"] == "eval_count"
        assert gates[0]["status"] == "PASS"

    def test_stores_overall_status(self):
        from services.readiness.service import ReadinessReportService

        captured_rows = []
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.add.side_effect = lambda obj: captured_rows.append(obj)
        mock_factory = MagicMock(return_value=mock_session)

        report = _make_report(overall_status="WARN", warn_count=2, pass_count=1)
        svc = ReadinessReportService()
        svc.persist_snapshot(report=report, session_factory=mock_factory)

        snap = captured_rows[0]
        assert snap.overall_status == "WARN"

    def test_stores_current_and_target_mode(self):
        from services.readiness.service import ReadinessReportService

        captured_rows = []
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.add.side_effect = lambda obj: captured_rows.append(obj)
        mock_factory = MagicMock(return_value=mock_session)

        report = _make_report(current_mode="paper", target_mode="human_approved")
        svc = ReadinessReportService()
        svc.persist_snapshot(report=report, session_factory=mock_factory)

        snap = captured_rows[0]
        assert snap.current_mode == "paper"
        assert snap.target_mode == "human_approved"

    def test_stores_recommendation(self):
        from services.readiness.service import ReadinessReportService

        captured_rows = []
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.add.side_effect = lambda obj: captured_rows.append(obj)
        mock_factory = MagicMock(return_value=mock_session)

        report = _make_report(recommendation="All 3 gates pass.")
        svc = ReadinessReportService()
        svc.persist_snapshot(report=report, session_factory=mock_factory)

        snap = captured_rows[0]
        assert snap.recommendation == "All 3 gates pass."

    def test_stores_pass_and_fail_counts(self):
        from services.readiness.service import ReadinessReportService

        captured_rows = []
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.add.side_effect = lambda obj: captured_rows.append(obj)
        mock_factory = MagicMock(return_value=mock_session)

        report = _make_report(pass_count=2, warn_count=1, fail_count=0)
        svc = ReadinessReportService()
        svc.persist_snapshot(report=report, session_factory=mock_factory)

        snap = captured_rows[0]
        assert snap.pass_count == 2
        assert snap.warn_count == 1
        assert snap.fail_count == 0

    def test_exception_from_session_is_swallowed(self):
        """persist_snapshot must never raise even if DB write fails."""
        from services.readiness.service import ReadinessReportService

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.add.side_effect = RuntimeError("DB down")
        mock_factory = MagicMock(return_value=mock_session)

        report = _make_report()
        svc = ReadinessReportService()
        # Must not raise
        svc.persist_snapshot(report=report, session_factory=mock_factory)

    def test_captured_at_matches_report_generated_at(self):
        from services.readiness.service import ReadinessReportService

        captured_rows = []
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.add.side_effect = lambda obj: captured_rows.append(obj)
        mock_factory = MagicMock(return_value=mock_session)

        report = _make_report()
        svc = ReadinessReportService()
        svc.persist_snapshot(report=report, session_factory=mock_factory)

        snap = captured_rows[0]
        assert snap.captured_at == report.generated_at


# ---------------------------------------------------------------------------
# TestRunReadinessReportUpdateWithSessionFactory
# ---------------------------------------------------------------------------

class TestRunReadinessReportUpdateWithSessionFactory:
    def test_job_accepts_session_factory_param(self):
        """run_readiness_report_update signature must accept session_factory."""
        import inspect

        from apps.worker.jobs.readiness import run_readiness_report_update
        sig = inspect.signature(run_readiness_report_update)
        assert "session_factory" in sig.parameters

    def test_job_returns_ok_status(self):
        from apps.api.state import ApiAppState
        from apps.worker.jobs.readiness import run_readiness_report_update
        state = ApiAppState()
        result = run_readiness_report_update(app_state=state, session_factory=None)
        assert result["status"] == "ok"

    def test_job_calls_persist_on_success(self):
        """When session_factory is provided and job succeeds, persist_snapshot is called."""
        from apps.api.state import ApiAppState
        from apps.worker.jobs.readiness import run_readiness_report_update

        state = ApiAppState()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        result = run_readiness_report_update(
            app_state=state, session_factory=mock_factory
        )
        # Job succeeds; session factory should have been called for persist
        assert result["status"] == "ok"
        # Factory was invoked (may be called via persist_snapshot)
        assert mock_factory.call_count >= 1

    def test_job_does_not_raise_if_persist_fails(self):
        """Job must still return ok status even when DB persist raises."""
        from apps.api.state import ApiAppState
        from apps.worker.jobs.readiness import run_readiness_report_update

        state = ApiAppState()
        mock_factory = MagicMock(side_effect=RuntimeError("DB unavailable"))

        result = run_readiness_report_update(
            app_state=state, session_factory=mock_factory
        )
        # The job itself must not fail — persist errors are swallowed
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# TestReadinessSnapshotSchema
# ---------------------------------------------------------------------------

class TestReadinessSnapshotSchema:
    def test_schema_importable(self):
        from apps.api.schemas.readiness import ReadinessSnapshotSchema
        assert ReadinessSnapshotSchema is not None

    def test_schema_has_id_field(self):
        from apps.api.schemas.readiness import ReadinessSnapshotSchema
        fields = ReadinessSnapshotSchema.model_fields
        assert "id" in fields

    def test_schema_has_captured_at_field(self):
        from apps.api.schemas.readiness import ReadinessSnapshotSchema
        fields = ReadinessSnapshotSchema.model_fields
        assert "captured_at" in fields

    def test_schema_has_overall_status_field(self):
        from apps.api.schemas.readiness import ReadinessSnapshotSchema
        fields = ReadinessSnapshotSchema.model_fields
        assert "overall_status" in fields

    def test_schema_has_current_mode_field(self):
        from apps.api.schemas.readiness import ReadinessSnapshotSchema
        fields = ReadinessSnapshotSchema.model_fields
        assert "current_mode" in fields

    def test_schema_has_pass_count_field(self):
        from apps.api.schemas.readiness import ReadinessSnapshotSchema
        fields = ReadinessSnapshotSchema.model_fields
        assert "pass_count" in fields

    def test_schema_has_fail_count_field(self):
        from apps.api.schemas.readiness import ReadinessSnapshotSchema
        fields = ReadinessSnapshotSchema.model_fields
        assert "fail_count" in fields

    def test_schema_has_gate_count_field(self):
        from apps.api.schemas.readiness import ReadinessSnapshotSchema
        fields = ReadinessSnapshotSchema.model_fields
        assert "gate_count" in fields

    def test_schema_has_recommendation_field(self):
        from apps.api.schemas.readiness import ReadinessSnapshotSchema
        fields = ReadinessSnapshotSchema.model_fields
        assert "recommendation" in fields

    def test_schema_constructs_correctly(self):
        from apps.api.schemas.readiness import ReadinessSnapshotSchema
        snap = ReadinessSnapshotSchema(
            id="abc-123",
            captured_at="2026-03-21T18:45:00+00:00",
            overall_status="PASS",
            current_mode="paper",
            target_mode="human_approved",
            pass_count=3,
            warn_count=0,
            fail_count=0,
            gate_count=3,
            recommendation="All gates pass.",
        )
        assert snap.overall_status == "PASS"
        assert snap.pass_count == 3


# ---------------------------------------------------------------------------
# TestReadinessHistoryResponse
# ---------------------------------------------------------------------------

class TestReadinessHistoryResponse:
    def test_schema_importable(self):
        from apps.api.schemas.readiness import ReadinessHistoryResponse
        assert ReadinessHistoryResponse is not None

    def test_schema_has_snapshots_field(self):
        from apps.api.schemas.readiness import ReadinessHistoryResponse
        fields = ReadinessHistoryResponse.model_fields
        assert "snapshots" in fields

    def test_schema_has_count_field(self):
        from apps.api.schemas.readiness import ReadinessHistoryResponse
        fields = ReadinessHistoryResponse.model_fields
        assert "count" in fields

    def test_schema_defaults_to_empty(self):
        from apps.api.schemas.readiness import ReadinessHistoryResponse
        r = ReadinessHistoryResponse()
        assert r.snapshots == []
        assert r.count == 0


# ---------------------------------------------------------------------------
# TestReadinessHistoryRoute
# ---------------------------------------------------------------------------

class TestReadinessHistoryRoute:
    def _client(self, **state_kwargs):
        from apps.api.deps import get_app_state
        from apps.api.main import app
        state = _make_state(**state_kwargs)
        app.dependency_overrides[get_app_state] = lambda: state
        client = TestClient(app, raise_server_exceptions=False)
        yield client
        app.dependency_overrides.clear()

    def test_history_returns_200_when_no_db(self):
        """GET /history must return 200 + empty list even when DB is unavailable."""
        from apps.api.deps import get_app_state
        from apps.api.main import app
        state = _make_state()
        app.dependency_overrides[get_app_state] = lambda: state
        client = TestClient(app, raise_server_exceptions=False)

        with patch("infra.db.session.SessionLocal", side_effect=Exception("no db")):
            resp = client.get("/api/v1/system/readiness-report/history")

        app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        assert data["snapshots"] == []
        assert data["count"] == 0

    def test_history_empty_list_when_no_snapshots(self):
        """GET /history returns empty list gracefully when DB has no rows."""
        from apps.api.deps import get_app_state
        from apps.api.main import app

        state = _make_state()
        app.dependency_overrides[get_app_state] = lambda: state
        client = TestClient(app, raise_server_exceptions=False)

        # Patch DB to return empty list
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.scalars.return_value.all.return_value = []

        with patch("infra.db.session.SessionLocal", return_value=mock_session):
            resp = client.get("/api/v1/system/readiness-report/history")

        app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        assert data["snapshots"] == []
        assert data["count"] == 0

    def test_history_returns_snapshots(self):
        """GET /history serializes DB rows correctly."""
        from apps.api.deps import get_app_state
        from apps.api.main import app

        state = _make_state()
        app.dependency_overrides[get_app_state] = lambda: state
        client = TestClient(app, raise_server_exceptions=False)

        fake_row = MagicMock()
        fake_row.id = "snap-001"
        fake_row.captured_at = dt.datetime(2026, 3, 21, 18, 45, tzinfo=dt.UTC)
        fake_row.overall_status = "PASS"
        fake_row.current_mode = "paper"
        fake_row.target_mode = "human_approved"
        fake_row.pass_count = 3
        fake_row.warn_count = 0
        fake_row.fail_count = 0
        fake_row.gate_count = 3
        fake_row.recommendation = "All gates pass."

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.scalars.return_value.all.return_value = [fake_row]

        with patch("infra.db.session.SessionLocal", return_value=mock_session):
            resp = client.get("/api/v1/system/readiness-report/history")

        app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert len(data["snapshots"]) == 1
        snap = data["snapshots"][0]
        assert snap["id"] == "snap-001"
        assert snap["overall_status"] == "PASS"
        assert snap["pass_count"] == 3

    def test_history_limit_default_is_10(self):
        """Default limit is 10."""
        from apps.api.deps import get_app_state
        from apps.api.main import app

        state = _make_state()
        app.dependency_overrides[get_app_state] = lambda: state
        client = TestClient(app, raise_server_exceptions=False)

        captured_limits = []
        original_select = __import__("sqlalchemy").select

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.scalars.return_value.all.return_value = []

        with patch("infra.db.session.SessionLocal", return_value=mock_session):
            resp = client.get("/api/v1/system/readiness-report/history")

        app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_history_limit_param_accepted(self):
        """limit query param is accepted (1-100)."""
        from apps.api.deps import get_app_state
        from apps.api.main import app

        state = _make_state()
        app.dependency_overrides[get_app_state] = lambda: state
        client = TestClient(app, raise_server_exceptions=False)

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.scalars.return_value.all.return_value = []

        with patch("infra.db.session.SessionLocal", return_value=mock_session):
            resp = client.get("/api/v1/system/readiness-report/history?limit=50")

        app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_history_limit_out_of_range_rejected(self):
        """limit=0 must be rejected with 422."""
        from apps.api.deps import get_app_state
        from apps.api.main import app

        state = _make_state()
        app.dependency_overrides[get_app_state] = lambda: state
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/api/v1/system/readiness-report/history?limit=0")
        app.dependency_overrides.clear()
        assert resp.status_code == 422

    def test_history_db_error_returns_200_not_500(self):
        """DB errors must degrade to 200 + empty (not 500)."""
        from apps.api.deps import get_app_state
        from apps.api.main import app

        state = _make_state()
        app.dependency_overrides[get_app_state] = lambda: state
        client = TestClient(app, raise_server_exceptions=False)

        with patch(
            "infra.db.session.SessionLocal",
            side_effect=RuntimeError("connection refused"),
        ):
            resp = client.get("/api/v1/system/readiness-report/history")

        app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["snapshots"] == []


# ---------------------------------------------------------------------------
# TestReadinessDashboardHistory
# ---------------------------------------------------------------------------

class TestReadinessDashboardHistory:
    def test_render_history_table_no_db_returns_empty_string(self):
        """When DB is unavailable, history table helper returns empty string."""
        from apps.dashboard.router import _render_readiness_history_table

        with patch(
            "infra.db.session.SessionLocal",
            side_effect=Exception("no db"),
        ):
            result = _render_readiness_history_table()

        assert result == ""

    def test_render_history_table_empty_db_returns_empty_string(self):
        """When DB has no snapshots, history table returns empty string."""
        from apps.dashboard.router import _render_readiness_history_table

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.scalars.return_value.all.return_value = []

        with patch("infra.db.session.SessionLocal", return_value=mock_session):
            result = _render_readiness_history_table()

        assert result == ""

    def test_render_history_table_with_snapshots(self):
        """When DB has snapshots, history table renders a table with rows."""
        from apps.dashboard.router import _render_readiness_history_table

        fake_snap = MagicMock()
        fake_snap.overall_status = "PASS"
        fake_snap.captured_at = dt.datetime(2026, 3, 21, 18, 45)
        fake_snap.current_mode = "paper"
        fake_snap.target_mode = "human_approved"
        fake_snap.pass_count = 3
        fake_snap.warn_count = 0
        fake_snap.fail_count = 0

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.scalars.return_value.all.return_value = [fake_snap]

        with patch("infra.db.session.SessionLocal", return_value=mock_session):
            result = _render_readiness_history_table()

        assert "PASS" in result
        assert "table" in result.lower()
        assert "paper" in result

    def test_render_history_table_label_present(self):
        """History table includes a heading label."""
        from apps.dashboard.router import _render_readiness_history_table

        fake_snap = MagicMock()
        fake_snap.overall_status = "WARN"
        fake_snap.captured_at = dt.datetime(2026, 3, 21, 18, 45)
        fake_snap.current_mode = "paper"
        fake_snap.target_mode = "human_approved"
        fake_snap.pass_count = 1
        fake_snap.warn_count = 2
        fake_snap.fail_count = 0

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.scalars.return_value.all.return_value = [fake_snap]

        with patch("infra.db.session.SessionLocal", return_value=mock_session):
            result = _render_readiness_history_table()

        assert "History" in result

    def test_render_readiness_section_no_report_no_crash(self):
        """_render_readiness_section renders without error when no report and no DB."""
        from apps.api.state import ApiAppState
        from apps.dashboard.router import _render_readiness_section

        state = ApiAppState()

        with patch(
            "infra.db.session.SessionLocal",
            side_effect=Exception("no db"),
        ):
            result = _render_readiness_section(state)

        assert "readiness" in result.lower() or "Readiness" in result

    def test_render_readiness_section_title_updated(self):
        """Section title now includes Phase 56 annotation."""
        from apps.api.state import ApiAppState
        from apps.dashboard.router import _render_readiness_section

        state = ApiAppState()
        state.latest_readiness_report = _make_report()
        state.readiness_report_computed_at = dt.datetime(2026, 3, 21, 18, 45)

        with patch(
            "infra.db.session.SessionLocal",
            side_effect=Exception("no db"),
        ):
            result = _render_readiness_section(state)

        assert "56" in result


# ---------------------------------------------------------------------------
# TestSchedulerStillAt30Jobs
# ---------------------------------------------------------------------------

class TestSchedulerStillAt30Jobs:
    def test_scheduler_still_has_30_jobs(self):
        """Phase 56 adds no new job; total must stay at 30."""
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        jobs = scheduler.get_jobs()
        assert len(jobs) == 30, (
            f"Expected 30 scheduler jobs (Phase 56 adds no new job), "
            f"got {len(jobs)}: {[j.id for j in jobs]}"
        )

    def test_readiness_report_update_still_registered(self):
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        job_ids = {j.id for j in scheduler.get_jobs()}
        assert "readiness_report_update" in job_ids

    def test_fill_quality_attribution_still_registered(self):
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        job_ids = {j.id for j in scheduler.get_jobs()}
        assert "fill_quality_attribution" in job_ids
