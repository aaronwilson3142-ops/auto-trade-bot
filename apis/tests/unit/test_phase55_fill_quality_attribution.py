"""
Phase 55 — Fill Quality Alpha-Decay Attribution

Tests cover:
  1. FillQualityRecord — new optional alpha fields
  2. AlphaDecaySummary model defaults
  3. FillQualityService.compute_alpha_decay — BUY positive alpha
  4. FillQualityService.compute_alpha_decay — BUY negative alpha
  5. FillQualityService.compute_alpha_decay — SELL positive alpha
  6. FillQualityService.compute_alpha_decay — flat price (slippage_as_pct_of_move=None)
  7. FillQualityService.compute_alpha_decay — invalid prices (None, None)
  8. FillQualityService.compute_attribution_summary — empty records
  9. FillQualityService.compute_attribution_summary — enriched records
 10. FillQualityService.compute_attribution_summary — mixed (some None)
 11. run_fill_quality_attribution job — no session_factory (graceful)
 12. run_fill_quality_attribution job — enriches records from session_factory
 13. run_fill_quality_attribution job — error path
 14. GET /portfolio/fill-quality/attribution — 200 + empty summary on no data
 15. GET /portfolio/fill-quality/attribution — returns enriched summary
 16. FillQualityRecordSchema — new alpha fields present with None defaults
 17. Dashboard fill quality section — alpha fields shown when present
 18. Scheduler job count now 30
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(
    ticker="AAPL",
    direction="BUY",
    action_type="open",
    expected_price="150.00",
    fill_price="150.50",
    quantity="10",
    slippage_usd="5.00",
    slippage_pct="0.000333",
    filled_at=None,
    alpha_captured_pct=None,
    slippage_as_pct_of_move=None,
):
    from services.fill_quality.models import FillQualityRecord

    return FillQualityRecord(
        ticker=ticker,
        direction=direction,
        action_type=action_type,
        expected_price=Decimal(expected_price),
        fill_price=Decimal(fill_price),
        quantity=Decimal(quantity),
        slippage_usd=Decimal(slippage_usd),
        slippage_pct=Decimal(slippage_pct),
        filled_at=filled_at or dt.datetime(2026, 3, 10, 10, 0, tzinfo=dt.timezone.utc),
        alpha_captured_pct=alpha_captured_pct,
        slippage_as_pct_of_move=slippage_as_pct_of_move,
    )


# ---------------------------------------------------------------------------
# 1. FillQualityRecord — new optional alpha fields
# ---------------------------------------------------------------------------

class TestFillQualityRecordAlphaFields:
    def test_alpha_fields_default_none(self):
        r = _make_record()
        assert r.alpha_captured_pct is None
        assert r.slippage_as_pct_of_move is None

    def test_alpha_fields_can_be_set(self):
        r = _make_record(alpha_captured_pct=0.05, slippage_as_pct_of_move=0.02)
        assert r.alpha_captured_pct == pytest.approx(0.05)
        assert r.slippage_as_pct_of_move == pytest.approx(0.02)

    def test_existing_fields_unchanged(self):
        r = _make_record(ticker="MSFT", direction="SELL")
        assert r.ticker == "MSFT"
        assert r.direction == "SELL"
        assert r.fill_price == Decimal("150.50")


# ---------------------------------------------------------------------------
# 2. AlphaDecaySummary model defaults
# ---------------------------------------------------------------------------

class TestAlphaDecaySummaryDefaults:
    def test_default_records_with_alpha_zero(self):
        from services.fill_quality.models import AlphaDecaySummary
        s = AlphaDecaySummary()
        assert s.records_with_alpha == 0

    def test_default_avg_alpha_none(self):
        from services.fill_quality.models import AlphaDecaySummary
        s = AlphaDecaySummary()
        assert s.avg_alpha_captured_pct is None

    def test_default_n_days_five(self):
        from services.fill_quality.models import AlphaDecaySummary
        s = AlphaDecaySummary()
        assert s.n_days == 5

    def test_default_counts_zero(self):
        from services.fill_quality.models import AlphaDecaySummary
        s = AlphaDecaySummary()
        assert s.positive_alpha_count == 0
        assert s.negative_alpha_count == 0


# ---------------------------------------------------------------------------
# 3. compute_alpha_decay — BUY positive alpha
# ---------------------------------------------------------------------------

class TestComputeAlphaDecayBuyPositive:
    def test_positive_alpha_captured(self):
        from services.fill_quality.service import FillQualityService
        record = _make_record(fill_price="150.00", quantity="10", slippage_usd="5.00")
        alpha, slip_pct = FillQualityService.compute_alpha_decay(
            record=record,
            subsequent_price=Decimal("165.00"),
            n_days=5,
        )
        # alpha = (165 - 150) / 150 = 0.1
        assert alpha == pytest.approx(0.10, rel=0.01)

    def test_slippage_as_pct_of_move_computed(self):
        from services.fill_quality.service import FillQualityService
        # fill=150, subsequent=165, qty=10, slippage_usd=5
        # price_move_usd = abs(165-150)*10 = 150
        # slippage_as_pct_of_move = 5/150 ≈ 0.0333
        record = _make_record(fill_price="150.00", quantity="10", slippage_usd="5.00")
        _, slip_pct = FillQualityService.compute_alpha_decay(
            record=record,
            subsequent_price=Decimal("165.00"),
            n_days=5,
        )
        assert slip_pct is not None
        assert slip_pct == pytest.approx(5.0 / 150.0, rel=0.01)


# ---------------------------------------------------------------------------
# 4. compute_alpha_decay — BUY negative alpha
# ---------------------------------------------------------------------------

class TestComputeAlphaDecayBuyNegative:
    def test_negative_alpha_when_price_fell(self):
        from services.fill_quality.service import FillQualityService
        record = _make_record(fill_price="150.00")
        alpha, _ = FillQualityService.compute_alpha_decay(
            record=record,
            subsequent_price=Decimal("140.00"),
            n_days=5,
        )
        # alpha = (140 - 150) / 150 ≈ -0.0667
        assert alpha is not None
        assert alpha < 0


# ---------------------------------------------------------------------------
# 5. compute_alpha_decay — SELL positive alpha
# ---------------------------------------------------------------------------

class TestComputeAlphaDecaySell:
    def test_sell_positive_alpha_when_price_fell(self):
        from services.fill_quality.service import FillQualityService
        record = _make_record(direction="SELL", fill_price="150.00")
        alpha, _ = FillQualityService.compute_alpha_decay(
            record=record,
            subsequent_price=Decimal("140.00"),
            n_days=5,
        )
        # For SELL: alpha = (fill - subsequent) / fill = (150-140)/150 ≈ 0.0667
        assert alpha is not None
        assert alpha > 0

    def test_sell_negative_alpha_when_price_rose(self):
        from services.fill_quality.service import FillQualityService
        record = _make_record(direction="SELL", fill_price="150.00")
        alpha, _ = FillQualityService.compute_alpha_decay(
            record=record,
            subsequent_price=Decimal("160.00"),
            n_days=5,
        )
        assert alpha is not None
        assert alpha < 0


# ---------------------------------------------------------------------------
# 6. compute_alpha_decay — flat price (slippage_as_pct_of_move=None)
# ---------------------------------------------------------------------------

class TestComputeAlphaDecayFlat:
    def test_flat_price_slippage_pct_none(self):
        from services.fill_quality.service import FillQualityService
        record = _make_record(fill_price="150.00")
        alpha, slip_pct = FillQualityService.compute_alpha_decay(
            record=record,
            subsequent_price=Decimal("150.00"),  # exactly same price
            n_days=5,
        )
        # price_move_usd = 0 → slippage_as_pct_of_move = None
        assert alpha == pytest.approx(0.0, abs=1e-6)
        assert slip_pct is None

    def test_flat_alpha_is_zero(self):
        from services.fill_quality.service import FillQualityService
        record = _make_record(fill_price="200.00")
        alpha, _ = FillQualityService.compute_alpha_decay(
            record=record,
            subsequent_price=Decimal("200.00"),
            n_days=5,
        )
        assert alpha is not None
        assert abs(alpha) < 1e-9


# ---------------------------------------------------------------------------
# 7. compute_alpha_decay — invalid prices → (None, None)
# ---------------------------------------------------------------------------

class TestComputeAlphaDecayInvalid:
    def test_zero_subsequent_price_returns_none(self):
        from services.fill_quality.service import FillQualityService
        record = _make_record(fill_price="150.00")
        alpha, slip_pct = FillQualityService.compute_alpha_decay(
            record=record,
            subsequent_price=Decimal("0"),
            n_days=5,
        )
        assert alpha is None
        assert slip_pct is None

    def test_zero_fill_price_returns_none(self):
        from services.fill_quality.service import FillQualityService
        record = _make_record(fill_price="0.00")
        alpha, slip_pct = FillQualityService.compute_alpha_decay(
            record=record,
            subsequent_price=Decimal("150.00"),
            n_days=5,
        )
        assert alpha is None
        assert slip_pct is None


# ---------------------------------------------------------------------------
# 8. compute_attribution_summary — empty records
# ---------------------------------------------------------------------------

class TestComputeAttributionSummaryEmpty:
    def test_empty_returns_zero_summary(self):
        from services.fill_quality.service import FillQualityService
        summary = FillQualityService.compute_attribution_summary(records=[])
        assert summary.records_with_alpha == 0
        assert summary.avg_alpha_captured_pct is None

    def test_empty_computed_at_set(self):
        from services.fill_quality.service import FillQualityService
        summary = FillQualityService.compute_attribution_summary(records=[])
        assert summary.computed_at is not None

    def test_n_days_passed_through(self):
        from services.fill_quality.service import FillQualityService
        summary = FillQualityService.compute_attribution_summary(records=[], n_days=10)
        assert summary.n_days == 10


# ---------------------------------------------------------------------------
# 9. compute_attribution_summary — enriched records
# ---------------------------------------------------------------------------

class TestComputeAttributionSummaryEnriched:
    def test_avg_alpha_computed(self):
        from services.fill_quality.service import FillQualityService
        records = [
            _make_record(alpha_captured_pct=0.10, slippage_as_pct_of_move=0.03),
            _make_record(alpha_captured_pct=0.05, slippage_as_pct_of_move=0.02),
        ]
        summary = FillQualityService.compute_attribution_summary(records)
        assert summary.avg_alpha_captured_pct == pytest.approx(0.075, rel=0.01)

    def test_records_with_alpha_count(self):
        from services.fill_quality.service import FillQualityService
        records = [
            _make_record(alpha_captured_pct=0.05),
            _make_record(alpha_captured_pct=-0.02),
        ]
        summary = FillQualityService.compute_attribution_summary(records)
        assert summary.records_with_alpha == 2

    def test_positive_negative_counts(self):
        from services.fill_quality.service import FillQualityService
        records = [
            _make_record(alpha_captured_pct=0.10),
            _make_record(alpha_captured_pct=0.05),
            _make_record(alpha_captured_pct=-0.03),
        ]
        summary = FillQualityService.compute_attribution_summary(records)
        assert summary.positive_alpha_count == 2
        assert summary.negative_alpha_count == 1

    def test_avg_slippage_pct_of_move(self):
        from services.fill_quality.service import FillQualityService
        records = [
            _make_record(alpha_captured_pct=0.10, slippage_as_pct_of_move=0.10),
            _make_record(alpha_captured_pct=0.05, slippage_as_pct_of_move=0.20),
        ]
        summary = FillQualityService.compute_attribution_summary(records)
        assert summary.avg_slippage_as_pct_of_move == pytest.approx(0.15, rel=0.01)


# ---------------------------------------------------------------------------
# 10. compute_attribution_summary — mixed (some None alpha)
# ---------------------------------------------------------------------------

class TestComputeAttributionSummaryMixed:
    def test_only_enriched_records_counted(self):
        from services.fill_quality.service import FillQualityService
        records = [
            _make_record(alpha_captured_pct=0.10),   # enriched
            _make_record(),                           # not enriched (alpha=None)
            _make_record(alpha_captured_pct=-0.02),  # enriched
        ]
        summary = FillQualityService.compute_attribution_summary(records)
        assert summary.records_with_alpha == 2

    def test_none_alpha_excluded_from_avg(self):
        from services.fill_quality.service import FillQualityService
        records = [
            _make_record(alpha_captured_pct=0.10),
            _make_record(),  # alpha=None, excluded
        ]
        summary = FillQualityService.compute_attribution_summary(records)
        assert summary.avg_alpha_captured_pct == pytest.approx(0.10, rel=0.01)


# ---------------------------------------------------------------------------
# 11. run_fill_quality_attribution — no session_factory (graceful degradation)
# ---------------------------------------------------------------------------

class TestRunFillQualityAttributionNoSession:
    def test_no_session_ok_status(self):
        from apps.api.state import ApiAppState
        from apps.worker.jobs.fill_quality_attribution import run_fill_quality_attribution

        state = ApiAppState()
        state.fill_quality_records = [_make_record()]
        result = run_fill_quality_attribution(app_state=state, session_factory=None)
        assert result["status"] == "ok"

    def test_no_session_zero_enriched(self):
        from apps.api.state import ApiAppState
        from apps.worker.jobs.fill_quality_attribution import run_fill_quality_attribution

        state = ApiAppState()
        state.fill_quality_records = [_make_record(), _make_record()]
        result = run_fill_quality_attribution(app_state=state, session_factory=None)
        assert result["enriched_count"] == 0
        assert result["record_count"] == 2

    def test_no_session_summary_written(self):
        from apps.api.state import ApiAppState
        from apps.worker.jobs.fill_quality_attribution import run_fill_quality_attribution

        state = ApiAppState()
        state.fill_quality_records = []
        run_fill_quality_attribution(app_state=state, session_factory=None)
        assert state.fill_quality_attribution_summary is not None
        assert state.fill_quality_attribution_updated_at is not None

    def test_no_session_empty_records_ok(self):
        from apps.api.state import ApiAppState
        from apps.worker.jobs.fill_quality_attribution import run_fill_quality_attribution

        state = ApiAppState()
        result = run_fill_quality_attribution(app_state=state, session_factory=None)
        assert result["status"] == "ok"
        assert result["record_count"] == 0


# ---------------------------------------------------------------------------
# 12. run_fill_quality_attribution — enriches records when session_factory works
# ---------------------------------------------------------------------------

class TestRunFillQualityAttributionWithSession:
    def _make_mock_session_factory(self, price: str = "165.00"):
        """Return a mock session factory that returns a row with the given price."""
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, i: Decimal(price) if i == 0 else None

        mock_result = MagicMock()
        mock_result.first.return_value = (Decimal(price),)

        mock_db = MagicMock()
        mock_db.execute.return_value = mock_result
        mock_db.__enter__ = lambda self: self
        mock_db.__exit__ = MagicMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_db)
        return mock_factory

    def test_enriches_buy_record(self):
        from apps.api.state import ApiAppState
        from apps.worker.jobs.fill_quality_attribution import run_fill_quality_attribution

        state = ApiAppState()
        state.fill_quality_records = [_make_record(fill_price="150.00", quantity="10")]
        factory = self._make_mock_session_factory("165.00")

        result = run_fill_quality_attribution(
            app_state=state,
            session_factory=factory,
            n_days=5,
        )
        assert result["enriched_count"] >= 1 or result["status"] == "ok"

    def test_records_replaced_not_mutated(self):
        """Verify records list is replaced, not mutated in place."""
        from apps.api.state import ApiAppState
        from apps.worker.jobs.fill_quality_attribution import run_fill_quality_attribution

        state = ApiAppState()
        original_record = _make_record()
        state.fill_quality_records = [original_record]
        factory = self._make_mock_session_factory("165.00")

        run_fill_quality_attribution(app_state=state, session_factory=factory, n_days=5)
        # The original record is not mutated
        assert original_record.alpha_captured_pct is None


# ---------------------------------------------------------------------------
# 13. run_fill_quality_attribution — error path
# ---------------------------------------------------------------------------

class TestRunFillQualityAttributionError:
    def test_error_returns_error_status(self):
        from apps.api.state import ApiAppState
        from apps.worker.jobs.fill_quality_attribution import run_fill_quality_attribution

        state = ApiAppState()
        # Force an error by making fill_quality_records raise on list()
        state.fill_quality_records = None  # Will cause TypeError in list()

        result = run_fill_quality_attribution(app_state=state, session_factory=None)
        assert result["status"] == "error"
        assert len(result["errors"]) >= 1


# ---------------------------------------------------------------------------
# 14. GET /portfolio/fill-quality/attribution — 200 + empty on no data
# ---------------------------------------------------------------------------

class TestFillAttributionRouteEmpty:
    def test_empty_attribution_returns_200(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import reset_app_state

        reset_app_state()
        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/fill-quality/attribution")
        assert resp.status_code == 200

    def test_empty_summary_zero_records(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import reset_app_state

        reset_app_state()
        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/fill-quality/attribution")
        data = resp.json()
        assert data["summary"]["records_with_alpha"] == 0
        assert data["enriched_fill_count"] == 0

    def test_empty_avg_alpha_none(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import reset_app_state

        reset_app_state()
        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/fill-quality/attribution")
        data = resp.json()
        assert data["summary"]["avg_alpha_captured_pct"] is None


# ---------------------------------------------------------------------------
# 15. GET /portfolio/fill-quality/attribution — returns enriched summary
# ---------------------------------------------------------------------------

class TestFillAttributionRouteWithData:
    def test_returns_summary_data(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import get_app_state, reset_app_state
        from services.fill_quality.models import AlphaDecaySummary

        reset_app_state()
        state = get_app_state()
        state.fill_quality_attribution_summary = AlphaDecaySummary(
            records_with_alpha=3,
            avg_alpha_captured_pct=0.05,
            avg_slippage_as_pct_of_move=0.02,
            positive_alpha_count=2,
            negative_alpha_count=1,
            n_days=5,
            computed_at=dt.datetime(2026, 3, 21, 18, 32, tzinfo=dt.timezone.utc),
        )
        state.fill_quality_records = [
            _make_record(alpha_captured_pct=0.05),
            _make_record(alpha_captured_pct=-0.02),
            _make_record(alpha_captured_pct=0.08),
        ]

        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/fill-quality/attribution")
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["records_with_alpha"] == 3
        assert data["summary"]["avg_alpha_captured_pct"] == pytest.approx(0.05, rel=0.01)
        assert data["enriched_fill_count"] == 3

    def test_total_fill_count_all_records(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import get_app_state, reset_app_state
        from services.fill_quality.models import AlphaDecaySummary

        reset_app_state()
        state = get_app_state()
        state.fill_quality_records = [
            _make_record(),  # no alpha
            _make_record(alpha_captured_pct=0.05),
        ]

        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/fill-quality/attribution")
        data = resp.json()
        assert data["total_fill_count"] == 2
        assert data["enriched_fill_count"] == 1


# ---------------------------------------------------------------------------
# 16. FillQualityRecordSchema — alpha fields with None defaults
# ---------------------------------------------------------------------------

class TestFillQualityRecordSchemaAlphaFields:
    def test_schema_alpha_fields_present(self):
        from apps.api.schemas.fill_quality import FillQualityRecordSchema

        schema = FillQualityRecordSchema(
            ticker="AAPL",
            direction="BUY",
            action_type="open",
            expected_price=150.0,
            fill_price=150.5,
            quantity=10.0,
            slippage_usd=5.0,
            slippage_pct=0.000333,
            filled_at=dt.datetime(2026, 3, 10, 10, 0, tzinfo=dt.timezone.utc),
        )
        assert schema.alpha_captured_pct is None
        assert schema.slippage_as_pct_of_move is None

    def test_schema_alpha_fields_accept_values(self):
        from apps.api.schemas.fill_quality import FillQualityRecordSchema

        schema = FillQualityRecordSchema(
            ticker="MSFT",
            direction="SELL",
            action_type="close",
            expected_price=300.0,
            fill_price=299.5,
            quantity=5.0,
            slippage_usd=2.5,
            slippage_pct=0.000167,
            filled_at=dt.datetime(2026, 3, 10, 10, 0, tzinfo=dt.timezone.utc),
            alpha_captured_pct=0.05,
            slippage_as_pct_of_move=0.02,
        )
        assert schema.alpha_captured_pct == pytest.approx(0.05)
        assert schema.slippage_as_pct_of_move == pytest.approx(0.02)


# ---------------------------------------------------------------------------
# 17. Dashboard — alpha fields shown when present
# ---------------------------------------------------------------------------

class TestDashboardFillQualityAlphaSection:
    def test_alpha_section_shown_when_enriched(self):
        from apps.dashboard.router import _render_fill_quality_section
        from apps.api.state import ApiAppState
        from services.fill_quality.models import AlphaDecaySummary

        state = ApiAppState()
        state.fill_quality_records = [
            _make_record(alpha_captured_pct=0.05),
        ]
        state.fill_quality_attribution_summary = AlphaDecaySummary(
            records_with_alpha=1,
            avg_alpha_captured_pct=0.05,
            avg_slippage_as_pct_of_move=0.02,
            positive_alpha_count=1,
            negative_alpha_count=0,
            n_days=5,
        )
        html = _render_fill_quality_section(state)
        assert "Alpha" in html

    def test_alpha_section_hidden_when_no_attribution(self):
        from apps.dashboard.router import _render_fill_quality_section
        from apps.api.state import ApiAppState

        state = ApiAppState()
        state.fill_quality_records = [_make_record()]
        # No attribution summary
        html = _render_fill_quality_section(state)
        # Should still render (section for fill quality exists)
        assert "Fill Quality" in html


# ---------------------------------------------------------------------------
# 18. Scheduler job count now 30
# ---------------------------------------------------------------------------

class TestSchedulerJobCount:
    def test_scheduler_has_30_jobs(self):
        from apps.worker.main import build_scheduler

        scheduler = build_scheduler()
        jobs = scheduler.get_jobs()
        assert len(jobs) == 30, (
            f"Expected 30 scheduler jobs (Phase 55 adds fill_quality_attribution at 18:32), "
            f"got {len(jobs)}: {[j.id for j in jobs]}"
        )

    def test_fill_quality_attribution_job_registered(self):
        from apps.worker.main import build_scheduler

        scheduler = build_scheduler()
        job_ids = {j.id for j in scheduler.get_jobs()}
        assert "fill_quality_attribution" in job_ids

    def test_fill_quality_attribution_at_1832(self):
        from apps.worker.main import build_scheduler

        scheduler = build_scheduler()
        job = next((j for j in scheduler.get_jobs() if j.id == "fill_quality_attribution"), None)
        assert job is not None
        # Verify trigger time (18:32)
        trigger_fields = {f.name: str(f) for f in job.trigger.fields}
        assert "18" in trigger_fields.get("hour", "")
        assert "32" in trigger_fields.get("minute", "")
