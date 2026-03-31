"""
Phase 46 — Signal Quality Tracking + Per-Strategy Attribution

Tests cover:
  1. StrategyQualityResult dataclass
  2. SignalQualityReport dataclass
  3. SignalQualityService.compute_strategy_quality()
  4. SignalQualityService.compute_quality_report()
  5. SignalQualityService.build_outcome_dict()
  6. run_signal_quality_update() — no-DB path
  7. run_signal_quality_update() — DB path (mocked session)
  8. GET /signals/quality API route
  9. GET /signals/quality/{strategy_name} API route
 10. SignalOutcome ORM model
 11. Dashboard signal quality section
 12. Scheduler job count (24 → 25)
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

# =============================================================================
# Helpers
# =============================================================================

def _make_outcome(
    strategy_name: str = "momentum",
    outcome_return_pct: float = 0.05,
    was_profitable: bool = True,
    hold_days: int = 5,
    ticker: str = "AAPL",
    signal_score: float | None = 0.8,
) -> dict:
    from services.signal_engine.signal_quality import SignalQualityService
    return SignalQualityService.build_outcome_dict(
        ticker=ticker,
        strategy_name=strategy_name,
        trade_opened_at=dt.datetime(2026, 3, 1, tzinfo=dt.UTC),
        trade_closed_at=dt.datetime(2026, 3, 6, tzinfo=dt.UTC),
        outcome_return_pct=outcome_return_pct,
        hold_days=hold_days,
        was_profitable=was_profitable,
        signal_score=signal_score,
    )


def _make_closed_trade(
    ticker: str = "AAPL",
    realized_pnl_pct: float = 0.05,
    hold_duration_days: int = 5,
    is_winner: bool = True,
) -> MagicMock:
    trade = MagicMock()
    trade.ticker = ticker
    trade.realized_pnl_pct = Decimal(str(realized_pnl_pct))
    trade.hold_duration_days = hold_duration_days
    trade.is_winner = is_winner
    trade.opened_at = dt.datetime(2026, 3, 1, tzinfo=dt.UTC)
    trade.closed_at = dt.datetime(2026, 3, 6, tzinfo=dt.UTC)
    return trade


# =============================================================================
# 1. StrategyQualityResult
# =============================================================================

class TestStrategyQualityResult:

    def test_defaults_to_zero(self):
        from services.signal_engine.signal_quality import StrategyQualityResult
        r = StrategyQualityResult(strategy_name="momentum")
        assert r.prediction_count == 0
        assert r.win_rate == 0.0
        assert r.avg_return_pct == 0.0
        assert r.sharpe_estimate == 0.0

    def test_fields_populated(self):
        from services.signal_engine.signal_quality import StrategyQualityResult
        r = StrategyQualityResult(
            strategy_name="sentiment",
            prediction_count=10,
            win_count=7,
            win_rate=0.7,
            avg_return_pct=0.03,
            best_return_pct=0.12,
            worst_return_pct=-0.04,
            avg_hold_days=6.0,
            sharpe_estimate=1.5,
        )
        assert r.strategy_name == "sentiment"
        assert r.win_count == 7
        assert r.best_return_pct == 0.12

    def test_strategy_name_preserved(self):
        from services.signal_engine.signal_quality import StrategyQualityResult
        r = StrategyQualityResult(strategy_name="theme_alignment")
        assert r.strategy_name == "theme_alignment"

    def test_sharpe_estimate_float(self):
        from services.signal_engine.signal_quality import StrategyQualityResult
        r = StrategyQualityResult(strategy_name="x", sharpe_estimate=2.34)
        assert isinstance(r.sharpe_estimate, float)

    def test_win_rate_float(self):
        from services.signal_engine.signal_quality import StrategyQualityResult
        r = StrategyQualityResult(strategy_name="x", win_rate=0.55)
        assert isinstance(r.win_rate, float)


# =============================================================================
# 2. SignalQualityReport
# =============================================================================

class TestSignalQualityReport:

    def test_defaults(self):
        from services.signal_engine.signal_quality import SignalQualityReport
        ts = dt.datetime.now(dt.UTC)
        r = SignalQualityReport(computed_at=ts)
        assert r.total_outcomes_recorded == 0
        assert r.strategies_with_data == []
        assert r.strategy_results == []

    def test_populated_report(self):
        from services.signal_engine.signal_quality import SignalQualityReport, StrategyQualityResult
        ts = dt.datetime.now(dt.UTC)
        result = StrategyQualityResult(strategy_name="momentum", prediction_count=5)
        r = SignalQualityReport(
            computed_at=ts,
            total_outcomes_recorded=5,
            strategies_with_data=["momentum"],
            strategy_results=[result],
        )
        assert r.total_outcomes_recorded == 5
        assert len(r.strategy_results) == 1

    def test_computed_at_stored(self):
        from services.signal_engine.signal_quality import SignalQualityReport
        ts = dt.datetime(2026, 3, 20, 17, 20, tzinfo=dt.UTC)
        r = SignalQualityReport(computed_at=ts)
        assert r.computed_at == ts

    def test_strategies_with_data_list(self):
        from services.signal_engine.signal_quality import SignalQualityReport
        ts = dt.datetime.now(dt.UTC)
        r = SignalQualityReport(computed_at=ts, strategies_with_data=["a", "b"])
        assert "a" in r.strategies_with_data
        assert "b" in r.strategies_with_data


# =============================================================================
# 3. SignalQualityService.compute_strategy_quality()
# =============================================================================

class TestComputeStrategyQuality:

    def test_empty_outcomes_returns_zeroed_result(self):
        from services.signal_engine.signal_quality import SignalQualityService
        r = SignalQualityService.compute_strategy_quality("momentum", [])
        assert r.prediction_count == 0
        assert r.win_rate == 0.0
        assert r.sharpe_estimate == 0.0

    def test_single_winning_trade(self):
        from services.signal_engine.signal_quality import SignalQualityService
        outcomes = [_make_outcome(outcome_return_pct=0.10, was_profitable=True)]
        r = SignalQualityService.compute_strategy_quality("momentum", outcomes)
        assert r.prediction_count == 1
        assert r.win_count == 1
        assert r.win_rate == 1.0
        assert r.avg_return_pct == pytest.approx(0.10)

    def test_single_losing_trade(self):
        from services.signal_engine.signal_quality import SignalQualityService
        outcomes = [_make_outcome(outcome_return_pct=-0.05, was_profitable=False)]
        r = SignalQualityService.compute_strategy_quality("momentum", outcomes)
        assert r.win_count == 0
        assert r.win_rate == 0.0
        assert r.avg_return_pct == pytest.approx(-0.05)

    def test_mixed_trades(self):
        from services.signal_engine.signal_quality import SignalQualityService
        outcomes = [
            _make_outcome(outcome_return_pct=0.10, was_profitable=True),
            _make_outcome(outcome_return_pct=-0.05, was_profitable=False),
            _make_outcome(outcome_return_pct=0.08, was_profitable=True),
            _make_outcome(outcome_return_pct=0.03, was_profitable=True),
        ]
        r = SignalQualityService.compute_strategy_quality("momentum", outcomes)
        assert r.prediction_count == 4
        assert r.win_count == 3
        assert r.win_rate == pytest.approx(0.75)
        assert r.avg_return_pct == pytest.approx(0.04)

    def test_best_and_worst_return(self):
        from services.signal_engine.signal_quality import SignalQualityService
        outcomes = [
            _make_outcome(outcome_return_pct=0.20, was_profitable=True),
            _make_outcome(outcome_return_pct=-0.10, was_profitable=False),
            _make_outcome(outcome_return_pct=0.05, was_profitable=True),
        ]
        r = SignalQualityService.compute_strategy_quality("momentum", outcomes)
        assert r.best_return_pct == pytest.approx(0.20)
        assert r.worst_return_pct == pytest.approx(-0.10)

    def test_sharpe_zero_for_single_observation(self):
        from services.signal_engine.signal_quality import SignalQualityService
        outcomes = [_make_outcome(outcome_return_pct=0.05, was_profitable=True)]
        r = SignalQualityService.compute_strategy_quality("momentum", outcomes)
        assert r.sharpe_estimate == 0.0

    def test_sharpe_nonzero_for_two_different_returns(self):
        from services.signal_engine.signal_quality import SignalQualityService
        outcomes = [
            _make_outcome(outcome_return_pct=0.10, was_profitable=True),
            _make_outcome(outcome_return_pct=0.02, was_profitable=True),
        ]
        r = SignalQualityService.compute_strategy_quality("momentum", outcomes)
        assert r.sharpe_estimate != 0.0

    def test_avg_hold_days(self):
        from services.signal_engine.signal_quality import SignalQualityService
        outcomes = [
            _make_outcome(hold_days=4),
            _make_outcome(hold_days=6),
            _make_outcome(hold_days=8),
        ]
        r = SignalQualityService.compute_strategy_quality("momentum", outcomes)
        assert r.avg_hold_days == pytest.approx(6.0)

    def test_strategy_name_preserved(self):
        from services.signal_engine.signal_quality import SignalQualityService
        outcomes = [_make_outcome()]
        r = SignalQualityService.compute_strategy_quality("theme_alignment", outcomes)
        assert r.strategy_name == "theme_alignment"


# =============================================================================
# 4. SignalQualityService.compute_quality_report()
# =============================================================================

class TestComputeQualityReport:

    def test_empty_outcomes(self):
        from services.signal_engine.signal_quality import SignalQualityService
        report = SignalQualityService.compute_quality_report([])
        assert report.total_outcomes_recorded == 0
        assert report.strategies_with_data == []
        assert report.strategy_results == []

    def test_single_strategy(self):
        from services.signal_engine.signal_quality import SignalQualityService
        outcomes = [
            _make_outcome(strategy_name="momentum", outcome_return_pct=0.05),
            _make_outcome(strategy_name="momentum", outcome_return_pct=-0.02, was_profitable=False),
        ]
        report = SignalQualityService.compute_quality_report(outcomes)
        assert report.total_outcomes_recorded == 2
        assert "momentum" in report.strategies_with_data
        assert len(report.strategy_results) == 1
        assert report.strategy_results[0].prediction_count == 2

    def test_multiple_strategies(self):
        from services.signal_engine.signal_quality import SignalQualityService
        outcomes = [
            _make_outcome(strategy_name="momentum"),
            _make_outcome(strategy_name="sentiment"),
            _make_outcome(strategy_name="valuation"),
        ]
        report = SignalQualityService.compute_quality_report(outcomes)
        assert report.total_outcomes_recorded == 3
        assert len(report.strategy_results) == 3
        names = {r.strategy_name for r in report.strategy_results}
        assert names == {"momentum", "sentiment", "valuation"}

    def test_sorted_by_win_rate_descending(self):
        from services.signal_engine.signal_quality import SignalQualityService
        outcomes = [
            # momentum: 1/2 wins = 0.5
            _make_outcome(strategy_name="momentum", was_profitable=True),
            _make_outcome(strategy_name="momentum", was_profitable=False),
            # sentiment: 2/2 wins = 1.0
            _make_outcome(strategy_name="sentiment", was_profitable=True),
            _make_outcome(strategy_name="sentiment", was_profitable=True),
            # valuation: 0/2 wins = 0.0
            _make_outcome(strategy_name="valuation", was_profitable=False),
            _make_outcome(strategy_name="valuation", was_profitable=False),
        ]
        report = SignalQualityService.compute_quality_report(outcomes)
        names = [r.strategy_name for r in report.strategy_results]
        assert names[0] == "sentiment"   # highest win rate
        assert names[-1] == "valuation"  # lowest win rate

    def test_computed_at_defaults_to_now(self):
        from services.signal_engine.signal_quality import SignalQualityService
        before = dt.datetime.now(dt.UTC)
        report = SignalQualityService.compute_quality_report([])
        after = dt.datetime.now(dt.UTC)
        assert before <= report.computed_at <= after

    def test_computed_at_can_be_set(self):
        from services.signal_engine.signal_quality import SignalQualityService
        ts = dt.datetime(2026, 3, 20, 17, 20, tzinfo=dt.UTC)
        report = SignalQualityService.compute_quality_report([], computed_at=ts)
        assert report.computed_at == ts

    def test_strategies_with_data_sorted(self):
        from services.signal_engine.signal_quality import SignalQualityService
        outcomes = [
            _make_outcome(strategy_name="valuation"),
            _make_outcome(strategy_name="momentum"),
        ]
        report = SignalQualityService.compute_quality_report(outcomes)
        assert report.strategies_with_data == sorted(report.strategies_with_data)


# =============================================================================
# 5. SignalQualityService.build_outcome_dict()
# =============================================================================

class TestBuildOutcomeDict:

    def test_basic_fields(self):
        from services.signal_engine.signal_quality import SignalQualityService
        d = SignalQualityService.build_outcome_dict(
            ticker="AAPL",
            strategy_name="momentum",
            trade_opened_at=dt.datetime(2026, 3, 1, tzinfo=dt.UTC),
            trade_closed_at=dt.datetime(2026, 3, 6, tzinfo=dt.UTC),
            outcome_return_pct=0.05,
            hold_days=5,
            was_profitable=True,
            signal_score=0.8,
        )
        assert d["ticker"] == "AAPL"
        assert d["strategy_name"] == "momentum"
        assert d["outcome_return_pct"] == pytest.approx(0.05)
        assert d["hold_days"] == 5
        assert d["was_profitable"] is True
        assert d["signal_score"] == pytest.approx(0.8)

    def test_decimal_return_converted_to_float(self):
        from services.signal_engine.signal_quality import SignalQualityService
        d = SignalQualityService.build_outcome_dict(
            ticker="MSFT",
            strategy_name="valuation",
            trade_opened_at=dt.datetime(2026, 3, 1, tzinfo=dt.UTC),
            trade_closed_at=dt.datetime(2026, 3, 6, tzinfo=dt.UTC),
            outcome_return_pct=Decimal("0.1234"),
            hold_days=10,
            was_profitable=True,
        )
        assert isinstance(d["outcome_return_pct"], float)
        assert d["outcome_return_pct"] == pytest.approx(0.1234)

    def test_null_signal_score(self):
        from services.signal_engine.signal_quality import SignalQualityService
        d = SignalQualityService.build_outcome_dict(
            ticker="NVDA",
            strategy_name="sentiment",
            trade_opened_at=dt.datetime(2026, 3, 1, tzinfo=dt.UTC),
            trade_closed_at=dt.datetime(2026, 3, 6, tzinfo=dt.UTC),
            outcome_return_pct=-0.03,
            hold_days=3,
            was_profitable=False,
            signal_score=None,
        )
        assert d["signal_score"] is None

    def test_was_profitable_bool(self):
        from services.signal_engine.signal_quality import SignalQualityService
        d = SignalQualityService.build_outcome_dict(
            ticker="X",
            strategy_name="momentum",
            trade_opened_at=dt.datetime(2026, 3, 1, tzinfo=dt.UTC),
            trade_closed_at=dt.datetime(2026, 3, 6, tzinfo=dt.UTC),
            outcome_return_pct=0.01,
            hold_days=1,
            was_profitable=1,  # truthy int
        )
        assert d["was_profitable"] is True


# =============================================================================
# 6. run_signal_quality_update() — no-DB path
# =============================================================================

class TestRunSignalQualityUpdateNoDB:

    def test_skips_when_no_closed_trades(self):
        from apps.api.state import ApiAppState
        from apps.worker.jobs.signal_quality import run_signal_quality_update

        state = ApiAppState()
        state.closed_trades = []
        result = run_signal_quality_update(app_state=state)
        assert result["status"] == "skipped_no_trades"
        assert result["trades_processed"] == 0

    def test_no_db_path_returns_ok_no_db(self):
        from apps.api.state import ApiAppState
        from apps.worker.jobs.signal_quality import run_signal_quality_update

        state = ApiAppState()
        state.closed_trades = [_make_closed_trade()]
        result = run_signal_quality_update(app_state=state, session_factory=None)
        assert result["status"] == "ok_no_db"
        assert result["trades_processed"] == 1

    def test_no_db_path_populates_app_state(self):
        from apps.api.state import ApiAppState
        from apps.worker.jobs.signal_quality import run_signal_quality_update

        state = ApiAppState()
        state.closed_trades = [_make_closed_trade("AAPL", 0.05), _make_closed_trade("MSFT", -0.02)]
        run_signal_quality_update(app_state=state, session_factory=None)
        assert state.latest_signal_quality is not None
        assert state.signal_quality_computed_at is not None

    def test_no_db_path_creates_report_with_default_strategies(self):
        from apps.api.state import ApiAppState
        from apps.worker.jobs.signal_quality import DEFAULT_STRATEGIES, run_signal_quality_update

        state = ApiAppState()
        state.closed_trades = [_make_closed_trade()]
        run_signal_quality_update(app_state=state)
        report = state.latest_signal_quality
        strategy_names = {r.strategy_name for r in report.strategy_results}
        assert strategy_names == set(DEFAULT_STRATEGIES)

    def test_no_db_path_outcomes_total_is_trades_times_strategies(self):
        from apps.api.state import ApiAppState
        from apps.worker.jobs.signal_quality import DEFAULT_STRATEGIES, run_signal_quality_update

        state = ApiAppState()
        state.closed_trades = [_make_closed_trade(), _make_closed_trade("MSFT")]
        result = run_signal_quality_update(app_state=state)
        assert result["outcomes_total"] == 2 * len(DEFAULT_STRATEGIES)

    def test_returns_error_on_exception(self):
        from apps.api.state import ApiAppState
        from apps.worker.jobs.signal_quality import run_signal_quality_update

        state = ApiAppState()
        state.closed_trades = [_make_closed_trade()]

        with patch(
            "apps.worker.jobs.signal_quality._run_no_db",
            side_effect=RuntimeError("boom"),
        ):
            with patch(
                "apps.worker.jobs.signal_quality._run_with_db",
                side_effect=RuntimeError("boom"),
            ):
                # Provide a mock session_factory so the DB path is taken
                mock_sf = MagicMock(side_effect=RuntimeError("boom"))
                result = run_signal_quality_update(app_state=state, session_factory=mock_sf)
        assert result["status"] == "error"
        assert "boom" in result["error"]


# =============================================================================
# 7. run_signal_quality_update() — settings acceptance
# =============================================================================

class TestRunSignalQualityUpdateSettings:

    def test_accepts_explicit_settings(self):
        from apps.api.state import ApiAppState
        from apps.worker.jobs.signal_quality import run_signal_quality_update
        from config.settings import Settings

        state = ApiAppState()
        state.closed_trades = []
        cfg = Settings()
        result = run_signal_quality_update(app_state=state, settings=cfg)
        assert result["status"] == "skipped_no_trades"

    def test_falls_back_to_get_settings_when_none(self):
        from apps.api.state import ApiAppState
        from apps.worker.jobs.signal_quality import run_signal_quality_update

        state = ApiAppState()
        state.closed_trades = []
        result = run_signal_quality_update(app_state=state, settings=None)
        assert "status" in result


# =============================================================================
# 8. GET /signals/quality API route
# =============================================================================

class TestSignalQualityAPINoData:

    def _client(self):
        from fastapi.testclient import TestClient

        from apps.api.main import app
        return TestClient(app)

    def test_returns_200_when_no_data(self):
        from apps.api.state import reset_app_state
        reset_app_state()
        resp = self._client().get("/api/v1/signals/quality")
        assert resp.status_code == 200

    def test_data_available_false_when_no_data(self):
        from apps.api.state import reset_app_state
        reset_app_state()
        resp = self._client().get("/api/v1/signals/quality")
        data = resp.json()
        assert data["data_available"] is False
        assert data["total_outcomes_recorded"] == 0
        assert data["strategy_results"] == []

    def test_returns_report_when_data_present(self):
        from apps.api.state import get_app_state, reset_app_state
        from services.signal_engine.signal_quality import SignalQualityReport, StrategyQualityResult

        reset_app_state()
        state = get_app_state()
        ts = dt.datetime(2026, 3, 20, 17, 20, tzinfo=dt.UTC)
        state.latest_signal_quality = SignalQualityReport(
            computed_at=ts,
            total_outcomes_recorded=10,
            strategies_with_data=["momentum"],
            strategy_results=[
                StrategyQualityResult(
                    strategy_name="momentum",
                    prediction_count=10,
                    win_count=7,
                    win_rate=0.7,
                    avg_return_pct=0.04,
                    best_return_pct=0.12,
                    worst_return_pct=-0.05,
                    avg_hold_days=5.5,
                    sharpe_estimate=1.2,
                )
            ],
        )

        resp = self._client().get("/api/v1/signals/quality")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data_available"] is True
        assert data["total_outcomes_recorded"] == 10
        assert len(data["strategy_results"]) == 1
        assert data["strategy_results"][0]["strategy_name"] == "momentum"
        assert data["strategy_results"][0]["win_rate"] == pytest.approx(0.7)

    def test_strategy_count_matches_results_length(self):
        from apps.api.state import get_app_state, reset_app_state
        from services.signal_engine.signal_quality import SignalQualityReport, StrategyQualityResult

        reset_app_state()
        state = get_app_state()
        state.latest_signal_quality = SignalQualityReport(
            computed_at=dt.datetime.now(dt.UTC),
            total_outcomes_recorded=4,
            strategies_with_data=["momentum", "sentiment"],
            strategy_results=[
                StrategyQualityResult(strategy_name="momentum", prediction_count=2),
                StrategyQualityResult(strategy_name="sentiment", prediction_count=2),
            ],
        )
        resp = self._client().get("/api/v1/signals/quality")
        data = resp.json()
        assert data["strategy_count"] == 2


# =============================================================================
# 9. GET /signals/quality/{strategy_name} API route
# =============================================================================

class TestStrategyQualityDetailAPI:

    def _client(self):
        from fastapi.testclient import TestClient

        from apps.api.main import app
        return TestClient(app)

    def test_returns_200_no_data(self):
        from apps.api.state import reset_app_state
        reset_app_state()
        resp = self._client().get("/api/v1/signals/quality/momentum")
        assert resp.status_code == 200
        assert resp.json()["data_available"] is False

    def test_data_available_false_strategy_not_found(self):
        from apps.api.state import get_app_state, reset_app_state
        from services.signal_engine.signal_quality import SignalQualityReport, StrategyQualityResult

        reset_app_state()
        state = get_app_state()
        state.latest_signal_quality = SignalQualityReport(
            computed_at=dt.datetime.now(dt.UTC),
            total_outcomes_recorded=5,
            strategies_with_data=["momentum"],
            strategy_results=[StrategyQualityResult(strategy_name="momentum", prediction_count=5)],
        )
        resp = self._client().get("/api/v1/signals/quality/valuation")
        data = resp.json()
        assert data["data_available"] is False
        assert data["strategy_name"] == "valuation"

    def test_returns_detail_for_known_strategy(self):
        from apps.api.state import get_app_state, reset_app_state
        from services.signal_engine.signal_quality import SignalQualityReport, StrategyQualityResult

        reset_app_state()
        state = get_app_state()
        state.latest_signal_quality = SignalQualityReport(
            computed_at=dt.datetime.now(dt.UTC),
            total_outcomes_recorded=8,
            strategies_with_data=["sentiment"],
            strategy_results=[
                StrategyQualityResult(
                    strategy_name="sentiment",
                    prediction_count=8,
                    win_count=5,
                    win_rate=0.625,
                    avg_return_pct=0.035,
                    best_return_pct=0.10,
                    worst_return_pct=-0.04,
                    avg_hold_days=4.5,
                    sharpe_estimate=0.9,
                )
            ],
        )
        resp = self._client().get("/api/v1/signals/quality/sentiment")
        data = resp.json()
        assert data["data_available"] is True
        assert data["strategy_name"] == "sentiment"
        assert data["prediction_count"] == 8
        assert data["win_rate"] == pytest.approx(0.625)

    def test_case_insensitive_lookup(self):
        from apps.api.state import get_app_state, reset_app_state
        from services.signal_engine.signal_quality import SignalQualityReport, StrategyQualityResult

        reset_app_state()
        state = get_app_state()
        state.latest_signal_quality = SignalQualityReport(
            computed_at=dt.datetime.now(dt.UTC),
            total_outcomes_recorded=3,
            strategies_with_data=["momentum"],
            strategy_results=[StrategyQualityResult(strategy_name="momentum", prediction_count=3)],
        )
        resp = self._client().get("/api/v1/signals/quality/MOMENTUM")
        data = resp.json()
        assert data["data_available"] is True

    def test_strategy_name_in_response(self):
        from apps.api.state import reset_app_state
        reset_app_state()
        resp = self._client().get("/api/v1/signals/quality/macro_tailwind")
        data = resp.json()
        assert data["strategy_name"] == "macro_tailwind"


# =============================================================================
# 10. SignalOutcome ORM model
# =============================================================================

class TestSignalOutcomeORM:

    def test_model_importable(self):
        from infra.db.models.signal_quality import SignalOutcome
        assert SignalOutcome is not None

    def test_tablename(self):
        from infra.db.models.signal_quality import SignalOutcome
        assert SignalOutcome.__tablename__ == "signal_outcomes"

    def test_has_required_columns(self):
        from infra.db.models.signal_quality import SignalOutcome
        cols = {c.name for c in SignalOutcome.__table__.columns}
        assert "id" in cols
        assert "ticker" in cols
        assert "strategy_name" in cols
        assert "signal_score" in cols
        assert "trade_opened_at" in cols
        assert "trade_closed_at" in cols
        assert "outcome_return_pct" in cols
        assert "hold_days" in cols
        assert "was_profitable" in cols

    def test_has_unique_constraint(self):
        from infra.db.models.signal_quality import SignalOutcome
        constraint_names = {
            c.name
            for c in SignalOutcome.__table__.constraints
            if hasattr(c, "name") and c.name
        }
        assert "uq_signal_outcome_trade" in constraint_names

    def test_registered_in_models_init(self):
        from infra.db.models import SignalOutcome
        assert SignalOutcome is not None


# =============================================================================
# 11. Dashboard signal quality section
# =============================================================================

class TestDashboardSignalQualitySection:

    def _state_with_report(self):
        from apps.api.state import ApiAppState
        from services.signal_engine.signal_quality import SignalQualityReport, StrategyQualityResult

        state = ApiAppState()
        state.latest_signal_quality = SignalQualityReport(
            computed_at=dt.datetime(2026, 3, 20, 17, 20, tzinfo=dt.UTC),
            total_outcomes_recorded=12,
            strategies_with_data=["momentum", "sentiment"],
            strategy_results=[
                StrategyQualityResult(
                    strategy_name="momentum",
                    prediction_count=7,
                    win_count=5,
                    win_rate=0.714,
                    avg_return_pct=0.04,
                    sharpe_estimate=1.1,
                    avg_hold_days=5.0,
                ),
                StrategyQualityResult(
                    strategy_name="sentiment",
                    prediction_count=5,
                    win_count=2,
                    win_rate=0.40,
                    avg_return_pct=0.01,
                    sharpe_estimate=0.3,
                    avg_hold_days=4.0,
                ),
            ],
        )
        state.signal_quality_computed_at = dt.datetime(2026, 3, 20, 17, 20, tzinfo=dt.UTC)
        return state

    def test_renders_without_data(self):
        from apps.api.state import ApiAppState
        from apps.dashboard.router import _render_signal_quality_section

        state = ApiAppState()
        html = _render_signal_quality_section(state)
        assert "Signal Quality" in html
        assert "No signal quality data yet" in html

    def test_renders_with_data(self):
        from apps.dashboard.router import _render_signal_quality_section

        html = _render_signal_quality_section(self._state_with_report())
        assert "Signal Quality" in html
        assert "momentum" in html
        assert "sentiment" in html
        assert "12" in html  # total outcomes

    def test_renders_strategy_table(self):
        from apps.dashboard.router import _render_signal_quality_section

        html = _render_signal_quality_section(self._state_with_report())
        assert "<table>" in html
        assert "Win Rate" in html
        assert "Avg Return" in html

    def test_wired_into_main_dashboard(self):
        from fastapi.testclient import TestClient

        from apps.api.main import app
        from apps.api.state import reset_app_state

        reset_app_state()
        resp = TestClient(app).get("/dashboard/")
        assert resp.status_code == 200
        assert "Signal Quality" in resp.text

    def test_warn_class_for_low_win_rate(self):
        from apps.api.state import ApiAppState
        from apps.dashboard.router import _render_signal_quality_section
        from services.signal_engine.signal_quality import SignalQualityReport, StrategyQualityResult

        state = ApiAppState()
        state.latest_signal_quality = SignalQualityReport(
            computed_at=dt.datetime.now(dt.UTC),
            total_outcomes_recorded=5,
            strategies_with_data=["valuation"],
            strategy_results=[
                StrategyQualityResult(
                    strategy_name="valuation",
                    prediction_count=5,
                    win_count=1,
                    win_rate=0.2,  # below 0.40 threshold → warn class
                    avg_return_pct=-0.01,
                    sharpe_estimate=-0.5,
                    avg_hold_days=3.0,
                )
            ],
        )
        state.signal_quality_computed_at = dt.datetime.now(dt.UTC)
        html = _render_signal_quality_section(state)
        assert 'class="warn"' in html


# =============================================================================
# 12. Scheduler job count (24 → 25) + export
# =============================================================================

class TestWorkerJobCountPhase46:
    """Verify scheduler registers 25 jobs after Phase 46 (+signal_quality_update)."""

    def _build(self):
        from apps.worker.main import build_scheduler
        return build_scheduler()

    def test_scheduler_has_25_jobs(self):
        scheduler = self._build()
        assert len(scheduler.get_jobs()) == 30

    def test_signal_quality_update_job_registered(self):
        scheduler = self._build()
        job_ids = {job.id for job in scheduler.get_jobs()}
        assert "signal_quality_update" in job_ids

    def test_signal_quality_update_scheduled_at_17_20(self):
        scheduler = self._build()
        job = next(j for j in scheduler.get_jobs() if j.id == "signal_quality_update")
        trigger = job.trigger
        fields = {f.name: str(f) for f in trigger.fields}
        assert fields.get("hour") == "17"
        assert fields.get("minute") == "20"
        assert fields.get("day_of_week") == "mon-fri"

    def test_run_signal_quality_update_exported(self):
        from apps.worker.jobs import run_signal_quality_update
        assert callable(run_signal_quality_update)

    def test_signal_quality_update_after_attribution(self):
        """signal_quality_update (17:20) fires after attribution_analysis (17:15)."""
        scheduler = self._build()
        jobs_by_id = {j.id: j for j in scheduler.get_jobs()}
        sq_job = jobs_by_id["signal_quality_update"]
        attr_job = jobs_by_id["attribution_analysis"]
        sq_fields = {f.name: str(f) for f in sq_job.trigger.fields}
        attr_fields = {f.name: str(f) for f in attr_job.trigger.fields}
        sq_minute = int(sq_fields.get("minute", "0"))
        attr_minute = int(attr_fields.get("minute", "0"))
        assert sq_minute > attr_minute  # 20 > 15
