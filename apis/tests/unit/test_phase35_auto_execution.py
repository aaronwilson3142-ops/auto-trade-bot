"""
Phase 35 — Self-Improvement Proposal Auto-Execution tests.

Coverage
--------
 1. TestProposalExecutionORM          — ORM model structure + fields
 2. TestProposalExecutionMigration    — migration file structure
 3. TestExecutionRecord               — ExecutionRecord dataclass
 4. TestAutoExecutionServiceExecute   — execute_proposal happy path + guardrails
 5. TestAutoExecutionServiceRollback  — rollback happy path + edge cases
 6. TestAutoExecutionServiceBatch     — auto_execute_promoted batch logic
 7. TestAutoExecutionDBPersist        — fire-and-forget DB writes never raise
 8. TestSelfImprovementSchemas        — Pydantic schema imports + field checks
 9. TestSelfImprovementRoutes         — FastAPI route responses
10. TestAutoExecuteWorkerJob          — run_auto_execute_proposals job function
11. TestSchedulerNewJob               — scheduler has 17 jobs; 06:05 + 18:15 jobs present
"""
from __future__ import annotations

import datetime as dt
import types
import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from apps.api.state import ApiAppState, reset_app_state
from services.self_improvement.models import (
    ImprovementProposal,
    ProposalStatus,
    ProposalType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_promoted_proposal(**kwargs) -> ImprovementProposal:
    """Return a PROMOTED ImprovementProposal with sane defaults."""
    p = ImprovementProposal(
        proposal_type=kwargs.get("proposal_type", ProposalType.RANKING_THRESHOLD),
        target_component=kwargs.get("target_component", "ranking_engine"),
        baseline_version="1.0.0",
        candidate_version="1.0.1",
        proposal_summary="Test proposal",
        expected_benefit="Better results",
        baseline_params=kwargs.get("baseline_params", {"min_score": 0.5}),
        candidate_params=kwargs.get("candidate_params", {"min_score": 0.65}),
    )
    p.status = ProposalStatus.PROMOTED
    return p


def _make_app_state() -> ApiAppState:
    reset_app_state()
    from apps.api.state import get_app_state
    return get_app_state()


# ---------------------------------------------------------------------------
# 1. TestProposalExecutionORM
# ---------------------------------------------------------------------------

class TestProposalExecutionORM:
    def test_import(self):
        from infra.db.models.proposal_execution import ProposalExecution
        assert ProposalExecution is not None

    def test_tablename(self):
        from infra.db.models.proposal_execution import ProposalExecution
        assert ProposalExecution.__tablename__ == "proposal_executions"

    def test_required_columns(self):
        from infra.db.models.proposal_execution import ProposalExecution
        cols = {c.name for c in ProposalExecution.__table__.columns}
        for col in ("id", "proposal_id", "status", "executed_at", "created_at"):
            assert col in cols, f"Missing column: {col}"

    def test_optional_columns(self):
        from infra.db.models.proposal_execution import ProposalExecution
        cols = {c.name for c in ProposalExecution.__table__.columns}
        for col in (
            "proposal_type", "target_component",
            "config_delta_json", "baseline_params_json",
            "rolled_back_at", "notes", "updated_at",
        ):
            assert col in cols, f"Missing column: {col}"

    def test_proposal_id_is_indexed(self):
        from infra.db.models.proposal_execution import ProposalExecution
        index_names = {idx.name for idx in ProposalExecution.__table__.indexes}
        assert any("proposal" in n for n in index_names)

    def test_executed_at_is_indexed(self):
        from infra.db.models.proposal_execution import ProposalExecution
        index_names = {idx.name for idx in ProposalExecution.__table__.indexes}
        assert any("executed" in n for n in index_names)

    def test_exported_from_models_init(self):
        from infra.db.models import ProposalExecution
        assert ProposalExecution is not None


# ---------------------------------------------------------------------------
# 2. TestProposalExecutionMigration
# ---------------------------------------------------------------------------

class TestProposalExecutionMigration:
    def _load_migration(self):
        import importlib.util, os
        path = os.path.join(
            os.path.dirname(__file__),
            "../../infra/db/versions/f6a7b8c9d0e1_add_proposal_executions.py",
        )
        spec = importlib.util.spec_from_file_location("migration_phase35", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_revision_id(self):
        mod = self._load_migration()
        assert mod.revision == "f6a7b8c9d0e1"

    def test_down_revision(self):
        mod = self._load_migration()
        assert mod.down_revision == "e5f6a7b8c9d0"

    def test_upgrade_defined(self):
        mod = self._load_migration()
        assert callable(mod.upgrade)

    def test_downgrade_defined(self):
        mod = self._load_migration()
        assert callable(mod.downgrade)


# ---------------------------------------------------------------------------
# 3. TestExecutionRecord
# ---------------------------------------------------------------------------

class TestExecutionRecord:
    def test_import(self):
        from services.self_improvement.execution import ExecutionRecord
        assert ExecutionRecord is not None

    def test_fields(self):
        from services.self_improvement.execution import ExecutionRecord
        rec = ExecutionRecord(
            id="exec-1",
            proposal_id="prop-1",
            proposal_type="ranking_threshold",
            target_component="ranking_engine",
            config_delta={"min_score": 0.65},
            baseline_params={"min_score": 0.5},
            status="applied",
            executed_at=dt.datetime.now(dt.timezone.utc),
        )
        assert rec.id == "exec-1"
        assert rec.status == "applied"
        assert rec.rolled_back_at is None

    def test_default_notes(self):
        from services.self_improvement.execution import ExecutionRecord
        rec = ExecutionRecord(
            id="x",
            proposal_id="y",
            proposal_type="t",
            target_component="c",
            config_delta={},
            baseline_params={},
            status="applied",
            executed_at=dt.datetime.now(dt.timezone.utc),
        )
        assert rec.notes == ""


# ---------------------------------------------------------------------------
# 4. TestAutoExecutionServiceExecute
# ---------------------------------------------------------------------------

class TestAutoExecutionServiceExecute:
    def setup_method(self):
        from services.self_improvement.execution import AutoExecutionService
        self.svc = AutoExecutionService()

    def test_execute_promoted_proposal(self):
        state = _make_app_state()
        proposal = _make_promoted_proposal()
        record = self.svc.execute_proposal(proposal, state)
        assert record.status == "applied"
        assert record.proposal_id == proposal.id

    def test_execute_updates_runtime_overrides(self):
        state = _make_app_state()
        proposal = _make_promoted_proposal(
            candidate_params={"min_score": 0.7}
        )
        self.svc.execute_proposal(proposal, state)
        assert state.runtime_overrides.get("min_score") == 0.7

    def test_execute_updates_promoted_versions(self):
        state = _make_app_state()
        proposal = _make_promoted_proposal(
            target_component="signal_engine",
        )
        proposal.candidate_version = "1.2.0"
        self.svc.execute_proposal(proposal, state)
        assert state.promoted_versions.get("signal_engine") == "1.2.0"

    def test_execute_appends_to_applied_executions(self):
        state = _make_app_state()
        proposal = _make_promoted_proposal()
        self.svc.execute_proposal(proposal, state)
        assert len(state.applied_executions) == 1

    def test_execute_raises_when_not_promoted(self):
        state = _make_app_state()
        proposal = _make_promoted_proposal()
        proposal.status = ProposalStatus.PENDING
        with pytest.raises(ValueError, match="must be PROMOTED"):
            self.svc.execute_proposal(proposal, state)

    def test_execute_raises_for_protected_component(self):
        state = _make_app_state()
        proposal = _make_promoted_proposal(target_component="risk_engine")
        proposal.status = ProposalStatus.PROMOTED
        with pytest.raises(ValueError, match="protected"):
            self.svc.execute_proposal(proposal, state)

    def test_execute_without_session_factory_skips_db(self):
        """execute_proposal with no session_factory never raises."""
        state = _make_app_state()
        proposal = _make_promoted_proposal()
        record = self.svc.execute_proposal(proposal, state, session_factory=None)
        assert record.status == "applied"

    def test_execute_record_captures_proposal_type(self):
        state = _make_app_state()
        proposal = _make_promoted_proposal(proposal_type=ProposalType.SOURCE_WEIGHT)
        record = self.svc.execute_proposal(proposal, state)
        assert "source_weight" in record.proposal_type

    def test_execute_empty_candidate_params(self):
        """Proposals with empty candidate_params still execute cleanly."""
        state = _make_app_state()
        proposal = _make_promoted_proposal(candidate_params={})
        record = self.svc.execute_proposal(proposal, state)
        assert record.config_delta == {}

    def test_execute_rejected_proposal_raises(self):
        state = _make_app_state()
        proposal = _make_promoted_proposal()
        proposal.status = ProposalStatus.REJECTED
        with pytest.raises(ValueError):
            self.svc.execute_proposal(proposal, state)


# ---------------------------------------------------------------------------
# 5. TestAutoExecutionServiceRollback
# ---------------------------------------------------------------------------

class TestAutoExecutionServiceRollback:
    def setup_method(self):
        from services.self_improvement.execution import AutoExecutionService
        self.svc = AutoExecutionService()

    def test_rollback_restores_baseline(self):
        state = _make_app_state()
        proposal = _make_promoted_proposal(
            baseline_params={"min_score": 0.5},
            candidate_params={"min_score": 0.7},
        )
        record = self.svc.execute_proposal(proposal, state)
        assert state.runtime_overrides.get("min_score") == 0.7

        result = self.svc.rollback_execution(record.id, state)
        assert result is True
        assert state.runtime_overrides.get("min_score") == 0.5

    def test_rollback_marks_record_rolled_back(self):
        state = _make_app_state()
        proposal = _make_promoted_proposal()
        record = self.svc.execute_proposal(proposal, state)
        self.svc.rollback_execution(record.id, state)
        assert record.status == "rolled_back"
        assert record.rolled_back_at is not None

    def test_rollback_returns_false_when_not_found(self):
        state = _make_app_state()
        result = self.svc.rollback_execution("nonexistent-id", state)
        assert result is False

    def test_rollback_returns_false_when_already_rolled_back(self):
        state = _make_app_state()
        proposal = _make_promoted_proposal()
        record = self.svc.execute_proposal(proposal, state)
        self.svc.rollback_execution(record.id, state)
        result = self.svc.rollback_execution(record.id, state)
        assert result is False

    def test_rollback_removes_keys_not_in_baseline(self):
        """Keys in candidate_params but not in baseline_params should be removed."""
        state = _make_app_state()
        proposal = _make_promoted_proposal(
            baseline_params={},
            candidate_params={"new_key": 99},
        )
        record = self.svc.execute_proposal(proposal, state)
        assert state.runtime_overrides.get("new_key") == 99
        self.svc.rollback_execution(record.id, state)
        assert "new_key" not in state.runtime_overrides

    def test_rollback_without_session_factory_skips_db(self):
        state = _make_app_state()
        proposal = _make_promoted_proposal()
        record = self.svc.execute_proposal(proposal, state)
        result = self.svc.rollback_execution(record.id, state, session_factory=None)
        assert result is True


# ---------------------------------------------------------------------------
# 6. TestAutoExecutionServiceBatch
# ---------------------------------------------------------------------------

class TestAutoExecutionServiceBatch:
    def setup_method(self):
        from services.self_improvement.execution import AutoExecutionService
        self.svc = AutoExecutionService()

    def test_batch_executes_promoted(self):
        state = _make_app_state()
        proposals = [_make_promoted_proposal()]
        result = self.svc.auto_execute_promoted(proposals, state)
        assert result["executed_count"] == 1
        assert result["skipped_count"] == 0

    def test_batch_skips_non_promoted(self):
        state = _make_app_state()
        proposal = _make_promoted_proposal()
        proposal.status = ProposalStatus.PENDING
        result = self.svc.auto_execute_promoted([proposal], state)
        assert result["skipped_count"] == 1
        assert result["executed_count"] == 0

    def test_batch_skips_protected_component(self):
        state = _make_app_state()
        proposal = _make_promoted_proposal(target_component="execution_engine")
        proposal.status = ProposalStatus.PROMOTED
        result = self.svc.auto_execute_promoted([proposal], state)
        assert result["skipped_count"] == 1

    def test_batch_skips_already_applied(self):
        state = _make_app_state()
        proposal = _make_promoted_proposal()
        # Execute once
        self.svc.execute_proposal(proposal, state)
        # Try batch again with same proposal
        result = self.svc.auto_execute_promoted([proposal], state)
        assert result["skipped_count"] == 1
        assert result["executed_count"] == 0

    def test_batch_updates_last_auto_execute_at(self):
        state = _make_app_state()
        assert state.last_auto_execute_at is None
        self.svc.auto_execute_promoted([], state)
        assert state.last_auto_execute_at is not None

    def test_batch_multiple_proposals(self):
        state = _make_app_state()
        p1 = _make_promoted_proposal(target_component="ranking_engine")
        p2 = _make_promoted_proposal(target_component="signal_engine")
        result = self.svc.auto_execute_promoted([p1, p2], state)
        assert result["executed_count"] == 2
        assert len(state.applied_executions) == 2

    def test_batch_error_count(self):
        """If execute_proposal raises unexpectedly, error_count increments."""
        state = _make_app_state()
        proposal = _make_promoted_proposal()

        svc = __import__(
            "services.self_improvement.execution",
            fromlist=["AutoExecutionService"],
        ).AutoExecutionService()

        original = svc.execute_proposal

        def exploding_execute(*args, **kwargs):
            raise RuntimeError("simulated failure")

        svc.execute_proposal = exploding_execute
        result = svc.auto_execute_promoted([proposal], state)
        assert result["error_count"] == 1
        assert len(result["errors"]) == 1

    def test_batch_empty_proposals(self):
        state = _make_app_state()
        result = self.svc.auto_execute_promoted([], state)
        assert result["executed_count"] == 0
        assert result["skipped_count"] == 0
        assert result["error_count"] == 0


# ---------------------------------------------------------------------------
# 7. TestAutoExecutionDBPersist
# ---------------------------------------------------------------------------

class TestAutoExecutionDBPersist:
    def setup_method(self):
        from services.self_improvement.execution import AutoExecutionService
        self.svc = AutoExecutionService()

    def test_persist_execution_does_not_raise_on_db_error(self):
        from services.self_improvement.execution import ExecutionRecord

        def bad_factory():
            raise RuntimeError("DB down")

        record = ExecutionRecord(
            id=str(uuid.uuid4()),
            proposal_id="p1",
            proposal_type="source_weight",
            target_component="signal_engine",
            config_delta={},
            baseline_params={},
            status="applied",
            executed_at=dt.datetime.now(dt.timezone.utc),
        )
        # Should not raise
        self.svc._persist_execution(record, bad_factory)

    def test_persist_execution_skips_when_no_session_factory(self):
        from services.self_improvement.execution import ExecutionRecord

        record = ExecutionRecord(
            id=str(uuid.uuid4()),
            proposal_id="p1",
            proposal_type="source_weight",
            target_component="signal_engine",
            config_delta={},
            baseline_params={},
            status="applied",
            executed_at=dt.datetime.now(dt.timezone.utc),
        )
        # Must not raise
        self.svc._persist_execution(record, None)

    def test_persist_rollback_skips_when_no_session_factory(self):
        self.svc._persist_rollback(
            "some-id",
            dt.datetime.now(dt.timezone.utc),
            None,
        )  # must not raise

    def test_persist_rollback_does_not_raise_on_db_error(self):
        def bad_factory():
            raise RuntimeError("DB down")

        self.svc._persist_rollback(
            "some-id",
            dt.datetime.now(dt.timezone.utc),
            bad_factory,
        )  # must not raise


# ---------------------------------------------------------------------------
# 8. TestSelfImprovementSchemas
# ---------------------------------------------------------------------------

class TestSelfImprovementSchemas:
    def test_import(self):
        from apps.api.schemas.self_improvement import (
            AutoExecuteSummaryResponse,
            ExecuteProposalResponse,
            ExecutionListResponse,
            ExecutionRecordSchema,
            RollbackExecutionResponse,
        )
        assert ExecutionRecordSchema is not None
        assert ExecutionListResponse is not None
        assert ExecuteProposalResponse is not None
        assert RollbackExecutionResponse is not None
        assert AutoExecuteSummaryResponse is not None

    def test_execution_record_schema_fields(self):
        from apps.api.schemas.self_improvement import ExecutionRecordSchema
        now = dt.datetime.now(dt.timezone.utc)
        schema = ExecutionRecordSchema(
            id="e1",
            proposal_id="p1",
            proposal_type="source_weight",
            target_component="signal_engine",
            config_delta={"k": 1},
            baseline_params={},
            status="applied",
            executed_at=now,
        )
        assert schema.status == "applied"
        assert schema.rolled_back_at is None

    def test_execution_list_response(self):
        from apps.api.schemas.self_improvement import ExecutionListResponse
        resp = ExecutionListResponse(count=0, items=[])
        assert resp.count == 0

    def test_execute_proposal_response(self):
        from apps.api.schemas.self_improvement import ExecuteProposalResponse
        resp = ExecuteProposalResponse(
            status="executed",
            execution_id="exec-1",
            proposal_id="prop-1",
            message="done",
        )
        assert resp.status == "executed"

    def test_rollback_response(self):
        from apps.api.schemas.self_improvement import RollbackExecutionResponse
        resp = RollbackExecutionResponse(
            status="rolled_back",
            execution_id="e1",
            message="ok",
        )
        assert resp.status == "rolled_back"

    def test_auto_execute_summary_response(self):
        from apps.api.schemas.self_improvement import AutoExecuteSummaryResponse
        resp = AutoExecuteSummaryResponse(
            status="ok",
            executed_count=2,
            skipped_count=1,
            error_count=0,
            errors=[],
            run_at=dt.datetime.now(dt.timezone.utc),
        )
        assert resp.executed_count == 2


# ---------------------------------------------------------------------------
# 9. TestSelfImprovementRoutes
# ---------------------------------------------------------------------------

class TestSelfImprovementRoutes:
    def _client(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        return TestClient(app)

    def test_execute_returns_404_when_proposal_not_found(self):
        reset_app_state()
        client = self._client()
        resp = client.post("/api/v1/self-improvement/proposals/nonexistent/execute")
        assert resp.status_code == 404

    def test_list_executions_empty(self):
        reset_app_state()
        client = self._client()
        resp = client.get("/api/v1/self-improvement/executions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["items"] == []

    def test_rollback_returns_not_found(self):
        reset_app_state()
        client = self._client()
        resp = client.post("/api/v1/self-improvement/executions/fake-id/rollback")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "not_found"

    def test_auto_execute_returns_ok_when_no_proposals(self):
        reset_app_state()
        client = self._client()
        resp = client.post("/api/v1/self-improvement/auto-execute")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["executed_count"] == 0

    def test_execute_promoted_proposal_via_route(self):
        reset_app_state()
        from apps.api.state import get_app_state
        state = get_app_state()
        proposal = _make_promoted_proposal()
        state.improvement_proposals = [proposal]

        client = self._client()
        resp = client.post(
            f"/api/v1/self-improvement/proposals/{proposal.id}/execute"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "executed"
        assert data["proposal_id"] == proposal.id

    def test_execute_non_promoted_returns_400(self):
        reset_app_state()
        from apps.api.state import get_app_state
        state = get_app_state()
        proposal = _make_promoted_proposal()
        proposal.status = ProposalStatus.PENDING
        state.improvement_proposals = [proposal]

        client = self._client()
        resp = client.post(
            f"/api/v1/self-improvement/proposals/{proposal.id}/execute"
        )
        assert resp.status_code == 400

    def test_list_executions_after_execute(self):
        reset_app_state()
        from apps.api.state import get_app_state
        state = get_app_state()
        proposal = _make_promoted_proposal()
        state.improvement_proposals = [proposal]

        client = self._client()
        client.post(f"/api/v1/self-improvement/proposals/{proposal.id}/execute")

        resp = client.get("/api/v1/self-improvement/executions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1

    def test_rollback_after_execute(self):
        reset_app_state()
        from apps.api.state import get_app_state
        state = get_app_state()
        proposal = _make_promoted_proposal()
        state.improvement_proposals = [proposal]

        client = self._client()
        exec_resp = client.post(
            f"/api/v1/self-improvement/proposals/{proposal.id}/execute"
        )
        exec_id = exec_resp.json()["execution_id"]

        rb_resp = client.post(
            f"/api/v1/self-improvement/executions/{exec_id}/rollback"
        )
        assert rb_resp.status_code == 200
        assert rb_resp.json()["status"] == "rolled_back"

    def test_router_is_registered(self):
        from apps.api.main import app
        paths = {r.path for r in app.routes}
        assert any("self-improvement" in p for p in paths)


# ---------------------------------------------------------------------------
# 10. TestAutoExecuteWorkerJob
# ---------------------------------------------------------------------------

class TestAutoExecuteWorkerJob:
    def test_import(self):
        from apps.worker.jobs.self_improvement import run_auto_execute_proposals
        assert callable(run_auto_execute_proposals)

    def test_exported_from_jobs_package(self):
        from apps.worker.jobs import run_auto_execute_proposals
        assert callable(run_auto_execute_proposals)

    def test_returns_ok_status_when_no_proposals(self):
        from apps.worker.jobs.self_improvement import run_auto_execute_proposals
        state = _make_app_state()
        result = run_auto_execute_proposals(app_state=state)
        assert result["status"] == "ok"
        assert result["executed_count"] == 0

    def test_returns_ok_with_promoted_proposals(self):
        from apps.worker.jobs.self_improvement import run_auto_execute_proposals
        state = _make_app_state()
        state.improvement_proposals = [_make_promoted_proposal()]
        result = run_auto_execute_proposals(app_state=state)
        assert result["status"] == "ok"
        assert result["executed_count"] == 1

    def test_returns_error_status_on_exception(self):
        from apps.worker.jobs.self_improvement import run_auto_execute_proposals
        from services.self_improvement.execution import AutoExecutionService

        bad_svc = AutoExecutionService()
        bad_svc.auto_execute_promoted = MagicMock(
            side_effect=RuntimeError("unexpected")
        )
        state = _make_app_state()
        result = run_auto_execute_proposals(
            app_state=state,
            auto_execution_service=bad_svc,
        )
        assert result["status"] == "error"

    def test_result_has_run_at_field(self):
        from apps.worker.jobs.self_improvement import run_auto_execute_proposals
        state = _make_app_state()
        result = run_auto_execute_proposals(app_state=state)
        assert "run_at" in result

    def test_accepts_session_factory_kwarg(self):
        from apps.worker.jobs.self_improvement import run_auto_execute_proposals
        state = _make_app_state()
        result = run_auto_execute_proposals(
            app_state=state,
            session_factory=None,
        )
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# 11. TestSchedulerNewJob
# ---------------------------------------------------------------------------

class TestSchedulerNewJob:
    def _build(self):
        from apps.worker.main import build_scheduler
        return build_scheduler()

    def test_total_job_count_is_16(self):
        """Phase 48 adds universe_refresh: total is now 26."""
        scheduler = self._build()
        assert len(scheduler.get_jobs()) == 30

    def test_auto_execute_proposals_job_present(self):
        scheduler = self._build()
        ids = {job.id for job in scheduler.get_jobs()}
        assert "auto_execute_proposals" in ids

    def test_auto_execute_proposals_fires_at_18_15(self):
        from apscheduler.triggers.cron import CronTrigger
        scheduler = self._build()
        job = next(j for j in scheduler.get_jobs() if j.id == "auto_execute_proposals")
        trigger = job.trigger
        assert isinstance(trigger, CronTrigger)
        fields = {f.name: str(f) for f in trigger.fields}
        assert fields.get("hour") == "18"
        assert fields.get("minute") == "15"

    def test_auto_execute_proposals_is_weekday_only(self):
        scheduler = self._build()
        job = next(j for j in scheduler.get_jobs() if j.id == "auto_execute_proposals")
        fields = {f.name: str(f) for f in job.trigger.fields}
        assert fields.get("day_of_week") == "mon-fri"
