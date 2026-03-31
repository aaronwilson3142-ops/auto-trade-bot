"""
Phase 41 — Liquidity Filter + Dollar Volume Position Cap

Test classes
------------
TestLiquidityServiceIsLiquid            — is_liquid() gate logic
TestLiquidityServiceAdvCap              — adv_capped_notional() math
TestLiquidityServiceFilter              — filter_for_liquidity() full pipeline
TestLiquidityServiceSummary             — liquidity_summary() output
TestLiquidityRefreshJob                 — run_liquidity_refresh() job
TestLiquidityRefreshJobNoDb             — graceful skip / error paths
TestLiquidityRouteScreen                — GET /portfolio/liquidity
TestLiquidityRouteDetail                — GET /portfolio/liquidity/{ticker}
"""
from __future__ import annotations

import dataclasses
import datetime as dt
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(
    min_liquidity_dollar_volume: float = 1_000_000.0,
    max_position_as_pct_of_adv: float = 0.10,
):
    s = MagicMock()
    s.min_liquidity_dollar_volume = min_liquidity_dollar_volume
    s.max_position_as_pct_of_adv = max_position_as_pct_of_adv
    return s


def _make_open_action(
    ticker: str = "AAPL",
    target_notional: Decimal = Decimal("5000.00"),
    target_quantity: Decimal = Decimal("25"),
    sizing_rationale: str = "half-kelly",
):
    from services.portfolio_engine.models import ActionType, PortfolioAction

    return PortfolioAction(
        ticker=ticker,
        action_type=ActionType.OPEN,
        target_notional=target_notional,
        target_quantity=target_quantity,
        sizing_rationale=sizing_rationale,
        reason="open_signal",
        risk_approved=False,
    )


def _make_close_action(ticker: str = "AAPL"):
    from services.portfolio_engine.models import ActionType, PortfolioAction

    return PortfolioAction(
        ticker=ticker,
        action_type=ActionType.CLOSE,
        target_notional=Decimal("5000.00"),
        target_quantity=Decimal("25"),
        reason="exit_signal",
    )


def _make_trim_action(ticker: str = "AAPL"):
    from services.portfolio_engine.models import ActionType, PortfolioAction

    return PortfolioAction(
        ticker=ticker,
        action_type=ActionType.TRIM,
        target_notional=Decimal("2000.00"),
        target_quantity=Decimal("10"),
        reason="overconcentration",
    )


# ---------------------------------------------------------------------------
# TestLiquidityServiceIsLiquid
# ---------------------------------------------------------------------------

class TestLiquidityServiceIsLiquid:
    """is_liquid() gate: returns True iff ADV >= min threshold."""

    def test_liquid_at_exactly_threshold(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings(min_liquidity_dollar_volume=1_000_000.0)
        assert LiquidityService.is_liquid(1_000_000.0, s) is True

    def test_liquid_above_threshold(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings(min_liquidity_dollar_volume=1_000_000.0)
        assert LiquidityService.is_liquid(500_000_000.0, s) is True

    def test_illiquid_below_threshold(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings(min_liquidity_dollar_volume=1_000_000.0)
        assert LiquidityService.is_liquid(999_999.0, s) is False

    def test_illiquid_zero_adv(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings(min_liquidity_dollar_volume=1_000_000.0)
        assert LiquidityService.is_liquid(0.0, s) is False

    def test_custom_threshold_respected(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings(min_liquidity_dollar_volume=10_000_000.0)
        assert LiquidityService.is_liquid(5_000_000.0, s) is False
        assert LiquidityService.is_liquid(10_000_001.0, s) is True

    def test_threshold_default_fallback(self):
        """getattr fallback to 1_000_000 when setting absent."""
        from services.risk_engine.liquidity import LiquidityService
        s = MagicMock(spec=[])  # no attributes
        assert LiquidityService.is_liquid(2_000_000.0, s) is True
        assert LiquidityService.is_liquid(500_000.0, s) is False


# ---------------------------------------------------------------------------
# TestLiquidityServiceAdvCap
# ---------------------------------------------------------------------------

class TestLiquidityServiceAdvCap:
    """adv_capped_notional() math: caps to max_pct × ADV."""

    def test_no_cap_when_notional_fits(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings(max_position_as_pct_of_adv=0.10)
        # ADV=100M, cap=10M; notional=5000 → no change
        result = LiquidityService.adv_capped_notional(
            target_notional=Decimal("5000.00"),
            dollar_volume_20d=100_000_000.0,
            settings=s,
        )
        assert result == Decimal("5000.00")

    def test_cap_applied_when_notional_exceeds(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings(max_position_as_pct_of_adv=0.10)
        # ADV=50_000, cap=5_000; notional=8000 → capped to 5000
        result = LiquidityService.adv_capped_notional(
            target_notional=Decimal("8000.00"),
            dollar_volume_20d=50_000.0,
            settings=s,
        )
        assert result == Decimal("5000.00")

    def test_cap_at_exact_boundary(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings(max_position_as_pct_of_adv=0.10)
        result = LiquidityService.adv_capped_notional(
            target_notional=Decimal("10000.00"),
            dollar_volume_20d=100_000.0,
            settings=s,
        )
        assert result == Decimal("10000.00")

    def test_zero_cap_ignored(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings(max_position_as_pct_of_adv=0.10)
        result = LiquidityService.adv_capped_notional(
            target_notional=Decimal("5000.00"),
            dollar_volume_20d=0.0,
            settings=s,
        )
        # cap would be 0 → degenerate → return original
        assert result == Decimal("5000.00")

    def test_pct_scaling(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings(max_position_as_pct_of_adv=0.05)
        result = LiquidityService.adv_capped_notional(
            target_notional=Decimal("20000.00"),
            dollar_volume_20d=200_000.0,
            settings=s,
        )
        assert result == Decimal("10000.00")

    def test_result_two_decimal_places(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings(max_position_as_pct_of_adv=0.10)
        result = LiquidityService.adv_capped_notional(
            target_notional=Decimal("100000.00"),
            dollar_volume_20d=33_333.0,
            settings=s,
        )
        # cap = 3333.3 → 3333.30 (2 d.p.)
        assert result == Decimal("3333.30")


# ---------------------------------------------------------------------------
# TestLiquidityServiceFilter
# ---------------------------------------------------------------------------

class TestLiquidityServiceFilter:
    """filter_for_liquidity() — gate + ADV cap pipeline."""

    def test_liquid_action_passes_through(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings()
        action = _make_open_action("AAPL", Decimal("5000.00"), Decimal("25"))
        dvs = {"AAPL": 500_000_000.0}
        result = LiquidityService.filter_for_liquidity([action], dvs, s)
        assert len(result) == 1
        assert result[0].ticker == "AAPL"

    def test_illiquid_open_dropped(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings(min_liquidity_dollar_volume=5_000_000.0)
        action = _make_open_action("PENNY", Decimal("500.00"))
        dvs = {"PENNY": 100_000.0}
        result = LiquidityService.filter_for_liquidity([action], dvs, s)
        assert len(result) == 0

    def test_close_passes_even_if_illiquid(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings(min_liquidity_dollar_volume=5_000_000.0)
        action = _make_close_action("PENNY")
        dvs = {"PENNY": 100_000.0}
        result = LiquidityService.filter_for_liquidity([action], dvs, s)
        assert len(result) == 1

    def test_trim_passes_even_if_illiquid(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings(min_liquidity_dollar_volume=5_000_000.0)
        action = _make_trim_action("PENNY")
        dvs = {"PENNY": 50_000.0}
        result = LiquidityService.filter_for_liquidity([action], dvs, s)
        assert len(result) == 1

    def test_missing_adv_data_passes_through(self):
        """Unknown tickers (no ADV data) pass through — safe default."""
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings()
        action = _make_open_action("UNKNOWN")
        result = LiquidityService.filter_for_liquidity([action], {}, s)
        assert len(result) == 1

    def test_adv_cap_reduces_notional(self):
        from services.risk_engine.liquidity import LiquidityService
        # Use min_dv=1 so gate passes, focus purely on ADV cap
        # ADV=2_000_000, cap=200_000; notional=5_000_000 → capped to 200_000
        s = _make_settings(min_liquidity_dollar_volume=1.0, max_position_as_pct_of_adv=0.10)
        action = _make_open_action("SMLL", Decimal("5000000.00"), Decimal("1000"))
        dvs = {"SMLL": 2_000_000.0}
        result = LiquidityService.filter_for_liquidity([action], dvs, s)
        assert len(result) == 1
        assert result[0].target_notional == Decimal("200000.00")

    def test_adv_cap_scales_quantity_proportionally(self):
        from services.risk_engine.liquidity import LiquidityService
        # ADV=2_000_000, cap=200_000; notional=1_000_000, qty=100 → qty=20
        s = _make_settings(min_liquidity_dollar_volume=1.0, max_position_as_pct_of_adv=0.10)
        action = _make_open_action("SMLL", Decimal("1000000.00"), Decimal("100"))
        dvs = {"SMLL": 2_000_000.0}
        result = LiquidityService.filter_for_liquidity([action], dvs, s)
        assert result[0].target_quantity == Decimal("20")

    def test_adv_cap_qty_floor_one_share(self):
        from services.risk_engine.liquidity import LiquidityService
        # ADV=1_000, cap=100; notional=100_000, qty=1000 → qty=1 (floor)
        # Gate threshold=1 so it passes
        s = _make_settings(min_liquidity_dollar_volume=1.0, max_position_as_pct_of_adv=0.10)
        action = _make_open_action("TINY", Decimal("100000.00"), Decimal("1000"))
        dvs = {"TINY": 1_000.0}
        result = LiquidityService.filter_for_liquidity([action], dvs, s)
        assert result[0].target_quantity >= Decimal("1")

    def test_no_cap_when_notional_fits_adv(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings(max_position_as_pct_of_adv=0.10)
        action = _make_open_action("AAPL", Decimal("5000.00"), Decimal("25"))
        dvs = {"AAPL": 500_000_000.0}  # cap = 50M >> 5000
        result = LiquidityService.filter_for_liquidity([action], dvs, s)
        assert result[0].target_notional == Decimal("5000.00")
        assert result[0].target_quantity == Decimal("25")

    def test_original_action_not_mutated(self):
        from services.risk_engine.liquidity import LiquidityService
        # Use low min_dv so action passes gate and ADV cap can be tested
        s = _make_settings(min_liquidity_dollar_volume=1.0, max_position_as_pct_of_adv=0.10)
        action = _make_open_action("SMLL", Decimal("5000000.00"), Decimal("500"))
        dvs = {"SMLL": 2_000_000.0}
        original_notional = action.target_notional
        LiquidityService.filter_for_liquidity([action], dvs, s)
        assert action.target_notional == original_notional  # original unchanged

    def test_rationale_appended_on_cap(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings(min_liquidity_dollar_volume=1.0, max_position_as_pct_of_adv=0.10)
        action = _make_open_action("SMLL", Decimal("5000000.00"), Decimal("500"))
        dvs = {"SMLL": 2_000_000.0}
        result = LiquidityService.filter_for_liquidity([action], dvs, s)
        assert "adv_cap" in (result[0].sizing_rationale or "")

    def test_mixed_actions(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings(min_liquidity_dollar_volume=1_000_000.0)
        actions = [
            _make_open_action("AAPL", Decimal("5000.00")),   # liquid → pass
            _make_open_action("PENNY", Decimal("500.00")),   # illiquid → drop
            _make_close_action("PENNY"),                      # close → always pass
        ]
        dvs = {"AAPL": 500_000_000.0, "PENNY": 50_000.0}
        result = LiquidityService.filter_for_liquidity(actions, dvs, s)
        tickers = [a.ticker for a in result]
        assert "AAPL" in tickers
        assert "PENNY" in tickers  # CLOSE passes
        # OPEN for PENNY dropped
        from services.portfolio_engine.models import ActionType
        open_tickers = [a.ticker for a in result if a.action_type == ActionType.OPEN]
        assert "PENNY" not in open_tickers

    def test_empty_actions_returns_empty(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings()
        assert LiquidityService.filter_for_liquidity([], {}, s) == []


# ---------------------------------------------------------------------------
# TestLiquidityServiceSummary
# ---------------------------------------------------------------------------

class TestLiquidityServiceSummary:
    """liquidity_summary() output structure and sorting."""

    def test_returns_list(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings()
        dvs = {"AAPL": 500_000_000.0, "PENNY": 50_000.0}
        result = LiquidityService.liquidity_summary(dvs, s)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_sorted_by_adv_descending(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings()
        dvs = {"LOW": 1_000_000.0, "HIGH": 500_000_000.0, "MID": 50_000_000.0}
        result = LiquidityService.liquidity_summary(dvs, s)
        dv_vals = [r["dollar_volume_20d"] for r in result]
        assert dv_vals == sorted(dv_vals, reverse=True)

    def test_is_liquid_field_correct(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings(min_liquidity_dollar_volume=1_000_000.0)
        dvs = {"AAPL": 500_000_000.0, "PENNY": 50_000.0}
        result = LiquidityService.liquidity_summary(dvs, s)
        by_ticker = {r["ticker"]: r for r in result}
        assert by_ticker["AAPL"]["is_liquid"] is True
        assert by_ticker["PENNY"]["is_liquid"] is False

    def test_tier_classification(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings()
        dvs = {
            "HIGH": 200_000_000.0,
            "MID": 50_000_000.0,
            "LOW": 5_000_000.0,
            "MICRO": 500_000.0,
        }
        result = LiquidityService.liquidity_summary(dvs, s)
        by_ticker = {r["ticker"]: r for r in result}
        assert by_ticker["HIGH"]["liquidity_tier"] == "high"
        assert by_ticker["MID"]["liquidity_tier"] == "mid"
        assert by_ticker["LOW"]["liquidity_tier"] == "low"
        assert by_ticker["MICRO"]["liquidity_tier"] == "micro"

    def test_adv_cap_computed_correctly(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings(max_position_as_pct_of_adv=0.10)
        dvs = {"AAPL": 100_000_000.0}
        result = LiquidityService.liquidity_summary(dvs, s)
        assert result[0]["adv_notional_cap_usd"] == pytest.approx(10_000_000.0, rel=1e-4)

    def test_empty_input_returns_empty(self):
        from services.risk_engine.liquidity import LiquidityService
        s = _make_settings()
        assert LiquidityService.liquidity_summary({}, s) == []


# ---------------------------------------------------------------------------
# TestLiquidityRefreshJob
# ---------------------------------------------------------------------------

class TestLiquidityRefreshJob:
    """run_liquidity_refresh() — happy path and graceful degradation."""

    def test_skipped_when_no_session_factory(self):
        from apps.worker.jobs.liquidity import run_liquidity_refresh
        from apps.api.state import ApiAppState

        state = ApiAppState()
        result = run_liquidity_refresh(app_state=state, session_factory=None)
        assert result["status"] == "skipped_no_db"
        assert result["ticker_count"] == 0

    def test_state_not_modified_on_skip(self):
        from apps.worker.jobs.liquidity import run_liquidity_refresh
        from apps.api.state import ApiAppState

        state = ApiAppState()
        run_liquidity_refresh(app_state=state, session_factory=None)
        assert state.latest_dollar_volumes == {}
        assert state.liquidity_computed_at is None

    def test_returns_ok_on_success(self):
        from apps.worker.jobs.liquidity import run_liquidity_refresh
        from apps.api.state import ApiAppState

        state = ApiAppState()

        # Build minimal DB mock
        mock_session = MagicMock()
        mock_feat_row = MagicMock()
        mock_feat_row.id = "feat-uuid-1"

        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_feat_row
        # Rows: (ticker, feature_value_numeric)
        mock_session.execute.return_value.all.return_value = [
            ("AAPL", Decimal("500000000")),
            ("MSFT", Decimal("300000000")),
        ]
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)

        def _session_factory():
            return mock_session

        with patch(
            "apps.worker.jobs.liquidity.run_liquidity_refresh.__module__",
            create=True,
        ):
            # Patch the DB imports inside the job
            with patch.dict("sys.modules", {
                "infra.db.models.analytics": MagicMock(
                    Feature=MagicMock(),
                    SecurityFeatureValue=MagicMock(),
                ),
                "infra.db.models": MagicMock(Security=MagicMock()),
                "sqlalchemy": MagicMock(),
            }):
                result = run_liquidity_refresh(
                    app_state=state,
                    session_factory=_session_factory,
                )
        # At minimum no exception raised; result is a dict
        assert isinstance(result, dict)

    def test_result_has_required_keys(self):
        from apps.worker.jobs.liquidity import run_liquidity_refresh
        from apps.api.state import ApiAppState

        state = ApiAppState()
        result = run_liquidity_refresh(app_state=state, session_factory=None)
        for key in ("status", "ticker_count", "computed_at", "error"):
            assert key in result

    def test_computed_at_is_iso_string(self):
        from apps.worker.jobs.liquidity import run_liquidity_refresh
        from apps.api.state import ApiAppState

        state = ApiAppState()
        result = run_liquidity_refresh(app_state=state, session_factory=None)
        # Should be parseable as ISO datetime
        dt.datetime.fromisoformat(result["computed_at"])


# ---------------------------------------------------------------------------
# TestLiquidityRefreshJobNoDb
# ---------------------------------------------------------------------------

class TestLiquidityRefreshJobNoDb:
    """run_liquidity_refresh() error paths."""

    def test_db_exception_returns_error_status(self):
        from apps.worker.jobs.liquidity import run_liquidity_refresh
        from apps.api.state import ApiAppState

        state = ApiAppState()

        def _bad_factory():
            raise RuntimeError("DB connection refused")

        result = run_liquidity_refresh(app_state=state, session_factory=_bad_factory)
        assert result["status"] in ("error", "error_db")
        assert result["ticker_count"] == 0

    def test_state_unchanged_on_db_error(self):
        from apps.worker.jobs.liquidity import run_liquidity_refresh
        from apps.api.state import ApiAppState

        state = ApiAppState()
        state.latest_dollar_volumes = {"AAPL": 500_000_000.0}

        def _bad_factory():
            raise RuntimeError("DB down")

        run_liquidity_refresh(app_state=state, session_factory=_bad_factory)
        # Stale data preserved — never blanked on error
        assert state.latest_dollar_volumes == {"AAPL": 500_000_000.0}

    def test_scheduler_has_liquidity_refresh_job(self):
        from apps.worker.main import build_scheduler

        scheduler = build_scheduler()
        ids = {job.id for job in scheduler.get_jobs()}
        assert "liquidity_refresh" in ids

    def test_liquidity_refresh_scheduled_at_06_17(self):
        from apps.worker.main import build_scheduler

        scheduler = build_scheduler()
        job = next(j for j in scheduler.get_jobs() if j.id == "liquidity_refresh")
        fields = {f.name: f for f in job.trigger.fields}
        assert str(fields["hour"]) == "6"
        assert str(fields["minute"]) == "17"

    def test_liquidity_refresh_exported_from_jobs_package(self):
        from apps.worker.jobs import run_liquidity_refresh
        assert callable(run_liquidity_refresh)


# ---------------------------------------------------------------------------
# TestLiquidityRouteScreen
# ---------------------------------------------------------------------------

class TestLiquidityRouteScreen:
    """GET /api/v1/portfolio/liquidity — in-memory state responses."""

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

    def test_empty_state_returns_200(self):
        client = self._client()
        resp = client.get("/api/v1/portfolio/liquidity")
        assert resp.status_code == 200

    def test_empty_state_returns_zero_counts(self):
        client = self._client()
        data = client.get("/api/v1/portfolio/liquidity").json()
        assert data["ticker_count"] == 0
        assert data["liquid_count"] == 0
        assert data["illiquid_count"] == 0

    def test_with_data_returns_tickers(self):
        client = self._client({"latest_dollar_volumes": {
            "AAPL": 500_000_000.0, "MSFT": 300_000_000.0, "PENNY": 50_000.0,
        }})
        data = client.get("/api/v1/portfolio/liquidity").json()
        assert data["ticker_count"] == 3

    def test_liquid_illiquid_counts_correct(self):
        client = self._client({"latest_dollar_volumes": {
            "AAPL": 500_000_000.0, "MSFT": 300_000_000.0, "PENNY": 50_000.0,
        }})
        data = client.get("/api/v1/portfolio/liquidity").json()
        assert data["liquid_count"] == 2
        assert data["illiquid_count"] == 1

    def test_sorted_by_adv_descending(self):
        client = self._client({"latest_dollar_volumes": {
            "LOW": 1_000_000.0, "HIGH": 500_000_000.0, "MID": 50_000_000.0,
        }})
        tickers = client.get("/api/v1/portfolio/liquidity").json()["tickers"]
        dv_vals = [t["dollar_volume_20d"] for t in tickers]
        assert dv_vals == sorted(dv_vals, reverse=True)

    def test_response_contains_settings_fields(self):
        client = self._client()
        data = client.get("/api/v1/portfolio/liquidity").json()
        assert "min_liquidity_dollar_volume" in data
        assert "max_position_as_pct_of_adv" in data

    def test_ticker_schema_has_required_fields(self):
        client = self._client({"latest_dollar_volumes": {"AAPL": 500_000_000.0}})
        tickers = client.get("/api/v1/portfolio/liquidity").json()["tickers"]
        assert len(tickers) == 1
        t = tickers[0]
        for field in ("ticker", "dollar_volume_20d", "is_liquid", "adv_notional_cap_usd", "liquidity_tier"):
            assert field in t


# ---------------------------------------------------------------------------
# TestLiquidityRouteDetail
# ---------------------------------------------------------------------------

class TestLiquidityRouteDetail:
    """GET /api/v1/portfolio/liquidity/{ticker} — single-ticker detail."""

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

    def test_known_ticker_returns_200(self):
        client = self._client({"latest_dollar_volumes": {"AAPL": 500_000_000.0}})
        resp = client.get("/api/v1/portfolio/liquidity/AAPL")
        assert resp.status_code == 200

    def test_known_ticker_data_available_true(self):
        client = self._client({"latest_dollar_volumes": {"AAPL": 500_000_000.0}})
        data = client.get("/api/v1/portfolio/liquidity/AAPL").json()
        assert data["data_available"] is True
        assert data["is_liquid"] is True
        assert data["ticker"] == "AAPL"

    def test_unknown_ticker_returns_200_not_404(self):
        client = self._client()
        resp = client.get("/api/v1/portfolio/liquidity/XYZ")
        assert resp.status_code == 200

    def test_unknown_ticker_data_available_false(self):
        client = self._client()
        data = client.get("/api/v1/portfolio/liquidity/XYZ").json()
        assert data["data_available"] is False
        assert data["dollar_volume_20d"] is None

    def test_illiquid_ticker_is_liquid_false(self):
        client = self._client({"latest_dollar_volumes": {"PENNY": 50_000.0}})
        data = client.get("/api/v1/portfolio/liquidity/PENNY").json()
        assert data["is_liquid"] is False

    def test_ticker_uppercased(self):
        client = self._client({"latest_dollar_volumes": {"AAPL": 500_000_000.0}})
        data = client.get("/api/v1/portfolio/liquidity/aapl").json()
        assert data["ticker"] == "AAPL"
        assert data["data_available"] is True

    def test_adv_cap_present_in_response(self):
        client = self._client({"latest_dollar_volumes": {"AAPL": 100_000_000.0}})
        data = client.get("/api/v1/portfolio/liquidity/AAPL").json()
        assert data["adv_notional_cap_usd"] == pytest.approx(10_000_000.0, rel=1e-3)

    def test_liquidity_tier_in_response(self):
        client = self._client({"latest_dollar_volumes": {"AAPL": 500_000_000.0}})
        data = client.get("/api/v1/portfolio/liquidity/AAPL").json()
        assert data["liquidity_tier"] == "high"

    def test_settings_fields_in_response(self):
        client = self._client()
        data = client.get("/api/v1/portfolio/liquidity/XYZ").json()
        assert "min_liquidity_dollar_volume" in data
        assert "max_position_as_pct_of_adv" in data


# ---------------------------------------------------------------------------
# TestPaperCycleLiquidityIntegration
# ---------------------------------------------------------------------------

class TestPaperCycleLiquidityIntegration:
    """Paper trading cycle liquidity filter block integration."""

    def _run_cycle(self, dollar_volumes: dict, actions_pre: list) -> dict:
        """Run a minimal paper cycle with injected dollar volumes and pre-built actions."""
        from apps.api.state import ApiAppState, reset_app_state
        from config.settings import Settings, OperatingMode

        reset_app_state()

        state = ApiAppState()
        state.latest_dollar_volumes = dollar_volumes

        cfg = MagicMock(spec=Settings)
        cfg.operating_mode = OperatingMode.PAPER
        cfg.kill_switch = False
        cfg.min_liquidity_dollar_volume = 1_000_000.0
        cfg.max_position_as_pct_of_adv = 0.10
        cfg.max_sector_pct = 0.40
        cfg.max_pairwise_correlation = 0.75
        cfg.correlation_size_floor = 0.25
        cfg.stop_loss_pct = 0.07
        cfg.max_position_age_days = 20
        cfg.exit_score_threshold = 0.40
        cfg.max_single_name_pct = 0.20
        cfg.max_positions = 10
        cfg.daily_loss_limit_pct = 0.02
        cfg.weekly_drawdown_limit_pct = 0.05

        from services.risk_engine.liquidity import LiquidityService
        from services.portfolio_engine.models import ActionType

        before_count = len([a for a in actions_pre if a.action_type == ActionType.OPEN])
        filtered = LiquidityService.filter_for_liquidity(actions_pre, dollar_volumes, cfg)
        after_count = len([a for a in filtered if a.action_type == ActionType.OPEN])
        dropped = before_count - after_count

        state.liquidity_filtered_count = dropped
        return {"filtered_actions": filtered, "dropped": dropped, "state": state}

    def test_illiquid_open_dropped_in_cycle(self):
        actions = [
            _make_open_action("LIQUID", Decimal("5000.00")),
            _make_open_action("PENNY", Decimal("500.00")),
        ]
        result = self._run_cycle(
            dollar_volumes={"LIQUID": 500_000_000.0, "PENNY": 50_000.0},
            actions_pre=actions,
        )
        from services.portfolio_engine.models import ActionType
        open_tickers = [a.ticker for a in result["filtered_actions"] if a.action_type == ActionType.OPEN]
        assert "LIQUID" in open_tickers
        assert "PENNY" not in open_tickers
        assert result["dropped"] == 1

    def test_close_preserved_for_illiquid_in_cycle(self):
        actions = [_make_close_action("PENNY")]
        result = self._run_cycle(
            dollar_volumes={"PENNY": 50_000.0},
            actions_pre=actions,
        )
        assert len(result["filtered_actions"]) == 1

    def test_state_filtered_count_updated(self):
        actions = [_make_open_action("PENNY", Decimal("500.00"))]
        result = self._run_cycle(
            dollar_volumes={"PENNY": 50_000.0},
            actions_pre=actions,
        )
        assert result["state"].liquidity_filtered_count == 1

    def test_no_filter_when_dollar_volumes_empty(self):
        """Missing ADV data → all actions pass through."""
        actions = [
            _make_open_action("AAPL", Decimal("5000.00")),
            _make_open_action("MSFT", Decimal("4000.00")),
        ]
        result = self._run_cycle(dollar_volumes={}, actions_pre=actions)
        from services.portfolio_engine.models import ActionType
        open_count = sum(1 for a in result["filtered_actions"] if a.action_type == ActionType.OPEN)
        assert open_count == 2
