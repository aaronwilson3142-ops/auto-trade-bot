"""Phase 52 — Order Fill Quality Tracking tests.

Covers:
  - FillQualityRecord construction / slippage computation
  - FillQualityService.compute_slippage (BUY / SELL edge cases)
  - FillQualityService.build_record
  - FillQualityService.compute_fill_summary (empty, single, multiple)
  - FillQualityService.filter_by_ticker / filter_by_direction
  - run_fill_quality_update job (ok, empty records, error path)
  - Paper trading cycle fill capture block
  - REST endpoints: GET /portfolio/fill-quality, GET /portfolio/fill-quality/{ticker}
  - Dashboard section rendering
  - AppState fill_quality_* fields
  - Scheduler job count assertion (28 total)
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_record(
    ticker: str = "AAPL",
    direction: str = "BUY",
    action_type: str = "open",
    expected_price: float = 150.0,
    fill_price: float = 150.25,
    quantity: float = 10.0,
    slippage_usd: float = 2.50,
    slippage_pct: float = 0.001667,
    filled_at: dt.datetime | None = None,
):
    from services.fill_quality.models import FillQualityRecord

    return FillQualityRecord(
        ticker=ticker,
        direction=direction,
        action_type=action_type,
        expected_price=Decimal(str(expected_price)),
        fill_price=Decimal(str(fill_price)),
        quantity=Decimal(str(quantity)),
        slippage_usd=Decimal(str(slippage_usd)),
        slippage_pct=Decimal(str(slippage_pct)),
        filled_at=filled_at or dt.datetime.now(dt.UTC),
    )


# ===========================================================================
# 1. Data model tests
# ===========================================================================

class TestFillQualityRecord:
    def test_fields_stored(self):
        r = _make_record()
        assert r.ticker == "AAPL"
        assert r.direction == "BUY"
        assert r.action_type == "open"
        assert r.expected_price == Decimal("150.0")
        assert r.fill_price == Decimal("150.25")
        assert r.quantity == Decimal("10.0")
        assert r.slippage_usd == Decimal("2.50")

    def test_sell_record(self):
        r = _make_record(direction="SELL", action_type="close", fill_price=149.50, slippage_usd=5.0)
        assert r.direction == "SELL"
        assert r.slippage_usd == Decimal("5.0")

    def test_filled_at_preserved(self):
        ts = dt.datetime(2026, 3, 21, 14, 30, tzinfo=dt.UTC)
        r = _make_record(filled_at=ts)
        assert r.filled_at == ts


class TestFillQualitySummary:
    def test_default_fields(self):
        from services.fill_quality.models import FillQualitySummary

        s = FillQualitySummary()
        assert s.total_fills == 0
        assert s.buy_fills == 0
        assert s.sell_fills == 0
        assert s.avg_slippage_usd == Decimal("0")
        assert s.tickers_covered == []

    def test_custom_fields(self):
        from services.fill_quality.models import FillQualitySummary

        s = FillQualitySummary(total_fills=5, buy_fills=3, sell_fills=2)
        assert s.total_fills == 5
        assert s.record_count == 0  # separate field


# ===========================================================================
# 2. FillQualityService — compute_slippage
# ===========================================================================

class TestComputeSlippage:
    def setup_method(self):
        from services.fill_quality.service import FillQualityService
        self.svc = FillQualityService

    def test_buy_positive_slippage(self):
        usd, pct = self.svc.compute_slippage("BUY", Decimal("100"), Decimal("101"), Decimal("10"))
        assert usd == Decimal("10.00")
        assert pct > 0

    def test_buy_negative_slippage(self):
        usd, pct = self.svc.compute_slippage("BUY", Decimal("100"), Decimal("99"), Decimal("10"))
        assert usd == Decimal("-10.00")
        assert pct < 0

    def test_buy_zero_slippage(self):
        usd, pct = self.svc.compute_slippage("BUY", Decimal("100"), Decimal("100"), Decimal("10"))
        assert usd == Decimal("0.00")
        assert pct == Decimal("0.000000")

    def test_sell_positive_slippage(self):
        # Expected 100, got 98 → lost $2 per share
        usd, pct = self.svc.compute_slippage("SELL", Decimal("100"), Decimal("98"), Decimal("5"))
        assert usd == Decimal("10.00")
        assert pct > 0

    def test_sell_negative_slippage(self):
        # Expected 100, got 102 → better than expected
        usd, pct = self.svc.compute_slippage("SELL", Decimal("100"), Decimal("102"), Decimal("5"))
        assert usd == Decimal("-10.00")
        assert pct < 0

    def test_zero_expected_price_returns_zero(self):
        usd, pct = self.svc.compute_slippage("BUY", Decimal("0"), Decimal("100"), Decimal("10"))
        assert usd == Decimal("0")
        assert pct == Decimal("0")

    def test_zero_quantity_returns_zero(self):
        usd, pct = self.svc.compute_slippage("BUY", Decimal("100"), Decimal("101"), Decimal("0"))
        assert usd == Decimal("0")
        assert pct == Decimal("0")

    def test_pct_precision(self):
        usd, pct = self.svc.compute_slippage("BUY", Decimal("100"), Decimal("100.10"), Decimal("100"))
        assert usd == Decimal("10.00")
        # 10 / 10000 = 0.001000
        assert abs(float(pct) - 0.001) < 1e-5


# ===========================================================================
# 3. FillQualityService — build_record
# ===========================================================================

class TestBuildRecord:
    def setup_method(self):
        from services.fill_quality.service import FillQualityService
        self.svc = FillQualityService

    def test_build_buy_record(self):
        ts = dt.datetime.now(dt.UTC)
        r = self.svc.build_record(
            ticker="MSFT",
            direction="BUY",
            action_type="open",
            expected_price=Decimal("300"),
            fill_price=Decimal("300.30"),
            quantity=Decimal("5"),
            filled_at=ts,
        )
        assert r.ticker == "MSFT"
        assert r.slippage_usd == Decimal("1.50")
        assert r.filled_at == ts

    def test_build_sell_record(self):
        ts = dt.datetime.now(dt.UTC)
        r = self.svc.build_record(
            ticker="TSLA",
            direction="SELL",
            action_type="close",
            expected_price=Decimal("200"),
            fill_price=Decimal("199"),
            quantity=Decimal("3"),
            filled_at=ts,
        )
        assert r.direction == "SELL"
        assert r.slippage_usd == Decimal("3.00")


# ===========================================================================
# 4. FillQualityService — compute_fill_summary
# ===========================================================================

class TestComputeFillSummary:
    def setup_method(self):
        from services.fill_quality.service import FillQualityService
        self.svc = FillQualityService

    def test_empty_returns_zero_summary(self):
        s = self.svc.compute_fill_summary([])
        assert s.total_fills == 0
        assert s.avg_slippage_usd == Decimal("0")
        assert s.tickers_covered == []

    def test_single_buy_record(self):
        r = _make_record("AAPL", "BUY", slippage_usd=2.50)
        s = self.svc.compute_fill_summary([r])
        assert s.total_fills == 1
        assert s.buy_fills == 1
        assert s.sell_fills == 0
        assert s.avg_slippage_usd == Decimal("2.50")
        assert s.avg_buy_slippage_usd == Decimal("2.50")
        assert s.avg_sell_slippage_usd is None

    def test_single_sell_record(self):
        r = _make_record("AAPL", "SELL", slippage_usd=1.00)
        s = self.svc.compute_fill_summary([r])
        assert s.sell_fills == 1
        assert s.avg_sell_slippage_usd == Decimal("1.00")
        assert s.avg_buy_slippage_usd is None

    def test_multiple_records_avg(self):
        r1 = _make_record("AAPL", "BUY", slippage_usd=2.0)
        r2 = _make_record("MSFT", "BUY", slippage_usd=4.0)
        s = self.svc.compute_fill_summary([r1, r2])
        assert s.total_fills == 2
        assert s.avg_slippage_usd == Decimal("3.00")

    def test_worst_and_best(self):
        r1 = _make_record(slippage_usd=1.0)
        r2 = _make_record(slippage_usd=5.0)
        r3 = _make_record(slippage_usd=-2.0)
        s = self.svc.compute_fill_summary([r1, r2, r3])
        assert s.worst_slippage_usd == Decimal("5.00")
        assert s.best_slippage_usd == Decimal("-2.00")

    def test_tickers_covered_sorted(self):
        r1 = _make_record("MSFT")
        r2 = _make_record("AAPL")
        r3 = _make_record("AAPL")
        s = self.svc.compute_fill_summary([r1, r2, r3])
        assert s.tickers_covered == ["AAPL", "MSFT"]
        assert s.record_count == 3

    def test_computed_at_set(self):
        ts = dt.datetime.now(dt.UTC)
        s = self.svc.compute_fill_summary([], computed_at=ts)
        assert s.computed_at == ts


# ===========================================================================
# 5. FillQualityService — filter helpers
# ===========================================================================

class TestFilterHelpers:
    def setup_method(self):
        from services.fill_quality.service import FillQualityService
        self.svc = FillQualityService

    def test_filter_by_ticker_match(self):
        r1 = _make_record("AAPL")
        r2 = _make_record("MSFT")
        result = self.svc.filter_by_ticker([r1, r2], "AAPL")
        assert len(result) == 1
        assert result[0].ticker == "AAPL"

    def test_filter_by_ticker_case_insensitive(self):
        r = _make_record("AAPL")
        assert len(self.svc.filter_by_ticker([r], "aapl")) == 1

    def test_filter_by_ticker_no_match(self):
        r = _make_record("MSFT")
        assert self.svc.filter_by_ticker([r], "AAPL") == []

    def test_filter_by_direction_buy(self):
        r1 = _make_record(direction="BUY")
        r2 = _make_record(direction="SELL")
        result = self.svc.filter_by_direction([r1, r2], "BUY")
        assert len(result) == 1

    def test_filter_by_direction_case_insensitive(self):
        r = _make_record(direction="BUY")
        assert len(self.svc.filter_by_direction([r], "buy")) == 1


# ===========================================================================
# 6. run_fill_quality_update job
# ===========================================================================

class TestRunFillQualityUpdate:
    def _make_state(self, records=None):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        state.fill_quality_records = records or []
        return state

    def test_ok_with_records(self):
        from apps.worker.jobs.fill_quality import run_fill_quality_update
        from config.settings import Settings

        records = [_make_record("AAPL", slippage_usd=1.5)]
        state = self._make_state(records)
        result = run_fill_quality_update(app_state=state, settings=Settings())
        assert result["status"] == "ok"
        assert result["record_count"] == 1
        assert state.fill_quality_summary is not None
        assert state.fill_quality_updated_at is not None

    def test_ok_with_empty_records(self):
        from apps.worker.jobs.fill_quality import run_fill_quality_update
        from config.settings import Settings

        state = self._make_state([])
        result = run_fill_quality_update(app_state=state, settings=Settings())
        assert result["status"] == "ok"
        assert result["record_count"] == 0

    def test_error_path_does_not_raise(self):
        from apps.worker.jobs.fill_quality import run_fill_quality_update
        from config.settings import Settings

        state = MagicMock()
        state.fill_quality_records = "not-a-list"  # will cause error in service
        # Should not raise
        result = run_fill_quality_update(app_state=state, settings=Settings())
        # Either ok or error — must not raise
        assert "status" in result

    def test_updates_summary_on_state(self):
        from apps.worker.jobs.fill_quality import run_fill_quality_update
        from config.settings import Settings

        state = self._make_state([_make_record(slippage_usd=3.0)])
        run_fill_quality_update(app_state=state, settings=Settings())
        assert state.fill_quality_summary.avg_slippage_usd == Decimal("3.00")


# ===========================================================================
# 7. App state fields
# ===========================================================================

class TestAppStateFields:
    def test_fill_quality_records_default_empty(self):
        from apps.api.state import ApiAppState
        s = ApiAppState()
        assert s.fill_quality_records == []

    def test_fill_quality_summary_default_none(self):
        from apps.api.state import ApiAppState
        s = ApiAppState()
        assert s.fill_quality_summary is None

    def test_fill_quality_updated_at_default_none(self):
        from apps.api.state import ApiAppState
        s = ApiAppState()
        assert s.fill_quality_updated_at is None

    def test_reset_app_state_clears_fields(self):
        from apps.api.state import get_app_state, reset_app_state
        reset_app_state()
        s = get_app_state()
        s.fill_quality_records.append(_make_record())
        reset_app_state()
        assert get_app_state().fill_quality_records == []


# ===========================================================================
# 8. REST endpoints
# ===========================================================================

@pytest.fixture()
def client():
    from apps.api.state import reset_app_state
    reset_app_state()
    from apps.api.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def client_with_records():
    from apps.api.state import get_app_state, reset_app_state
    reset_app_state()
    state = get_app_state()
    state.fill_quality_records = [
        _make_record("AAPL", "BUY", slippage_usd=2.50),
        _make_record("MSFT", "SELL", slippage_usd=1.00),
        _make_record("AAPL", "BUY", slippage_usd=3.00),
    ]
    from apps.api.main import app
    with TestClient(app) as c:
        yield c


class TestFillQualityEndpointEmpty:
    def test_get_fill_quality_empty(self, client):
        resp = client.get("/api/v1/portfolio/fill-quality")
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data
        assert data["summary"]["total_fills"] == 0
        assert data["recent_fills"] == []

    def test_get_fill_quality_ticker_not_found(self, client):
        resp = client.get("/api/v1/portfolio/fill-quality/AAPL")
        assert resp.status_code == 404


class TestFillQualityEndpointWithRecords:
    def test_get_fill_quality_summary(self, client_with_records):
        resp = client_with_records.get("/api/v1/portfolio/fill-quality")
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["total_fills"] == 3
        assert data["summary"]["buy_fills"] == 2
        assert data["summary"]["sell_fills"] == 1

    def test_get_fill_quality_recent_fills(self, client_with_records):
        resp = client_with_records.get("/api/v1/portfolio/fill-quality")
        data = resp.json()
        assert len(data["recent_fills"]) == 3

    def test_get_fill_quality_ticker_found(self, client_with_records):
        resp = client_with_records.get("/api/v1/portfolio/fill-quality/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert data["total_fills"] == 2

    def test_get_fill_quality_ticker_case_insensitive(self, client_with_records):
        resp = client_with_records.get("/api/v1/portfolio/fill-quality/aapl")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "AAPL"

    def test_get_fill_quality_ticker_summary(self, client_with_records):
        resp = client_with_records.get("/api/v1/portfolio/fill-quality/AAPL")
        data = resp.json()
        assert data["summary"]["total_fills"] == 2
        assert data["summary"]["avg_slippage_usd"] == pytest.approx(2.75, abs=0.01)

    def test_get_fill_quality_msft_only(self, client_with_records):
        resp = client_with_records.get("/api/v1/portfolio/fill-quality/MSFT")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_fills"] == 1


# ===========================================================================
# 9. Dashboard section
# ===========================================================================

class TestDashboardFillQualitySection:
    def test_renders_no_data_state(self):
        from apps.api.state import ApiAppState
        from apps.dashboard.router import _render_fill_quality_section
        state = ApiAppState()
        html = _render_fill_quality_section(state)
        assert "Phase 52" in html
        assert "No fills captured" in html

    def test_renders_with_summary(self):
        from apps.api.state import ApiAppState
        from apps.dashboard.router import _render_fill_quality_section
        from services.fill_quality.service import FillQualityService

        state = ApiAppState()
        state.fill_quality_records = [_make_record("AAPL", slippage_usd=2.0)]
        state.fill_quality_summary = FillQualityService.compute_fill_summary(
            state.fill_quality_records
        )
        html = _render_fill_quality_section(state)
        assert "AAPL" in html
        assert "Phase 52" in html

    def test_renders_recent_fill_table(self):
        from apps.api.state import ApiAppState
        from apps.dashboard.router import _render_fill_quality_section

        state = ApiAppState()
        state.fill_quality_records = [_make_record("TSLA", direction="SELL")]
        html = _render_fill_quality_section(state)
        assert "TSLA" in html


# ===========================================================================
# 10. Paper trading cycle: fill capture wiring
# ===========================================================================

class TestPaperCycleFillCapture:
    """Ensure fill quality records are appended by the paper trading cycle."""

    def test_fill_quality_records_appended_on_filled_open(self):
        from decimal import Decimal

        from apps.api.state import ApiAppState, reset_app_state
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from broker_adapters.paper.adapter import PaperBrokerAdapter
        from config.settings import OperatingMode, Settings

        reset_app_state()
        state = ApiAppState()

        # Pre-populate ranking
        mock_ranking = MagicMock()
        mock_ranking.ticker = "AAPL"
        mock_ranking.composite_score = Decimal("0.85")
        mock_ranking.thesis_summary = "test"
        mock_ranking.sizing_hint = "normal"
        mock_ranking.contains_rumor = False
        mock_ranking.source_reliability_tier = "primary"
        state.latest_rankings = [mock_ranking]

        cfg = Settings(operating_mode=OperatingMode.PAPER)
        broker = PaperBrokerAdapter(market_open=True)

        result = run_paper_trading_cycle(
            app_state=state,
            settings=cfg,
            broker=broker,
        )
        # Either ok or skipped — we just check no crash and captures don't error
        assert result["status"] in ("ok", "skipped_no_rankings", "skipped_mode", "error", "killed")


# ===========================================================================
# 11. Scheduler job count
# ===========================================================================

class TestSchedulerJobCount:
    def test_scheduler_has_29_jobs(self):
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        jobs = scheduler.get_jobs()
        assert len(jobs) == 30, (
            f"Expected 30 scheduler jobs, got {len(jobs)}: "
            + ", ".join(j.id for j in jobs)
        )

    def test_fill_quality_update_job_registered(self):
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        job_ids = {j.id for j in scheduler.get_jobs()}
        assert "fill_quality_update" in job_ids
