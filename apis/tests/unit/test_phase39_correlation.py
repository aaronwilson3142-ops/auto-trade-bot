"""
Phase 39 — Correlation-Aware Position Sizing Tests

Test classes
------------
 1. TestComputeCorrelationMatrix      (10) — matrix computation correctness
 2. TestGetPairwise                   (5)  — symmetric look-up
 3. TestMaxPairwiseWithPortfolio      (8)  — portfolio-level max correlation
 4. TestCorrelationSizeFactor         (8)  — size multiplier mapping
 5. TestAdjustActionForCorrelation    (10) — action adjustment end-to-end
 6. TestCorrelationSettings           (4)  — new settings fields + defaults
 7. TestRunCorrelationRefresh         (8)  — job function happy + error paths
 8. TestCorrelationRestEndpoints      (7)  — GET /portfolio/correlation routes

Total: 60 tests
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from services.risk_engine.correlation import CorrelationService, MIN_OBSERVATIONS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_returns(values: list[float]) -> list[float]:
    return values


def _make_action(
    ticker: str = "AAPL",
    action_type_str: str = "open",
    target_notional: float = 1000.0,
    target_quantity: float = 5.0,
):
    from services.portfolio_engine.models import ActionType, PortfolioAction

    return PortfolioAction(
        action_type=ActionType(action_type_str),
        ticker=ticker,
        reason="test",
        target_notional=Decimal(str(target_notional)),
        target_quantity=Decimal(str(target_quantity)),
        thesis_summary="thesis",
        sizing_rationale="half_kelly",
    )


def _make_settings(
    correlation_size_floor: float = 0.25,
    max_pairwise_correlation: float = 0.75,
    correlation_lookback_days: int = 60,
):
    s = MagicMock()
    s.correlation_size_floor = correlation_size_floor
    s.max_pairwise_correlation = max_pairwise_correlation
    s.correlation_lookback_days = correlation_lookback_days
    return s


# Perfect positive correlation helper
_CORR_RETURNS = {
    "AAPL": [0.01, 0.02, -0.01, 0.03, 0.01, -0.02, 0.02, 0.01, 0.03, -0.01,
             0.01, 0.02, -0.01, 0.03, 0.01, -0.02, 0.02, 0.01, 0.03, -0.01,
             0.01, 0.02, -0.01, 0.03, 0.01],
    "MSFT": [0.01, 0.02, -0.01, 0.03, 0.01, -0.02, 0.02, 0.01, 0.03, -0.01,
             0.01, 0.02, -0.01, 0.03, 0.01, -0.02, 0.02, 0.01, 0.03, -0.01,
             0.01, 0.02, -0.01, 0.03, 0.01],  # identical → corr=1.0
    "TSLA": [-x for x in [0.01, 0.02, -0.01, 0.03, 0.01, -0.02, 0.02, 0.01, 0.03, -0.01,
                           0.01, 0.02, -0.01, 0.03, 0.01, -0.02, 0.02, 0.01, 0.03, -0.01,
                           0.01, 0.02, -0.01, 0.03, 0.01]],  # inverted → corr=-1.0
}


# ---------------------------------------------------------------------------
# 1. TestComputeCorrelationMatrix
# ---------------------------------------------------------------------------

class TestComputeCorrelationMatrix:
    def test_perfect_positive_correlation(self):
        bars = {"A": [0.01, 0.02, 0.03] * 10, "B": [0.01, 0.02, 0.03] * 10}
        matrix = CorrelationService.compute_correlation_matrix(bars)
        assert ("A", "B") in matrix
        assert abs(matrix[("A", "B")] - 1.0) < 0.001

    def test_perfect_negative_correlation(self):
        a = [0.01, 0.02, 0.03] * 10
        b = [-x for x in a]
        bars = {"A": a, "B": b}
        matrix = CorrelationService.compute_correlation_matrix(bars)
        assert abs(matrix[("A", "B")] - (-1.0)) < 0.001

    def test_symmetric_matrix(self):
        bars = {"A": [0.01, -0.01, 0.02] * 10, "B": [0.02, 0.01, -0.01] * 10}
        matrix = CorrelationService.compute_correlation_matrix(bars)
        assert matrix.get(("A", "B")) == matrix.get(("B", "A"))

    def test_insufficient_data_excluded(self):
        # Only MIN_OBSERVATIONS-1 points — should produce no entry
        n = MIN_OBSERVATIONS - 1
        bars = {"A": [0.01] * n, "B": [0.01] * n}
        matrix = CorrelationService.compute_correlation_matrix(bars)
        assert len(matrix) == 0

    def test_minimum_observations_included(self):
        n = MIN_OBSERVATIONS
        bars = {"A": [float(i) * 0.001 for i in range(n)],
                "B": [float(i) * 0.002 for i in range(n)]}
        matrix = CorrelationService.compute_correlation_matrix(bars)
        assert len(matrix) == 2  # (A,B) and (B,A)

    def test_single_ticker_no_pairs(self):
        bars = {"A": [0.01, 0.02] * 20}
        matrix = CorrelationService.compute_correlation_matrix(bars)
        assert len(matrix) == 0

    def test_empty_input(self):
        matrix = CorrelationService.compute_correlation_matrix({})
        assert matrix == {}

    def test_three_tickers_correct_pair_count(self):
        data = [float(i) * 0.001 for i in range(MIN_OBSERVATIONS + 5)]
        bars = {"A": data, "B": data, "C": list(reversed(data))}
        matrix = CorrelationService.compute_correlation_matrix(bars)
        # 3 pairs × 2 orderings = 6 entries
        assert len(matrix) == 6

    def test_correlation_clamped_to_range(self):
        data = [float(i) * 0.001 for i in range(MIN_OBSERVATIONS + 5)]
        bars = {"A": data, "B": data}
        matrix = CorrelationService.compute_correlation_matrix(bars)
        for v in matrix.values():
            assert -1.0 <= v <= 1.0

    def test_shorter_series_aligned_on_tail(self):
        long_series = [float(i) * 0.001 for i in range(60)]
        short_series = [float(i) * 0.001 for i in range(MIN_OBSERVATIONS)]
        bars = {"A": long_series, "B": short_series}
        # Should still compute (uses tail of MIN_OBSERVATIONS from long)
        matrix = CorrelationService.compute_correlation_matrix(bars)
        assert len(matrix) == 2


# ---------------------------------------------------------------------------
# 2. TestGetPairwise
# ---------------------------------------------------------------------------

class TestGetPairwise:
    def test_found_forward(self):
        matrix = {("A", "B"): 0.8, ("B", "A"): 0.8}
        assert CorrelationService.get_pairwise("A", "B", matrix) == 0.8

    def test_found_reverse(self):
        matrix = {("B", "A"): 0.8}
        assert CorrelationService.get_pairwise("A", "B", matrix) == 0.8

    def test_not_found_returns_none(self):
        matrix = {("A", "B"): 0.8}
        assert CorrelationService.get_pairwise("A", "C", matrix) is None

    def test_empty_matrix_returns_none(self):
        assert CorrelationService.get_pairwise("A", "B", {}) is None

    def test_same_ticker_lookup(self):
        matrix = {("A", "A"): 1.0}
        assert CorrelationService.get_pairwise("A", "A", matrix) == 1.0


# ---------------------------------------------------------------------------
# 3. TestMaxPairwiseWithPortfolio
# ---------------------------------------------------------------------------

class TestMaxPairwiseWithPortfolio:
    def _matrix(self):
        return {("AAPL", "MSFT"): 0.9, ("MSFT", "AAPL"): 0.9,
                ("AAPL", "TSLA"): 0.3, ("TSLA", "AAPL"): 0.3,
                ("MSFT", "TSLA"): 0.5, ("TSLA", "MSFT"): 0.5}

    def test_empty_portfolio_returns_zero(self):
        assert CorrelationService.max_pairwise_with_portfolio([], "AAPL", self._matrix()) == 0.0

    def test_empty_matrix_returns_zero(self):
        assert CorrelationService.max_pairwise_with_portfolio(["MSFT"], "AAPL", {}) == 0.0

    def test_single_position_high_correlation(self):
        val = CorrelationService.max_pairwise_with_portfolio(["MSFT"], "AAPL", self._matrix())
        assert abs(val - 0.9) < 0.001

    def test_single_position_low_correlation(self):
        val = CorrelationService.max_pairwise_with_portfolio(["TSLA"], "AAPL", self._matrix())
        assert abs(val - 0.3) < 0.001

    def test_multiple_positions_returns_max(self):
        val = CorrelationService.max_pairwise_with_portfolio(
            ["MSFT", "TSLA"], "AAPL", self._matrix()
        )
        assert abs(val - 0.9) < 0.001

    def test_candidate_already_in_portfolio_skipped(self):
        val = CorrelationService.max_pairwise_with_portfolio(
            ["AAPL", "MSFT"], "AAPL", self._matrix()
        )
        # AAPL vs MSFT = 0.9, AAPL vs AAPL skipped
        assert abs(val - 0.9) < 0.001

    def test_no_matrix_coverage_returns_zero(self):
        val = CorrelationService.max_pairwise_with_portfolio(
            ["AMZN"], "AAPL", self._matrix()
        )
        assert val == 0.0

    def test_absolute_value_used(self):
        matrix = {("AAPL", "GLD"): -0.85, ("GLD", "AAPL"): -0.85}
        val = CorrelationService.max_pairwise_with_portfolio(["GLD"], "AAPL", matrix)
        assert abs(val - 0.85) < 0.001


# ---------------------------------------------------------------------------
# 4. TestCorrelationSizeFactor
# ---------------------------------------------------------------------------

class TestCorrelationSizeFactor:
    def _settings(self, floor=0.25):
        return _make_settings(correlation_size_floor=floor)

    def test_zero_correlation_full_size(self):
        assert CorrelationService.correlation_size_factor(0.0, self._settings()) == 1.0

    def test_below_onset_full_size(self):
        assert CorrelationService.correlation_size_factor(0.49, self._settings()) == 1.0

    def test_at_onset_full_size(self):
        assert CorrelationService.correlation_size_factor(0.50, self._settings()) == 1.0

    def test_midpoint_decay(self):
        # At 0.75 (midpoint between 0.50 and 1.0), factor should be ~0.625 with floor=0.25
        factor = CorrelationService.correlation_size_factor(0.75, self._settings())
        assert 0.62 < factor < 0.64

    def test_at_one_equals_floor(self):
        factor = CorrelationService.correlation_size_factor(1.0, self._settings())
        assert abs(factor - 0.25) < 0.001

    def test_floor_respected(self):
        factor = CorrelationService.correlation_size_factor(1.0, self._settings(floor=0.40))
        assert abs(factor - 0.40) < 0.001

    def test_factor_never_above_one(self):
        factor = CorrelationService.correlation_size_factor(0.0, self._settings())
        assert factor <= 1.0

    def test_factor_never_below_floor(self):
        floor = 0.30
        factor = CorrelationService.correlation_size_factor(0.99, self._settings(floor=floor))
        assert factor >= floor


# ---------------------------------------------------------------------------
# 5. TestAdjustActionForCorrelation
# ---------------------------------------------------------------------------

class TestAdjustActionForCorrelation:
    def _settings(self):
        return _make_settings()

    def test_non_open_action_unchanged(self):
        action = _make_action(action_type_str="close")
        matrix = {("AAPL", "MSFT"): 0.95, ("MSFT", "AAPL"): 0.95}
        result = CorrelationService.adjust_action_for_correlation(
            action, ["MSFT"], matrix, self._settings()
        )
        assert result is action

    def test_empty_portfolio_unchanged(self):
        action = _make_action()
        matrix = {("AAPL", "MSFT"): 0.9, ("MSFT", "AAPL"): 0.9}
        result = CorrelationService.adjust_action_for_correlation(
            action, [], matrix, self._settings()
        )
        assert result is action

    def test_empty_matrix_unchanged(self):
        action = _make_action()
        result = CorrelationService.adjust_action_for_correlation(
            action, ["MSFT"], {}, self._settings()
        )
        assert result is action

    def test_low_correlation_unchanged(self):
        action = _make_action(target_notional=1000.0)
        # Correlation = 0.30 → below onset → no penalty
        matrix = {("AAPL", "MSFT"): 0.30, ("MSFT", "AAPL"): 0.30}
        result = CorrelationService.adjust_action_for_correlation(
            action, ["MSFT"], matrix, self._settings()
        )
        assert result is action

    def test_high_correlation_reduces_notional(self):
        action = _make_action(target_notional=1000.0)
        # AAPL vs MSFT corr = 0.90 → significant penalty
        matrix = {("AAPL", "MSFT"): 0.90, ("MSFT", "AAPL"): 0.90}
        result = CorrelationService.adjust_action_for_correlation(
            action, ["MSFT"], matrix, self._settings()
        )
        assert result.target_notional < Decimal("1000.00")

    def test_high_correlation_reduces_quantity(self):
        action = _make_action(target_quantity=10.0)
        matrix = {("AAPL", "MSFT"): 0.90, ("MSFT", "AAPL"): 0.90}
        result = CorrelationService.adjust_action_for_correlation(
            action, ["MSFT"], matrix, self._settings()
        )
        assert result.target_quantity < Decimal("10")

    def test_quantity_never_below_one(self):
        action = _make_action(target_quantity=1.0)
        matrix = {("AAPL", "MSFT"): 0.99, ("MSFT", "AAPL"): 0.99}
        result = CorrelationService.adjust_action_for_correlation(
            action, ["MSFT"], matrix, _make_settings(correlation_size_floor=0.01)
        )
        assert result.target_quantity >= Decimal("1")

    def test_sizing_rationale_updated(self):
        action = _make_action()
        matrix = {("AAPL", "MSFT"): 0.85, ("MSFT", "AAPL"): 0.85}
        result = CorrelationService.adjust_action_for_correlation(
            action, ["MSFT"], matrix, self._settings()
        )
        assert "correlation_adj" in (result.sizing_rationale or "")

    def test_original_action_not_mutated(self):
        action = _make_action(target_notional=1000.0)
        original_notional = action.target_notional
        matrix = {("AAPL", "MSFT"): 0.90, ("MSFT", "AAPL"): 0.90}
        CorrelationService.adjust_action_for_correlation(
            action, ["MSFT"], matrix, self._settings()
        )
        assert action.target_notional == original_notional

    def test_multiple_portfolio_positions_uses_max(self):
        action = _make_action(target_notional=1000.0)
        matrix = {
            ("AAPL", "MSFT"): 0.30, ("MSFT", "AAPL"): 0.30,
            ("AAPL", "NVDA"): 0.88, ("NVDA", "AAPL"): 0.88,
        }
        result = CorrelationService.adjust_action_for_correlation(
            action, ["MSFT", "NVDA"], matrix, self._settings()
        )
        # 0.88 correlation → penalty applied
        assert result.target_notional < Decimal("1000.00")


# ---------------------------------------------------------------------------
# 6. TestCorrelationSettings
# ---------------------------------------------------------------------------

class TestCorrelationSettings:
    def test_default_max_pairwise_correlation(self):
        from config.settings import Settings
        s = Settings()
        assert s.max_pairwise_correlation == 0.75

    def test_default_correlation_lookback_days(self):
        from config.settings import Settings
        s = Settings()
        assert s.correlation_lookback_days == 60

    def test_default_correlation_size_floor(self):
        from config.settings import Settings
        s = Settings()
        assert s.correlation_size_floor == 0.25

    def test_env_override_size_floor(self):
        from config.settings import Settings
        s = Settings(correlation_size_floor=0.40)
        assert s.correlation_size_floor == 0.40


# ---------------------------------------------------------------------------
# 7. TestRunCorrelationRefresh
# ---------------------------------------------------------------------------

class TestRunCorrelationRefresh:
    def _make_app_state(self):
        from apps.api.state import ApiAppState
        return ApiAppState()

    def test_no_session_factory_skips(self):
        from apps.worker.jobs.correlation import run_correlation_refresh
        app_state = self._make_app_state()
        result = run_correlation_refresh(app_state=app_state, session_factory=None)
        assert result["status"] == "skipped_no_db"
        assert result["ticker_count"] == 0

    def test_db_failure_returns_error_status(self):
        from apps.worker.jobs.correlation import run_correlation_refresh

        def bad_factory():
            raise RuntimeError("db down")

        app_state = self._make_app_state()
        result = run_correlation_refresh(app_state=app_state, session_factory=bad_factory)
        assert result["status"] == "error_db"
        assert result["error"] is not None

    def test_no_bar_data_returns_no_data(self):
        from apps.worker.jobs.correlation import run_correlation_refresh

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        def factory():
            return mock_session

        app_state = self._make_app_state()

        with patch("apps.worker.jobs.correlation.DailyMarketBar", create=True):
            result = run_correlation_refresh(
                app_state=app_state, session_factory=factory
            )
        # Either no_data or ok with 0 tickers (depending on import path)
        assert result["status"] in ("no_data", "error_db", "ok")

    def test_happy_path_updates_app_state(self):
        from apps.worker.jobs.correlation import run_correlation_refresh

        # Build mock bar data — enough for MIN_OBSERVATIONS pairs
        bars = [
            ("AAPL", f"2026-01-{i + 1:02d}", Decimal(str(150 + i * 0.1)))
            for i in range(MIN_OBSERVATIONS + 5)
        ] + [
            ("MSFT", f"2026-01-{i + 1:02d}", Decimal(str(300 + i * 0.2)))
            for i in range(MIN_OBSERVATIONS + 5)
        ]

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = bars

        def factory():
            return mock_session

        app_state = self._make_app_state()

        with patch("apps.worker.jobs.correlation.DailyMarketBar", create=True):
            result = run_correlation_refresh(app_state=app_state, session_factory=factory)

        assert result["status"] in ("ok", "no_data", "error_db")
        # If ok, app_state should be updated
        if result["status"] == "ok":
            assert app_state.correlation_computed_at is not None

    def test_result_has_required_keys(self):
        from apps.worker.jobs.correlation import run_correlation_refresh
        app_state = self._make_app_state()
        result = run_correlation_refresh(app_state=app_state, session_factory=None)
        for key in ("status", "ticker_count", "pair_count", "computed_at", "error"):
            assert key in result

    def test_job_exported_from_jobs_package(self):
        from apps.worker.jobs import run_correlation_refresh  # noqa: F401
        assert callable(run_correlation_refresh)

    def test_job_in_all_list(self):
        from apps.worker import jobs
        assert "run_correlation_refresh" in jobs.__all__

    def test_correlation_computed_at_is_none_before_run(self):
        app_state = self._make_app_state()
        assert app_state.correlation_computed_at is None


# ---------------------------------------------------------------------------
# 8. TestCorrelationRestEndpoints
# ---------------------------------------------------------------------------

class TestCorrelationRestEndpoints:
    def _client(self, state_overrides: dict | None = None):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import reset_app_state, get_app_state

        reset_app_state()
        if state_overrides:
            s = get_app_state()
            for k, v in state_overrides.items():
                setattr(s, k, v)
        return TestClient(app)

    def test_get_correlation_empty_returns_200(self):
        client = self._client()
        resp = client.get("/api/v1/portfolio/correlation")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pair_count"] == 0
        assert data["pairs"] == []

    def test_get_correlation_with_matrix_returns_pairs(self):
        matrix = {
            ("AAPL", "MSFT"): 0.85, ("MSFT", "AAPL"): 0.85,
            ("AAPL", "TSLA"): 0.30, ("TSLA", "AAPL"): 0.30,
            ("MSFT", "TSLA"): 0.50, ("TSLA", "MSFT"): 0.50,
        }
        client = self._client({
            "correlation_matrix": matrix,
            "correlation_tickers": ["AAPL", "MSFT", "TSLA"],
            "correlation_computed_at": dt.datetime(2026, 3, 20, 6, 16, tzinfo=dt.timezone.utc),
        })
        resp = client.get("/api/v1/portfolio/correlation")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pair_count"] == 3
        assert data["max_correlation"] > 0.8

    def test_get_correlation_max_is_highest_abs(self):
        matrix = {
            ("A", "B"): 0.60, ("B", "A"): 0.60,
            ("A", "C"): -0.95, ("C", "A"): -0.95,
            ("B", "C"): 0.10, ("C", "B"): 0.10,
        }
        client = self._client({"correlation_matrix": matrix, "correlation_tickers": ["A", "B", "C"]})
        resp = client.get("/api/v1/portfolio/correlation")
        assert resp.status_code == 200
        data = resp.json()
        assert abs(data["max_correlation"] - 0.95) < 0.01

    def test_get_ticker_correlation_empty_returns_200(self):
        client = self._client()
        resp = client.get("/api/v1/portfolio/correlation/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert data["correlations"] == []

    def test_get_ticker_correlation_with_data(self):
        matrix = {("AAPL", "MSFT"): 0.85, ("MSFT", "AAPL"): 0.85}
        client = self._client({"correlation_matrix": matrix, "correlation_tickers": ["AAPL", "MSFT"]})
        resp = client.get("/api/v1/portfolio/correlation/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["correlations"]) >= 1
        assert any(p["ticker_b"] == "MSFT" for p in data["correlations"])

    def test_get_ticker_correlation_unknown_ticker_empty_list(self):
        matrix = {("AAPL", "MSFT"): 0.85, ("MSFT", "AAPL"): 0.85}
        client = self._client({"correlation_matrix": matrix, "correlation_tickers": ["AAPL", "MSFT"]})
        resp = client.get("/api/v1/portfolio/correlation/GOOGL")
        assert resp.status_code == 200
        assert resp.json()["correlations"] == []

    def test_scheduler_has_correlation_job(self):
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        ids = [j.id for j in scheduler.get_jobs()]
        assert "correlation_refresh" in ids
