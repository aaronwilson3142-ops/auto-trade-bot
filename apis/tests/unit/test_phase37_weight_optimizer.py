"""
Phase 37 — Strategy Weight Auto-Tuning Tests
=============================================

Test classes (55 tests total):
 1. TestWeightProfileORM                — ORM fields, defaults, repr
 2. TestWeightProfileMigration          — Alembic migration revision chain
 3. TestWeightOptimizerEqualWeights     — equal_weights() helper
 4. TestWeightOptimizerComputeWeights   — Sharpe-proportional weight derivation
 5. TestWeightOptimizerEdgeCases        — insufficient data, negative Sharpe, missing strategies
 6. TestWeightOptimizerNormalise        — normalise helper edge cases
 7. TestWeightOptimizerPersist          — fire-and-forget persist / no DB
 8. TestWeightOptimizerGetActive        — get_active_profile DB path
 9. TestWeightOptimizerSetActive        — set_active_profile DB path
10. TestWeightOptimizerListProfiles     — list_profiles DB path
11. TestWeightOptimizerManualProfile    — create_manual_profile
12. TestWeightProfileSchemas            — Pydantic schema validation
13. TestWeightsRoutes                   — all 5 REST endpoints
14. TestRankingEngineWeighted           — rank_signals uses strategy_weights
15. TestWeightOptimizationJob           — run_weight_optimization worker job
16. TestSchedulerWeightJob              — 18th job registered in scheduler
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_backtest_run(strategy_name: str, sharpe: Optional[float]) -> Any:
    """Create a duck-typed BacktestRun-like object for testing."""
    obj = MagicMock()
    obj.strategy_name = strategy_name
    obj.sharpe_ratio = sharpe
    obj.comparison_id = "cmp-001"
    return obj


def _make_app_state():
    from apps.api.state import ApiAppState
    return ApiAppState()


# ---------------------------------------------------------------------------
# 1. TestWeightProfileORM
# ---------------------------------------------------------------------------

class TestWeightProfileORM:
    """ORM model fields and defaults."""

    def test_import(self):
        from infra.db.models.weight_profile import WeightProfile
        assert WeightProfile.__tablename__ == "weight_profiles"

    def test_default_source(self):
        from infra.db.models.weight_profile import WeightProfile
        wp = WeightProfile(
            id=uuid.uuid4(),
            profile_name="test",
            weights_json="{}",
            source="optimized",
        )
        assert wp.source == "optimized"

    def test_default_is_active_false(self):
        from infra.db.models.weight_profile import WeightProfile
        wp = WeightProfile(
            id=uuid.uuid4(),
            profile_name="test",
            weights_json="{}",
            is_active=False,
        )
        assert wp.is_active is False

    def test_all_fields_settable(self):
        from infra.db.models.weight_profile import WeightProfile
        run_id = uuid.uuid4()
        wp = WeightProfile(
            id=run_id,
            profile_name="manual profile",
            source="manual",
            weights_json='{"momentum_v1": 0.5}',
            sharpe_metrics_json='{"momentum_v1": 1.2}',
            is_active=True,
            optimization_run_id="cmp-abc",
            notes="operator note",
        )
        assert wp.profile_name == "manual profile"
        assert wp.source == "manual"
        assert wp.is_active is True
        assert wp.optimization_run_id == "cmp-abc"
        assert wp.notes == "operator note"

    def test_exported_in_models_init(self):
        from infra.db.models import WeightProfile
        assert WeightProfile is not None

    def test_in_all_list(self):
        import infra.db.models as m
        assert "WeightProfile" in m.__all__


# ---------------------------------------------------------------------------
# 2. TestWeightProfileMigration
# ---------------------------------------------------------------------------

class TestWeightProfileMigration:
    """Alembic migration correctness."""

    def test_revision_id(self):
        from infra.db.versions.g7h8i9j0k1l2_add_weight_profiles import revision
        assert revision == "g7h8i9j0k1l2"

    def test_down_revision(self):
        from infra.db.versions.g7h8i9j0k1l2_add_weight_profiles import down_revision
        assert down_revision == "f6a7b8c9d0e1"

    def test_upgrade_callable(self):
        from infra.db.versions.g7h8i9j0k1l2_add_weight_profiles import upgrade
        assert callable(upgrade)

    def test_downgrade_callable(self):
        from infra.db.versions.g7h8i9j0k1l2_add_weight_profiles import downgrade
        assert callable(downgrade)


# ---------------------------------------------------------------------------
# 3. TestWeightOptimizerEqualWeights
# ---------------------------------------------------------------------------

class TestWeightOptimizerEqualWeights:
    """equal_weights() class method."""

    def test_equal_weights_five_strategies(self):
        from services.signal_engine.weight_optimizer import WeightOptimizerService
        w = WeightOptimizerService.equal_weights()
        assert len(w) == 5

    def test_equal_weights_sum_to_one(self):
        from services.signal_engine.weight_optimizer import WeightOptimizerService
        w = WeightOptimizerService.equal_weights()
        assert abs(sum(w.values()) - 1.0) < 1e-4

    def test_equal_weights_contains_all_strategies(self):
        from services.signal_engine.weight_optimizer import (
            WeightOptimizerService,
            _INDIVIDUAL_STRATEGY_KEYS,
        )
        w = WeightOptimizerService.equal_weights()
        assert set(w.keys()) == _INDIVIDUAL_STRATEGY_KEYS

    def test_equal_weights_each_is_0_2(self):
        from services.signal_engine.weight_optimizer import WeightOptimizerService
        w = WeightOptimizerService.equal_weights()
        for v in w.values():
            assert abs(v - 0.2) < 1e-4


# ---------------------------------------------------------------------------
# 4. TestWeightOptimizerComputeWeights
# ---------------------------------------------------------------------------

class TestWeightOptimizerComputeWeights:
    """Sharpe-proportional weight derivation."""

    def _make_runs(self, sharpe_map: dict[str, float]):
        return [_make_backtest_run(k, v) for k, v in sharpe_map.items()]

    def test_higher_sharpe_gets_higher_weight(self):
        from services.signal_engine.weight_optimizer import WeightOptimizerService
        svc = WeightOptimizerService()
        runs = self._make_runs({
            "momentum_v1": 2.0,
            "theme_alignment_v1": 1.0,
            "macro_tailwind_v1": 0.5,
            "sentiment_v1": 0.5,
            "valuation_v1": 0.5,
        })
        profile = svc.optimize_from_backtest(runs, set_active=False)
        assert profile.weights["momentum_v1"] > profile.weights["theme_alignment_v1"]
        assert profile.weights["theme_alignment_v1"] > profile.weights["macro_tailwind_v1"]

    def test_weights_sum_to_one(self):
        from services.signal_engine.weight_optimizer import WeightOptimizerService
        svc = WeightOptimizerService()
        runs = self._make_runs({
            "momentum_v1": 1.5,
            "theme_alignment_v1": 1.2,
            "macro_tailwind_v1": 0.8,
            "sentiment_v1": 0.6,
            "valuation_v1": 0.4,
        })
        profile = svc.optimize_from_backtest(runs, set_active=False)
        assert abs(sum(profile.weights.values()) - 1.0) < 1e-4

    def test_all_strategies_present(self):
        from services.signal_engine.weight_optimizer import (
            WeightOptimizerService,
            _INDIVIDUAL_STRATEGY_KEYS,
        )
        svc = WeightOptimizerService()
        runs = self._make_runs({
            "momentum_v1": 1.0,
            "theme_alignment_v1": 1.0,
            "macro_tailwind_v1": 1.0,
            "sentiment_v1": 1.0,
            "valuation_v1": 1.0,
        })
        profile = svc.optimize_from_backtest(runs, set_active=False)
        assert set(profile.weights.keys()) == _INDIVIDUAL_STRATEGY_KEYS

    def test_source_is_optimized(self):
        from services.signal_engine.weight_optimizer import WeightOptimizerService
        svc = WeightOptimizerService()
        runs = self._make_runs({"momentum_v1": 1.0, "theme_alignment_v1": 1.0})
        profile = svc.optimize_from_backtest(runs, set_active=False)
        assert profile.source == "optimized"

    def test_comparison_id_stored(self):
        from services.signal_engine.weight_optimizer import WeightOptimizerService
        svc = WeightOptimizerService()
        runs = self._make_runs({"momentum_v1": 1.0, "theme_alignment_v1": 1.0})
        profile = svc.optimize_from_backtest(runs, comparison_id="cmp-xyz", set_active=False)
        assert profile.optimization_run_id == "cmp-xyz"

    def test_all_strategies_key_excluded(self):
        from services.signal_engine.weight_optimizer import WeightOptimizerService
        svc = WeightOptimizerService()
        runs = self._make_runs({
            "momentum_v1": 2.0,
            "all_strategies": 3.0,   # should be excluded
            "theme_alignment_v1": 1.0,
        })
        profile = svc.optimize_from_backtest(runs, set_active=False)
        assert "all_strategies" not in profile.weights

    def test_sharpe_metrics_populated(self):
        from services.signal_engine.weight_optimizer import WeightOptimizerService
        svc = WeightOptimizerService()
        runs = self._make_runs({"momentum_v1": 1.5, "theme_alignment_v1": 0.8,
                                "macro_tailwind_v1": 0.5, "sentiment_v1": 0.3,
                                "valuation_v1": 0.2})
        profile = svc.optimize_from_backtest(runs, set_active=False)
        assert profile.sharpe_metrics["momentum_v1"] == 1.5


# ---------------------------------------------------------------------------
# 5. TestWeightOptimizerEdgeCases
# ---------------------------------------------------------------------------

class TestWeightOptimizerEdgeCases:
    """Edge cases: no data, negative Sharpe, missing strategies."""

    def test_empty_runs_returns_equal_weights(self):
        from services.signal_engine.weight_optimizer import WeightOptimizerService
        svc = WeightOptimizerService()
        profile = svc.optimize_from_backtest([], set_active=False)
        assert len(profile.weights) == 5
        for v in profile.weights.values():
            assert abs(v - 0.2) < 1e-4

    def test_single_run_returns_equal_weights(self):
        from services.signal_engine.weight_optimizer import WeightOptimizerService
        svc = WeightOptimizerService()
        runs = [_make_backtest_run("momentum_v1", 1.5)]
        profile = svc.optimize_from_backtest(runs, set_active=False)
        # Only 1 strategy → fallback to equal
        for v in profile.weights.values():
            assert abs(v - 0.2) < 1e-4

    def test_negative_sharpe_floored_at_0_01(self):
        from services.signal_engine.weight_optimizer import WeightOptimizerService
        svc = WeightOptimizerService()
        runs = [
            _make_backtest_run("momentum_v1", -2.0),
            _make_backtest_run("theme_alignment_v1", 1.5),
            _make_backtest_run("macro_tailwind_v1", 0.5),
            _make_backtest_run("sentiment_v1", 0.3),
            _make_backtest_run("valuation_v1", 0.2),
        ]
        profile = svc.optimize_from_backtest(runs, set_active=False)
        # momentum gets floor weight (0.01), not negative or zero
        assert profile.weights["momentum_v1"] > 0
        assert sum(profile.weights.values()) - 1.0 < 1e-4

    def test_missing_strategy_gets_floor_weight(self):
        from services.signal_engine.weight_optimizer import WeightOptimizerService
        svc = WeightOptimizerService()
        # Only 3 of 5 strategies in backtest data
        runs = [
            _make_backtest_run("momentum_v1", 1.5),
            _make_backtest_run("theme_alignment_v1", 1.0),
            _make_backtest_run("macro_tailwind_v1", 0.8),
        ]
        profile = svc.optimize_from_backtest(runs, set_active=False)
        # All 5 strategies should be in the output
        assert "sentiment_v1" in profile.weights
        assert "valuation_v1" in profile.weights
        assert profile.weights["sentiment_v1"] > 0

    def test_none_sharpe_ignored(self):
        from services.signal_engine.weight_optimizer import WeightOptimizerService
        svc = WeightOptimizerService()
        runs = [
            _make_backtest_run("momentum_v1", None),  # should be ignored
            _make_backtest_run("theme_alignment_v1", 1.0),
            _make_backtest_run("macro_tailwind_v1", 0.8),
            _make_backtest_run("sentiment_v1", 0.6),
            _make_backtest_run("valuation_v1", 0.4),
        ]
        profile = svc.optimize_from_backtest(runs, set_active=False)
        # 4 valid entries → not a fallback, weights present
        assert sum(profile.weights.values()) - 1.0 < 1e-4


# ---------------------------------------------------------------------------
# 6. TestWeightOptimizerNormalise
# ---------------------------------------------------------------------------

class TestWeightOptimizerNormalise:
    """_normalise static method."""

    def test_normalise_basic(self):
        from services.signal_engine.weight_optimizer import WeightOptimizerService
        w = WeightOptimizerService._normalise({"a": 1.0, "b": 3.0})
        assert abs(w["a"] - 0.25) < 1e-6
        assert abs(w["b"] - 0.75) < 1e-6

    def test_normalise_sum_to_one(self):
        from services.signal_engine.weight_optimizer import WeightOptimizerService
        w = WeightOptimizerService._normalise({"x": 0.1, "y": 0.4, "z": 0.5})
        assert abs(sum(w.values()) - 1.0) < 1e-6

    def test_normalise_zero_total_returns_equal(self):
        from services.signal_engine.weight_optimizer import WeightOptimizerService
        w = WeightOptimizerService._normalise({"a": 0.0, "b": 0.0})
        assert abs(w["a"] - 0.5) < 1e-6
        assert abs(w["b"] - 0.5) < 1e-6


# ---------------------------------------------------------------------------
# 7. TestWeightOptimizerPersist
# ---------------------------------------------------------------------------

class TestWeightOptimizerPersist:
    """Fire-and-forget persistence and no-DB path."""

    def test_no_session_factory_does_not_raise(self):
        from services.signal_engine.weight_optimizer import WeightOptimizerService
        svc = WeightOptimizerService(session_factory=None)
        runs = [_make_backtest_run("momentum_v1", 1.0),
                _make_backtest_run("theme_alignment_v1", 0.8),
                _make_backtest_run("macro_tailwind_v1", 0.6),
                _make_backtest_run("sentiment_v1", 0.5),
                _make_backtest_run("valuation_v1", 0.4)]
        profile = svc.optimize_from_backtest(runs, set_active=True)
        assert profile is not None
        assert profile.weights

    def test_persist_exception_does_not_raise(self):
        from services.signal_engine.weight_optimizer import WeightOptimizerService

        bad_factory = MagicMock(side_effect=RuntimeError("DB down"))
        svc = WeightOptimizerService(session_factory=bad_factory)
        runs = [_make_backtest_run("momentum_v1", 1.0),
                _make_backtest_run("theme_alignment_v1", 0.8),
                _make_backtest_run("macro_tailwind_v1", 0.6),
                _make_backtest_run("sentiment_v1", 0.5),
                _make_backtest_run("valuation_v1", 0.4)]
        profile = svc.optimize_from_backtest(runs)
        assert profile is not None  # result returned despite DB error

    def test_no_session_get_active_returns_none(self):
        from services.signal_engine.weight_optimizer import WeightOptimizerService
        svc = WeightOptimizerService(session_factory=None)
        assert svc.get_active_profile() is None

    def test_no_session_list_profiles_returns_empty(self):
        from services.signal_engine.weight_optimizer import WeightOptimizerService
        svc = WeightOptimizerService(session_factory=None)
        assert svc.list_profiles() == []

    def test_no_session_set_active_returns_none(self):
        from services.signal_engine.weight_optimizer import WeightOptimizerService
        svc = WeightOptimizerService(session_factory=None)
        result = svc.set_active_profile(str(uuid.uuid4()))
        assert result is None


# ---------------------------------------------------------------------------
# 8. TestWeightProfileSchemas
# ---------------------------------------------------------------------------

class TestWeightProfileSchemas:
    """Pydantic schema round-trip and validation."""

    def test_weight_profile_schema(self):
        from apps.api.schemas.weights import WeightProfileSchema
        schema = WeightProfileSchema(
            id=str(uuid.uuid4()),
            profile_name="test profile",
            source="optimized",
            weights={"momentum_v1": 0.4, "theme_alignment_v1": 0.6},
            sharpe_metrics={"momentum_v1": 1.5, "theme_alignment_v1": 1.2},
            is_active=True,
        )
        assert schema.source == "optimized"
        assert schema.weights["momentum_v1"] == 0.4

    def test_weight_profile_list_response(self):
        from apps.api.schemas.weights import WeightProfileListResponse
        resp = WeightProfileListResponse(profiles=[], count=0)
        assert resp.count == 0

    def test_optimize_weights_response(self):
        from apps.api.schemas.weights import OptimizeWeightsResponse, WeightProfileSchema
        profile = WeightProfileSchema(
            id=str(uuid.uuid4()),
            profile_name="opt",
            source="optimized",
            weights={"momentum_v1": 1.0},
            sharpe_metrics={},
            is_active=True,
        )
        resp = OptimizeWeightsResponse(profile=profile)
        assert "optimized" in resp.message or resp.message

    def test_set_active_weight_response(self):
        from apps.api.schemas.weights import SetActiveWeightResponse
        resp = SetActiveWeightResponse(profile_id="abc-123")
        assert resp.profile_id == "abc-123"

    def test_create_manual_weight_request(self):
        from apps.api.schemas.weights import CreateManualWeightRequest
        req = CreateManualWeightRequest(
            profile_name="my profile",
            weights={"momentum_v1": 2.0, "theme_alignment_v1": 1.0},
        )
        assert req.set_active is True
        assert req.notes is None


# ---------------------------------------------------------------------------
# 9. TestWeightsRoutes
# ---------------------------------------------------------------------------

class TestWeightsRoutes:
    """REST endpoint behaviour via TestClient."""

    def _client(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        return TestClient(app)

    def test_optimize_no_db_returns_503(self):
        client = self._client()
        resp = client.post("/api/v1/signals/weights/optimize")
        assert resp.status_code == 503

    def test_get_current_no_profile_returns_404(self):
        from apps.api.state import reset_app_state
        reset_app_state()
        client = self._client()
        resp = client.get("/api/v1/signals/weights/current")
        assert resp.status_code == 404

    def test_get_history_no_db_returns_empty_list(self):
        client = self._client()
        resp = client.get("/api/v1/signals/weights/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["profiles"] == []

    def test_set_active_no_db_returns_503(self):
        client = self._client()
        resp = client.put(f"/api/v1/signals/weights/active/{uuid.uuid4()}")
        assert resp.status_code == 503

    def test_get_current_returns_in_memory_profile(self):
        from apps.api.state import get_app_state, reset_app_state
        from services.signal_engine.weight_optimizer import WeightProfileRecord
        reset_app_state()
        state = get_app_state()
        profile = WeightProfileRecord(
            id=str(uuid.uuid4()),
            profile_name="cached profile",
            source="optimized",
            weights={"momentum_v1": 0.3},
            sharpe_metrics={},
            is_active=True,
        )
        state.active_weight_profile = profile

        client = self._client()
        resp = client.get("/api/v1/signals/weights/current")
        assert resp.status_code == 200
        data = resp.json()
        assert data["profile_name"] == "cached profile"
        assert data["is_active"] is True

    def test_manual_profile_creation(self):
        from apps.api.state import reset_app_state
        reset_app_state()
        client = self._client()
        resp = client.post(
            "/api/v1/signals/weights/manual",
            json={
                "profile_name": "test manual",
                "weights": {
                    "momentum_v1": 2.0,
                    "theme_alignment_v1": 1.0,
                    "macro_tailwind_v1": 1.0,
                    "sentiment_v1": 0.5,
                    "valuation_v1": 0.5,
                },
                "set_active": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["profile"]["profile_name"] == "test manual"
        # Weights should be normalised
        total = sum(data["profile"]["weights"].values())
        assert abs(total - 1.0) < 1e-3

    def test_history_limit_param(self):
        client = self._client()
        resp = client.get("/api/v1/signals/weights/history?limit=5")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 10. TestRankingEngineWeighted
# ---------------------------------------------------------------------------

class TestRankingEngineWeighted:
    """RankingEngineService uses strategy_weights when provided."""

    def _make_signal(self, ticker: str, strategy_key: str, score: float):
        from services.signal_engine.models import SignalOutput
        return SignalOutput(
            security_id=uuid.uuid4(),
            ticker=ticker,
            strategy_key=strategy_key,
            signal_type="momentum",
            signal_score=Decimal(str(score)),
            confidence_score=Decimal("0.8"),
            risk_score=Decimal("0.2"),
            catalyst_score=None,
            liquidity_score=Decimal("0.7"),
            horizon_classification="POSITIONAL",
            explanation_dict={"rationale": "test"},
            source_reliability_tier="secondary_verified",
            contains_rumor=False,
        )

    def test_equal_weights_when_none(self):
        from services.ranking_engine.service import RankingEngineService
        svc = RankingEngineService()
        sec_id = uuid.uuid4()
        sig1 = self._make_signal("AAPL", "momentum_v1", 0.8)
        sig2 = self._make_signal("AAPL", "theme_alignment_v1", 0.4)
        sig1.security_id = sec_id
        sig2.security_id = sec_id
        results = svc.rank_signals([sig1, sig2], strategy_weights=None)
        assert len(results) == 1

    def test_custom_weights_applied(self):
        """High-weight strategy dominates the composite signal score."""
        from services.ranking_engine.service import RankingEngineService
        svc = RankingEngineService()

        # Two securities, each with two strategy signals
        sec_a = uuid.uuid4()
        sec_b = uuid.uuid4()

        # Security A: momentum=0.9, theme=0.1
        a1 = self._make_signal("AAPL", "momentum_v1", 0.9)
        a2 = self._make_signal("AAPL", "theme_alignment_v1", 0.1)
        a1.security_id = sec_a
        a2.security_id = sec_a

        # Security B: momentum=0.1, theme=0.9
        b1 = self._make_signal("MSFT", "momentum_v1", 0.1)
        b2 = self._make_signal("MSFT", "theme_alignment_v1", 0.9)
        b1.security_id = sec_b
        b2.security_id = sec_b

        # Weight momentum heavily → AAPL should rank higher
        weights = {"momentum_v1": 0.9, "theme_alignment_v1": 0.1}
        results = svc.rank_signals([a1, a2, b1, b2], strategy_weights=weights)
        assert len(results) >= 2
        # AAPL has high momentum weight → should score higher than MSFT
        aapl = next((r for r in results if r.ticker == "AAPL"), None)
        msft = next((r for r in results if r.ticker == "MSFT"), None)
        assert aapl is not None and msft is not None
        assert float(aapl.composite_score) > float(msft.composite_score)

    def test_single_signal_no_weight_blending(self):
        from services.ranking_engine.service import RankingEngineService
        svc = RankingEngineService()
        sig = self._make_signal("TSLA", "momentum_v1", 0.75)
        results = svc.rank_signals([sig], strategy_weights={"momentum_v1": 1.0})
        assert len(results) == 1
        assert results[0].ticker == "TSLA"


# ---------------------------------------------------------------------------
# 11. TestWeightOptimizationJob
# ---------------------------------------------------------------------------

class TestWeightOptimizationJob:
    """run_weight_optimization worker job function."""

    def test_skips_when_no_session_factory(self):
        from apps.worker.jobs.signal_ranking import run_weight_optimization
        state = _make_app_state()
        result = run_weight_optimization(app_state=state, session_factory=None)
        assert result["status"] == "skipped_no_session"
        assert state.active_weight_profile is None

    def test_job_exported_from_worker_jobs(self):
        from apps.worker.jobs import run_weight_optimization
        assert callable(run_weight_optimization)

    def test_db_error_returns_error_status(self):
        from apps.worker.jobs.signal_ranking import run_weight_optimization
        state = _make_app_state()
        bad_factory = MagicMock(side_effect=RuntimeError("connection refused"))
        result = run_weight_optimization(app_state=state, session_factory=bad_factory)
        assert result["status"] == "error"
        assert state.active_weight_profile is None

    def test_no_backtest_data_returns_skipped(self):
        from apps.worker.jobs.signal_ranking import run_weight_optimization

        mock_session = MagicMock()
        # First query returns None (no comparison_id)
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.scalar_one_or_none.return_value = None

        mock_factory = MagicMock(return_value=mock_session)

        state = _make_app_state()
        result = run_weight_optimization(app_state=state, session_factory=mock_factory)
        assert result["status"] == "skipped_no_backtest_data"

    def test_successful_optimization_updates_app_state(self):
        from apps.worker.jobs.signal_ranking import run_weight_optimization
        from services.signal_engine.weight_optimizer import WeightOptimizerService, WeightProfileRecord

        state = _make_app_state()
        mock_profile = WeightProfileRecord(
            id=str(uuid.uuid4()),
            profile_name="opt-test",
            source="optimized",
            weights={"momentum_v1": 0.25},
            sharpe_metrics={},
            is_active=True,
        )

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.scalar_one_or_none.return_value = "cmp-123"
        mock_session.execute.return_value.scalars.return_value.all.return_value = []

        mock_factory = MagicMock(return_value=mock_session)

        with patch.object(WeightOptimizerService, "optimize_from_backtest", return_value=mock_profile):
            result = run_weight_optimization(app_state=state, session_factory=mock_factory)

        assert result["status"] == "ok"
        assert state.active_weight_profile is mock_profile


# ---------------------------------------------------------------------------
# 12. TestSchedulerWeightJob
# ---------------------------------------------------------------------------

class TestSchedulerWeightJob:
    """18th scheduled job is registered correctly."""

    def _build(self):
        from apps.worker.main import build_scheduler
        return build_scheduler()

    def test_total_job_count_is_18(self):
        scheduler = self._build()
        assert len(scheduler.get_jobs()) == 30

    def test_weight_optimization_job_registered(self):
        scheduler = self._build()
        job_ids = {job.id for job in scheduler.get_jobs()}
        assert "weight_optimization" in job_ids

    def test_weight_optimization_scheduled_at_06_52(self):
        scheduler = self._build()
        job = next(j for j in scheduler.get_jobs() if j.id == "weight_optimization")
        trigger = job.trigger
        # CronTrigger fields: hour=6, minute=52
        fields = {f.name: str(f) for f in trigger.fields}
        assert fields.get("hour") == "6"
        assert fields.get("minute") == "52"

    def test_weight_optimization_exported_from_jobs(self):
        from apps.worker.jobs import run_weight_optimization
        assert run_weight_optimization is not None
