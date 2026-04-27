"""
Phase 34 — Strategy Backtesting Comparison API + Dashboard Page
===============================================================

Tests cover:
  TestBacktestRunORM              — BacktestRun model importable, columns correct
  TestBacktestMigration           — migration file exists with correct revision chain
  TestBacktestSchemas             — all 5 Pydantic schema classes validate correctly
  TestBacktestComparisonService   — run_comparison returns 6 results (5+combined)
  TestBacktestComparisonPersist   — DB rows written via session_factory
  TestBacktestComparisonNoDB      — no session_factory: runs succeed without persisting
  TestBacktestComparisonEngineError — engine failure captured in error field
  TestBacktestCompareEndpoint     — POST /api/v1/backtest/compare happy path
  TestBacktestRunsEndpoint        — GET /api/v1/backtest/runs graceful fallback
  TestBacktestDetailEndpoint      — GET /api/v1/backtest/runs/{comparison_id}
  TestBacktestDashboardPage       — GET /dashboard/backtest renders correctly
"""
from __future__ import annotations

import datetime as dt
import json
import uuid
from contextlib import contextmanager
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app_state(**overrides: Any):
    from apps.api.state import ApiAppState
    state = ApiAppState()
    for k, v in overrides.items():
        setattr(state, k, v)
    return state


def _make_settings(**overrides):
    from config.settings import Settings
    base = dict(
        env="development",
        operating_mode="research",
        log_level="INFO",
        secret_key="test-secret",
        is_kill_switch_active=False,
        max_positions=10,
        max_single_name_pct=0.15,
        daily_loss_limit_pct=0.02,
        max_drawdown_pct=0.10,
        db_url="postgresql://localhost/apis_test",
        alpaca_api_key="test-key",
        alpaca_api_secret="test-secret-val",
    )
    base.update(overrides)
    return Settings(**base)


def _make_backtest_result(
    total_return_pct: float = 5.0,
    sharpe_ratio: float = 1.2,
    max_drawdown_pct: float = -3.0,
    win_rate: float = 0.6,
    total_trades: int = 10,
    days_simulated: int = 30,
    final_portfolio_value: float = 105_000.0,
    initial_cash: float = 100_000.0,
) -> Any:
    from services.backtest.models import BacktestResult
    r = BacktestResult(
        start_date=dt.date(2025, 1, 1),
        end_date=dt.date(2025, 3, 31),
        initial_cash=Decimal(str(initial_cash)),
        final_portfolio_value=Decimal(str(final_portfolio_value)),
    )
    r.total_return_pct = total_return_pct
    r.sharpe_ratio = sharpe_ratio
    r.max_drawdown_pct = max_drawdown_pct
    r.win_rate = win_rate
    r.total_trades = total_trades
    r.days_simulated = days_simulated
    return r


@contextmanager
def _null_session():
    """Context manager that yields a mock DB session."""
    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = MagicMock(return_value=False)
    yield session


def _make_session_factory(session=None):
    """Return a callable session factory that yields a mock session."""
    mock_session = session or MagicMock()
    mock_session.__enter__ = lambda s: s
    mock_session.__exit__ = MagicMock(return_value=False)

    @contextmanager
    def _factory():
        yield mock_session

    return _factory


# ---------------------------------------------------------------------------
# TestBacktestRunORM
# ---------------------------------------------------------------------------

class TestBacktestRunORM:
    def test_import(self):
        from infra.db.models.backtest import BacktestRun
        assert BacktestRun is not None

    def test_tablename(self):
        from infra.db.models.backtest import BacktestRun
        assert BacktestRun.__tablename__ == "backtest_runs"

    def test_required_columns(self):
        from infra.db.models.backtest import BacktestRun
        cols = {c.name for c in BacktestRun.__table__.columns}
        for col in (
            "id", "comparison_id", "strategy_name", "start_date", "end_date",
            "ticker_count", "total_return_pct", "sharpe_ratio", "max_drawdown_pct",
            "win_rate", "total_trades", "days_simulated", "final_portfolio_value",
            "initial_cash", "status",
        ):
            assert col in cols, f"Missing column: {col}"

    def test_index_on_comparison_id(self):
        from infra.db.models.backtest import BacktestRun
        index_names = {idx.name for idx in BacktestRun.__table__.indexes}
        assert "ix_backtest_runs_comparison_id" in index_names

    def test_exported_from_models_init(self):
        from infra.db.models import BacktestRun
        assert BacktestRun is not None

    def test_instantiate(self):
        from infra.db.models.backtest import BacktestRun
        row = BacktestRun(
            id=uuid.uuid4(),
            comparison_id=str(uuid.uuid4()),
            strategy_name="momentum_v1",
            start_date=dt.date(2025, 1, 1),
            end_date=dt.date(2025, 3, 31),
            ticker_count=5,
            total_return_pct=3.5,
            status="completed",
        )
        assert row.strategy_name == "momentum_v1"
        assert row.ticker_count == 5


# ---------------------------------------------------------------------------
# TestBacktestMigration
# ---------------------------------------------------------------------------

class TestBacktestMigration:
    def test_migration_file_exists(self):
        import importlib
        mod = importlib.import_module(
            "infra.db.versions.e5f6a7b8c9d0_add_backtest_runs"
        )
        assert mod is not None

    def test_revision_id(self):
        from infra.db.versions.e5f6a7b8c9d0_add_backtest_runs import revision
        assert revision == "e5f6a7b8c9d0"

    def test_down_revision(self):
        from infra.db.versions.e5f6a7b8c9d0_add_backtest_runs import down_revision
        assert down_revision == "d4e5f6a7b8c9"

    def test_upgrade_callable(self):
        from infra.db.versions.e5f6a7b8c9d0_add_backtest_runs import upgrade
        assert callable(upgrade)

    def test_downgrade_callable(self):
        from infra.db.versions.e5f6a7b8c9d0_add_backtest_runs import downgrade
        assert callable(downgrade)


# ---------------------------------------------------------------------------
# TestBacktestSchemas
# ---------------------------------------------------------------------------

class TestBacktestSchemas:
    def test_import_all(self):
        from apps.api.schemas.backtest import (
            BacktestCompareRequest,
        )
        assert BacktestCompareRequest is not None

    def test_compare_request_defaults(self):
        from apps.api.schemas.backtest import BacktestCompareRequest
        req = BacktestCompareRequest(
            start_date=dt.date(2025, 1, 1),
            end_date=dt.date(2025, 3, 31),
        )
        assert len(req.tickers) > 0
        assert req.initial_cash == 100_000.0

    def test_compare_request_custom(self):
        from apps.api.schemas.backtest import BacktestCompareRequest
        req = BacktestCompareRequest(
            tickers=["AAPL", "MSFT"],
            start_date=dt.date(2025, 1, 1),
            end_date=dt.date(2025, 3, 31),
            initial_cash=50_000.0,
        )
        assert req.tickers == ["AAPL", "MSFT"]
        assert req.initial_cash == 50_000.0

    def test_backtest_run_record(self):
        from apps.api.schemas.backtest import BacktestRunRecord
        rec = BacktestRunRecord(
            comparison_id="abc",
            strategy_name="momentum_v1",
            start_date=dt.date(2025, 1, 1),
            end_date=dt.date(2025, 3, 31),
            ticker_count=5,
            total_return_pct=4.5,
            sharpe_ratio=1.1,
        )
        assert rec.strategy_name == "momentum_v1"
        assert rec.total_return_pct == 4.5

    def test_comparison_response(self):
        from apps.api.schemas.backtest import BacktestComparisonResponse, BacktestRunRecord
        rec = BacktestRunRecord(
            comparison_id="cid1",
            strategy_name="all_strategies",
            start_date=dt.date(2025, 1, 1),
            end_date=dt.date(2025, 3, 31),
            ticker_count=3,
        )
        resp = BacktestComparisonResponse(
            comparison_id="cid1",
            run_count=1,
            runs=[rec],
        )
        assert resp.run_count == 1
        assert resp.runs[0].strategy_name == "all_strategies"

    def test_run_list_response(self):
        from apps.api.schemas.backtest import BacktestComparisonSummary, BacktestRunListResponse
        summ = BacktestComparisonSummary(
            comparison_id="c1",
            run_count=6,
            best_strategy="momentum_v1",
            best_total_return_pct=7.2,
        )
        resp = BacktestRunListResponse(count=1, comparisons=[summ])
        assert resp.count == 1
        assert resp.comparisons[0].best_strategy == "momentum_v1"

    def test_run_detail_response(self):
        from apps.api.schemas.backtest import BacktestRunDetailResponse
        resp = BacktestRunDetailResponse(
            comparison_id="xyz",
            run_count=0,
            runs=[],
        )
        assert resp.run_count == 0


# ---------------------------------------------------------------------------
# TestBacktestComparisonService
# ---------------------------------------------------------------------------

class TestBacktestComparisonService:
    def _make_mock_engine_factory(self, result=None):
        """Return an engine_factory whose engine.run() returns the given result."""
        mock_result = result or _make_backtest_result()
        mock_engine = MagicMock()
        mock_engine.run.return_value = mock_result
        return lambda strategies: mock_engine

    def test_import(self):
        from services.backtest.comparison import BacktestComparisonService
        assert BacktestComparisonService is not None

    def test_run_comparison_returns_6_results(self):
        from services.backtest.comparison import BacktestComparisonService
        factory = self._make_mock_engine_factory()
        svc = BacktestComparisonService(engine_factory=factory)
        cid, results = svc.run_comparison(
            tickers=["AAPL", "MSFT"],
            start_date=dt.date(2025, 1, 1),
            end_date=dt.date(2025, 3, 31),
        )
        assert len(results) == 6

    def test_run_comparison_strategy_names(self):
        from services.backtest.comparison import BacktestComparisonService
        factory = self._make_mock_engine_factory()
        svc = BacktestComparisonService(engine_factory=factory)
        _, results = svc.run_comparison(
            tickers=["AAPL"],
            start_date=dt.date(2025, 1, 1),
            end_date=dt.date(2025, 3, 31),
        )
        names = [r.strategy_name for r in results]
        assert "momentum_v1" in names
        assert "theme_alignment_v1" in names
        assert "macro_tailwind_v1" in names
        assert "sentiment_v1" in names
        assert "valuation_v1" in names
        assert "all_strategies" in names

    def test_run_comparison_comparison_id_consistent(self):
        from services.backtest.comparison import BacktestComparisonService
        factory = self._make_mock_engine_factory()
        svc = BacktestComparisonService(engine_factory=factory)
        cid, results = svc.run_comparison(
            tickers=["AAPL"],
            start_date=dt.date(2025, 1, 1),
            end_date=dt.date(2025, 3, 31),
        )
        for r in results:
            # Each result has its own run_id but no comparison_id field on StrategyRunResult
            # comparison_id is returned as first element
            assert cid is not None
        assert isinstance(cid, str)

    def test_run_comparison_each_result_has_run_id(self):
        from services.backtest.comparison import BacktestComparisonService
        factory = self._make_mock_engine_factory()
        svc = BacktestComparisonService(engine_factory=factory)
        _, results = svc.run_comparison(
            tickers=["AAPL"],
            start_date=dt.date(2025, 1, 1),
            end_date=dt.date(2025, 3, 31),
        )
        for r in results:
            assert r.run_id is not None

    def test_run_comparison_no_errors_on_success(self):
        from services.backtest.comparison import BacktestComparisonService
        factory = self._make_mock_engine_factory()
        svc = BacktestComparisonService(engine_factory=factory)
        _, results = svc.run_comparison(
            tickers=["AAPL"],
            start_date=dt.date(2025, 1, 1),
            end_date=dt.date(2025, 3, 31),
        )
        for r in results:
            assert r.error is None

    def test_run_comparison_unique_comparison_ids_across_calls(self):
        from services.backtest.comparison import BacktestComparisonService
        factory = self._make_mock_engine_factory()
        svc = BacktestComparisonService(engine_factory=factory)
        cid1, _ = svc.run_comparison(
            tickers=["AAPL"],
            start_date=dt.date(2025, 1, 1),
            end_date=dt.date(2025, 3, 31),
        )
        cid2, _ = svc.run_comparison(
            tickers=["AAPL"],
            start_date=dt.date(2025, 1, 1),
            end_date=dt.date(2025, 3, 31),
        )
        assert cid1 != cid2


# ---------------------------------------------------------------------------
# TestBacktestComparisonPersist
# ---------------------------------------------------------------------------

class TestBacktestComparisonPersist:
    def test_persist_called_for_each_run(self):
        from services.backtest.comparison import BacktestComparisonService

        mock_result = _make_backtest_result()
        mock_engine = MagicMock()
        mock_engine.run.return_value = mock_result
        factory = lambda strategies: mock_engine

        added_rows = []
        mock_session = MagicMock()
        mock_session.add.side_effect = added_rows.append
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)

        @contextmanager
        def session_factory():
            yield mock_session

        svc = BacktestComparisonService(
            engine_factory=factory,
            session_factory=session_factory,
        )
        _, results = svc.run_comparison(
            tickers=["AAPL"],
            start_date=dt.date(2025, 1, 1),
            end_date=dt.date(2025, 3, 31),
        )
        # 6 runs → 6 rows persisted
        assert len(added_rows) == 6
        assert mock_session.commit.call_count == 6

    def test_persist_row_fields(self):
        from services.backtest.comparison import BacktestComparisonService

        mock_result = _make_backtest_result(total_return_pct=7.5, sharpe_ratio=1.8)
        mock_engine = MagicMock()
        mock_engine.run.return_value = mock_result
        factory = lambda strategies: mock_engine

        added_rows = []
        mock_session = MagicMock()
        mock_session.add.side_effect = added_rows.append
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)

        @contextmanager
        def session_factory():
            yield mock_session

        svc = BacktestComparisonService(
            engine_factory=factory,
            session_factory=session_factory,
        )
        cid, _ = svc.run_comparison(
            tickers=["AAPL", "MSFT"],
            start_date=dt.date(2025, 1, 1),
            end_date=dt.date(2025, 3, 31),
        )
        momentum_row = next(r for r in added_rows if r.strategy_name == "momentum_v1")
        assert momentum_row.comparison_id == cid
        assert momentum_row.total_return_pct == 7.5
        assert momentum_row.sharpe_ratio == 1.8
        assert momentum_row.ticker_count == 2
        assert momentum_row.status == "completed"


# ---------------------------------------------------------------------------
# TestBacktestComparisonNoDB
# ---------------------------------------------------------------------------

class TestBacktestComparisonNoDB:
    def test_no_session_factory_runs_succeed(self):
        from services.backtest.comparison import BacktestComparisonService

        mock_result = _make_backtest_result()
        mock_engine = MagicMock()
        mock_engine.run.return_value = mock_result
        factory = lambda strategies: mock_engine

        svc = BacktestComparisonService(engine_factory=factory, session_factory=None)
        cid, results = svc.run_comparison(
            tickers=["AAPL"],
            start_date=dt.date(2025, 1, 1),
            end_date=dt.date(2025, 3, 31),
        )
        assert len(results) == 6
        assert cid is not None

    def test_no_session_factory_no_db_calls(self):
        from services.backtest.comparison import BacktestComparisonService

        mock_result = _make_backtest_result()
        mock_engine = MagicMock()
        mock_engine.run.return_value = mock_result
        factory = lambda strategies: mock_engine

        svc = BacktestComparisonService(engine_factory=factory, session_factory=None)
        # Should complete without any DB interaction
        cid, results = svc.run_comparison(
            tickers=["AAPL"],
            start_date=dt.date(2025, 1, 1),
            end_date=dt.date(2025, 3, 31),
        )
        assert all(r.error is None for r in results)


# ---------------------------------------------------------------------------
# TestBacktestComparisonEngineError
# ---------------------------------------------------------------------------

class TestBacktestComparisonEngineError:
    def test_engine_error_captured_not_raised(self):
        from services.backtest.comparison import BacktestComparisonService

        mock_engine = MagicMock()
        mock_engine.run.side_effect = RuntimeError("yfinance unavailable")
        factory = lambda strategies: mock_engine

        svc = BacktestComparisonService(engine_factory=factory, session_factory=None)
        cid, results = svc.run_comparison(
            tickers=["AAPL"],
            start_date=dt.date(2025, 1, 1),
            end_date=dt.date(2025, 3, 31),
        )
        assert len(results) == 6
        for r in results:
            assert r.error is not None
            assert "yfinance unavailable" in r.error

    def test_db_persist_error_does_not_raise(self):
        from services.backtest.comparison import BacktestComparisonService

        mock_result = _make_backtest_result()
        mock_engine = MagicMock()
        mock_engine.run.return_value = mock_result
        factory = lambda strategies: mock_engine

        bad_session = MagicMock()
        bad_session.add.side_effect = Exception("DB down")
        bad_session.__enter__ = lambda s: s
        bad_session.__exit__ = MagicMock(return_value=False)

        @contextmanager
        def bad_factory():
            yield bad_session

        svc = BacktestComparisonService(engine_factory=factory, session_factory=bad_factory)
        cid, results = svc.run_comparison(
            tickers=["AAPL"],
            start_date=dt.date(2025, 1, 1),
            end_date=dt.date(2025, 3, 31),
        )
        # Persisting failed but results still returned
        assert len(results) == 6


# ---------------------------------------------------------------------------
# TestBacktestCompareEndpoint
# ---------------------------------------------------------------------------

class TestBacktestCompareEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self):
        from apps.api.main import app
        from apps.api.state import get_app_state
        from config.settings import get_settings

        state = _make_app_state()
        settings = _make_settings()
        app.dependency_overrides[get_app_state] = lambda: state
        app.dependency_overrides[get_settings] = lambda: settings
        self.client = TestClient(app, raise_server_exceptions=False)
        yield
        app.dependency_overrides.clear()

    def test_compare_returns_200(self):
        mock_result = _make_backtest_result()
        mock_engine = MagicMock()
        mock_engine.run.return_value = mock_result

        with patch(
            "services.backtest.comparison.BacktestEngine",
            return_value=mock_engine,
        ):
            resp = self.client.post(
                "/api/v1/backtest/compare",
                json={
                    "tickers": ["AAPL", "MSFT"],
                    "start_date": "2025-01-01",
                    "end_date": "2025-03-31",
                },
            )
        assert resp.status_code == 200

    def test_compare_response_structure(self):
        mock_result = _make_backtest_result()
        mock_engine = MagicMock()
        mock_engine.run.return_value = mock_result

        with patch(
            "services.backtest.comparison.BacktestEngine",
            return_value=mock_engine,
        ):
            resp = self.client.post(
                "/api/v1/backtest/compare",
                json={
                    "tickers": ["AAPL"],
                    "start_date": "2025-01-01",
                    "end_date": "2025-03-31",
                },
            )
        data = resp.json()
        assert "comparison_id" in data
        assert "run_count" in data
        assert "runs" in data
        assert data["run_count"] == 6

    def test_compare_has_all_strategy_names(self):
        mock_result = _make_backtest_result()
        mock_engine = MagicMock()
        mock_engine.run.return_value = mock_result

        with patch(
            "services.backtest.comparison.BacktestEngine",
            return_value=mock_engine,
        ):
            resp = self.client.post(
                "/api/v1/backtest/compare",
                json={
                    "tickers": ["AAPL"],
                    "start_date": "2025-01-01",
                    "end_date": "2025-03-31",
                },
            )
        runs = resp.json()["runs"]
        names = {r["strategy_name"] for r in runs}
        assert "momentum_v1" in names
        assert "all_strategies" in names

    def test_compare_returns_metrics(self):
        mock_result = _make_backtest_result(
            total_return_pct=8.5,
            sharpe_ratio=1.5,
            max_drawdown_pct=-4.0,
            win_rate=0.65,
        )
        mock_engine = MagicMock()
        mock_engine.run.return_value = mock_result

        with patch(
            "services.backtest.comparison.BacktestEngine",
            return_value=mock_engine,
        ):
            resp = self.client.post(
                "/api/v1/backtest/compare",
                json={
                    "tickers": ["AAPL"],
                    "start_date": "2025-01-01",
                    "end_date": "2025-03-31",
                },
            )
        run = resp.json()["runs"][0]
        assert run["total_return_pct"] == 8.5
        assert run["sharpe_ratio"] == 1.5


# ---------------------------------------------------------------------------
# TestBacktestRunsEndpoint
# ---------------------------------------------------------------------------

class TestBacktestRunsEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self):
        from apps.api.main import app
        from apps.api.state import get_app_state
        from config.settings import get_settings

        state = _make_app_state()
        settings = _make_settings()
        app.dependency_overrides[get_app_state] = lambda: state
        app.dependency_overrides[get_settings] = lambda: settings
        self.client = TestClient(app, raise_server_exceptions=False)
        yield
        app.dependency_overrides.clear()

    def test_runs_no_session_factory_returns_empty(self):
        resp = self.client.get("/api/v1/backtest/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["comparisons"] == []

    def test_runs_db_error_returns_empty(self):
        from apps.api.main import app
        from apps.api.state import get_app_state

        bad_session = MagicMock()
        bad_session.__enter__ = MagicMock(side_effect=Exception("DB down"))
        bad_session.__exit__ = MagicMock(return_value=False)

        @contextmanager
        def bad_factory():
            raise Exception("DB down")
            yield  # unreachable — required for @contextmanager

        state = _make_app_state()
        state._session_factory = bad_factory
        app.dependency_overrides[get_app_state] = lambda: state

        resp = self.client.get("/api/v1/backtest/runs")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_runs_with_session_factory_queries_db(self):
        from apps.api.main import app
        from apps.api.state import get_app_state

        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.scalars.return_value.all.return_value = []

        @contextmanager
        def sf():
            yield mock_session

        state = _make_app_state()
        state._session_factory = sf
        app.dependency_overrides[get_app_state] = lambda: state

        resp = self.client.get("/api/v1/backtest/runs")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# TestBacktestDetailEndpoint
# ---------------------------------------------------------------------------

class TestBacktestDetailEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self):
        from apps.api.main import app
        from apps.api.state import get_app_state
        from config.settings import get_settings

        state = _make_app_state()
        settings = _make_settings()
        app.dependency_overrides[get_app_state] = lambda: state
        app.dependency_overrides[get_settings] = lambda: settings
        self.client = TestClient(app, raise_server_exceptions=False)
        yield
        app.dependency_overrides.clear()

    def test_detail_no_session_factory_returns_503(self):
        resp = self.client.get("/api/v1/backtest/runs/nonexistent-id")
        assert resp.status_code == 503

    def test_detail_not_found_returns_404(self):
        from apps.api.main import app
        from apps.api.state import get_app_state

        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.scalars.return_value.all.return_value = []

        @contextmanager
        def sf():
            yield mock_session

        state = _make_app_state()
        state._session_factory = sf
        app.dependency_overrides[get_app_state] = lambda: state

        resp = self.client.get("/api/v1/backtest/runs/nonexistent-id")
        assert resp.status_code == 404

    def test_detail_returns_runs(self):
        from apps.api.main import app
        from apps.api.state import get_app_state
        from infra.db.models.backtest import BacktestRun

        cid = str(uuid.uuid4())
        row = BacktestRun(
            id=uuid.uuid4(),
            comparison_id=cid,
            strategy_name="momentum_v1",
            start_date=dt.date(2025, 1, 1),
            end_date=dt.date(2025, 3, 31),
            ticker_count=3,
            tickers_json=json.dumps(["AAPL", "MSFT", "NVDA"]),
            total_return_pct=5.0,
            status="completed",
        )

        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.scalars.return_value.all.return_value = [row]

        @contextmanager
        def sf():
            yield mock_session

        state = _make_app_state()
        state._session_factory = sf
        app.dependency_overrides[get_app_state] = lambda: state

        resp = self.client.get(f"/api/v1/backtest/runs/{cid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["comparison_id"] == cid
        assert data["run_count"] == 1
        assert data["runs"][0]["strategy_name"] == "momentum_v1"
        assert data["runs"][0]["tickers"] == ["AAPL", "MSFT", "NVDA"]


# ---------------------------------------------------------------------------
# TestBacktestDashboardPage
# ---------------------------------------------------------------------------

class TestBacktestDashboardPage:
    @pytest.fixture(autouse=True)
    def setup(self):
        from apps.api.main import app
        from apps.api.state import get_app_state
        from config.settings import get_settings

        state = _make_app_state()
        settings = _make_settings()
        app.dependency_overrides[get_app_state] = lambda: state
        app.dependency_overrides[get_settings] = lambda: settings
        self.client = TestClient(app, raise_server_exceptions=False)
        yield
        app.dependency_overrides.clear()

    def test_backtest_page_returns_200(self):
        resp = self.client.get("/dashboard/backtest")
        assert resp.status_code == 200

    def test_backtest_page_is_html(self):
        resp = self.client.get("/dashboard/backtest")
        assert "text/html" in resp.headers["content-type"]

    def test_backtest_page_contains_title(self):
        resp = self.client.get("/dashboard/backtest")
        assert "Backtest" in resp.text or "backtest" in resp.text.lower()

    def test_backtest_page_nav_has_all_links(self):
        resp = self.client.get("/dashboard/backtest")
        assert "/dashboard/" in resp.text
        assert "/dashboard/positions" in resp.text
        assert "/dashboard/backtest" in resp.text

    def test_backtest_page_no_db_shows_unavailable(self):
        resp = self.client.get("/dashboard/backtest")
        # No session_factory → shows DB unavailable message
        assert "DB unavailable" in resp.text or "no backtest" in resp.text.lower() or "unavailable" in resp.text.lower()

    def test_backtest_page_db_error_degrades_gracefully(self):
        from apps.api.main import app
        from apps.api.state import get_app_state

        @contextmanager
        def bad_factory():
            raise Exception("connection refused")
            yield  # unreachable — required for @contextmanager

        state = _make_app_state()
        state._session_factory = bad_factory
        app.dependency_overrides[get_app_state] = lambda: state

        resp = self.client.get("/dashboard/backtest")
        assert resp.status_code == 200

    def test_overview_page_nav_includes_backtest_link(self):
        resp = self.client.get("/dashboard/")
        assert "/dashboard/backtest" in resp.text

    def test_positions_page_nav_includes_backtest_link(self):
        resp = self.client.get("/dashboard/positions")
        assert "/dashboard/backtest" in resp.text

    def test_backtest_page_with_db_rows(self):
        from apps.api.main import app
        from apps.api.state import get_app_state
        from infra.db.models.backtest import BacktestRun

        cid = str(uuid.uuid4())
        row = BacktestRun(
            id=uuid.uuid4(),
            comparison_id=cid,
            strategy_name="momentum_v1",
            start_date=dt.date(2025, 1, 1),
            end_date=dt.date(2025, 3, 31),
            ticker_count=5,
            total_return_pct=6.3,
            sharpe_ratio=1.4,
            max_drawdown_pct=-2.5,
            win_rate=0.6,
            total_trades=20,
            status="completed",
            created_at=dt.datetime(2026, 3, 20, 10, 0, 0),
        )

        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.scalars.return_value.all.return_value = [row]

        @contextmanager
        def sf():
            yield mock_session

        state = _make_app_state()
        state._session_factory = sf
        app.dependency_overrides[get_app_state] = lambda: state

        resp = self.client.get("/dashboard/backtest")
        assert resp.status_code == 200
        assert "momentum_v1" in resp.text
