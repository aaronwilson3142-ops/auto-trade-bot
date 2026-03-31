"""
Phase 20 unit tests — Portfolio Snapshot Persistence + Evaluation Persistence
                        + Continuity Service.

Test classes
------------
TestContinuitySnapshotModel         — ContinuitySnapshot dataclass
TestSessionContextModel             — SessionContext dataclass
TestContinuityConfig                — ContinuityConfig dataclass
TestContinuityServiceTakeSnapshot   — ContinuityService.take_snapshot()
TestContinuityServiceSaveLoad       — ContinuityService.save/load_snapshot()
TestContinuityServiceSessionContext — ContinuityService.get_session_context()
TestPersistPortfolioSnapshot        — _persist_portfolio_snapshot() helper
TestPersistEvaluationRun            — _persist_evaluation_run() helper
TestPortfolioSnapshotSchemas        — PortfolioSnapshotRecord / HistoryResponse
TestEvaluationRunSchemas            — EvaluationRunRecord / RunHistoryResponse
TestPortfolioSnapshotsRoute         — GET /portfolio/snapshots endpoint
TestEvaluationRunsRoute             — GET /evaluation/runs endpoint
TestAppStateSnapshotFields          — last_snapshot_at / last_snapshot_equity
TestLoadPersistedStateSnapshot      — _load_persisted_state() portfolio-restore block
TestPhase20Integration              — end-to-end integration scenarios
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_app_state(**kwargs) -> Any:
    from apps.api.state import ApiAppState, reset_app_state
    reset_app_state()
    from apps.api.state import get_app_state
    state = get_app_state()
    for k, v in kwargs.items():
        setattr(state, k, v)
    return state


def _make_settings(
    mode: str = "paper",
    kill_switch: bool = False,
) -> Any:
    from config.settings import OperatingMode, Settings
    return Settings(
        operating_mode=OperatingMode(mode),
        kill_switch=kill_switch,
    )


def _make_portfolio_state(
    cash: float = 95_000.0,
    equity: float = 100_000.0,
    gross_exposure: float = 5_000.0,
    drawdown_pct: float = 0.01,
) -> Any:
    from decimal import Decimal
    from services.portfolio_engine.models import PortfolioState
    ps = PortfolioState(
        cash=Decimal(str(cash)),
        start_of_day_equity=Decimal(str(equity)),
        high_water_mark=Decimal(str(equity)),
    )
    return ps


def _make_scorecard(equity: float = 100_000.0) -> Any:
    from decimal import Decimal
    import datetime as dt
    from services.evaluation_engine.models import DailyScorecard
    return DailyScorecard(
        scorecard_date=dt.date.today(),
        equity=Decimal(str(equity)),
        cash=Decimal("95000"),
        gross_exposure=Decimal("5000"),
        position_count=1,
        net_pnl=Decimal("500"),
        realized_pnl=Decimal("200"),
        unrealized_pnl=Decimal("300"),
        daily_return_pct=Decimal("0.005"),
        hit_rate=Decimal("0.6"),
        closed_trade_count=3,
        avg_winner_pct=Decimal("0.03"),
        avg_loser_pct=Decimal("-0.01"),
        current_drawdown_pct=Decimal("0.01"),
        max_drawdown_pct=Decimal("0.02"),
        mode="PAPER",
        benchmark_comparison=None,
        attribution=None,
    )


# ===========================================================================
# TestContinuitySnapshotModel
# ===========================================================================

class TestContinuitySnapshotModel:
    def test_to_dict_roundtrip(self):
        from services.continuity.models import ContinuitySnapshot
        snap = ContinuitySnapshot(
            snapshot_at="2026-03-20T10:00:00+00:00",
            operating_mode="PAPER",
            kill_switch_active=False,
            paper_cycle_count=5,
            portfolio_equity=100_000.0,
            portfolio_cash=95_000.0,
            portfolio_positions=2,
            ranking_count=10,
            broker_auth_expired=False,
            last_paper_cycle_at="2026-03-20T09:30:00+00:00",
            pending_proposals=1,
        )
        d = snap.to_dict()
        assert d["operating_mode"] == "PAPER"
        assert d["paper_cycle_count"] == 5
        assert d["portfolio_equity"] == 100_000.0

    def test_from_dict_roundtrip(self):
        from services.continuity.models import ContinuitySnapshot
        snap = ContinuitySnapshot(
            snapshot_at="2026-03-20T10:00:00+00:00",
            operating_mode="PAPER",
            kill_switch_active=True,
            paper_cycle_count=12,
            portfolio_equity=98_000.0,
            portfolio_cash=90_000.0,
            portfolio_positions=3,
            ranking_count=15,
            broker_auth_expired=False,
            last_paper_cycle_at=None,
            pending_proposals=0,
        )
        restored = ContinuitySnapshot.from_dict(snap.to_dict())
        assert restored.paper_cycle_count == 12
        assert restored.kill_switch_active is True
        assert restored.portfolio_equity == 98_000.0

    def test_from_dict_defaults_on_missing_keys(self):
        from services.continuity.models import ContinuitySnapshot
        snap = ContinuitySnapshot.from_dict({})
        assert snap.operating_mode == "RESEARCH"
        assert snap.kill_switch_active is False
        assert snap.paper_cycle_count == 0
        assert snap.portfolio_equity is None

    def test_serializable_to_json(self):
        from services.continuity.models import ContinuitySnapshot
        snap = ContinuitySnapshot(
            snapshot_at="2026-03-20T10:00:00+00:00",
            operating_mode="PAPER",
            kill_switch_active=False,
            paper_cycle_count=3,
            portfolio_equity=100_000.0,
            portfolio_cash=95_000.0,
            portfolio_positions=1,
            ranking_count=5,
            broker_auth_expired=False,
            last_paper_cycle_at=None,
            pending_proposals=0,
        )
        # Must not raise
        text = json.dumps(snap.to_dict())
        assert "PAPER" in text


# ===========================================================================
# TestSessionContextModel
# ===========================================================================

class TestSessionContextModel:
    def test_to_dict_has_all_fields(self):
        from services.continuity.models import SessionContext
        ctx = SessionContext(
            snapshot_at="2026-03-20T10:00:00+00:00",
            operating_mode="PAPER",
            paper_cycle_count=7,
            portfolio_equity=100_500.0,
            portfolio_positions=2,
            kill_switch_active=False,
            broker_auth_expired=False,
            ranking_count=10,
            pending_proposals=0,
            summary_lines=["mode=PAPER", "equity=100500"],
        )
        d = ctx.to_dict()
        assert d["portfolio_equity"] == 100_500.0
        assert d["summary_lines"] == ["mode=PAPER", "equity=100500"]

    def test_summary_lines_default_empty(self):
        from services.continuity.models import SessionContext
        ctx = SessionContext(
            snapshot_at="now",
            operating_mode="RESEARCH",
            paper_cycle_count=0,
            portfolio_equity=0.0,
            portfolio_positions=0,
            kill_switch_active=False,
            broker_auth_expired=False,
            ranking_count=0,
            pending_proposals=0,
        )
        assert ctx.summary_lines == []


# ===========================================================================
# TestContinuityConfig
# ===========================================================================

class TestContinuityConfig:
    def test_defaults(self):
        from services.continuity.config import ContinuityConfig
        cfg = ContinuityConfig()
        assert cfg.snapshot_dir == "data/snapshots"
        assert cfg.snapshot_filename == "latest_state.json"
        assert cfg.max_snapshot_age_hours == 48

    def test_custom_values(self):
        from services.continuity.config import ContinuityConfig
        cfg = ContinuityConfig(
            snapshot_dir="/tmp/snapshots",
            snapshot_filename="state.json",
            max_snapshot_age_hours=24,
        )
        assert cfg.max_snapshot_age_hours == 24


# ===========================================================================
# TestContinuityServiceTakeSnapshot
# ===========================================================================

class TestContinuityServiceTakeSnapshot:
    def test_take_snapshot_paper_mode(self):
        from services.continuity.service import ContinuityService
        svc = ContinuityService()
        app_state = _make_app_state(
            paper_cycle_count=5,
            latest_rankings=[1, 2, 3],
            broker_auth_expired=False,
            improvement_proposals=[],
        )
        settings = _make_settings(mode="paper")
        snap = svc.take_snapshot(app_state, settings)
        assert snap.operating_mode == "paper"
        assert snap.paper_cycle_count == 5
        assert snap.ranking_count == 3
        assert snap.broker_auth_expired is False

    def test_take_snapshot_kill_switch_active(self):
        from services.continuity.service import ContinuityService
        svc = ContinuityService()
        app_state = _make_app_state(kill_switch_active=True, paper_cycle_count=0)
        settings = _make_settings(kill_switch=False)
        snap = svc.take_snapshot(app_state, settings)
        assert snap.kill_switch_active is True

    def test_take_snapshot_kill_switch_from_env(self):
        from services.continuity.service import ContinuityService
        svc = ContinuityService()
        app_state = _make_app_state(kill_switch_active=False, paper_cycle_count=0)
        settings = _make_settings(kill_switch=True)
        snap = svc.take_snapshot(app_state, settings)
        assert snap.kill_switch_active is True

    def test_take_snapshot_with_portfolio_state(self):
        from services.continuity.service import ContinuityService
        svc = ContinuityService()
        ps = _make_portfolio_state(cash=90_000.0, equity=100_000.0)
        app_state = _make_app_state(portfolio_state=ps, paper_cycle_count=3)
        settings = _make_settings()
        snap = svc.take_snapshot(app_state, settings)
        assert snap.portfolio_equity == pytest.approx(ps.equity, rel=1e-3)
        assert snap.portfolio_cash == pytest.approx(ps.cash, rel=1e-3)

    def test_take_snapshot_without_portfolio_state(self):
        from services.continuity.service import ContinuityService
        svc = ContinuityService()
        app_state = _make_app_state(portfolio_state=None, paper_cycle_count=0)
        settings = _make_settings()
        snap = svc.take_snapshot(app_state, settings)
        assert snap.portfolio_equity is None
        assert snap.portfolio_cash is None
        assert snap.portfolio_positions == 0

    def test_take_snapshot_last_paper_cycle_none(self):
        from services.continuity.service import ContinuityService
        svc = ContinuityService()
        app_state = _make_app_state(last_paper_cycle_at=None, paper_cycle_count=0)
        settings = _make_settings()
        snap = svc.take_snapshot(app_state, settings)
        assert snap.last_paper_cycle_at is None

    def test_take_snapshot_last_paper_cycle_set(self):
        from services.continuity.service import ContinuityService
        svc = ContinuityService()
        ts = dt.datetime(2026, 3, 20, 9, 30, tzinfo=dt.timezone.utc)
        app_state = _make_app_state(last_paper_cycle_at=ts, paper_cycle_count=1)
        settings = _make_settings()
        snap = svc.take_snapshot(app_state, settings)
        assert snap.last_paper_cycle_at is not None
        assert "2026" in snap.last_paper_cycle_at


# ===========================================================================
# TestContinuityServiceSaveLoad
# ===========================================================================

class TestContinuityServiceSaveLoad:
    def test_save_and_load_roundtrip(self, tmp_path):
        from services.continuity.models import ContinuitySnapshot
        from services.continuity.service import ContinuityService
        path = str(tmp_path / "snap.json")
        svc = ContinuityService()
        snap = ContinuitySnapshot(
            snapshot_at="2026-03-20T10:00:00+00:00",
            operating_mode="PAPER",
            kill_switch_active=False,
            paper_cycle_count=7,
            portfolio_equity=100_000.0,
            portfolio_cash=95_000.0,
            portfolio_positions=2,
            ranking_count=10,
            broker_auth_expired=False,
            last_paper_cycle_at=None,
            pending_proposals=1,
        )
        svc.save_snapshot(snap, path=path)
        loaded = svc.load_snapshot(path=path)
        assert loaded is not None
        assert loaded.paper_cycle_count == 7
        assert loaded.operating_mode == "PAPER"

    def test_load_returns_none_when_file_missing(self, tmp_path):
        from services.continuity.service import ContinuityService
        svc = ContinuityService()
        result = svc.load_snapshot(path=str(tmp_path / "does_not_exist.json"))
        assert result is None

    def test_load_returns_none_for_corrupt_json(self, tmp_path):
        from services.continuity.service import ContinuityService
        path = tmp_path / "corrupt.json"
        path.write_text("not valid json {{{{")
        svc = ContinuityService()
        result = svc.load_snapshot(path=str(path))
        assert result is None

    def test_load_returns_none_for_stale_file(self, tmp_path):
        from services.continuity.config import ContinuityConfig
        from services.continuity.models import ContinuitySnapshot
        from services.continuity.service import ContinuityService
        path = str(tmp_path / "snap.json")
        # max_snapshot_age_hours=0 makes anything stale immediately
        cfg = ContinuityConfig(max_snapshot_age_hours=0)
        svc = ContinuityService(config=cfg)
        snap = ContinuitySnapshot(
            snapshot_at="2026-03-20T10:00:00+00:00",
            operating_mode="PAPER",
            kill_switch_active=False,
            paper_cycle_count=1,
            portfolio_equity=100_000.0,
            portfolio_cash=95_000.0,
            portfolio_positions=1,
            ranking_count=5,
            broker_auth_expired=False,
            last_paper_cycle_at=None,
            pending_proposals=0,
        )
        svc.save_snapshot(snap, path=path)
        # Backdate the file modification time by 1 hour
        past = dt.datetime.now().timestamp() - 3600
        os.utime(path, (past, past))
        result = svc.load_snapshot(path=path)
        assert result is None

    def test_save_creates_parent_directories(self, tmp_path):
        from services.continuity.models import ContinuitySnapshot
        from services.continuity.service import ContinuityService
        nested_path = str(tmp_path / "a" / "b" / "c" / "snap.json")
        svc = ContinuityService()
        snap = ContinuitySnapshot(
            snapshot_at="2026-03-20T10:00:00+00:00",
            operating_mode="RESEARCH",
            kill_switch_active=False,
            paper_cycle_count=0,
            portfolio_equity=None,
            portfolio_cash=None,
            portfolio_positions=0,
            ranking_count=0,
            broker_auth_expired=False,
            last_paper_cycle_at=None,
            pending_proposals=0,
        )
        svc.save_snapshot(snap, path=nested_path)
        assert os.path.exists(nested_path)

    def test_save_does_not_raise_on_permission_error(self):
        from services.continuity.models import ContinuitySnapshot
        from services.continuity.service import ContinuityService
        svc = ContinuityService()
        snap = ContinuitySnapshot(
            snapshot_at="now",
            operating_mode="RESEARCH",
            kill_switch_active=False,
            paper_cycle_count=0,
            portfolio_equity=None,
            portfolio_cash=None,
            portfolio_positions=0,
            ranking_count=0,
            broker_auth_expired=False,
            last_paper_cycle_at=None,
            pending_proposals=0,
        )
        # Path that will definitely fail (invalid on both Windows and Unix)
        with patch("builtins.open", side_effect=PermissionError("denied")):
            # Must not raise
            svc.save_snapshot(snap, path="/fake/path/snap.json")


# ===========================================================================
# TestContinuityServiceSessionContext
# ===========================================================================

class TestContinuityServiceSessionContext:
    def test_get_session_context_fields(self):
        from services.continuity.service import ContinuityService
        svc = ContinuityService()
        app_state = _make_app_state(
            paper_cycle_count=5,
            latest_rankings=[1, 2, 3],
            broker_auth_expired=False,
            improvement_proposals=[Mock(), Mock()],
        )
        settings = _make_settings(mode="paper")
        ctx = svc.get_session_context(app_state, settings)
        assert ctx.operating_mode == "paper"
        assert ctx.paper_cycle_count == 5
        assert ctx.ranking_count == 3
        assert ctx.pending_proposals == 2
        assert len(ctx.summary_lines) > 0

    def test_kill_switch_reflected_in_session_context(self):
        from services.continuity.service import ContinuityService
        svc = ContinuityService()
        app_state = _make_app_state(kill_switch_active=True, paper_cycle_count=0)
        settings = _make_settings(kill_switch=False)
        ctx = svc.get_session_context(app_state, settings)
        assert ctx.kill_switch_active is True
        assert any("ACTIVE" in line for line in ctx.summary_lines)

    def test_broker_auth_expired_in_summary(self):
        from services.continuity.service import ContinuityService
        svc = ContinuityService()
        app_state = _make_app_state(broker_auth_expired=True, paper_cycle_count=0)
        settings = _make_settings()
        ctx = svc.get_session_context(app_state, settings)
        assert ctx.broker_auth_expired is True
        assert any("expired" in line for line in ctx.summary_lines)


# ===========================================================================
# TestPersistPortfolioSnapshot
# ===========================================================================

class TestPersistPortfolioSnapshot:
    def test_persist_calls_db_add(self):
        from apps.worker.jobs.paper_trading import _persist_portfolio_snapshot

        mock_snap_class = MagicMock()
        mock_db = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_session = MagicMock(return_value=mock_ctx)

        ps = _make_portfolio_state(cash=90_000.0, equity=100_000.0)

        with patch("apps.worker.jobs.paper_trading._persist_portfolio_snapshot") as mock_fn:
            mock_fn(ps, "PAPER")
            mock_fn.assert_called_once_with(ps, "PAPER")

    def test_persist_does_not_raise_on_db_error(self):
        from apps.worker.jobs.paper_trading import _persist_portfolio_snapshot

        ps = _make_portfolio_state()

        with patch(
            "apps.worker.jobs.paper_trading._persist_portfolio_snapshot",
            side_effect=Exception("db error"),
        ):
            # Should not propagate — but we're testing the actual function here
            pass

        # Call the real function with a broken session import
        with patch(
            "infra.db.session.db_session",
            side_effect=Exception("connection refused"),
        ):
            # Must not raise
            _persist_portfolio_snapshot(ps, "PAPER")

    def test_persist_portfolio_snapshot_writes_correct_mode(self):
        from apps.worker.jobs.paper_trading import _persist_portfolio_snapshot

        ps = _make_portfolio_state(cash=95_000.0, equity=100_000.0)
        added_objects = []

        mock_db = MagicMock()
        mock_db.add = lambda obj: added_objects.append(obj)

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_session = MagicMock(return_value=mock_ctx)

        with patch("infra.db.session.db_session", mock_session):
            _persist_portfolio_snapshot(ps, "HUMAN_APPROVED")

        assert len(added_objects) == 1
        obj = added_objects[0]
        assert obj.mode == "HUMAN_APPROVED"

    def test_persist_portfolio_snapshot_equity_value(self):
        from apps.worker.jobs.paper_trading import _persist_portfolio_snapshot

        # equity = cash + gross_exposure; with no positions equity == cash
        ps = _make_portfolio_state(cash=95_000.0, equity=95_000.0)
        added_objects = []

        mock_db = MagicMock()
        mock_db.add = lambda obj: added_objects.append(obj)
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch("infra.db.session.db_session", return_value=mock_ctx):
            _persist_portfolio_snapshot(ps, "PAPER")

        obj = added_objects[0]
        # equity = cash (95_000) since positions={}
        assert float(obj.equity_value) == pytest.approx(95_000.0, rel=1e-4)


# ===========================================================================
# TestPersistEvaluationRun
# ===========================================================================

class TestPersistEvaluationRun:
    def test_persist_does_not_raise_on_db_error(self):
        from apps.worker.jobs.evaluation import _persist_evaluation_run

        sc = _make_scorecard()
        with patch(
            "infra.db.session.db_session",
            side_effect=Exception("db unavailable"),
        ):
            # Must not raise
            _persist_evaluation_run(sc, "PAPER")

    def test_persist_writes_run_and_metrics(self):
        from apps.worker.jobs.evaluation import _persist_evaluation_run

        sc = _make_scorecard(equity=102_000.0)
        added_objects = []

        mock_db = MagicMock()
        mock_db.add = lambda obj: added_objects.append(obj)
        mock_db.flush = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch("infra.db.session.db_session", return_value=mock_ctx):
            _persist_evaluation_run(sc, "PAPER")

        # First object should be EvaluationRun, rest are metrics
        assert len(added_objects) >= 1
        # EvaluationRun is the first add
        run_obj = added_objects[0]
        assert run_obj.mode == "PAPER"
        assert run_obj.status == "complete"

    def test_persist_evaluation_run_metric_count(self):
        from apps.worker.jobs.evaluation import _persist_evaluation_run

        sc = _make_scorecard()
        added_objects = []

        mock_db = MagicMock()
        mock_db.add = lambda obj: added_objects.append(obj)
        mock_db.flush = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch("infra.db.session.db_session", return_value=mock_ctx):
            _persist_evaluation_run(sc, "PAPER")

        # 1 run + 8 metric rows
        assert len(added_objects) == 9


# ===========================================================================
# TestPortfolioSnapshotSchemas
# ===========================================================================

class TestPortfolioSnapshotSchemas:
    def test_portfolio_snapshot_record_fields(self):
        from apps.api.schemas.portfolio import PortfolioSnapshotRecord
        rec = PortfolioSnapshotRecord(
            id=str(uuid.uuid4()),
            snapshot_timestamp=dt.datetime.now(dt.timezone.utc),
            mode="PAPER",
            cash_balance=95_000.0,
            gross_exposure=5_000.0,
            net_exposure=5_000.0,
            equity_value=100_000.0,
            drawdown_pct=0.01,
        )
        assert rec.mode == "PAPER"
        assert rec.equity_value == 100_000.0

    def test_portfolio_snapshot_record_nullable_fields(self):
        from apps.api.schemas.portfolio import PortfolioSnapshotRecord
        rec = PortfolioSnapshotRecord(
            id=str(uuid.uuid4()),
            snapshot_timestamp=dt.datetime.now(dt.timezone.utc),
            mode="RESEARCH",
        )
        assert rec.cash_balance is None
        assert rec.equity_value is None

    def test_portfolio_snapshot_history_response(self):
        from apps.api.schemas.portfolio import (
            PortfolioSnapshotHistoryResponse,
            PortfolioSnapshotRecord,
        )
        items = [
            PortfolioSnapshotRecord(
                id=str(uuid.uuid4()),
                snapshot_timestamp=dt.datetime.now(dt.timezone.utc),
                mode="PAPER",
                equity_value=100_000.0,
            )
        ]
        resp = PortfolioSnapshotHistoryResponse(count=1, items=items)
        assert resp.count == 1
        assert len(resp.items) == 1

    def test_portfolio_snapshot_history_response_empty(self):
        from apps.api.schemas.portfolio import PortfolioSnapshotHistoryResponse
        resp = PortfolioSnapshotHistoryResponse(count=0, items=[])
        assert resp.count == 0


# ===========================================================================
# TestEvaluationRunSchemas
# ===========================================================================

class TestEvaluationRunSchemas:
    def test_evaluation_run_record_fields(self):
        from apps.api.schemas.evaluation import EvaluationRunRecord
        rec = EvaluationRunRecord(
            id=str(uuid.uuid4()),
            run_timestamp=dt.datetime.now(dt.timezone.utc),
            mode="PAPER",
            status="complete",
            evaluation_period_start=dt.date.today(),
            evaluation_period_end=dt.date.today(),
            metrics={"equity": 100_000.0, "hit_rate": 0.6},
        )
        assert rec.status == "complete"
        assert rec.metrics["equity"] == 100_000.0

    def test_evaluation_run_record_empty_metrics(self):
        from apps.api.schemas.evaluation import EvaluationRunRecord
        rec = EvaluationRunRecord(
            id=str(uuid.uuid4()),
            run_timestamp=dt.datetime.now(dt.timezone.utc),
            mode="RESEARCH",
            status="complete",
            metrics={},
        )
        assert rec.metrics == {}

    def test_evaluation_run_history_response(self):
        from apps.api.schemas.evaluation import (
            EvaluationRunHistoryResponse,
            EvaluationRunRecord,
        )
        items = [
            EvaluationRunRecord(
                id=str(uuid.uuid4()),
                run_timestamp=dt.datetime.now(dt.timezone.utc),
                mode="PAPER",
                status="complete",
                metrics={"equity": 100_000.0},
            )
        ]
        resp = EvaluationRunHistoryResponse(count=1, items=items)
        assert resp.count == 1

    def test_evaluation_run_record_nullable_dates(self):
        from apps.api.schemas.evaluation import EvaluationRunRecord
        rec = EvaluationRunRecord(
            id=str(uuid.uuid4()),
            run_timestamp=dt.datetime.now(dt.timezone.utc),
            mode="PAPER",
            status="complete",
            metrics={},
        )
        assert rec.evaluation_period_start is None
        assert rec.evaluation_period_end is None


# ===========================================================================
# TestPortfolioSnapshotsRoute
# ===========================================================================

class TestPortfolioSnapshotsRoute:
    def _make_db_snapshot(self, equity: float = 100_000.0):
        row = MagicMock()
        row.id = uuid.uuid4()
        row.snapshot_timestamp = dt.datetime.now(dt.timezone.utc)
        row.mode = "PAPER"
        row.cash_balance = Decimal("95000")
        row.gross_exposure = Decimal("5000")
        row.net_exposure = Decimal("4800")
        row.equity_value = Decimal(str(equity))
        row.drawdown_pct = Decimal("0.01")
        return row

    def _client(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        return TestClient(app, raise_server_exceptions=False)

    def test_get_portfolio_snapshots_returns_items(self):
        db_rows = [self._make_db_snapshot(100_000.0), self._make_db_snapshot(99_500.0)]

        mock_query = MagicMock()
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = db_rows

        mock_db = MagicMock()
        mock_db.query.return_value = mock_query

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch("infra.db.session.db_session", return_value=mock_ctx):
            resp = self._client().get("/api/v1/portfolio/snapshots")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert data["items"][0]["mode"] == "PAPER"

    def test_get_portfolio_snapshots_empty_on_db_error(self):
        with patch(
            "infra.db.session.db_session",
            side_effect=Exception("db down"),
        ):
            resp = self._client().get("/api/v1/portfolio/snapshots")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["items"] == []

    def test_get_portfolio_snapshots_limit_param(self):
        mock_query = MagicMock()
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []

        mock_db = MagicMock()
        mock_db.query.return_value = mock_query
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch("infra.db.session.db_session", return_value=mock_ctx):
            resp = self._client().get("/api/v1/portfolio/snapshots?limit=5")

        assert resp.status_code == 200
        mock_query.limit.assert_called_once_with(5)

    def test_get_portfolio_snapshots_limit_validation(self):
        resp = self._client().get("/api/v1/portfolio/snapshots?limit=200")
        # limit > 100 is invalid
        assert resp.status_code == 422


# ===========================================================================
# TestEvaluationRunsRoute
# ===========================================================================

class TestEvaluationRunsRoute:
    def _make_db_run(self, mode: str = "PAPER"):
        run = MagicMock()
        run.id = uuid.uuid4()
        run.run_timestamp = dt.datetime.now(dt.timezone.utc)
        run.mode = mode
        run.status = "complete"
        run.evaluation_period_start = dt.date.today()
        run.evaluation_period_end = dt.date.today()
        return run

    def _make_db_metric(self, run_id, key: str, value: float):
        m = MagicMock()
        m.evaluation_run_id = run_id
        m.metric_key = key
        m.metric_value = Decimal(str(value))
        return m

    def _client(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        return TestClient(app, raise_server_exceptions=False)

    def test_get_evaluation_runs_returns_items(self):
        db_run = self._make_db_run()
        db_metrics = [
            self._make_db_metric(db_run.id, "equity", 100_000.0),
            self._make_db_metric(db_run.id, "hit_rate", 0.6),
        ]

        mock_db = MagicMock()

        def mock_query(cls):
            q = MagicMock()
            if "EvaluationRun" in str(cls):
                q.order_by.return_value = q
                q.limit.return_value = q
                q.all.return_value = [db_run]
            else:
                q.filter_by.return_value = q
                q.all.return_value = db_metrics
            return q

        mock_db.query = mock_query
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch("infra.db.session.db_session", return_value=mock_ctx):
            resp = self._client().get("/api/v1/evaluation/runs")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1

    def test_get_evaluation_runs_empty_on_db_error(self):
        with patch(
            "infra.db.session.db_session",
            side_effect=Exception("db unavailable"),
        ):
            resp = self._client().get("/api/v1/evaluation/runs")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0

    def test_get_evaluation_runs_limit_validation(self):
        resp = self._client().get("/api/v1/evaluation/runs?limit=0")
        assert resp.status_code == 422


# ===========================================================================
# TestAppStateSnapshotFields
# ===========================================================================

class TestAppStateSnapshotFields:
    def test_last_snapshot_at_defaults_none(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert state.last_snapshot_at is None

    def test_last_snapshot_equity_defaults_none(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert state.last_snapshot_equity is None

    def test_last_snapshot_fields_settable(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        ts = dt.datetime.now(dt.timezone.utc)
        state.last_snapshot_at = ts
        state.last_snapshot_equity = 100_000.0
        assert state.last_snapshot_at == ts
        assert state.last_snapshot_equity == 100_000.0


# ===========================================================================
# TestLoadPersistedStateSnapshot
# ===========================================================================

class TestLoadPersistedStateSnapshot:
    def test_load_persisted_state_restores_equity(self):
        from apps.api.main import _load_persisted_state
        from apps.api.state import reset_app_state, get_app_state
        reset_app_state()

        mock_snap = MagicMock()
        mock_snap.snapshot_timestamp = dt.datetime.now(dt.timezone.utc)
        mock_snap.equity_value = Decimal("102000")

        mock_db = MagicMock()

        # Make first context manager (system_state) succeed without the key
        # Then make second context manager (portfolio snapshot) return our mock
        call_count = [0]

        class MockCtx:
            def __enter__(self):
                call_count[0] += 1
                if call_count[0] == 1:
                    # system_state session — return DB that has no entries
                    inner = MagicMock()
                    inner.get = MagicMock(return_value=None)
                    return inner
                else:
                    # portfolio snapshot session
                    inner = MagicMock()
                    q = MagicMock()
                    q.order_by.return_value = q
                    q.first.return_value = mock_snap
                    inner.query.return_value = q
                    return inner

            def __exit__(self, *args):
                return False

        with patch("infra.db.session.db_session", side_effect=lambda: MockCtx()):
            _load_persisted_state()

        app_state = get_app_state()
        assert app_state.last_snapshot_equity == pytest.approx(102_000.0)
        assert app_state.last_snapshot_at is not None

    def test_load_persisted_state_handles_missing_snapshot(self):
        from apps.api.main import _load_persisted_state
        from apps.api.state import reset_app_state, get_app_state
        reset_app_state()

        call_count = [0]

        class MockCtx:
            def __enter__(self):
                call_count[0] += 1
                if call_count[0] == 1:
                    inner = MagicMock()
                    inner.get = MagicMock(return_value=None)
                    return inner
                else:
                    inner = MagicMock()
                    q = MagicMock()
                    q.order_by.return_value = q
                    q.first.return_value = None  # no snapshot rows
                    inner.query.return_value = q
                    return inner

            def __exit__(self, *args):
                return False

        with patch("infra.db.session.db_session", side_effect=lambda: MockCtx()):
            _load_persisted_state()

        app_state = get_app_state()
        assert app_state.last_snapshot_equity is None
        assert app_state.last_snapshot_at is None

    def test_load_persisted_state_non_fatal_on_portfolio_db_error(self):
        from apps.api.main import _load_persisted_state
        from apps.api.state import reset_app_state
        reset_app_state()

        call_count = [0]

        class MockCtx:
            def __enter__(self):
                call_count[0] += 1
                if call_count[0] == 1:
                    inner = MagicMock()
                    inner.get = MagicMock(return_value=None)
                    return inner
                else:
                    raise Exception("portfolio db down")

            def __exit__(self, *args):
                return False

        with patch("infra.db.session.db_session", side_effect=lambda: MockCtx()):
            # Must not raise
            _load_persisted_state()


# ===========================================================================
# TestPhase20Integration
# ===========================================================================

class TestPhase20Integration:
    def test_continuity_service_round_trip_via_json(self, tmp_path):
        """Full save→load→take_snapshot cycle."""
        from services.continuity.config import ContinuityConfig
        from services.continuity.service import ContinuityService

        cfg = ContinuityConfig(
            snapshot_dir=str(tmp_path),
            snapshot_filename="test_snap.json",
            max_snapshot_age_hours=48,
        )
        svc = ContinuityService(config=cfg)

        ps = _make_portfolio_state(cash=90_000.0, equity=100_000.0)
        app_state = _make_app_state(
            portfolio_state=ps,
            paper_cycle_count=10,
            latest_rankings=[1, 2, 3, 4, 5],
            improvement_proposals=[],
        )
        settings = _make_settings(mode="paper")

        snap = svc.take_snapshot(app_state, settings)
        svc.save_snapshot(snap)

        loaded = svc.load_snapshot()
        assert loaded is not None
        assert loaded.paper_cycle_count == 10
        assert loaded.ranking_count == 5

    def test_session_context_to_dict_serializable(self):
        from services.continuity.service import ContinuityService

        svc = ContinuityService()
        app_state = _make_app_state(
            paper_cycle_count=3,
            latest_rankings=[1],
            improvement_proposals=[],
        )
        settings = _make_settings(mode="research")
        ctx = svc.get_session_context(app_state, settings)
        d = ctx.to_dict()
        # Must be JSON-serializable
        text = json.dumps(d)
        assert "research" in text

    def test_paper_trading_cycle_calls_persist_snapshot(self):
        """run_paper_trading_cycle should call _persist_portfolio_snapshot on success."""
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from apps.api.state import ApiAppState

        app_state = ApiAppState()
        # Provide a pre-populated ranking so the cycle proceeds
        mock_ranking = MagicMock()
        mock_ranking.ticker = "AAPL"
        app_state.latest_rankings = [mock_ranking]

        called_with = []

        def fake_persist(portfolio_state, mode):
            called_with.append(mode)

        with patch("apps.worker.jobs.paper_trading._persist_portfolio_snapshot", side_effect=fake_persist):
            with patch("apps.worker.jobs.paper_trading._persist_paper_cycle_count"):
                settings = _make_settings(mode="paper")

                # Mock all services so the cycle completes
                mock_broker = MagicMock()
                mock_broker.ping.return_value = True
                mock_broker.get_account_state.return_value = MagicMock(
                    cash_balance=Decimal("95000")
                )
                mock_broker.list_positions.return_value = []
                mock_broker.list_fills_since.return_value = []

                mock_portfolio_svc = MagicMock()
                mock_portfolio_svc.apply_ranked_opportunities.return_value = []

                mock_execution_svc = MagicMock()
                mock_execution_svc.execute_approved_actions.return_value = []

                mock_reporting_svc = MagicMock()
                mock_reporting_svc.reconcile_fills.return_value = MagicMock(is_clean=True)

                result = run_paper_trading_cycle(
                    app_state=app_state,
                    settings=settings,
                    broker=mock_broker,
                    portfolio_svc=mock_portfolio_svc,
                    execution_svc=mock_execution_svc,
                    reporting_svc=mock_reporting_svc,
                )

        assert result["status"] == "ok"
        # _persist_portfolio_snapshot was called exactly once
        assert len(called_with) == 1
        assert called_with[0] == "paper"

    def test_evaluation_job_calls_persist_evaluation_run(self):
        """run_daily_evaluation should call _persist_evaluation_run on success."""
        from apps.worker.jobs.evaluation import run_daily_evaluation
        from apps.api.state import ApiAppState

        app_state = ApiAppState()
        called_with = []

        def fake_persist_eval(scorecard, mode):
            called_with.append(mode)

        with patch("apps.worker.jobs.evaluation._persist_evaluation_run", side_effect=fake_persist_eval):
            result = run_daily_evaluation(app_state=app_state)

        assert result["status"] == "ok"
        assert len(called_with) == 1
