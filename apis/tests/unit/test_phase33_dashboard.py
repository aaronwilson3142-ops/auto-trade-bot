"""
Phase 33 — Operator Dashboard Enhancements Tests

Verifies that the enhanced dashboard:
- renders all new sections (paper cycle, performance, recent trades, trade grades,
  intel feed, signal runs, alert service)
- renders the new /dashboard/positions sub-page
- includes auto-refresh meta tag
- renders navigation links
- handles empty/None state gracefully (muted placeholders)
- correctly reflects ApiAppState content in the HTML response
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
# Dependency override helpers
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
# Fake model factories
# ---------------------------------------------------------------------------

def _make_portfolio_state(
    cash: float = 90_000,
    positions: dict | None = None,
) -> Any:
    from services.portfolio_engine.models import PortfolioState
    return PortfolioState(
        cash=Decimal(str(cash)),
        positions=positions or {},
        start_of_day_equity=Decimal(str(cash * 0.99)),
        high_water_mark=Decimal(str(cash * 1.01)),
    )


def _make_position(
    ticker: str = "AAPL",
    quantity: float = 10,
    entry: float = 150.0,
    current: float = 155.0,
) -> Any:
    from services.portfolio_engine.models import PortfolioPosition
    return PortfolioPosition(
        ticker=ticker,
        quantity=Decimal(str(quantity)),
        avg_entry_price=Decimal(str(entry)),
        current_price=Decimal(str(current)),
        opened_at=dt.datetime(2026, 3, 15, 9, 35, tzinfo=dt.UTC),
        thesis_summary="test thesis",
        strategy_key="momentum_v1",
    )


def _make_closed_trade(
    ticker: str = "NVDA",
    pnl: float = 500.0,
    pnl_pct: float = 0.05,
    reason: str = "stop_loss",
    is_winner: bool = True,
) -> Any:
    from services.portfolio_engine.models import ActionType, ClosedTrade
    trade = ClosedTrade(
        ticker=ticker,
        action_type=ActionType.CLOSE,
        fill_price=Decimal("210.0"),
        avg_entry_price=Decimal("200.0"),
        quantity=Decimal("10"),
        realized_pnl=Decimal(str(pnl)),
        realized_pnl_pct=Decimal(str(pnl_pct)),
        reason=reason,
        opened_at=dt.datetime(2026, 3, 10, tzinfo=dt.UTC),
        closed_at=dt.datetime(2026, 3, 18, tzinfo=dt.UTC),
        hold_duration_days=8,
    )
    return trade


def _make_trade_grade(ticker: str = "NVDA", grade: str = "A") -> Any:
    from services.evaluation_engine.models import PositionGrade
    return PositionGrade(
        ticker=ticker,
        strategy_key="momentum_v1",
        realized_pnl=Decimal("500.0"),
        realized_pnl_pct=Decimal("0.05"),
        holding_days=8,
        is_winner=True,
        exit_reason="stop_loss",
        grade=grade,
    )


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
        hit_rate=Decimal("0.60"),
        avg_winner_pct=Decimal("0.04"),
        avg_loser_pct=Decimal("-0.02"),
        current_drawdown_pct=Decimal("0.02"),
        max_drawdown_pct=Decimal("0.05"),
        benchmark_comparison=bench,
        attribution=attribution,
        mode="paper",
    )


# Minimal alert service stub
class _FakeAlertService:
    pass


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
# TestDashboardHomeBasics  (pre-existing behaviour preserved)
# ===========================================================================

class TestDashboardHomeBasics:
    def test_returns_200(self):
        _override_state(_empty_state())
        _override_settings(_default_settings())
        with TestClient(app) as client:
            assert client.get("/dashboard/").status_code == 200

    def test_content_type_is_html(self):
        _override_state(_empty_state())
        _override_settings(_default_settings())
        with TestClient(app) as client:
            assert "text/html" in client.get("/dashboard/").headers["content-type"]

    def test_shows_title(self):
        _override_state(_empty_state())
        _override_settings(_default_settings())
        with TestClient(app) as client:
            assert "APIS" in client.get("/dashboard/").text

    def test_shows_operating_mode(self):
        _override_state(_empty_state())
        _override_settings(_default_settings(operating_mode="research"))
        with TestClient(app) as client:
            assert "research" in client.get("/dashboard/").text.lower()

    def test_shows_kill_switch_off(self):
        _override_state(_empty_state())
        _override_settings(_default_settings(is_kill_switch_active=False))
        with TestClient(app) as client:
            assert "off" in client.get("/dashboard/").text.lower()

    def test_shows_kill_switch_active_warning(self):
        _override_state(_empty_state())
        _override_settings(_default_settings(is_kill_switch_active=True))
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
            assert "active" in body.lower() or "warn" in body.lower()


# ===========================================================================
# TestDashboardAutoRefresh
# ===========================================================================

class TestDashboardAutoRefresh:
    def test_home_has_meta_refresh(self):
        _override_state(_empty_state())
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert 'http-equiv="refresh"' in body

    def test_home_refresh_interval_is_60(self):
        _override_state(_empty_state())
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert 'content="60"' in body


# ===========================================================================
# TestDashboardNavigation
# ===========================================================================

class TestDashboardNavigation:
    def test_home_has_nav_overview_link(self):
        _override_state(_empty_state())
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "/dashboard/" in body

    def test_home_has_nav_positions_link(self):
        _override_state(_empty_state())
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "/dashboard/positions" in body


# ===========================================================================
# TestDashboardPaperCycleSection
# ===========================================================================

class TestDashboardPaperCycleSection:
    def test_shows_cycle_count(self):
        state = _empty_state()
        state.paper_cycle_count = 42
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "42" in body

    def test_shows_broker_auth_ok(self):
        state = _empty_state()
        state.broker_auth_expired = False
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "ok" in body.lower()

    def test_shows_broker_auth_expired_warning(self):
        state = _empty_state()
        state.broker_auth_expired = True
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "expired" in body.lower()

    def test_shows_runtime_kill_switch_active(self):
        state = _empty_state()
        state.kill_switch_active = True
        state.kill_switch_activated_by = "10.0.0.1"
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "10.0.0.1" in body

    def test_shows_loop_active_flag(self):
        state = _empty_state()
        state.paper_loop_active = True
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "yes" in body.lower()


# ===========================================================================
# TestDashboardPortfolioSection
# ===========================================================================

class TestDashboardPortfolioSection:
    def test_muted_message_when_no_portfolio(self):
        _override_state(_empty_state())
        _override_settings(_default_settings())
        with TestClient(app) as client:
            assert "No portfolio data yet" in client.get("/dashboard/").text

    def test_shows_equity(self):
        # equity = cash + gross_exposure; with no positions, equity == cash
        state = _empty_state()
        state.portfolio_state = _make_portfolio_state(cash=123_456.78)
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "123,456.78" in body

    def test_shows_open_position_count(self):
        pos = _make_position("MSFT")
        state = _empty_state()
        state.portfolio_state = _make_portfolio_state(positions={"MSFT": pos})
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        # 1 open position in the portfolio section
        assert "Open Positions" in body


# ===========================================================================
# TestDashboardPerformanceSection
# ===========================================================================

class TestDashboardPerformanceSection:
    def test_muted_message_when_no_closed_trades(self):
        _override_state(_empty_state())
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "No closed trades yet" in body

    def test_shows_total_realized_pnl(self):
        state = _empty_state()
        state.closed_trades = [
            _make_closed_trade("NVDA", pnl=200.0),
            _make_closed_trade("TSLA", pnl=300.0),
        ]
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "500.00" in body

    def test_shows_win_rate(self):
        state = _empty_state()
        state.closed_trades = [
            _make_closed_trade("NVDA", pnl=200.0, is_winner=True),
            _make_closed_trade("TSLA", pnl=-50.0, is_winner=False),
        ]
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "50.00%" in body

    def test_shows_trade_count(self):
        state = _empty_state()
        state.closed_trades = [_make_closed_trade() for _ in range(7)]
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "7" in body


# ===========================================================================
# TestDashboardRecentTradesSection
# ===========================================================================

class TestDashboardRecentTradesSection:
    def test_shows_ticker_in_recent_trades(self):
        state = _empty_state()
        state.closed_trades = [_make_closed_trade("GOOGL")]
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "GOOGL" in body

    def test_only_shows_last_5_trades(self):
        state = _empty_state()
        state.closed_trades = [_make_closed_trade(f"TK{i}") for i in range(10)]
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        # The last 5 in reversed order should appear; TK9 is the last appended
        assert "TK9" in body
        # TK0 should NOT appear (too far back)
        assert "TK0" not in body

    def test_shows_winner_loser_indicator(self):
        state = _empty_state()
        state.closed_trades = [
            _make_closed_trade("WIN", pnl=100.0, is_winner=True),
            _make_closed_trade("LOS", pnl=-50.0, is_winner=False),
        ]
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert ">W<" in body
        assert ">L<" in body


# ===========================================================================
# TestDashboardTradeGradesSection
# ===========================================================================

class TestDashboardTradeGradesSection:
    def test_muted_when_no_grades(self):
        _override_state(_empty_state())
        _override_settings(_default_settings())
        with TestClient(app) as client:
            assert "No trade grades yet" in client.get("/dashboard/").text

    def test_shows_grade_distribution(self):
        state = _empty_state()
        state.trade_grades = [
            _make_trade_grade("NVDA", "A"),
            _make_trade_grade("TSLA", "B"),
            _make_trade_grade("MSFT", "A"),
        ]
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "Grade A" in body
        assert "Grade B" in body

    def test_shows_total_graded_count(self):
        state = _empty_state()
        state.trade_grades = [_make_trade_grade() for _ in range(5)]
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "5" in body


# ===========================================================================
# TestDashboardIntelSection
# ===========================================================================

class TestDashboardIntelSection:
    def test_shows_macro_regime(self):
        state = _empty_state()
        state.current_macro_regime = "RISK_OFF"
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "RISK_OFF" in body

    def test_shows_policy_signal_count(self):
        state = _empty_state()
        state.latest_policy_signals = ["sig1", "sig2", "sig3"]
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "3" in body

    def test_shows_news_insight_count(self):
        state = _empty_state()
        state.latest_news_insights = ["n1", "n2"]
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "2" in body

    def test_shows_fundamentals_count(self):
        state = _empty_state()
        state.latest_fundamentals = {"AAPL": object(), "MSFT": object()}
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "2" in body


# ===========================================================================
# TestDashboardSignalRunsSection
# ===========================================================================

class TestDashboardSignalRunsSection:
    def test_shows_dash_when_no_run_ids(self):
        _override_state(_empty_state())
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        # "—" appears for both signal and ranking run IDs
        assert "—" in body

    def test_shows_truncated_signal_run_id(self):
        state = _empty_state()
        state.last_signal_run_id = "abcd1234-5678-90ab-cdef-abcdef123456"
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "abcd1234-5678-90" in body

    def test_shows_truncated_ranking_run_id(self):
        state = _empty_state()
        state.last_ranking_run_id = "feedbeef-dead-beef-feed-beefdeadbeef"
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "feedbeef-dead-bee" in body


# ===========================================================================
# TestDashboardAlertServiceSection
# ===========================================================================

class TestDashboardAlertServiceSection:
    def test_shows_webhook_not_configured(self):
        state = _empty_state()
        state.alert_service = None
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "no" in body.lower()

    def test_shows_webhook_configured(self):
        state = _empty_state()
        state.alert_service = _FakeAlertService()
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "yes" in body.lower()


# ===========================================================================
# TestDashboardExistingSections  (scorecard, rankings, improvement still work)
# ===========================================================================

class TestDashboardExistingSections:
    def test_shows_no_rankings_muted(self):
        _override_state(_empty_state())
        _override_settings(_default_settings())
        with TestClient(app) as client:
            assert "No rankings available yet" in client.get("/dashboard/").text

    def test_shows_ranking_ticker(self):
        state = _empty_state()
        state.latest_rankings = [_make_ranked_result("NVDA", 0.90)]
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            assert "NVDA" in client.get("/dashboard/").text

    def test_shows_scorecard_date(self):
        state = _empty_state()
        state.latest_scorecard = _make_scorecard()
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            assert "2026-03-17" in client.get("/dashboard/").text

    def test_shows_proposal_count(self):
        state = _empty_state()
        state.improvement_proposals = ["p1", "p2"]
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            assert "2" in client.get("/dashboard/").text

    def test_shows_promoted_versions(self):
        state = _empty_state()
        state.promoted_versions = {"ranking_engine": "v1.2.0"}
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/").text
        assert "ranking_engine" in body
        assert "v1.2.0" in body


# ===========================================================================
# TestDashboardPositionsPage
# ===========================================================================

class TestDashboardPositionsPage:
    def test_positions_returns_200(self):
        _override_state(_empty_state())
        _override_settings(_default_settings())
        with TestClient(app) as client:
            assert client.get("/dashboard/positions").status_code == 200

    def test_positions_content_type_is_html(self):
        _override_state(_empty_state())
        _override_settings(_default_settings())
        with TestClient(app) as client:
            resp = client.get("/dashboard/positions")
        assert "text/html" in resp.headers["content-type"]

    def test_positions_muted_when_no_portfolio(self):
        _override_state(_empty_state())
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/positions").text
        assert "No open positions" in body

    def test_positions_muted_when_empty_positions(self):
        state = _empty_state()
        state.portfolio_state = _make_portfolio_state()
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/positions").text
        assert "No open positions" in body

    def test_positions_shows_ticker(self):
        pos = _make_position("AMZN", quantity=5, entry=180.0, current=190.0)
        state = _empty_state()
        state.portfolio_state = _make_portfolio_state(positions={"AMZN": pos})
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/positions").text
        assert "AMZN" in body

    def test_positions_shows_market_value(self):
        pos = _make_position("GOOG", quantity=10, entry=150.0, current=160.0)
        # market_value = 10 * 160 = 1600
        state = _empty_state()
        state.portfolio_state = _make_portfolio_state(positions={"GOOG": pos})
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/positions").text
        assert "1,600.00" in body

    def test_positions_shows_unrealized_pnl(self):
        pos = _make_position("META", quantity=5, entry=200.0, current=210.0)
        # unrealized_pnl = (210 - 200) * 5 = 50
        state = _empty_state()
        state.portfolio_state = _make_portfolio_state(positions={"META": pos})
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/positions").text
        assert "50.00" in body

    def test_positions_shows_opened_at(self):
        pos = _make_position("MSFT")
        state = _empty_state()
        state.portfolio_state = _make_portfolio_state(positions={"MSFT": pos})
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/positions").text
        assert "2026-03-15" in body

    def test_positions_shows_position_count_in_heading(self):
        positions = {
            "AAPL": _make_position("AAPL"),
            "TSLA": _make_position("TSLA"),
        }
        state = _empty_state()
        state.portfolio_state = _make_portfolio_state(positions=positions)
        _override_state(state)
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/positions").text
        assert "Open Positions (2)" in body

    def test_positions_has_auto_refresh(self):
        _override_state(_empty_state())
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/positions").text
        assert 'http-equiv="refresh"' in body

    def test_positions_has_nav_links(self):
        _override_state(_empty_state())
        _override_settings(_default_settings())
        with TestClient(app) as client:
            body = client.get("/dashboard/positions").text
        assert "/dashboard/" in body
        assert "/dashboard/positions" in body
