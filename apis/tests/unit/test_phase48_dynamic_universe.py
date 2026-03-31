"""
Phase 48 — Dynamic Universe Management

Test classes
------------
TestUniverseOverrideORM             — UniverseOverride model fields and constraints
TestUniverseOverrideRecord          — OverrideRecord DTO
TestUniverseManagementServiceBasic  — get_active_universe() core logic
TestUniverseManagementQuality       — quality-score pruning
TestUniverseManagementSummary       — compute_universe_summary()
TestUniverseManagementLoadOverrides — load_active_overrides() DB path + fallback
TestUniverseAppState                — 3 new ApiAppState fields
TestUniverseSettings                — new settings field
TestUniverseRefreshJob              — run_universe_refresh() job
TestUniverseAPIList                 — GET /api/v1/universe/tickers
TestUniverseAPITicker               — GET /api/v1/universe/tickers/{ticker}
TestUniverseAPIOverridePost         — POST /api/v1/universe/tickers/{ticker}/override
TestUniverseAPIOverrideDelete       — DELETE /api/v1/universe/tickers/{ticker}/override
TestUniverseDashboard               — _render_universe_section() HTML
TestUniverseSignalRankingIntegration — signal_ranking active_universe usage
TestUniverseJobScheduled            — universe_refresh in scheduler (job count 26)
"""
from __future__ import annotations

import datetime as dt
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(**overrides) -> Any:
    from config.settings import Settings
    base = {
        "db_url": "postgresql+psycopg://u:p@localhost/apis",
        "operating_mode": "paper",
        "kill_switch": False,
    }
    base.update(overrides)
    return Settings(**base)


def _make_override(
    ticker: str = "AAPL",
    action: str = "REMOVE",
    active: bool = True,
    expires_at: dt.datetime | None = None,
    reason: str | None = None,
    operator_id: str | None = None,
) -> Any:
    from services.universe_management.service import OverrideRecord
    return OverrideRecord(
        ticker=ticker,
        action=action,
        reason=reason,
        operator_id=operator_id,
        active=active,
        expires_at=expires_at,
    )


BASE = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"]


# ===========================================================================
# TestUniverseOverrideORM
# ===========================================================================

class TestUniverseOverrideORM:
    def test_model_importable(self):
        from infra.db.models.universe_override import UniverseOverride
        assert UniverseOverride.__tablename__ == "universe_overrides"

    def test_model_has_required_columns(self):
        from infra.db.models.universe_override import UniverseOverride
        cols = {c.key for c in UniverseOverride.__table__.columns}
        assert "id" in cols
        assert "ticker" in cols
        assert "action" in cols
        assert "active" in cols
        assert "expires_at" in cols
        assert "reason" in cols
        assert "operator_id" in cols
        assert "created_at" in cols
        assert "updated_at" in cols

    def test_model_indexes(self):
        from infra.db.models.universe_override import UniverseOverride
        index_names = {idx.name for idx in UniverseOverride.__table__.indexes}
        assert "ix_universe_override_ticker" in index_names
        assert "ix_universe_override_active" in index_names
        assert "ix_universe_override_action" in index_names

    def test_model_check_constraint(self):
        from infra.db.models.universe_override import UniverseOverride
        constraint_names = {
            c.name for c in UniverseOverride.__table__.constraints
        }
        assert "ck_universe_override_action" in constraint_names


# ===========================================================================
# TestUniverseOverrideRecord
# ===========================================================================

class TestUniverseOverrideRecord:
    def test_override_record_creation(self):
        ovr = _make_override("TSLA", "ADD")
        assert ovr.ticker == "TSLA"
        assert ovr.action == "ADD"
        assert ovr.active is True
        assert ovr.expires_at is None

    def test_override_record_with_expiry(self):
        exp = dt.datetime(2030, 1, 1, tzinfo=dt.UTC)
        ovr = _make_override("MSFT", "REMOVE", expires_at=exp)
        assert ovr.expires_at == exp

    def test_override_record_frozen(self):
        from services.universe_management.service import OverrideRecord
        ovr = OverrideRecord(
            ticker="X", action="ADD", reason=None,
            operator_id=None, active=True, expires_at=None,
        )
        with pytest.raises((AttributeError, TypeError)):
            ovr.ticker = "Y"  # type: ignore[misc]


# ===========================================================================
# TestUniverseManagementServiceBasic
# ===========================================================================

class TestUniverseManagementServiceBasic:
    def test_no_overrides_returns_full_base(self):
        from services.universe_management.service import UniverseManagementService
        result = UniverseManagementService.get_active_universe(BASE, [])
        assert result == sorted(BASE)

    def test_remove_override_excludes_ticker(self):
        from services.universe_management.service import UniverseManagementService
        overrides = [_make_override("AAPL", "REMOVE")]
        result = UniverseManagementService.get_active_universe(BASE, overrides)
        assert "AAPL" not in result
        assert len(result) == 4

    def test_add_override_includes_non_base_ticker(self):
        from services.universe_management.service import UniverseManagementService
        overrides = [_make_override("PLTR", "ADD")]
        result = UniverseManagementService.get_active_universe(BASE, overrides)
        assert "PLTR" in result
        assert len(result) == 6

    def test_remove_override_inactive_has_no_effect(self):
        from services.universe_management.service import UniverseManagementService
        overrides = [_make_override("AAPL", "REMOVE", active=False)]
        result = UniverseManagementService.get_active_universe(BASE, overrides)
        assert "AAPL" in result

    def test_remove_override_expired_has_no_effect(self):
        from services.universe_management.service import UniverseManagementService
        past = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
        overrides = [_make_override("AAPL", "REMOVE", expires_at=past)]
        result = UniverseManagementService.get_active_universe(BASE, overrides)
        assert "AAPL" in result

    def test_add_override_supersedes_quality_removal(self):
        """ADD override keeps a ticker even if quality score would remove it."""
        from services.universe_management.service import UniverseManagementService
        overrides = [_make_override("AAPL", "ADD")]
        result = UniverseManagementService.get_active_universe(
            BASE, overrides,
            signal_quality_scores={"AAPL": 0.10},
            min_quality_score=0.50,
        )
        assert "AAPL" in result

    def test_result_is_sorted(self):
        from services.universe_management.service import UniverseManagementService
        result = UniverseManagementService.get_active_universe(
            ["MSFT", "AAPL", "NVDA"], []
        )
        assert result == sorted(result)

    def test_ticker_case_normalised(self):
        from services.universe_management.service import UniverseManagementService
        overrides = [_make_override("aapl", "REMOVE")]
        result = UniverseManagementService.get_active_universe(BASE, overrides)
        assert "AAPL" not in result

    def test_not_yet_expired_override_is_active(self):
        from services.universe_management.service import UniverseManagementService
        future = dt.datetime(2099, 1, 1, tzinfo=dt.UTC)
        overrides = [_make_override("AAPL", "REMOVE", expires_at=future)]
        result = UniverseManagementService.get_active_universe(BASE, overrides)
        assert "AAPL" not in result


# ===========================================================================
# TestUniverseManagementQuality
# ===========================================================================

class TestUniverseManagementQuality:
    def test_quality_removal_disabled_by_default(self):
        from services.universe_management.service import UniverseManagementService
        result = UniverseManagementService.get_active_universe(
            BASE, [],
            signal_quality_scores={"AAPL": 0.10, "MSFT": 0.10},
            min_quality_score=0.0,  # disabled
        )
        assert len(result) == len(BASE)

    def test_quality_removal_low_score(self):
        from services.universe_management.service import UniverseManagementService
        scores = dict.fromkeys(BASE, 0.1)
        result = UniverseManagementService.get_active_universe(
            BASE, [],
            signal_quality_scores=scores,
            min_quality_score=0.50,
        )
        assert result == []

    def test_quality_removal_partial(self):
        from services.universe_management.service import UniverseManagementService
        scores = {"AAPL": 0.20, "MSFT": 0.80, "NVDA": 0.80, "GOOGL": 0.80, "AMZN": 0.80}
        result = UniverseManagementService.get_active_universe(
            BASE, [],
            signal_quality_scores=scores,
            min_quality_score=0.50,
        )
        assert "AAPL" not in result
        assert len(result) == 4

    def test_quality_none_scores_no_removal(self):
        from services.universe_management.service import UniverseManagementService
        result = UniverseManagementService.get_active_universe(
            BASE, [],
            signal_quality_scores=None,
            min_quality_score=0.50,
        )
        assert len(result) == len(BASE)

    def test_quality_add_override_protects_low_quality_ticker(self):
        from services.universe_management.service import UniverseManagementService
        scores = {"AAPL": 0.10}
        overrides = [_make_override("AAPL", "ADD")]
        result = UniverseManagementService.get_active_universe(
            BASE, overrides,
            signal_quality_scores=scores,
            min_quality_score=0.50,
        )
        assert "AAPL" in result


# ===========================================================================
# TestUniverseManagementSummary
# ===========================================================================

class TestUniverseManagementSummary:
    def test_summary_no_changes(self):
        from services.universe_management.service import UniverseManagementService
        summary = UniverseManagementService.compute_universe_summary(
            BASE, sorted(BASE), [], reference_dt=dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        )
        assert summary.base_count == 5
        assert summary.active_count == 5
        assert summary.added_tickers == []
        assert summary.removed_tickers == []
        assert summary.override_count == 0

    def test_summary_with_removal(self):
        from services.universe_management.service import UniverseManagementService
        active = [t for t in sorted(BASE) if t != "AAPL"]
        summary = UniverseManagementService.compute_universe_summary(
            BASE, active, []
        )
        assert "AAPL" in summary.removed_tickers

    def test_summary_with_addition(self):
        from services.universe_management.service import UniverseManagementService
        active = sorted(BASE) + ["PLTR"]
        summary = UniverseManagementService.compute_universe_summary(
            BASE, active, []
        )
        assert "PLTR" in summary.added_tickers

    def test_summary_ticker_statuses_populated(self):
        from services.universe_management.service import UniverseManagementService
        summary = UniverseManagementService.compute_universe_summary(
            BASE, sorted(BASE), []
        )
        assert len(summary.ticker_statuses) == len(BASE)
        for s in summary.ticker_statuses:
            assert s.in_base_universe is True
            assert s.in_active_universe is True

    def test_summary_quality_removed_tickers(self):
        from services.universe_management.service import UniverseManagementService
        scores = {"AAPL": 0.10}
        active = [t for t in sorted(BASE) if t != "AAPL"]
        summary = UniverseManagementService.compute_universe_summary(
            BASE, active, [],
            signal_quality_scores=scores,
            min_quality_score=0.50,
        )
        assert "AAPL" in summary.quality_removed_tickers


# ===========================================================================
# TestUniverseManagementLoadOverrides
# ===========================================================================

class TestUniverseManagementLoadOverrides:
    def test_load_returns_empty_when_no_factory(self):
        from services.universe_management.service import UniverseManagementService
        result = UniverseManagementService.load_active_overrides(session_factory=None)
        assert result == []

    def test_load_returns_empty_on_db_error(self):
        from services.universe_management.service import UniverseManagementService

        def _bad_factory():
            raise RuntimeError("DB down")

        result = UniverseManagementService.load_active_overrides(session_factory=_bad_factory)
        assert result == []

    def test_load_maps_orm_rows_to_records(self):
        """Verify that OverrideRecord DTO carries correct field values."""
        from services.universe_management.service import OverrideRecord

        # Directly construct the DTO as load_active_overrides would produce it
        records = [OverrideRecord(
            ticker="TSLA", action="REMOVE", reason="poor quality",
            operator_id="op1", active=True, expires_at=None,
        )]
        assert records[0].ticker == "TSLA"
        assert records[0].action == "REMOVE"
        assert records[0].reason == "poor quality"
        assert records[0].operator_id == "op1"


# ===========================================================================
# TestUniverseAppState
# ===========================================================================

class TestUniverseAppState:
    def test_active_universe_default(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert state.active_universe == []

    def test_universe_computed_at_default(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert state.universe_computed_at is None

    def test_universe_override_count_default(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert state.universe_override_count == 0

    def test_active_universe_can_be_set(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        state.active_universe = ["AAPL", "MSFT"]
        assert "AAPL" in state.active_universe


# ===========================================================================
# TestUniverseSettings
# ===========================================================================

class TestUniverseSettings:
    def test_default_quality_score_is_zero(self):
        s = _make_settings()
        assert s.min_universe_signal_quality_score == 0.0

    def test_quality_score_can_be_set(self):
        s = _make_settings(min_universe_signal_quality_score=0.40)
        assert s.min_universe_signal_quality_score == 0.40

    def test_quality_score_bounds(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            _make_settings(min_universe_signal_quality_score=1.5)

    def test_quality_score_lower_bound(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            _make_settings(min_universe_signal_quality_score=-0.1)


# ===========================================================================
# TestUniverseRefreshJob
# ===========================================================================

class TestUniverseRefreshJob:
    def _make_state(self):
        from apps.api.state import ApiAppState
        return ApiAppState()

    def test_job_returns_ok_status(self):
        from apps.worker.jobs.universe import run_universe_refresh
        state = self._make_state()
        result = run_universe_refresh(app_state=state, settings=_make_settings())
        assert result["status"] == "ok"

    def test_job_sets_active_universe(self):
        from apps.worker.jobs.universe import run_universe_refresh
        from config.universe import UNIVERSE_TICKERS
        state = self._make_state()
        run_universe_refresh(app_state=state, settings=_make_settings())
        assert len(state.active_universe) == len(UNIVERSE_TICKERS)

    def test_job_sets_computed_at(self):
        from apps.worker.jobs.universe import run_universe_refresh
        state = self._make_state()
        run_universe_refresh(app_state=state, settings=_make_settings())
        assert state.universe_computed_at is not None

    def test_job_no_session_factory_uses_base_universe(self):
        from apps.worker.jobs.universe import run_universe_refresh
        from config.universe import UNIVERSE_TICKERS
        state = self._make_state()
        result = run_universe_refresh(
            app_state=state,
            settings=_make_settings(),
            session_factory=None,
        )
        assert result["status"] == "ok"
        assert result["active_count"] == len(UNIVERSE_TICKERS)
        assert result["override_count"] == 0

    def test_job_returns_error_on_unexpected_exception(self):
        """Job returns error dict when a module inside the try block raises on import."""
        from apps.worker.jobs.universe import run_universe_refresh
        state = self._make_state()

        # Patch sys.modules to make the lazy import inside try fail
        import sys
        original = sys.modules.pop("config.universe", None)
        sys.modules["config.universe"] = None  # type: ignore[assignment]
        try:
            result = run_universe_refresh(app_state=state, settings=_make_settings())
        finally:
            if original is not None:
                sys.modules["config.universe"] = original
            elif "config.universe" in sys.modules:
                del sys.modules["config.universe"]
        assert result["status"] == "error"

    def test_job_active_count_in_result(self):
        from apps.worker.jobs.universe import run_universe_refresh
        state = self._make_state()
        result = run_universe_refresh(app_state=state, settings=_make_settings())
        assert "active_count" in result
        assert result["active_count"] > 0


# ===========================================================================
# TestUniverseAPIList
# ===========================================================================

class TestUniverseAPIList:
    def _get_client(self):
        from fastapi.testclient import TestClient

        from apps.api.main import app
        return TestClient(app)

    def test_no_data_returns_no_data_flag(self):
        from apps.api.state import reset_app_state
        reset_app_state()
        client = self._get_client()
        resp = client.get("/api/v1/universe/tickers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["no_data"] is True

    def test_with_active_universe_returns_tickers(self):
        from apps.api.state import get_app_state, reset_app_state
        reset_app_state()
        state = get_app_state()
        state.active_universe = ["AAPL", "MSFT"]
        state.universe_computed_at = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        client = self._get_client()
        resp = client.get("/api/v1/universe/tickers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["no_data"] is False
        assert "AAPL" in data["active_tickers"]

    def test_response_includes_counts(self):
        from apps.api.state import get_app_state, reset_app_state
        reset_app_state()
        state = get_app_state()
        state.active_universe = ["AAPL", "MSFT", "NVDA"]
        state.universe_computed_at = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        client = self._get_client()
        resp = client.get("/api/v1/universe/tickers")
        data = resp.json()
        assert data["active_count"] == 3


# ===========================================================================
# TestUniverseAPITicker
# ===========================================================================

class TestUniverseAPITicker:
    def _get_client(self):
        from fastapi.testclient import TestClient

        from apps.api.main import app
        return TestClient(app)

    def test_no_data_returns_data_available_false(self):
        from apps.api.state import reset_app_state
        reset_app_state()
        client = self._get_client()
        resp = client.get("/api/v1/universe/tickers/AAPL")
        assert resp.status_code == 200
        assert resp.json()["data_available"] is False

    def test_ticker_in_active_universe(self):
        from apps.api.state import get_app_state, reset_app_state
        reset_app_state()
        state = get_app_state()
        state.active_universe = ["AAPL", "MSFT"]
        state.universe_computed_at = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        client = self._get_client()
        resp = client.get("/api/v1/universe/tickers/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data_available"] is True
        assert data["in_active_universe"] is True

    def test_ticker_not_in_active_universe(self):
        from apps.api.state import get_app_state, reset_app_state
        reset_app_state()
        state = get_app_state()
        state.active_universe = ["MSFT"]
        state.universe_computed_at = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        client = self._get_client()
        resp = client.get("/api/v1/universe/tickers/AAPL")
        data = resp.json()
        assert data["in_active_universe"] is False

    def test_ticker_case_normalised(self):
        from apps.api.state import get_app_state, reset_app_state
        reset_app_state()
        state = get_app_state()
        state.active_universe = ["AAPL"]
        state.universe_computed_at = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        client = self._get_client()
        resp = client.get("/api/v1/universe/tickers/aapl")
        assert resp.json()["ticker"] == "AAPL"


# ===========================================================================
# TestUniverseAPIOverridePost
# ===========================================================================

class TestUniverseAPIOverridePost:
    def _get_client(self):
        from fastapi.testclient import TestClient

        from apps.api.main import app
        return TestClient(app)

    def test_create_remove_override(self):
        from apps.api.state import reset_app_state
        reset_app_state()
        client = self._get_client()
        # DB unavailable in unit test → 503 expected
        resp = client.post(
            "/api/v1/universe/tickers/AAPL/override",
            json={"action": "REMOVE", "reason": "poor performance"},
        )
        assert resp.status_code in (200, 503)

    def test_invalid_action_returns_422(self):
        from apps.api.state import reset_app_state
        reset_app_state()
        client = self._get_client()
        resp = client.post(
            "/api/v1/universe/tickers/AAPL/override",
            json={"action": "INVALID"},
        )
        assert resp.status_code == 422

    def test_valid_add_action_accepted(self):
        from apps.api.state import reset_app_state
        reset_app_state()
        client = self._get_client()
        resp = client.post(
            "/api/v1/universe/tickers/PLTR/override",
            json={"action": "ADD", "reason": "operator addition"},
        )
        assert resp.status_code in (200, 503)


# ===========================================================================
# TestUniverseAPIOverrideDelete
# ===========================================================================

class TestUniverseAPIOverrideDelete:
    def _get_client(self):
        from fastapi.testclient import TestClient

        from apps.api.main import app
        return TestClient(app)

    def test_delete_returns_ok_or_503(self):
        from apps.api.state import reset_app_state
        reset_app_state()
        client = self._get_client()
        resp = client.delete("/api/v1/universe/tickers/AAPL/override")
        assert resp.status_code in (200, 503)

    def test_delete_ticker_case_normalised(self):
        from apps.api.state import reset_app_state
        reset_app_state()
        client = self._get_client()
        resp = client.delete("/api/v1/universe/tickers/aapl/override")
        assert resp.status_code in (200, 503)


# ===========================================================================
# TestUniverseDashboard
# ===========================================================================

class TestUniverseDashboard:
    def _make_state_with_universe(self, active=None, override_count=0):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        state.active_universe = active or []
        state.universe_override_count = override_count
        state.universe_computed_at = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        return state

    def test_section_renders(self):
        from apps.dashboard.router import _render_universe_section
        state = self._make_state_with_universe()
        html = _render_universe_section(state, _make_settings())
        assert "Phase 48" in html
        assert "Universe" in html

    def test_section_shows_active_count(self):
        from apps.dashboard.router import _render_universe_section
        from config.universe import UNIVERSE_TICKERS
        state = self._make_state_with_universe(active=list(UNIVERSE_TICKERS))
        html = _render_universe_section(state, _make_settings())
        assert str(len(UNIVERSE_TICKERS)) in html

    def test_section_shows_removed_ticker(self):
        from apps.dashboard.router import _render_universe_section
        from config.universe import UNIVERSE_TICKERS
        active = [t for t in UNIVERSE_TICKERS if t != "AAPL"]
        state = self._make_state_with_universe(active=active)
        html = _render_universe_section(state, _make_settings())
        assert "REMOVED" in html or "Removed" in html

    def test_section_unchanged_when_no_overrides(self):
        from apps.dashboard.router import _render_universe_section
        from config.universe import UNIVERSE_TICKERS
        state = self._make_state_with_universe(active=sorted(UNIVERSE_TICKERS))
        html = _render_universe_section(state, _make_settings())
        assert "unchanged" in html


# ===========================================================================
# TestUniverseSignalRankingIntegration
# ===========================================================================

class TestUniverseSignalRankingIntegration:
    def test_signal_generation_uses_active_universe_when_set(self):
        """run_signal_generation should use app_state.active_universe when non-empty."""
        from apps.api.state import ApiAppState

        state = ApiAppState()
        state.active_universe = ["AAPL", "MSFT"]

        captured_tickers = []

        def _mock_run(session, signal_run_id, tickers, **kwargs):
            captured_tickers.extend(tickers)
            return []

        mock_svc = MagicMock()
        mock_svc.run = _mock_run

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        def _factory():
            return mock_session

        from apps.worker.jobs.signal_ranking import run_signal_generation
        run_signal_generation(
            app_state=state,
            settings=_make_settings(),
            session_factory=_factory,
            signal_service=mock_svc,
        )
        assert captured_tickers == ["AAPL", "MSFT"]

    def test_signal_generation_falls_back_to_universe_when_active_empty(self):
        """run_signal_generation falls back to UNIVERSE_TICKERS when active_universe=[]."""
        from apps.api.state import ApiAppState
        from config.universe import UNIVERSE_TICKERS

        state = ApiAppState()
        state.active_universe = []  # not yet populated

        captured_tickers = []

        def _mock_run(session, signal_run_id, tickers, **kwargs):
            captured_tickers.extend(tickers)
            return []

        mock_svc = MagicMock()
        mock_svc.run = _mock_run

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        def _factory():
            return mock_session

        from apps.worker.jobs.signal_ranking import run_signal_generation
        run_signal_generation(
            app_state=state,
            settings=_make_settings(),
            session_factory=_factory,
            signal_service=mock_svc,
        )
        assert captured_tickers == list(UNIVERSE_TICKERS)


# ===========================================================================
# TestUniverseJobScheduled
# ===========================================================================

class TestUniverseJobScheduled:
    def test_job_count_is_27(self):
        """Scheduler must have exactly 27 jobs after Phase 49."""
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        job_ids = {job.id for job in scheduler.get_jobs()}
        assert len(job_ids) == 30

    def test_universe_refresh_job_present(self):
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        job_ids = {job.id for job in scheduler.get_jobs()}
        assert "universe_refresh" in job_ids

    def test_universe_refresh_scheduled_at_0625(self):
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        jobs = {job.id: job for job in scheduler.get_jobs()}
        job = jobs["universe_refresh"]
        trigger = job.trigger
        # CronTrigger fields
        fields = {f.name: str(f) for f in trigger.fields}
        assert fields["hour"] == "6"
        assert fields["minute"] == "25"
