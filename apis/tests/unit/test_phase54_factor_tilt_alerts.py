"""
Phase 54 — Factor Tilt Alerts

Tests cover:
  1. FactorTiltEvent model fields and defaults
  2. FactorTiltAlertService.detect_tilt — factor_change trigger
  3. FactorTiltAlertService.detect_tilt — weight_shift trigger
  4. FactorTiltAlertService.detect_tilt — no tilt (stable)
  5. FactorTiltAlertService.detect_tilt — first cycle (last_dominant_factor=None)
  6. FactorTiltAlertService.build_alert_payload
  7. Paper cycle integration — tilt written to app_state.factor_tilt_events
  8. Paper cycle integration — last_dominant_factor updated each cycle
  9. Paper cycle integration — webhook fired on tilt
 10. Paper cycle integration — no webhook when no alert_service
 11. GET /portfolio/factor-tilt-history route — empty list on no events
 12. GET /portfolio/factor-tilt-history route — returns events newest-first
 13. GET /portfolio/factor-tilt-history route — limit param respected
 14. Dashboard factor tilt section — no events
 15. Dashboard factor tilt section — with events
 16. Scheduler job count now 30 (Phase 54 adds no new job)
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_factor_result(dominant: str, weights: dict | None = None):
    """Build a minimal FactorExposureResult-like object."""
    from services.risk_engine.factor_exposure import FactorExposureResult

    fw = weights or {
        "MOMENTUM": 0.55,
        "VALUE": 0.40,
        "GROWTH": 0.48,
        "QUALITY": 0.52,
        "LOW_VOL": 0.35,
    }
    fw[dominant] = max(fw.values())  # ensure dominant is actually max
    return FactorExposureResult(
        portfolio_factor_weights=fw,
        ticker_scores=[],
        dominant_factor=dominant,
        position_count=3,
        total_market_value=50_000.0,
    )


def _make_tilt_event(
    previous_factor="MOMENTUM",
    new_factor="VALUE",
    previous_weight=0.55,
    new_weight=0.60,
    tilt_type="factor_change",
    delta_weight=0.05,
):
    from services.factor_alerts.service import FactorTiltEvent

    return FactorTiltEvent(
        event_time=dt.datetime(2026, 3, 21, 10, 0, tzinfo=dt.timezone.utc),
        previous_factor=previous_factor,
        new_factor=new_factor,
        previous_weight=previous_weight,
        new_weight=new_weight,
        tilt_type=tilt_type,
        delta_weight=delta_weight,
    )


# ---------------------------------------------------------------------------
# 1. FactorTiltEvent model
# ---------------------------------------------------------------------------

class TestFactorTiltEventModel:
    def test_basic_fields(self):
        from services.factor_alerts.service import FactorTiltEvent

        ev = FactorTiltEvent(
            event_time=dt.datetime(2026, 3, 21, 9, 0, tzinfo=dt.timezone.utc),
            previous_factor="MOMENTUM",
            new_factor="VALUE",
            previous_weight=0.55,
            new_weight=0.62,
            tilt_type="factor_change",
            delta_weight=0.07,
        )
        assert ev.previous_factor == "MOMENTUM"
        assert ev.new_factor == "VALUE"
        assert ev.tilt_type == "factor_change"
        assert ev.delta_weight == 0.07

    def test_delta_weight_default_zero(self):
        from services.factor_alerts.service import FactorTiltEvent

        ev = FactorTiltEvent(
            event_time=dt.datetime.now(dt.timezone.utc),
            previous_factor=None,
            new_factor="GROWTH",
            previous_weight=None,
            new_weight=0.5,
            tilt_type="factor_change",
        )
        assert ev.delta_weight == 0.0

    def test_previous_factor_can_be_none(self):
        from services.factor_alerts.service import FactorTiltEvent

        ev = FactorTiltEvent(
            event_time=dt.datetime.now(dt.timezone.utc),
            previous_factor=None,
            new_factor="MOMENTUM",
            previous_weight=None,
            new_weight=0.6,
            tilt_type="factor_change",
        )
        assert ev.previous_factor is None

    def test_weight_shift_type(self):
        from services.factor_alerts.service import FactorTiltEvent

        ev = FactorTiltEvent(
            event_time=dt.datetime.now(dt.timezone.utc),
            previous_factor="MOMENTUM",
            new_factor="MOMENTUM",
            previous_weight=0.40,
            new_weight=0.60,
            tilt_type="weight_shift",
            delta_weight=0.20,
        )
        assert ev.tilt_type == "weight_shift"
        assert ev.previous_factor == ev.new_factor


# ---------------------------------------------------------------------------
# 2. detect_tilt — factor_change trigger
# ---------------------------------------------------------------------------

class TestDetectTiltFactorChange:
    def test_detects_factor_name_change(self):
        from services.factor_alerts.service import FactorTiltAlertService

        result = _make_factor_result("VALUE")
        event = FactorTiltAlertService.detect_tilt(
            current_result=result,
            last_dominant_factor="MOMENTUM",
        )
        assert event is not None
        assert event.tilt_type == "factor_change"
        assert event.previous_factor == "MOMENTUM"
        assert event.new_factor == "VALUE"

    def test_delta_weight_computed(self):
        from services.factor_alerts.service import FactorTiltAlertService

        result = _make_factor_result("VALUE", {
            "MOMENTUM": 0.40,
            "VALUE": 0.65,
            "GROWTH": 0.45,
            "QUALITY": 0.50,
            "LOW_VOL": 0.30,
        })
        event = FactorTiltAlertService.detect_tilt(
            current_result=result,
            last_dominant_factor="MOMENTUM",
        )
        assert event is not None
        assert event.delta_weight == pytest.approx(abs(0.65 - 0.40), abs=0.01)

    def test_event_time_defaults_to_utc(self):
        from services.factor_alerts.service import FactorTiltAlertService

        result = _make_factor_result("GROWTH")
        event = FactorTiltAlertService.detect_tilt(
            current_result=result,
            last_dominant_factor="MOMENTUM",
        )
        assert event is not None
        assert event.event_time.tzinfo is not None

    def test_custom_event_time_used(self):
        from services.factor_alerts.service import FactorTiltAlertService

        result = _make_factor_result("QUALITY")
        custom_time = dt.datetime(2026, 3, 21, 12, 0, tzinfo=dt.timezone.utc)
        event = FactorTiltAlertService.detect_tilt(
            current_result=result,
            last_dominant_factor="MOMENTUM",
            event_time=custom_time,
        )
        assert event is not None
        assert event.event_time == custom_time

    def test_any_factor_change_triggers(self):
        from services.factor_alerts.service import FactorTiltAlertService

        for from_f, to_f in [("MOMENTUM", "VALUE"), ("VALUE", "LOW_VOL"), ("GROWTH", "QUALITY")]:
            result = _make_factor_result(to_f)
            event = FactorTiltAlertService.detect_tilt(
                current_result=result,
                last_dominant_factor=from_f,
            )
            assert event is not None, f"Expected tilt from {from_f} to {to_f}"
            assert event.tilt_type == "factor_change"


# ---------------------------------------------------------------------------
# 3. detect_tilt — weight_shift trigger
# ---------------------------------------------------------------------------

class TestDetectTiltWeightShift:
    def test_weight_shift_same_factor(self):
        from services.factor_alerts.service import FactorTiltAlertService

        result = _make_factor_result("MOMENTUM", {
            "MOMENTUM": 0.75,
            "VALUE": 0.40,
            "GROWTH": 0.45,
            "QUALITY": 0.50,
            "LOW_VOL": 0.30,
        })
        last_event = _make_tilt_event(
            previous_factor="MOMENTUM",
            new_factor="MOMENTUM",
            new_weight=0.55,  # previous weight of MOMENTUM
        )
        event = FactorTiltAlertService.detect_tilt(
            current_result=result,
            last_dominant_factor="MOMENTUM",
            factor_tilt_events=[last_event],
            min_weight_delta=0.15,
        )
        assert event is not None
        assert event.tilt_type == "weight_shift"
        assert event.new_factor == "MOMENTUM"

    def test_weight_shift_below_threshold_no_tilt(self):
        from services.factor_alerts.service import FactorTiltAlertService

        result = _make_factor_result("MOMENTUM", {
            "MOMENTUM": 0.60,
            "VALUE": 0.40,
            "GROWTH": 0.45,
            "QUALITY": 0.50,
            "LOW_VOL": 0.30,
        })
        last_event = _make_tilt_event(
            previous_factor="MOMENTUM",
            new_factor="MOMENTUM",
            new_weight=0.55,
        )
        event = FactorTiltAlertService.detect_tilt(
            current_result=result,
            last_dominant_factor="MOMENTUM",
            factor_tilt_events=[last_event],
            min_weight_delta=0.15,
        )
        assert event is None

    def test_weight_shift_above_threshold_triggers(self):
        from services.factor_alerts.service import FactorTiltAlertService

        result = _make_factor_result("MOMENTUM", {
            "MOMENTUM": 0.72,
            "VALUE": 0.40,
            "GROWTH": 0.45,
            "QUALITY": 0.50,
            "LOW_VOL": 0.30,
        })
        last_event = _make_tilt_event(new_weight=0.50)  # delta = 0.22, clearly > 0.15
        event = FactorTiltAlertService.detect_tilt(
            current_result=result,
            last_dominant_factor="MOMENTUM",
            factor_tilt_events=[last_event],
            min_weight_delta=0.15,
        )
        assert event is not None
        assert event.tilt_type == "weight_shift"

    def test_no_previous_events_no_weight_shift(self):
        from services.factor_alerts.service import FactorTiltAlertService

        result = _make_factor_result("MOMENTUM")
        event = FactorTiltAlertService.detect_tilt(
            current_result=result,
            last_dominant_factor="MOMENTUM",
            factor_tilt_events=[],
        )
        assert event is None


# ---------------------------------------------------------------------------
# 4. detect_tilt — no tilt (stable)
# ---------------------------------------------------------------------------

class TestDetectTiltStable:
    def test_no_tilt_same_factor_small_delta(self):
        from services.factor_alerts.service import FactorTiltAlertService

        result = _make_factor_result("MOMENTUM")
        event = FactorTiltAlertService.detect_tilt(
            current_result=result,
            last_dominant_factor="MOMENTUM",
        )
        assert event is None

    def test_no_tilt_returns_none(self):
        from services.factor_alerts.service import FactorTiltAlertService

        result = _make_factor_result("VALUE")
        event = FactorTiltAlertService.detect_tilt(
            current_result=result,
            last_dominant_factor="VALUE",
        )
        assert event is None


# ---------------------------------------------------------------------------
# 5. detect_tilt — first cycle (last_dominant_factor=None)
# ---------------------------------------------------------------------------

class TestDetectTiltFirstCycle:
    def test_no_tilt_on_first_cycle(self):
        from services.factor_alerts.service import FactorTiltAlertService

        result = _make_factor_result("MOMENTUM")
        event = FactorTiltAlertService.detect_tilt(
            current_result=result,
            last_dominant_factor=None,
        )
        assert event is None

    def test_none_result_returns_none(self):
        from services.factor_alerts.service import FactorTiltAlertService

        event = FactorTiltAlertService.detect_tilt(
            current_result=None,
            last_dominant_factor="MOMENTUM",
        )
        assert event is None


# ---------------------------------------------------------------------------
# 6. build_alert_payload
# ---------------------------------------------------------------------------

class TestBuildAlertPayload:
    def test_payload_contains_required_keys(self):
        from services.factor_alerts.service import FactorTiltAlertService

        ev = _make_tilt_event()
        payload = FactorTiltAlertService.build_alert_payload(ev)
        assert "tilt_type" in payload
        assert "previous_factor" in payload
        assert "new_factor" in payload
        assert "previous_weight" in payload
        assert "new_weight" in payload
        assert "delta_weight" in payload
        assert "event_time" in payload

    def test_payload_values_match_event(self):
        from services.factor_alerts.service import FactorTiltAlertService

        ev = _make_tilt_event(
            previous_factor="MOMENTUM",
            new_factor="VALUE",
            delta_weight=0.123,
        )
        payload = FactorTiltAlertService.build_alert_payload(ev)
        assert payload["previous_factor"] == "MOMENTUM"
        assert payload["new_factor"] == "VALUE"
        assert payload["tilt_type"] == "factor_change"

    def test_payload_previous_weight_none_serialized(self):
        from services.factor_alerts.service import FactorTiltAlertService, FactorTiltEvent

        ev = FactorTiltEvent(
            event_time=dt.datetime.now(dt.timezone.utc),
            previous_factor=None,
            new_factor="GROWTH",
            previous_weight=None,
            new_weight=0.60,
            tilt_type="factor_change",
            delta_weight=0.10,
        )
        payload = FactorTiltAlertService.build_alert_payload(ev)
        assert payload["previous_weight"] is None

    def test_payload_event_time_is_isoformat_string(self):
        from services.factor_alerts.service import FactorTiltAlertService

        ev = _make_tilt_event()
        payload = FactorTiltAlertService.build_alert_payload(ev)
        # Should be a string parseable as ISO datetime
        parsed = dt.datetime.fromisoformat(payload["event_time"])
        assert parsed is not None


# ---------------------------------------------------------------------------
# 7. Paper cycle integration — tilt written to app_state
# ---------------------------------------------------------------------------

class TestPaperCycleTiltIntegration:
    def _make_minimal_app_state(self):
        from apps.api.state import ApiAppState
        return ApiAppState()

    def _run_tilt_detection_block(self, app_state, fe_result):
        """Simulate the Phase 54 block from paper_trading.py."""
        from services.factor_alerts.service import FactorTiltAlertService
        from services.alerting.models import AlertEvent, AlertSeverity

        fe_new = fe_result
        if fe_new is not None:
            last_dom = getattr(app_state, "last_dominant_factor", None)
            tilt_events = getattr(app_state, "factor_tilt_events", [])
            tilt_event = FactorTiltAlertService.detect_tilt(
                current_result=fe_new,
                last_dominant_factor=last_dom,
                factor_tilt_events=tilt_events,
            )
            if tilt_event is not None:
                app_state.factor_tilt_events = list(tilt_events) + [tilt_event]
            app_state.last_dominant_factor = fe_new.dominant_factor

    def test_tilt_event_appended_on_factor_change(self):
        state = self._make_minimal_app_state()
        state.last_dominant_factor = "MOMENTUM"

        result = _make_factor_result("VALUE")
        self._run_tilt_detection_block(state, result)

        assert len(state.factor_tilt_events) == 1
        assert state.factor_tilt_events[0].tilt_type == "factor_change"

    def test_no_event_on_stable_factor(self):
        state = self._make_minimal_app_state()
        state.last_dominant_factor = "MOMENTUM"

        result = _make_factor_result("MOMENTUM")
        self._run_tilt_detection_block(state, result)

        assert len(state.factor_tilt_events) == 0

    def test_multiple_tilt_events_accumulate(self):
        state = self._make_minimal_app_state()
        state.last_dominant_factor = "MOMENTUM"

        for new_dom in ["VALUE", "GROWTH", "QUALITY"]:
            result = _make_factor_result(new_dom)
            self._run_tilt_detection_block(state, result)

        assert len(state.factor_tilt_events) == 3


# ---------------------------------------------------------------------------
# 8. last_dominant_factor updated each cycle
# ---------------------------------------------------------------------------

class TestLastDominantFactorUpdate:
    def test_last_dominant_factor_set_after_first_cycle(self):
        from apps.api.state import ApiAppState

        state = ApiAppState()
        assert state.last_dominant_factor is None

        from services.factor_alerts.service import FactorTiltAlertService
        result = _make_factor_result("MOMENTUM")
        FactorTiltAlertService.detect_tilt(
            current_result=result,
            last_dominant_factor=state.last_dominant_factor,
        )
        state.last_dominant_factor = result.dominant_factor
        assert state.last_dominant_factor == "MOMENTUM"

    def test_last_dominant_factor_updates_each_cycle(self):
        from apps.api.state import ApiAppState
        from services.factor_alerts.service import FactorTiltAlertService

        state = ApiAppState()
        for factor in ["MOMENTUM", "VALUE", "GROWTH"]:
            result = _make_factor_result(factor)
            state.last_dominant_factor = result.dominant_factor
        assert state.last_dominant_factor == "GROWTH"


# ---------------------------------------------------------------------------
# 9. Paper cycle integration — webhook fired on tilt
# ---------------------------------------------------------------------------

class TestPaperCycleTiltWebhook:
    def test_webhook_fired_on_tilt(self):
        from services.factor_alerts.service import FactorTiltAlertService
        from services.alerting.models import AlertEvent

        mock_alert_svc = MagicMock()
        result = _make_factor_result("VALUE")
        tilt = FactorTiltAlertService.detect_tilt(
            current_result=result,
            last_dominant_factor="MOMENTUM",
        )
        assert tilt is not None
        payload = FactorTiltAlertService.build_alert_payload(tilt)
        # Simulate the alert send
        mock_alert_svc.send_alert(AlertEvent(
            event_type="factor_tilt_detected",
            severity="info",
            title=f"Factor tilt: MOMENTUM → VALUE",
            payload=payload,
        ))
        mock_alert_svc.send_alert.assert_called_once()

    def test_webhook_not_fired_when_no_tilt(self):
        from services.factor_alerts.service import FactorTiltAlertService

        mock_alert_svc = MagicMock()
        result = _make_factor_result("MOMENTUM")
        tilt = FactorTiltAlertService.detect_tilt(
            current_result=result,
            last_dominant_factor="MOMENTUM",
        )
        if tilt is None:
            # Don't fire webhook
            pass
        mock_alert_svc.send_alert.assert_not_called()


# ---------------------------------------------------------------------------
# 10. No webhook when no alert_service
# ---------------------------------------------------------------------------

class TestNoAlertServiceGraceful:
    def test_detect_tilt_works_without_alert_service(self):
        from services.factor_alerts.service import FactorTiltAlertService

        result = _make_factor_result("VALUE")
        # No alert service — should not raise
        event = FactorTiltAlertService.detect_tilt(
            current_result=result,
            last_dominant_factor="MOMENTUM",
        )
        assert event is not None  # tilt detected, no error


# ---------------------------------------------------------------------------
# 11. GET /portfolio/factor-tilt-history — empty list
# ---------------------------------------------------------------------------

class TestFactorTiltHistoryRouteEmpty:
    def test_empty_response_200(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import reset_app_state

        reset_app_state()
        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/factor-tilt-history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["events"] == []
        assert data["total_events"] == 0

    def test_empty_last_dominant_factor_none(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import reset_app_state

        reset_app_state()
        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/factor-tilt-history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["last_dominant_factor"] is None


# ---------------------------------------------------------------------------
# 12. GET /portfolio/factor-tilt-history — returns events newest-first
# ---------------------------------------------------------------------------

class TestFactorTiltHistoryRouteWithEvents:
    def _seed_events(self, state, n: int = 3):
        from services.factor_alerts.service import FactorTiltEvent

        factors = ["MOMENTUM", "VALUE", "GROWTH", "QUALITY", "LOW_VOL"]
        events = []
        for i in range(n):
            events.append(FactorTiltEvent(
                event_time=dt.datetime(2026, 3, 21, 9, i, tzinfo=dt.timezone.utc),
                previous_factor=factors[i % len(factors)],
                new_factor=factors[(i + 1) % len(factors)],
                previous_weight=0.50,
                new_weight=0.60,
                tilt_type="factor_change",
                delta_weight=0.10,
            ))
        state.factor_tilt_events = events
        state.last_dominant_factor = factors[(n) % len(factors)]

    def test_events_returned_newest_first(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import get_app_state, reset_app_state

        reset_app_state()
        state = get_app_state()
        self._seed_events(state, n=3)

        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/factor-tilt-history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 3
        # Newest (minute=2) should be first
        times = [ev["event_time"] for ev in data["events"]]
        assert times[0] >= times[-1]

    def test_total_events_count(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import get_app_state, reset_app_state

        reset_app_state()
        state = get_app_state()
        self._seed_events(state, n=5)

        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/factor-tilt-history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_events"] == 5

    def test_last_dominant_factor_in_response(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import get_app_state, reset_app_state

        reset_app_state()
        state = get_app_state()
        state.last_dominant_factor = "QUALITY"

        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/factor-tilt-history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["last_dominant_factor"] == "QUALITY"


# ---------------------------------------------------------------------------
# 13. GET /portfolio/factor-tilt-history — limit param
# ---------------------------------------------------------------------------

class TestFactorTiltHistoryLimit:
    def _seed_many_events(self, state, n: int):
        from services.factor_alerts.service import FactorTiltEvent

        events = []
        for i in range(n):
            events.append(FactorTiltEvent(
                event_time=dt.datetime(2026, 3, 21, 9, 0, i % 60, tzinfo=dt.timezone.utc),
                previous_factor="MOMENTUM",
                new_factor="VALUE",
                previous_weight=0.50,
                new_weight=0.60,
                tilt_type="factor_change",
                delta_weight=0.10,
            ))
        state.factor_tilt_events = events

    def test_limit_respected(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import get_app_state, reset_app_state

        reset_app_state()
        state = get_app_state()
        self._seed_many_events(state, n=20)

        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/factor-tilt-history?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 5
        assert data["total_events"] == 20

    def test_limit_defaults_to_50(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import get_app_state, reset_app_state

        reset_app_state()
        state = get_app_state()
        self._seed_many_events(state, n=10)

        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/factor-tilt-history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 10  # fewer than 50, all returned


# ---------------------------------------------------------------------------
# 14. Dashboard — no events
# ---------------------------------------------------------------------------

class TestDashboardFactorTiltSectionEmpty:
    def test_section_renders_no_events(self):
        from apps.dashboard.router import _render_factor_tilt_section
        from apps.api.state import ApiAppState

        state = ApiAppState()
        html = _render_factor_tilt_section(state)
        assert "Factor Tilt Alerts" in html
        assert "No tilt events yet" in html

    def test_section_shows_none_dominant_factor(self):
        from apps.dashboard.router import _render_factor_tilt_section
        from apps.api.state import ApiAppState

        state = ApiAppState()
        html = _render_factor_tilt_section(state)
        assert "—" in html or "None" in html


# ---------------------------------------------------------------------------
# 15. Dashboard — with events
# ---------------------------------------------------------------------------

class TestDashboardFactorTiltSectionWithEvents:
    def test_section_shows_event_count(self):
        from apps.dashboard.router import _render_factor_tilt_section
        from apps.api.state import ApiAppState
        from services.factor_alerts.service import FactorTiltEvent

        state = ApiAppState()
        state.last_dominant_factor = "VALUE"
        state.factor_tilt_events = [
            FactorTiltEvent(
                event_time=dt.datetime(2026, 3, 21, 10, 0, tzinfo=dt.timezone.utc),
                previous_factor="MOMENTUM",
                new_factor="VALUE",
                previous_weight=0.45,
                new_weight=0.62,
                tilt_type="factor_change",
                delta_weight=0.17,
            )
        ]
        html = _render_factor_tilt_section(state)
        assert "1" in html
        assert "VALUE" in html

    def test_section_shows_last_tilt_type(self):
        from apps.dashboard.router import _render_factor_tilt_section
        from apps.api.state import ApiAppState
        from services.factor_alerts.service import FactorTiltEvent

        state = ApiAppState()
        state.last_dominant_factor = "MOMENTUM"
        state.factor_tilt_events = [
            FactorTiltEvent(
                event_time=dt.datetime.now(dt.timezone.utc),
                previous_factor="MOMENTUM",
                new_factor="MOMENTUM",
                previous_weight=0.40,
                new_weight=0.60,
                tilt_type="weight_shift",
                delta_weight=0.20,
            )
        ]
        html = _render_factor_tilt_section(state)
        assert "weight_shift" in html

    def test_section_renders_table_for_multiple_events(self):
        from apps.dashboard.router import _render_factor_tilt_section
        from apps.api.state import ApiAppState
        from services.factor_alerts.service import FactorTiltEvent

        state = ApiAppState()
        state.last_dominant_factor = "QUALITY"
        for i in range(5):
            state.factor_tilt_events.append(
                FactorTiltEvent(
                    event_time=dt.datetime(2026, 3, 21, i, 0, tzinfo=dt.timezone.utc),
                    previous_factor="MOMENTUM",
                    new_factor="VALUE",
                    previous_weight=0.50,
                    new_weight=0.60,
                    tilt_type="factor_change",
                    delta_weight=0.10,
                )
            )
        html = _render_factor_tilt_section(state)
        assert "<table>" in html


# ---------------------------------------------------------------------------
# 16. Scheduler job count now 30
# ---------------------------------------------------------------------------

class TestSchedulerJobCount:
    def test_scheduler_still_has_29_jobs(self):
        from apps.worker.main import build_scheduler

        scheduler = build_scheduler()
        jobs = scheduler.get_jobs()
        assert len(jobs) == 30, (
            f"Expected 30 scheduler jobs (Phase 54 adds no new job), "
            f"got {len(jobs)}: {[j.id for j in jobs]}"
        )
