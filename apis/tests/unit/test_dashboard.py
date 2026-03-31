"""
Phase 10 — Step 4: Dashboard Tests

Verifies that the read-only operator dashboard:
- is importable and mountable
- returns HTTP 200 with an HTML content-type
- renders key UI sections (system status, portfolio, rankings, scorecard)
- correctly reflects ApiAppState content in the response
- is accessible via the main FastAPI app
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.state import ApiAppState, get_app_state
from config.settings import Settings, get_settings

# ---------------------------------------------------------------------------
# Dependency override helpers (re-uses the same pattern as test_api_routes.py)
# ---------------------------------------------------------------------------

def _override_state(state: ApiAppState):
    app.dependency_overrides[get_app_state] = lambda: state


def _override_settings(settings: Settings):
    app.dependency_overrides[get_settings] = lambda: settings


def _clear_overrides():
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def reset_overrides():
    yield
    _clear_overrides()


def _default_settings(**kwargs) -> Settings:
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
    base.update(kwargs)
    return Settings(**base)


def _empty_state() -> ApiAppState:
    return ApiAppState()


# ---------------------------------------------------------------------------
# A minimal fake RankedResult for the rankings section
# ---------------------------------------------------------------------------

def _make_ranked_result(ticker: str = "AAPL", score: float = 0.80) -> Any:
    from services.ranking_engine.models import RankedResult
    return RankedResult(
        rank_position=1,
        security_id=None,
        ticker=ticker,
        composite_score=Decimal(str(score)),
        portfolio_fit_score=Decimal("0.75"),
        recommended_action="buy",
        target_horizon="medium_term",
        thesis_summary="AI infrastructure play",
        disconfirming_factors="Valuation risk",
        sizing_hint_pct=Decimal("0.05"),
        source_reliability_tier="secondary_verified",
        contains_rumor=False,
        contributing_signals=[],
    )


# ---------------------------------------------------------------------------
# A minimal fake DailyScorecard for the scorecard section
# ---------------------------------------------------------------------------

def _make_scorecard() -> Any:
    from services.evaluation_engine.models import (
        BenchmarkComparison,
        DailyScorecard,
        PerformanceAttribution,
    )
    bench = BenchmarkComparison(
        portfolio_return=Decimal("0.005"),
        benchmark_returns={"SPY": Decimal("0.003")},
        differentials={"SPY": Decimal("0.002")},
    )
    attribution = PerformanceAttribution(by_ticker=[], by_strategy=[], by_theme=[])
    return DailyScorecard(
        scorecard_date=dt.date(2026, 3, 17),
        equity=Decimal("105_500"),
        cash=Decimal("90_000"),
        gross_exposure=Decimal("15_500"),
        position_count=1,
        net_pnl=Decimal("500"),
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("500"),
        daily_return_pct=Decimal("0.005"),
        closed_trade_count=0,
        hit_rate=Decimal("0"),
        avg_winner_pct=Decimal("0"),
        avg_loser_pct=Decimal("0"),
        current_drawdown_pct=Decimal("0.02"),
        max_drawdown_pct=Decimal("0.05"),
        benchmark_comparison=bench,
        attribution=attribution,
        mode="paper",
    )


# ===========================================================================
# TestDashboardImport
# ===========================================================================

class TestDashboardImport:
    def test_router_importable(self):
        from apps.dashboard.router import dashboard_router
        assert dashboard_router is not None

    def test_package_exports_router(self):
        from apps.dashboard import dashboard_router
        assert dashboard_router is not None

    def test_router_prefix_is_dashboard(self):
        from apps.dashboard.router import dashboard_router
        assert dashboard_router.prefix == "/dashboard"


# ===========================================================================
# TestDashboardHomeRoute
# ===========================================================================

class TestDashboardHomeRoute:
    def test_dashboard_returns_200_with_empty_state(self):
        _override_state(_empty_state())
        _override_settings(_default_settings())
        with TestClient(app) as client:
            resp = client.get("/dashboard/")
        assert resp.status_code == 200

    def test_dashboard_content_type_is_html(self):
        _override_state(_empty_state())
        _override_settings(_default_settings())
        with TestClient(app) as client:
            resp = client.get("/dashboard/")
        assert "text/html" in resp.headers["content-type"]

    def test_dashboard_shows_title(self):
        _override_state(_empty_state())
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "APIS" in body

    def test_dashboard_shows_operating_mode(self):
        _override_state(_empty_state())
        _override_settings(_default_settings(operating_mode="research"))
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "research" in body.lower()

    def test_dashboard_shows_kill_switch_off(self):
        _override_state(_empty_state())
        _override_settings(_default_settings(is_kill_switch_active=False))
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "off" in body.lower()

    def test_dashboard_shows_kill_switch_active_warning(self):
        _override_state(_empty_state())
        _override_settings(_default_settings(is_kill_switch_active=True))
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "active" in body.lower() or "warn" in body.lower()

    def test_dashboard_muted_message_when_no_portfolio(self):
        _override_state(_empty_state())
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "No portfolio data yet" in body

    def test_dashboard_muted_message_when_no_rankings(self):
        _override_state(_empty_state())
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "No rankings available yet" in body

    def test_dashboard_shows_ranking_tickers(self):
        state = _empty_state()
        state.latest_rankings = [_make_ranked_result("NVDA", 0.90)]
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "NVDA" in body

    def test_dashboard_shows_scorecard_date(self):
        state = _empty_state()
        state.latest_scorecard = _make_scorecard()
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "2026-03-17" in body

    def test_dashboard_shows_proposal_count(self):
        state = _empty_state()
        state.improvement_proposals = ["proposal1", "proposal2"]
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "2" in body

    def test_dashboard_shows_promoted_versions(self):
        state = _empty_state()
        state.promoted_versions = {"ranking_engine": "v1.2.0"}
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "ranking_engine" in body
        assert "v1.2.0" in body
