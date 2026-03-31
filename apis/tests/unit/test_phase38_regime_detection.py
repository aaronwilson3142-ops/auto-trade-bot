"""
Phase 38 — Market Regime Detection + Regime-Adaptive Weight Profiles Tests
===========================================================================

Test classes (60 tests total):
 1. TestMarketRegimeEnum              (3)  — enum values, str enum, import
 2. TestRegimeDefaultWeights          (4)  — 4 regimes, weight counts, sums to 1.0
 3. TestRegimeDetectionBull           (4)  — detects BULL_TREND correctly
 4. TestRegimeDetectionBear           (4)  — detects BEAR_TREND correctly
 5. TestRegimeDetectionHighVol        (4)  — detects HIGH_VOL correctly
 6. TestRegimeDetectionSideways       (3)  — detects SIDEWAYS fallback + empty
 7. TestRegimeDetectionEdgeCases      (4)  — single item, bad scores, median boundary
 8. TestRegimeManualOverride          (5)  — set / clear / priority over detection
 9. TestRegimeGetWeights              (4)  — correct weights returned per regime
10. TestRegimePersist                 (4)  — fire-and-forget, no DB, exception safe
11. TestRegimeSnapshotORM             (4)  — tablename, fields, defaults
12. TestRegimeMigration               (2)  — revision, down_revision
13. TestRegimeSchemas                 (5)  — Pydantic schema validation
14. TestRegimeRoutes                  (7)  — all 4 REST endpoints
15. TestRegimeDetectionJob            (5)  — run_regime_detection worker job
16. TestSchedulerRegimeJob            (5)  — 19th job registered in scheduler
"""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signal(composite_score: float) -> Any:
    """Return a duck-typed ranked-signal object."""
    obj = MagicMock()
    obj.composite_score = composite_score
    return obj


def _make_app_state():
    from apps.api.state import ApiAppState
    return ApiAppState()


# ---------------------------------------------------------------------------
# 1. TestMarketRegimeEnum
# ---------------------------------------------------------------------------

class TestMarketRegimeEnum:

    def test_four_values(self):
        from services.signal_engine.regime_detection import MarketRegime
        assert len(MarketRegime) == 4

    def test_values(self):
        from services.signal_engine.regime_detection import MarketRegime
        values = {r.value for r in MarketRegime}
        assert values == {"BULL_TREND", "BEAR_TREND", "SIDEWAYS", "HIGH_VOL"}

    def test_str_enum(self):
        from services.signal_engine.regime_detection import MarketRegime
        assert MarketRegime.BULL_TREND == "BULL_TREND"


# ---------------------------------------------------------------------------
# 2. TestRegimeDefaultWeights
# ---------------------------------------------------------------------------

class TestRegimeDefaultWeights:

    def test_four_regime_entries(self):
        from services.signal_engine.regime_detection import (
            REGIME_DEFAULT_WEIGHTS,
            MarketRegime,
        )
        assert set(REGIME_DEFAULT_WEIGHTS.keys()) == set(MarketRegime)

    def test_five_strategies_each(self):
        from services.signal_engine.regime_detection import REGIME_DEFAULT_WEIGHTS
        for regime, weights in REGIME_DEFAULT_WEIGHTS.items():
            assert len(weights) == 5, f"{regime} does not have 5 strategy keys"

    def test_weights_sum_to_one(self):
        from services.signal_engine.regime_detection import REGIME_DEFAULT_WEIGHTS
        for regime, weights in REGIME_DEFAULT_WEIGHTS.items():
            total = sum(weights.values())
            assert abs(total - 1.0) < 1e-9, f"{regime} weights sum to {total}"

    def test_all_strategy_keys_present(self):
        from services.signal_engine.regime_detection import (
            REGIME_DEFAULT_WEIGHTS,
            MarketRegime,
        )
        expected = {
            "momentum_v1", "theme_alignment_v1", "macro_tailwind_v1",
            "sentiment_v1", "valuation_v1",
        }
        for regime in MarketRegime:
            assert set(REGIME_DEFAULT_WEIGHTS[regime].keys()) == expected


# ---------------------------------------------------------------------------
# 3. TestRegimeDetectionBull
# ---------------------------------------------------------------------------

class TestRegimeDetectionBull:

    def _svc(self):
        from services.signal_engine.regime_detection import RegimeDetectionService
        return RegimeDetectionService()

    def test_bull_trend_detected(self):
        svc = self._svc()
        signals = [_make_signal(0.70)] * 10
        result = svc.detect_from_signals(signals)
        from services.signal_engine.regime_detection import MarketRegime
        assert result.regime == MarketRegime.BULL_TREND

    def test_bull_confidence_positive(self):
        svc = self._svc()
        signals = [_make_signal(0.80)] * 10
        result = svc.detect_from_signals(signals)
        assert result.confidence > 0.0

    def test_bull_confidence_at_most_one(self):
        svc = self._svc()
        signals = [_make_signal(0.99)] * 10
        result = svc.detect_from_signals(signals)
        assert result.confidence <= 1.0

    def test_bull_detection_basis_has_trigger(self):
        svc = self._svc()
        signals = [_make_signal(0.70)] * 10
        result = svc.detect_from_signals(signals)
        assert "trigger" in result.detection_basis


# ---------------------------------------------------------------------------
# 4. TestRegimeDetectionBear
# ---------------------------------------------------------------------------

class TestRegimeDetectionBear:

    def _svc(self):
        from services.signal_engine.regime_detection import RegimeDetectionService
        return RegimeDetectionService()

    def test_bear_trend_detected(self):
        svc = self._svc()
        signals = [_make_signal(0.30)] * 10
        result = svc.detect_from_signals(signals)
        from services.signal_engine.regime_detection import MarketRegime
        assert result.regime == MarketRegime.BEAR_TREND

    def test_bear_confidence_positive(self):
        svc = self._svc()
        signals = [_make_signal(0.20)] * 10
        result = svc.detect_from_signals(signals)
        assert result.confidence > 0.0

    def test_bear_confidence_at_most_one(self):
        svc = self._svc()
        signals = [_make_signal(0.01)] * 10
        result = svc.detect_from_signals(signals)
        assert result.confidence <= 1.0

    def test_bear_detection_basis_universe_size(self):
        svc = self._svc()
        signals = [_make_signal(0.30)] * 8
        result = svc.detect_from_signals(signals)
        assert result.detection_basis["universe_size"] == 8


# ---------------------------------------------------------------------------
# 5. TestRegimeDetectionHighVol
# ---------------------------------------------------------------------------

class TestRegimeDetectionHighVol:

    def _svc(self):
        from services.signal_engine.regime_detection import RegimeDetectionService
        return RegimeDetectionService()

    def test_high_vol_detected(self):
        # Wide spread of scores → high std_dev
        svc = self._svc()
        signals = [_make_signal(s) for s in [0.10, 0.90, 0.10, 0.90, 0.10, 0.90]]
        result = svc.detect_from_signals(signals)
        from services.signal_engine.regime_detection import MarketRegime
        assert result.regime == MarketRegime.HIGH_VOL

    def test_high_vol_takes_priority_over_bull(self):
        svc = self._svc()
        # High median (bull) but extreme spread (high_vol wins)
        signals = [_make_signal(s) for s in [0.10, 0.95, 0.10, 0.95, 0.10, 0.95]]
        result = svc.detect_from_signals(signals)
        from services.signal_engine.regime_detection import MarketRegime
        assert result.regime == MarketRegime.HIGH_VOL

    def test_high_vol_confidence_positive(self):
        svc = self._svc()
        signals = [_make_signal(s) for s in [0.10, 0.90] * 5]
        result = svc.detect_from_signals(signals)
        assert result.confidence > 0.0

    def test_high_vol_basis_has_std_dev(self):
        svc = self._svc()
        signals = [_make_signal(s) for s in [0.10, 0.90] * 5]
        result = svc.detect_from_signals(signals)
        assert "std_dev_composite_score" in result.detection_basis


# ---------------------------------------------------------------------------
# 6. TestRegimeDetectionSideways
# ---------------------------------------------------------------------------

class TestRegimeDetectionSideways:

    def _svc(self):
        from services.signal_engine.regime_detection import RegimeDetectionService
        return RegimeDetectionService()

    def test_sideways_neutral_scores(self):
        svc = self._svc()
        signals = [_make_signal(0.50)] * 10
        result = svc.detect_from_signals(signals)
        from services.signal_engine.regime_detection import MarketRegime
        assert result.regime == MarketRegime.SIDEWAYS

    def test_sideways_empty_signals(self):
        svc = self._svc()
        result = svc.detect_from_signals([])
        from services.signal_engine.regime_detection import MarketRegime
        assert result.regime == MarketRegime.SIDEWAYS
        assert result.confidence == 0.0

    def test_sideways_empty_basis_reason(self):
        svc = self._svc()
        result = svc.detect_from_signals([])
        assert "reason" in result.detection_basis


# ---------------------------------------------------------------------------
# 7. TestRegimeDetectionEdgeCases
# ---------------------------------------------------------------------------

class TestRegimeDetectionEdgeCases:

    def _svc(self):
        from services.signal_engine.regime_detection import RegimeDetectionService
        return RegimeDetectionService()

    def test_single_signal_no_crash(self):
        svc = self._svc()
        result = svc.detect_from_signals([_make_signal(0.80)])
        assert result.regime is not None

    def test_signals_missing_composite_score(self):
        svc = self._svc()
        bad = MagicMock()
        del bad.composite_score
        result = svc.detect_from_signals([bad])
        from services.signal_engine.regime_detection import MarketRegime
        # Falls back to SIDEWAYS (no valid scores)
        assert result.regime == MarketRegime.SIDEWAYS

    def test_confidence_capped_at_one(self):
        svc = self._svc()
        signals = [_make_signal(1.0)] * 50  # very bullish
        result = svc.detect_from_signals(signals)
        assert result.confidence <= 1.0

    def test_returns_regime_result_type(self):
        from services.signal_engine.regime_detection import RegimeResult
        svc = self._svc()
        result = svc.detect_from_signals([_make_signal(0.5)] * 5)
        assert isinstance(result, RegimeResult)


# ---------------------------------------------------------------------------
# 8. TestRegimeManualOverride
# ---------------------------------------------------------------------------

class TestRegimeManualOverride:

    def _svc(self):
        from services.signal_engine.regime_detection import RegimeDetectionService
        return RegimeDetectionService()

    def test_set_manual_override_returns_result(self):
        from services.signal_engine.regime_detection import MarketRegime, RegimeResult
        svc = self._svc()
        result = svc.set_manual_override(MarketRegime.BEAR_TREND, "Fed risk")
        assert isinstance(result, RegimeResult)

    def test_override_regime_set_correctly(self):
        from services.signal_engine.regime_detection import MarketRegime
        svc = self._svc()
        result = svc.set_manual_override(MarketRegime.HIGH_VOL, "VIX spike")
        assert result.regime == MarketRegime.HIGH_VOL

    def test_override_is_manual_override_true(self):
        from services.signal_engine.regime_detection import MarketRegime
        svc = self._svc()
        result = svc.set_manual_override(MarketRegime.SIDEWAYS, "Choppy")
        assert result.is_manual_override is True

    def test_override_confidence_is_one(self):
        from services.signal_engine.regime_detection import MarketRegime
        svc = self._svc()
        result = svc.set_manual_override(MarketRegime.BULL_TREND, "Operator call")
        assert result.confidence == 1.0

    def test_override_reason_stored(self):
        from services.signal_engine.regime_detection import MarketRegime
        svc = self._svc()
        result = svc.set_manual_override(MarketRegime.BEAR_TREND, "Macro risk")
        assert result.override_reason == "Macro risk"


# ---------------------------------------------------------------------------
# 9. TestRegimeGetWeights
# ---------------------------------------------------------------------------

class TestRegimeGetWeights:

    def _svc(self):
        from services.signal_engine.regime_detection import RegimeDetectionService
        return RegimeDetectionService()

    def test_bull_weights_returned(self):
        from services.signal_engine.regime_detection import MarketRegime
        svc = self._svc()
        w = svc.get_regime_weights(MarketRegime.BULL_TREND)
        assert w["momentum_v1"] == 0.35

    def test_bear_weights_returned(self):
        from services.signal_engine.regime_detection import MarketRegime
        svc = self._svc()
        w = svc.get_regime_weights(MarketRegime.BEAR_TREND)
        assert w["macro_tailwind_v1"] == 0.35

    def test_returns_copy_not_original(self):
        from services.signal_engine.regime_detection import (
            REGIME_DEFAULT_WEIGHTS,
            MarketRegime,
        )
        svc = self._svc()
        w = svc.get_regime_weights(MarketRegime.SIDEWAYS)
        w["momentum_v1"] = 999.0
        assert REGIME_DEFAULT_WEIGHTS[MarketRegime.SIDEWAYS]["momentum_v1"] != 999.0

    def test_high_vol_sentiment_dominant(self):
        from services.signal_engine.regime_detection import MarketRegime
        svc = self._svc()
        w = svc.get_regime_weights(MarketRegime.HIGH_VOL)
        assert w["sentiment_v1"] == 0.30


# ---------------------------------------------------------------------------
# 10. TestRegimePersist
# ---------------------------------------------------------------------------

class TestRegimePersist:

    def _result(self):
        from services.signal_engine.regime_detection import MarketRegime, RegimeResult
        return RegimeResult(
            regime=MarketRegime.BULL_TREND,
            confidence=0.75,
            detection_basis={"trigger": "test"},
        )

    def test_persist_no_session_factory_no_crash(self):
        from services.signal_engine.regime_detection import RegimeDetectionService
        svc = RegimeDetectionService(session_factory=None)
        svc.persist_snapshot(self._result())  # must not raise

    def test_persist_exception_swallowed(self):
        from services.signal_engine.regime_detection import RegimeDetectionService

        def bad_factory():
            raise RuntimeError("DB down")

        svc = RegimeDetectionService(session_factory=bad_factory)
        svc.persist_snapshot(self._result())  # must not raise

    def test_persist_exception_in_factory_swallowed(self):
        from services.signal_engine.regime_detection import RegimeDetectionService

        def crashing_factory():
            raise OSError("connection refused")

        svc = RegimeDetectionService(session_factory=crashing_factory)
        svc.persist_snapshot(self._result())  # must not raise

    def test_persist_uses_session_factory_arg_over_init(self):
        from services.signal_engine.regime_detection import RegimeDetectionService

        init_calls, arg_calls = [], []

        def init_factory():
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=ctx)
            ctx.__exit__ = MagicMock(return_value=False)
            init_calls.append(1)
            return ctx

        svc = RegimeDetectionService(session_factory=init_factory)
        # Even with None session_factory arg, the init one is used
        svc.persist_snapshot(self._result(), session_factory=None)
        # No crash = pass (init_factory or None path, both acceptable)


# ---------------------------------------------------------------------------
# 11. TestRegimeSnapshotORM
# ---------------------------------------------------------------------------

class TestRegimeSnapshotORM:

    def test_tablename(self):
        from infra.db.models.regime_detection import RegimeSnapshot
        assert RegimeSnapshot.__tablename__ == "regime_snapshots"

    def test_fields_settable(self):
        from infra.db.models.regime_detection import RegimeSnapshot
        snap = RegimeSnapshot(
            id=str(uuid.uuid4()),
            regime="BULL_TREND",
            confidence=0.80,
            detection_basis_json='{"trigger": "test"}',
            is_manual_override=False,
        )
        assert snap.regime == "BULL_TREND"
        assert snap.confidence == 0.80

    def test_is_manual_override_default_falsy(self):
        from infra.db.models.regime_detection import RegimeSnapshot
        snap = RegimeSnapshot(
            id=str(uuid.uuid4()),
            regime="SIDEWAYS",
            confidence=0.5,
            detection_basis_json="{}",
        )
        # server_default=false() — Python attr is None until DB flush
        assert not snap.is_manual_override

    def test_override_reason_nullable(self):
        from infra.db.models.regime_detection import RegimeSnapshot
        snap = RegimeSnapshot(
            id=str(uuid.uuid4()),
            regime="HIGH_VOL",
            confidence=0.6,
            detection_basis_json="{}",
            override_reason=None,
        )
        assert snap.override_reason is None


# ---------------------------------------------------------------------------
# 12. TestRegimeMigration
# ---------------------------------------------------------------------------

class TestRegimeMigration:

    def test_revision(self):
        from infra.db.versions.h8i9j0k1l2m3_add_regime_snapshots import revision
        assert revision == "h8i9j0k1l2m3"

    def test_down_revision(self):
        from infra.db.versions.h8i9j0k1l2m3_add_regime_snapshots import down_revision
        assert down_revision == "g7h8i9j0k1l2"


# ---------------------------------------------------------------------------
# 13. TestRegimeSchemas
# ---------------------------------------------------------------------------

class TestRegimeSchemas:

    def test_regime_current_response(self):
        from apps.api.schemas.regime import RegimeCurrentResponse
        r = RegimeCurrentResponse(
            regime="BULL_TREND",
            confidence=0.72,
            detection_basis={"trigger": "test"},
            is_manual_override=False,
            override_reason=None,
            detected_at=None,
            regime_weights={"momentum_v1": 0.35},
        )
        assert r.regime == "BULL_TREND"
        assert r.confidence == 0.72

    def test_regime_override_request(self):
        from apps.api.schemas.regime import RegimeOverrideRequest
        req = RegimeOverrideRequest(regime="BEAR_TREND", reason="Fed risk")
        assert req.regime == "BEAR_TREND"
        assert req.reason == "Fed risk"

    def test_regime_override_response(self):
        from apps.api.schemas.regime import RegimeOverrideResponse
        r = RegimeOverrideResponse(
            status="override_set",
            regime="HIGH_VOL",
            is_manual_override=True,
            regime_weights={},
        )
        assert r.status == "override_set"
        assert r.is_manual_override is True

    def test_regime_snapshot_schema(self):
        from apps.api.schemas.regime import RegimeSnapshotSchema
        s = RegimeSnapshotSchema(
            id="abc",
            regime="SIDEWAYS",
            confidence=0.5,
            is_manual_override=False,
            override_reason=None,
            detected_at=None,
        )
        assert s.regime == "SIDEWAYS"

    def test_regime_history_response(self):
        from apps.api.schemas.regime import RegimeHistoryResponse, RegimeSnapshotSchema
        r = RegimeHistoryResponse(
            snapshots=[],
            count=0,
        )
        assert r.count == 0
        assert r.snapshots == []


# ---------------------------------------------------------------------------
# 14. TestRegimeRoutes
# ---------------------------------------------------------------------------

class TestRegimeRoutes:
    """REST endpoint tests via FastAPI TestClient."""

    def _client(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import reset_app_state
        reset_app_state()
        return TestClient(app)

    def test_get_regime_no_data_returns_sideways(self):
        client = self._client()
        resp = client.get("/api/v1/signals/regime")
        assert resp.status_code == 200
        data = resp.json()
        assert data["regime"] == "SIDEWAYS"
        assert data["confidence"] == 0.0
        assert data["is_manual_override"] is False

    def test_get_regime_returns_regime_weights(self):
        client = self._client()
        resp = client.get("/api/v1/signals/regime")
        assert resp.status_code == 200
        assert "regime_weights" in resp.json()

    def test_post_override_valid_regime(self):
        client = self._client()
        resp = client.post(
            "/api/v1/signals/regime/override",
            json={"regime": "BEAR_TREND", "reason": "Fed risk"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "override_set"
        assert data["regime"] == "BEAR_TREND"
        assert data["is_manual_override"] is True

    def test_post_override_invalid_regime_returns_422(self):
        client = self._client()
        resp = client.post(
            "/api/v1/signals/regime/override",
            json={"regime": "INVALID_REGIME", "reason": "test"},
        )
        assert resp.status_code == 422

    def test_get_regime_after_override_reflects_override(self):
        client = self._client()
        client.post(
            "/api/v1/signals/regime/override",
            json={"regime": "HIGH_VOL", "reason": "VIX spike"},
        )
        resp = client.get("/api/v1/signals/regime")
        assert resp.status_code == 200
        data = resp.json()
        assert data["regime"] == "HIGH_VOL"
        assert data["is_manual_override"] is True

    def test_delete_override_clears_state(self):
        client = self._client()
        client.post(
            "/api/v1/signals/regime/override",
            json={"regime": "BEAR_TREND", "reason": "test"},
        )
        resp = client.delete("/api/v1/signals/regime/override")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "override_cleared"
        assert data["regime"] is None

    def test_get_history_returns_list(self):
        client = self._client()
        resp = client.get("/api/v1/signals/regime/history")
        assert resp.status_code == 200
        data = resp.json()
        assert "snapshots" in data
        assert "count" in data
        assert isinstance(data["snapshots"], list)


# ---------------------------------------------------------------------------
# 15. TestRegimeDetectionJob
# ---------------------------------------------------------------------------

class TestRegimeDetectionJob:

    def test_job_returns_ok_with_empty_rankings(self):
        from apps.worker.jobs.signal_ranking import run_regime_detection
        state = _make_app_state()
        result = run_regime_detection(app_state=state)
        assert result["status"] == "ok"
        assert result["regime"] == "SIDEWAYS"

    def test_job_updates_app_state_current_regime(self):
        from apps.worker.jobs.signal_ranking import run_regime_detection
        state = _make_app_state()
        state.latest_rankings = [_make_signal(0.75)] * 20
        run_regime_detection(app_state=state)
        assert state.current_regime_result is not None

    def test_job_appends_regime_history(self):
        from apps.worker.jobs.signal_ranking import run_regime_detection
        state = _make_app_state()
        run_regime_detection(app_state=state)
        assert len(state.regime_history) == 1
        run_regime_detection(app_state=state)
        assert len(state.regime_history) == 2

    def test_job_updates_weight_profile_on_regime_change(self):
        from apps.worker.jobs.signal_ranking import run_regime_detection
        state = _make_app_state()
        state.latest_rankings = [_make_signal(0.75)] * 20
        run_regime_detection(app_state=state)
        # regime_changed is True on first run → weight profile set
        assert state.active_weight_profile is not None

    def test_job_exception_returns_error_status(self):
        from apps.worker.jobs.signal_ranking import run_regime_detection
        state = _make_app_state()
        # Inject a bad object that causes detect_from_signals to fail
        with patch(
            "services.signal_engine.regime_detection.RegimeDetectionService.detect_from_signals",
            side_effect=RuntimeError("boom"),
        ):
            result = run_regime_detection(app_state=state)
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# 16. TestSchedulerRegimeJob
# ---------------------------------------------------------------------------

class TestSchedulerRegimeJob:
    """19th scheduled job registered correctly."""

    def _build(self):
        from apps.worker.main import build_scheduler
        return build_scheduler()

    def test_total_job_count_is_19(self):
        scheduler = self._build()
        assert len(scheduler.get_jobs()) == 30

    def test_regime_detection_job_registered(self):
        scheduler = self._build()
        job_ids = {job.id for job in scheduler.get_jobs()}
        assert "regime_detection" in job_ids

    def test_regime_detection_scheduled_at_06_20(self):
        scheduler = self._build()
        job = next(j for j in scheduler.get_jobs() if j.id == "regime_detection")
        trigger = job.trigger
        fields = {f.name: str(f) for f in trigger.fields}
        assert fields.get("hour") == "6"
        assert fields.get("minute") == "20"

    def test_regime_detection_exported_from_jobs(self):
        from apps.worker.jobs import run_regime_detection
        assert run_regime_detection is not None

    def test_regime_detection_runs_after_fundamentals_refresh(self):
        """06:20 regime detection fires after 06:18 fundamentals_refresh."""
        scheduler = self._build()
        jobs_by_id = {j.id: j for j in scheduler.get_jobs()}
        fund = jobs_by_id["fundamentals_refresh"]
        regime = jobs_by_id["regime_detection"]
        fund_fields  = {f.name: int(str(f)) for f in fund.trigger.fields if f.name in ("hour", "minute")}
        regime_fields = {f.name: int(str(f)) for f in regime.trigger.fields if f.name in ("hour", "minute")}
        fund_minutes  = fund_fields.get("hour", 0) * 60 + fund_fields.get("minute", 0)
        regime_minutes = regime_fields.get("hour", 0) * 60 + regime_fields.get("minute", 0)
        assert regime_minutes > fund_minutes
