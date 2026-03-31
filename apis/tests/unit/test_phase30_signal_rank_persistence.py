"""
Phase 30 — DB-backed Signal/Rank Persistence
==============================================

Tests cover:
  - ApiAppState.last_signal_run_id / last_ranking_run_id fields
  - SignalEngineService.run() creates a SignalRun header row before signals
  - SignalEngineService.run() marks SignalRun.status = "completed" at end
  - run_signal_generation stores last_signal_run_id in app_state
  - run_ranking_generation: in-memory path (no session_factory)
  - run_ranking_generation: DB path (session_factory + last_signal_run_id)
  - run_ranking_generation: falls back to memory path when signal_run_id absent
  - SignalRunHistoryResponse schema validation
  - RankingRunHistoryResponse schema validation
  - RankingRunDetailResponse schema validation
  - GET /api/v1/signals/runs — no session_factory → empty list (graceful)
  - GET /api/v1/signals/runs — session_factory returns records
  - GET /api/v1/rankings/runs — no session_factory → empty list (graceful)
  - GET /api/v1/rankings/runs — session_factory returns records
  - GET /api/v1/rankings/latest — no session_factory → 503
  - GET /api/v1/rankings/latest — no rows → 404
  - GET /api/v1/rankings/latest — returns newest run with opportunities
  - GET /api/v1/rankings/runs/{id} — bad UUID → 422
  - GET /api/v1/rankings/runs/{id} — not found → 404
  - GET /api/v1/rankings/runs/{id} — found → full detail
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app_state(**overrides: Any):
    from apps.api.state import ApiAppState
    state = ApiAppState()
    for k, v in overrides.items():
        setattr(state, k, v)
    return state


def _make_ranked_result(ticker: str = "AAPL", rank: int = 1) -> Any:
    from services.ranking_engine.models import RankedResult
    return RankedResult(
        rank_position=rank,
        security_id=uuid.uuid4(),
        ticker=ticker,
        composite_score=Decimal("0.75"),
        portfolio_fit_score=Decimal("0.70"),
        recommended_action="BUY",
        target_horizon="positional",
        thesis_summary=f"{ticker} test thesis",
        disconfirming_factors="None",
        sizing_hint_pct=Decimal("5.00"),
        source_reliability_tier="secondary_verified",
        contains_rumor=False,
    )


# ---------------------------------------------------------------------------
# TestAppStatePhase30Fields
# ---------------------------------------------------------------------------

class TestAppStatePhase30Fields:
    def test_last_signal_run_id_default_none(self):
        state = _make_app_state()
        assert state.last_signal_run_id is None

    def test_last_ranking_run_id_default_none(self):
        state = _make_app_state()
        assert state.last_ranking_run_id is None

    def test_set_last_signal_run_id(self):
        state = _make_app_state()
        rid = str(uuid.uuid4())
        state.last_signal_run_id = rid
        assert state.last_signal_run_id == rid

    def test_set_last_ranking_run_id(self):
        state = _make_app_state()
        rid = str(uuid.uuid4())
        state.last_ranking_run_id = rid
        assert state.last_ranking_run_id == rid

    def test_all_previous_fields_intact(self):
        """Pre-existing state fields are not broken by Phase 30 additions."""
        state = _make_app_state()
        assert state.latest_rankings == []
        assert state.latest_fundamentals == {}
        assert state.current_macro_regime == "NEUTRAL"
        assert state.kill_switch_active is False


# ---------------------------------------------------------------------------
# TestSignalEngineServiceSignalRun
# ---------------------------------------------------------------------------

class TestSignalEngineServiceSignalRun:
    """Verify SignalRun header row creation (mocked DB)."""

    def _make_service(self):
        from services.signal_engine.service import SignalEngineService
        from services.signal_engine.strategies.momentum import MomentumStrategy
        svc = SignalEngineService(strategies=[MomentumStrategy()])
        return svc

    def test_signal_run_row_added_to_session(self):
        svc = self._make_service()
        session = MagicMock()
        # Make execute() for strategy lookup return empty (no rows)
        session.execute.return_value.scalars.return_value.__iter__ = lambda s: iter([])
        session.execute.return_value.scalars.return_value.all.return_value = []
        session.execute.return_value.scalars.return_value = MagicMock(
            __iter__=lambda s: iter([]),
            all=lambda: [],
        )
        signal_run_id = uuid.uuid4()
        with patch.object(svc, "_load_security_ids", return_value={}), \
             patch.object(svc, "_ensure_strategy_rows", return_value={}):
            svc.run(session=session, signal_run_id=signal_run_id, tickers=[])
        # SignalRun row should be added
        added_types = [type(call.args[0]).__name__ for call in session.add.call_args_list]
        assert "SignalRun" in added_types

    def test_signal_run_row_has_correct_id(self):
        svc = self._make_service()
        session = MagicMock()
        signal_run_id = uuid.uuid4()
        added_objects = []
        session.add.side_effect = added_objects.append
        with patch.object(svc, "_load_security_ids", return_value={}), \
             patch.object(svc, "_ensure_strategy_rows", return_value={}):
            svc.run(session=session, signal_run_id=signal_run_id, tickers=[])
        from infra.db.models import SignalRun
        signal_run_rows = [o for o in added_objects if isinstance(o, SignalRun)]
        assert len(signal_run_rows) == 1
        assert signal_run_rows[0].id == signal_run_id

    def test_signal_run_status_completed_after_run(self):
        svc = self._make_service()
        session = MagicMock()
        signal_run_id = uuid.uuid4()
        added_objects = []
        session.add.side_effect = added_objects.append
        with patch.object(svc, "_load_security_ids", return_value={}), \
             patch.object(svc, "_ensure_strategy_rows", return_value={}):
            svc.run(session=session, signal_run_id=signal_run_id, tickers=[])
        from infra.db.models import SignalRun
        signal_run_rows = [o for o in added_objects if isinstance(o, SignalRun)]
        assert signal_run_rows[0].status == "completed"

    def test_signal_run_run_mode_is_paper(self):
        svc = self._make_service()
        session = MagicMock()
        added_objects = []
        session.add.side_effect = added_objects.append
        with patch.object(svc, "_load_security_ids", return_value={}), \
             patch.object(svc, "_ensure_strategy_rows", return_value={}):
            svc.run(session=session, signal_run_id=uuid.uuid4(), tickers=[])
        from infra.db.models import SignalRun
        signal_run_rows = [o for o in added_objects if isinstance(o, SignalRun)]
        assert signal_run_rows[0].run_mode == "paper"

    def test_flush_called_after_signal_run_add(self):
        svc = self._make_service()
        session = MagicMock()
        with patch.object(svc, "_load_security_ids", return_value={}), \
             patch.object(svc, "_ensure_strategy_rows", return_value={}):
            svc.run(session=session, signal_run_id=uuid.uuid4(), tickers=[])
        assert session.flush.called


# ---------------------------------------------------------------------------
# TestRunSignalGenerationState
# ---------------------------------------------------------------------------

class TestRunSignalGenerationState:
    """run_signal_generation stores last_signal_run_id in app_state."""

    def test_stores_signal_run_id_on_success(self):
        from apps.worker.jobs.signal_ranking import run_signal_generation
        state = _make_app_state()
        assert state.last_signal_run_id is None

        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)

        mock_svc = MagicMock()
        mock_svc.run.return_value = []

        result = run_signal_generation(
            app_state=state,
            session_factory=lambda: mock_session,
            signal_service=mock_svc,
        )
        assert result["status"] == "ok"
        # last_signal_run_id should now be set to the used signal_run_id
        assert state.last_signal_run_id == result["signal_run_id"]

    def test_does_not_set_run_id_when_error(self):
        from apps.worker.jobs.signal_ranking import run_signal_generation
        state = _make_app_state()

        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)

        mock_svc = MagicMock()
        mock_svc.run.side_effect = RuntimeError("DB exploded")

        result = run_signal_generation(
            app_state=state,
            session_factory=lambda: mock_session,
            signal_service=mock_svc,
        )
        assert result["status"] == "error"
        assert state.last_signal_run_id is None  # unchanged

    def test_skipped_when_no_session_factory(self):
        from apps.worker.jobs.signal_ranking import run_signal_generation
        state = _make_app_state()
        result = run_signal_generation(app_state=state, session_factory=None)
        assert result["status"] == "skipped_no_session"
        assert state.last_signal_run_id is None


# ---------------------------------------------------------------------------
# TestRunRankingGenerationDbPath
# ---------------------------------------------------------------------------

class TestRunRankingGenerationDbPath:
    """run_ranking_generation DB path."""

    def _make_mock_session(self, run_id: uuid.UUID) -> MagicMock:
        """Return a mock session_factory whose DB call produces (run_id, [])."""
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)
        return mock_session

    def test_uses_db_path_when_session_and_signal_run_available(self):
        from apps.worker.jobs.signal_ranking import run_ranking_generation
        state = _make_app_state()
        sig_run_id = uuid.uuid4()
        state.last_signal_run_id = str(sig_run_id)

        db_run_id = uuid.uuid4()

        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)

        mock_svc = MagicMock()
        mock_svc.run.return_value = (db_run_id, [_make_ranked_result()])

        result = run_ranking_generation(
            app_state=state,
            signals=[],
            ranking_service=mock_svc,
            session_factory=lambda: mock_session,
        )
        assert result["status"] == "ok"
        assert result["ranking_run_id"] == str(db_run_id)
        assert state.last_ranking_run_id == str(db_run_id)
        # Verify svc.run() was called (DB path)
        mock_svc.run.assert_called_once()

    def test_uses_memory_path_when_no_session_factory(self):
        from apps.worker.jobs.signal_ranking import run_ranking_generation
        state = _make_app_state()
        state.last_signal_run_id = str(uuid.uuid4())

        mock_svc = MagicMock()
        mock_svc.rank_signals.return_value = [_make_ranked_result()]

        result = run_ranking_generation(
            app_state=state,
            signals=[],
            ranking_service=mock_svc,
            session_factory=None,
        )
        assert result["status"] == "ok"
        mock_svc.rank_signals.assert_called_once()

    def test_uses_memory_path_when_no_signal_run_id(self):
        from apps.worker.jobs.signal_ranking import run_ranking_generation
        state = _make_app_state()
        # last_signal_run_id is None → memory path even if session_factory is set
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)

        mock_svc = MagicMock()
        mock_svc.rank_signals.return_value = []

        result = run_ranking_generation(
            app_state=state,
            signals=[],
            ranking_service=mock_svc,
            session_factory=lambda: mock_session,
        )
        assert result["status"] == "ok"
        mock_svc.rank_signals.assert_called_once()
        mock_svc.run.assert_not_called()

    def test_sets_last_ranking_run_id_memory_path(self):
        from apps.worker.jobs.signal_ranking import run_ranking_generation
        state = _make_app_state()
        mock_svc = MagicMock()
        mock_svc.rank_signals.return_value = []
        run_ranking_generation(app_state=state, signals=[], ranking_service=mock_svc)
        assert state.last_ranking_run_id is not None

    def test_error_returns_error_status(self):
        from apps.worker.jobs.signal_ranking import run_ranking_generation
        state = _make_app_state()
        mock_svc = MagicMock()
        mock_svc.rank_signals.side_effect = RuntimeError("boom")
        result = run_ranking_generation(app_state=state, signals=[], ranking_service=mock_svc)
        assert result["status"] == "error"
        assert result["ranked_count"] == 0


# ---------------------------------------------------------------------------
# TestSignalRunSchema
# ---------------------------------------------------------------------------

class TestSignalRunSchema:
    def test_signal_run_record_valid(self):
        from apps.api.schemas.signals import SignalRunRecord
        r = SignalRunRecord(
            run_id=str(uuid.uuid4()),
            run_timestamp=dt.datetime.now(dt.UTC),
            run_mode="paper",
            universe_name="default",
            status="completed",
            signal_count=250,
            strategy_count=5,
        )
        assert r.signal_count == 250
        assert r.strategy_count == 5

    def test_signal_run_history_response(self):
        from apps.api.schemas.signals import SignalRunHistoryResponse
        resp = SignalRunHistoryResponse(count=0, runs=[])
        assert resp.count == 0
        assert resp.runs == []

    def test_ranking_run_record_valid(self):
        from apps.api.schemas.signals import RankingRunRecord
        r = RankingRunRecord(
            run_id=str(uuid.uuid4()),
            signal_run_id=str(uuid.uuid4()),
            run_timestamp=dt.datetime.now(dt.UTC),
            status="completed",
            ranked_count=10,
        )
        assert r.ranked_count == 10

    def test_ranked_opportunity_record_optional_fields(self):
        from apps.api.schemas.signals import RankedOpportunityRecord
        r = RankedOpportunityRecord(
            rank_position=1,
            ticker=None,
            composite_score=None,
            portfolio_fit_score=None,
            recommended_action="BUY",
            target_horizon=None,
            thesis_summary=None,
            disconfirming_factors=None,
            sizing_hint_pct=None,
        )
        assert r.rank_position == 1
        assert r.ticker is None

    def test_ranking_run_detail_response(self):
        from apps.api.schemas.signals import RankedOpportunityRecord, RankingRunDetailResponse
        opp = RankedOpportunityRecord(
            rank_position=1, ticker="AAPL", composite_score=0.75,
            portfolio_fit_score=0.70, recommended_action="BUY",
            target_horizon="positional", thesis_summary="thesis",
            disconfirming_factors=None, sizing_hint_pct=5.0,
        )
        resp = RankingRunDetailResponse(
            run_id=str(uuid.uuid4()),
            signal_run_id=str(uuid.uuid4()),
            run_timestamp=dt.datetime.now(dt.UTC),
            status="completed",
            opportunities=[opp],
        )
        assert len(resp.opportunities) == 1
        assert resp.opportunities[0].ticker == "AAPL"


# ---------------------------------------------------------------------------
# TestSignalRunsEndpoint
# ---------------------------------------------------------------------------

class TestSignalRunsEndpoint:
    """GET /api/v1/signals/runs."""

    def _client(self, state=None):
        from fastapi.testclient import TestClient

        from apps.api.deps import get_app_state
        from apps.api.main import app
        _state = state or _make_app_state()
        app.dependency_overrides[get_app_state] = lambda: _state
        client = TestClient(app, raise_server_exceptions=False)
        return client, _state

    def teardown_method(self, _):
        from apps.api.main import app
        app.dependency_overrides.clear()

    def test_returns_200(self):
        client, _ = self._client()
        resp = client.get("/api/v1/signals/runs")
        assert resp.status_code == 200

    def test_empty_list_when_no_session_factory(self):
        client, _ = self._client()
        data = client.get("/api/v1/signals/runs").json()
        assert data["count"] == 0
        assert data["runs"] == []

    def test_session_factory_error_returns_empty(self):
        state = _make_app_state()
        state._session_factory = MagicMock(side_effect=RuntimeError("DB down"))
        client, _ = self._client(state)
        data = client.get("/api/v1/signals/runs").json()
        assert data["count"] == 0


# ---------------------------------------------------------------------------
# TestRankingRunsEndpoint
# ---------------------------------------------------------------------------

class TestRankingRunsEndpoint:
    """GET /api/v1/rankings/runs."""

    def _client(self, state=None):
        from fastapi.testclient import TestClient

        from apps.api.deps import get_app_state
        from apps.api.main import app
        _state = state or _make_app_state()
        app.dependency_overrides[get_app_state] = lambda: _state
        client = TestClient(app, raise_server_exceptions=False)
        return client, _state

    def teardown_method(self, _):
        from apps.api.main import app
        app.dependency_overrides.clear()

    def test_returns_200(self):
        client, _ = self._client()
        resp = client.get("/api/v1/rankings/runs")
        assert resp.status_code == 200

    def test_empty_list_when_no_session_factory(self):
        client, _ = self._client()
        data = client.get("/api/v1/rankings/runs").json()
        assert data["count"] == 0
        assert data["runs"] == []

    def test_session_factory_db_error_returns_empty(self):
        state = _make_app_state()
        # Simulate DB failure via a session factory that raises
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = lambda s: MagicMock(execute=MagicMock(side_effect=RuntimeError("oops")))
        mock_ctx.__exit__ = MagicMock(return_value=False)
        state._session_factory = lambda: mock_ctx
        client, _ = self._client(state)
        data = client.get("/api/v1/rankings/runs").json()
        assert data["count"] == 0


# ---------------------------------------------------------------------------
# TestRankingsLatestEndpoint
# ---------------------------------------------------------------------------

class TestRankingsLatestEndpoint:
    """GET /api/v1/rankings/latest."""

    def _client(self, state=None):
        from fastapi.testclient import TestClient

        from apps.api.deps import get_app_state
        from apps.api.main import app
        _state = state or _make_app_state()
        app.dependency_overrides[get_app_state] = lambda: _state
        client = TestClient(app, raise_server_exceptions=False)
        return client, _state

    def teardown_method(self, _):
        from apps.api.main import app
        app.dependency_overrides.clear()

    def test_503_when_no_session_factory(self):
        client, _ = self._client()
        resp = client.get("/api/v1/rankings/latest")
        assert resp.status_code == 503

    def test_404_when_no_ranking_runs(self):
        state = _make_app_state()
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)
        # Return None for RankingRun query (no rows)
        mock_session.execute.return_value.scalar_one_or_none.return_value = None
        state._session_factory = lambda: mock_session
        client, _ = self._client(state)
        resp = client.get("/api/v1/rankings/latest")
        assert resp.status_code == 404

    def test_returns_ranking_run_detail_when_found(self):
        state = _make_app_state()
        sig_run_id = uuid.uuid4()
        run_id = uuid.uuid4()

        mock_run = MagicMock()
        mock_run.id = run_id
        mock_run.signal_run_id = sig_run_id
        mock_run.run_timestamp = dt.datetime.now(dt.UTC)
        mock_run.status = "completed"
        mock_run.config_version = None

        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)
        # First execute: get RankingRun
        exec1 = MagicMock()
        exec1.scalar_one_or_none.return_value = mock_run
        # Second execute: get RankedOpportunity rows
        exec2 = MagicMock()
        exec2.all.return_value = []     # no opportunities
        mock_session.execute.side_effect = [exec1, exec2]

        state._session_factory = lambda: mock_session
        client, _ = self._client(state)
        resp = client.get("/api/v1/rankings/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == str(run_id)
        assert data["opportunities"] == []


# ---------------------------------------------------------------------------
# TestRankingRunByIdEndpoint
# ---------------------------------------------------------------------------

class TestRankingRunByIdEndpoint:
    """GET /api/v1/rankings/runs/{run_id}."""

    def _client(self, state=None):
        from fastapi.testclient import TestClient

        from apps.api.deps import get_app_state
        from apps.api.main import app
        _state = state or _make_app_state()
        app.dependency_overrides[get_app_state] = lambda: _state
        client = TestClient(app, raise_server_exceptions=False)
        return client, _state

    def teardown_method(self, _):
        from apps.api.main import app
        app.dependency_overrides.clear()

    def test_422_for_invalid_uuid(self):
        client, _ = self._client()
        resp = client.get("/api/v1/rankings/runs/not-a-uuid")
        assert resp.status_code == 422

    def test_503_when_no_session_factory(self):
        client, _ = self._client()
        resp = client.get(f"/api/v1/rankings/runs/{uuid.uuid4()}")
        assert resp.status_code == 503

    def test_404_when_run_not_found(self):
        state = _make_app_state()
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.get.return_value = None
        state._session_factory = lambda: mock_session
        client, _ = self._client(state)
        resp = client.get(f"/api/v1/rankings/runs/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_200_when_found(self):
        state = _make_app_state()
        run_id = uuid.uuid4()
        mock_run = MagicMock()
        mock_run.id = run_id
        mock_run.signal_run_id = uuid.uuid4()
        mock_run.run_timestamp = dt.datetime.now(dt.UTC)
        mock_run.status = "completed"

        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.get.return_value = mock_run
        exec1 = MagicMock()
        exec1.all.return_value = []
        mock_session.execute.return_value = exec1

        state._session_factory = lambda: mock_session
        client, _ = self._client(state)
        resp = client.get(f"/api/v1/rankings/runs/{run_id}")
        assert resp.status_code == 200
        assert resp.json()["run_id"] == str(run_id)
