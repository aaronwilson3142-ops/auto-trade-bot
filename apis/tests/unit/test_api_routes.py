"""
Gate G QA — Phase 8: FastAPI Routes

Tests cover:
  - /health and /system/status (system routes)
  - /api/v1/recommendations/latest  and /{ticker}
  - /api/v1/portfolio, /positions, /positions/{ticker}
  - /api/v1/actions/proposed  and POST /actions/review
  - /api/v1/evaluation/latest  and /history
  - /api/v1/reports/daily/latest  and /history
  - /api/v1/config/active  and /risk/status
  - Response schema validation (Pydantic models)

All tests run fully in-memory with dependency overrides.
No database, no broker, no external API calls.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.state import ApiAppState, get_app_state
from config.settings import OperatingMode, Settings, get_settings


# ---------------------------------------------------------------------------
# Test domain-object factories (real dataclasses, no mocks)
# ---------------------------------------------------------------------------

def _make_ranked_result(
    rank: int = 1,
    ticker: str = "AAPL",
    score: float = 0.75,
    contains_rumor: bool = False,
    action: str = "buy",
) -> Any:
    """Return a minimal fake RankedResult-compatible dataclass."""
    from services.ranking_engine.models import RankedResult
    return RankedResult(
        rank_position=rank,
        security_id=None,
        ticker=ticker,
        composite_score=Decimal(str(score)),
        portfolio_fit_score=Decimal("0.80"),
        recommended_action=action,
        target_horizon="medium_term",
        thesis_summary="AI infrastructure momentum",
        disconfirming_factors="Valuation stretched",
        sizing_hint_pct=Decimal("0.05"),
        source_reliability_tier="secondary_verified",
        contains_rumor=contains_rumor,
        contributing_signals=[],
    )


def _make_portfolio_state(
    cash: float = 90_000.0,
    tickers: list[str] | None = None,
) -> Any:
    from services.portfolio_engine.models import PortfolioPosition, PortfolioState
    positions = {}
    for ticker in (tickers or ["AAPL"]):
        positions[ticker] = PortfolioPosition(
            ticker=ticker,
            quantity=Decimal("100"),
            avg_entry_price=Decimal("150.00"),
            current_price=Decimal("155.00"),
            opened_at=dt.datetime(2026, 3, 1, tzinfo=dt.timezone.utc),
        )
    return PortfolioState(
        cash=Decimal(str(cash)),
        positions=positions,
        start_of_day_equity=Decimal("105_000"),
        high_water_mark=Decimal("110_000"),
    )


def _make_scorecard(date: dt.date | None = None) -> Any:
    from services.evaluation_engine.models import (
        BenchmarkComparison,
        DailyScorecard,
        DrawdownMetrics,
        PerformanceAttribution,
    )
    bench = BenchmarkComparison(
        portfolio_return=Decimal("0.005"),
        benchmark_returns={"SPY": Decimal("0.003"), "QQQ": Decimal("0.004")},
        differentials={"SPY": Decimal("0.002"), "QQQ": Decimal("0.001")},
    )
    dd = DrawdownMetrics(
        max_drawdown=Decimal("0.05"),
        current_drawdown=Decimal("0.02"),
        high_water_mark=Decimal("110_000"),
        recovery_time_est_days=None,
    )
    attribution = PerformanceAttribution(
        by_ticker=[], by_strategy=[], by_theme=[]
    )
    return DailyScorecard(
        scorecard_date=date or dt.date(2026, 3, 17),
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


def _make_daily_report() -> Any:
    from services.reporting.models import (
        DailyOperationalReport,
        FillReconciliationSummary,
    )
    recon = FillReconciliationSummary(records=[])
    return DailyOperationalReport(
        report_date=dt.date(2026, 3, 17),
        report_timestamp=dt.datetime(2026, 3, 17, 18, 0, tzinfo=dt.timezone.utc),
        equity=Decimal("105_500"),
        cash=Decimal("90_000"),
        gross_exposure=Decimal("15_500"),
        position_count=1,
        realized_pnl=Decimal("200"),
        unrealized_pnl=Decimal("300"),
        daily_return_pct=Decimal("0.005"),
        orders_submitted=2,
        orders_filled=2,
        orders_cancelled=0,
        orders_rejected=0,
        reconciliation=recon,
        scorecard_grade="B",
        benchmark_differentials={"SPY": Decimal("0.002"), "QQQ": Decimal("0.001")},
        improvement_proposals_generated=1,
        improvement_proposals_promoted=0,
        narrative="Solid day. Two fills executed cleanly.",
    )


def _make_portfolio_action() -> Any:
    from services.portfolio_engine.models import ActionType, PortfolioAction
    return PortfolioAction(
        action_type=ActionType.OPEN,
        ticker="NVDA",
        reason="Ranked #1",
        target_notional=Decimal("5000"),
        thesis_summary="AI chip demand",
    )


def _make_settings(**overrides) -> Settings:
    kwargs = dict(
        env="development",
        operating_mode="research",
        kill_switch=False,
        max_positions=10,
        daily_loss_limit_pct=0.02,
        weekly_drawdown_limit_pct=0.05,
        max_single_name_pct=0.20,
        max_sector_pct=0.40,
        max_thematic_pct=0.50,
    )
    kwargs.update(overrides)
    return Settings(**kwargs)


def _client_with_state(state: ApiAppState, settings: Settings | None = None) -> TestClient:
    """Return a TestClient with dependency overrides for the given state."""
    _settings = settings or _make_settings()

    def _get_state() -> ApiAppState:
        return state

    def _get_settings() -> Settings:
        return _settings

    app.dependency_overrides[get_app_state] = _get_state
    app.dependency_overrides[get_settings] = _get_settings
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# TestHealthAndSystemRoutes
# ---------------------------------------------------------------------------

class TestHealthAndSystemRoutes:
    def test_health_returns_ok(self):
        from unittest.mock import patch, MagicMock
        state = ApiAppState()
        client = _client_with_state(state)
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute = MagicMock(return_value=None)
        mock_engine.connect.return_value = mock_conn
        with patch("infra.db.session.engine", mock_engine):
            resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_health_includes_service_field(self):
        state = ApiAppState()
        client = _client_with_state(state)
        resp = client.get("/health")
        data = resp.json()
        assert data["service"] == "api"

    def test_health_includes_timestamp(self):
        state = ApiAppState()
        client = _client_with_state(state)
        resp = client.get("/health")
        assert "timestamp" in resp.json()

    def test_health_includes_mode(self):
        # /health uses a module-level settings instance (not DI) so we only
        # assert the field is present and is a valid operating mode string.
        state = ApiAppState()
        client = _client_with_state(state)
        resp = client.get("/health")
        assert "mode" in resp.json()
        assert resp.json()["mode"] in ("research", "backtest", "paper", "human_approved")

    def test_system_status_returns_env(self):
        state = ApiAppState()
        client = _client_with_state(state, _make_settings(env="development"))
        resp = client.get("/system/status")
        assert resp.status_code == 200
        assert resp.json()["env"] == "development"

    def test_system_status_includes_kill_switch(self):
        state = ApiAppState()
        client = _client_with_state(state, _make_settings(kill_switch=False))
        resp = client.get("/system/status")
        assert resp.json()["kill_switch"] is False

    def test_system_status_includes_max_positions(self):
        state = ApiAppState()
        client = _client_with_state(state)
        resp = client.get("/system/status")
        assert resp.json()["max_positions"] == 10


# ---------------------------------------------------------------------------
# TestRecommendationsRouter
# ---------------------------------------------------------------------------

class TestRecommendationsRouter:
    def test_latest_empty_state_returns_empty_list(self):
        state = ApiAppState()
        client = _client_with_state(state)
        resp = client.get("/api/v1/recommendations/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["items"] == []

    def test_latest_returns_all_rankings(self):
        state = ApiAppState()
        state.latest_rankings = [_make_ranked_result(rank=i, ticker=f"T{i}") for i in range(1, 4)]
        client = _client_with_state(state)
        resp = client.get("/api/v1/recommendations/latest")
        data = resp.json()
        assert data["count"] == 3
        assert len(data["items"]) == 3

    def test_latest_limit_filter(self):
        state = ApiAppState()
        state.latest_rankings = [_make_ranked_result(rank=i, ticker=f"T{i}") for i in range(1, 11)]
        client = _client_with_state(state)
        resp = client.get("/api/v1/recommendations/latest?limit=3")
        data = resp.json()
        assert data["count"] == 3

    def test_latest_min_score_filter(self):
        state = ApiAppState()
        state.latest_rankings = [
            _make_ranked_result(rank=1, ticker="HIGH", score=0.90),
            _make_ranked_result(rank=2, ticker="LOW",  score=0.30),
        ]
        client = _client_with_state(state)
        resp = client.get("/api/v1/recommendations/latest?min_score=0.50")
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["ticker"] == "HIGH"

    def test_latest_contains_rumor_filter_false(self):
        state = ApiAppState()
        state.latest_rankings = [
            _make_ranked_result(rank=1, ticker="CLEAN", contains_rumor=False),
            _make_ranked_result(rank=2, ticker="RUMOR", contains_rumor=True),
        ]
        client = _client_with_state(state)
        resp = client.get("/api/v1/recommendations/latest?contains_rumor=false")
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["ticker"] == "CLEAN"

    def test_latest_contains_rumor_filter_true(self):
        state = ApiAppState()
        state.latest_rankings = [
            _make_ranked_result(rank=1, ticker="CLEAN", contains_rumor=False),
            _make_ranked_result(rank=2, ticker="RUMOR", contains_rumor=True),
        ]
        client = _client_with_state(state)
        resp = client.get("/api/v1/recommendations/latest?contains_rumor=true")
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["ticker"] == "RUMOR"

    def test_latest_action_filter(self):
        state = ApiAppState()
        state.latest_rankings = [
            _make_ranked_result(rank=1, ticker="BUY1", action="buy"),
            _make_ranked_result(rank=2, ticker="WATCH1", action="watch"),
        ]
        client = _client_with_state(state)
        resp = client.get("/api/v1/recommendations/latest?recommended_action=buy")
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["ticker"] == "BUY1"

    def test_latest_includes_run_id(self):
        state = ApiAppState()
        state.ranking_run_id = "run-abc-123"
        client = _client_with_state(state)
        resp = client.get("/api/v1/recommendations/latest")
        assert resp.json()["run_id"] == "run-abc-123"

    def test_ticker_lookup_found(self):
        state = ApiAppState()
        state.latest_rankings = [_make_ranked_result(rank=1, ticker="AAPL")]
        client = _client_with_state(state)
        resp = client.get("/api/v1/recommendations/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is True
        assert data["item"]["ticker"] == "AAPL"

    def test_ticker_lookup_not_found(self):
        state = ApiAppState()
        client = _client_with_state(state)
        resp = client.get("/api/v1/recommendations/MISSING")
        data = resp.json()
        assert data["found"] is False
        assert data["item"] is None

    def test_ticker_lookup_case_insensitive(self):
        state = ApiAppState()
        state.latest_rankings = [_make_ranked_result(rank=1, ticker="NVDA")]
        client = _client_with_state(state)
        resp = client.get("/api/v1/recommendations/nvda")
        assert resp.json()["found"] is True

    def test_item_fields_present(self):
        state = ApiAppState()
        state.latest_rankings = [_make_ranked_result(rank=1, ticker="MSFT")]
        client = _client_with_state(state)
        resp = client.get("/api/v1/recommendations/MSFT")
        item = resp.json()["item"]
        for key in ["rank_position", "ticker", "composite_score", "recommended_action",
                    "thesis_summary", "contains_rumor", "source_reliability_tier"]:
            assert key in item


# ---------------------------------------------------------------------------
# TestPortfolioRouter
# ---------------------------------------------------------------------------

class TestPortfolioRouter:
    def test_portfolio_empty_state_returns_zeros(self):
        state = ApiAppState()
        client = _client_with_state(state)
        resp = client.get("/api/v1/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cash"] == 0.0
        assert data["equity"] == 0.0
        assert data["position_count"] == 0
        assert data["positions"] == []

    def test_portfolio_populated_returns_cash_equity(self):
        state = ApiAppState()
        state.portfolio_state = _make_portfolio_state(cash=90_000.0)
        client = _client_with_state(state)
        resp = client.get("/api/v1/portfolio")
        data = resp.json()
        assert data["cash"] == pytest.approx(90_000.0)
        assert data["equity"] > 0

    def test_portfolio_positions_included(self):
        state = ApiAppState()
        state.portfolio_state = _make_portfolio_state(tickers=["AAPL", "MSFT"])
        client = _client_with_state(state)
        resp = client.get("/api/v1/portfolio")
        data = resp.json()
        assert data["position_count"] == 2
        assert len(data["positions"]) == 2

    def test_portfolio_includes_drawdown_pct(self):
        state = ApiAppState()
        state.portfolio_state = _make_portfolio_state()
        client = _client_with_state(state)
        resp = client.get("/api/v1/portfolio")
        assert "drawdown_pct" in resp.json()

    def test_positions_empty_state(self):
        state = ApiAppState()
        client = _client_with_state(state)
        resp = client.get("/api/v1/portfolio/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["positions"] == []

    def test_positions_populated(self):
        state = ApiAppState()
        state.portfolio_state = _make_portfolio_state(tickers=["AAPL", "GOOG"])
        client = _client_with_state(state)
        resp = client.get("/api/v1/portfolio/positions")
        data = resp.json()
        assert data["count"] == 2

    def test_position_detail_found(self):
        state = ApiAppState()
        state.portfolio_state = _make_portfolio_state(tickers=["AAPL"])
        client = _client_with_state(state)
        resp = client.get("/api/v1/portfolio/positions/AAPL")
        data = resp.json()
        assert data["found"] is True
        assert data["position"]["ticker"] == "AAPL"

    def test_position_detail_not_found(self):
        state = ApiAppState()
        state.portfolio_state = _make_portfolio_state(tickers=["AAPL"])
        client = _client_with_state(state)
        resp = client.get("/api/v1/portfolio/positions/NVDA")
        data = resp.json()
        assert data["found"] is False
        assert data["position"] is None

    def test_position_detail_case_insensitive(self):
        state = ApiAppState()
        state.portfolio_state = _make_portfolio_state(tickers=["AAPL"])
        client = _client_with_state(state)
        resp = client.get("/api/v1/portfolio/positions/aapl")
        assert resp.json()["found"] is True

    def test_position_detail_empty_portfolio(self):
        state = ApiAppState()
        client = _client_with_state(state)
        resp = client.get("/api/v1/portfolio/positions/AAPL")
        assert resp.json()["found"] is False

    def test_position_fields_present(self):
        state = ApiAppState()
        state.portfolio_state = _make_portfolio_state(tickers=["AAPL"])
        client = _client_with_state(state)
        resp = client.get("/api/v1/portfolio/positions/AAPL")
        pos = resp.json()["position"]
        for key in ["ticker", "quantity", "avg_entry_price", "current_price",
                    "market_value", "cost_basis", "unrealized_pnl"]:
            assert key in pos


# ---------------------------------------------------------------------------
# TestActionsRouter
# ---------------------------------------------------------------------------

class TestActionsRouter:
    def test_proposed_actions_empty_state(self):
        state = ApiAppState()
        client = _client_with_state(state)
        resp = client.get("/api/v1/actions/proposed")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["actions"] == []

    def test_proposed_actions_populated(self):
        state = ApiAppState()
        state.proposed_actions = [_make_portfolio_action()]
        client = _client_with_state(state)
        resp = client.get("/api/v1/actions/proposed")
        data = resp.json()
        assert data["count"] == 1
        assert data["actions"][0]["ticker"] == "NVDA"

    def test_proposed_actions_includes_mode(self):
        state = ApiAppState()
        settings = _make_settings(operating_mode="paper")
        client = _client_with_state(state, settings)
        resp = client.get("/api/v1/actions/proposed")
        assert resp.json()["mode"] == "paper"

    def test_review_blocked_in_research_mode(self):
        state = ApiAppState()
        settings = _make_settings(operating_mode="research")
        client = _client_with_state(state, settings)
        resp = client.post(
            "/api/v1/actions/review",
            json={"action_ids": ["id-1"], "decision": "approve"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["error"]["code"] == "MODE_RESTRICTION"

    def test_review_blocked_in_backtest_mode(self):
        state = ApiAppState()
        settings = _make_settings(operating_mode="backtest")
        client = _client_with_state(state, settings)
        resp = client.post(
            "/api/v1/actions/review",
            json={"action_ids": ["id-1"], "decision": "approve"},
        )
        assert resp.status_code == 403

    def test_review_allowed_in_paper_mode(self):
        state = ApiAppState()
        settings = _make_settings(operating_mode="paper")
        client = _client_with_state(state, settings)
        resp = client.post(
            "/api/v1/actions/review",
            json={"action_ids": ["id-1", "id-2"], "decision": "approve"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["processed"] == 2
        assert data["decision"] == "approve"

    def test_review_allowed_in_human_approved_mode(self):
        state = ApiAppState()
        settings = _make_settings(operating_mode="human_approved")
        client = _client_with_state(state, settings)
        resp = client.post(
            "/api/v1/actions/review",
            json={"action_ids": ["id-1"], "decision": "reject"},
        )
        assert resp.status_code == 200
        assert resp.json()["decision"] == "reject"

    def test_review_invalid_decision_returns_422(self):
        state = ApiAppState()
        settings = _make_settings(operating_mode="paper")
        client = _client_with_state(state, settings)
        resp = client.post(
            "/api/v1/actions/review",
            json={"action_ids": ["id-1"], "decision": "maybe"},
        )
        assert resp.status_code == 422

    def test_review_empty_action_ids(self):
        state = ApiAppState()
        settings = _make_settings(operating_mode="paper")
        client = _client_with_state(state, settings)
        resp = client.post(
            "/api/v1/actions/review",
            json={"action_ids": [], "decision": "approve"},
        )
        assert resp.status_code == 200
        assert resp.json()["processed"] == 0

    def test_action_fields_present(self):
        state = ApiAppState()
        state.proposed_actions = [_make_portfolio_action()]
        client = _client_with_state(state)
        resp = client.get("/api/v1/actions/proposed")
        action = resp.json()["actions"][0]
        for key in ["action_type", "ticker", "reason", "target_notional", "risk_approved"]:
            assert key in action


# ---------------------------------------------------------------------------
# TestActionsExecutionEngine — execution engine wired to state
# ---------------------------------------------------------------------------

def _make_execution_engine():
    """Return a live ExecutionEngineService backed by PaperBrokerAdapter."""
    from decimal import Decimal as D
    from broker_adapters.paper.adapter import PaperBrokerAdapter
    from config.settings import Settings
    from services.execution_engine.service import ExecutionEngineService

    broker = PaperBrokerAdapter(
        starting_cash=D("100000.00"),
        slippage_bps=0,
        fill_immediately=True,
        market_open=True,
    )
    broker.connect()
    broker.set_price("NVDA", D("500.00"))
    broker.set_price("AAPL", D("175.00"))

    settings = _make_settings(operating_mode="paper")
    return ExecutionEngineService(settings=settings, broker=broker)


class TestActionsExecutionEngine:
    """Tests for the wired execution engine path in POST /actions/review."""

    def test_approve_with_engine_executes_matched_actions(self):
        """Matching action ID triggers actual execution; response includes execution_results."""
        from services.portfolio_engine.models import ActionType, PortfolioAction
        from decimal import Decimal

        action = PortfolioAction(
            action_type=ActionType.OPEN,
            ticker="NVDA",
            reason="ranked #1",
            target_notional=Decimal("5000"),
            thesis_summary="AI chip demand",
            risk_approved=True,
        )
        state = ApiAppState()
        state.proposed_actions = [action]
        state.execution_engine = _make_execution_engine()
        settings = _make_settings(operating_mode="paper")
        client = _client_with_state(state, settings)

        resp = client.post(
            "/api/v1/actions/review",
            json={
                "action_ids": [action.id],
                "decision": "approve",
                "prices": {"NVDA": 500.00},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["processed"] == 1
        assert data["decision"] == "approve"
        assert len(data["execution_results"]) == 1
        result = data["execution_results"][0]
        assert result["ticker"] == "NVDA"
        assert result["status"] == "filled"

    def test_approve_with_engine_removes_action_from_proposed(self):
        """Executed actions are removed from state.proposed_actions."""
        from services.portfolio_engine.models import ActionType, PortfolioAction
        from decimal import Decimal

        action = PortfolioAction(
            action_type=ActionType.OPEN,
            ticker="NVDA",
            reason="ranked #1",
            target_notional=Decimal("5000"),
            thesis_summary="AI chip",
            risk_approved=True,
        )
        state = ApiAppState()
        state.proposed_actions = [action]
        state.execution_engine = _make_execution_engine()
        settings = _make_settings(operating_mode="paper")
        client = _client_with_state(state, settings)

        client.post(
            "/api/v1/actions/review",
            json={"action_ids": [action.id], "decision": "approve", "prices": {"NVDA": 500.0}},
        )
        assert len(state.proposed_actions) == 0

    def test_approve_with_engine_unmatched_ids_returns_empty_results(self):
        """Action IDs that don't match any proposed action return empty execution_results."""
        state = ApiAppState()
        state.execution_engine = _make_execution_engine()
        settings = _make_settings(operating_mode="paper")
        client = _client_with_state(state, settings)

        resp = client.post(
            "/api/v1/actions/review",
            json={"action_ids": ["nonexistent-id"], "decision": "approve"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_results"] == []

    def test_approve_without_engine_falls_back_to_intent(self):
        """When no execution engine is set, approval is recorded as intent only."""
        state = ApiAppState()
        settings = _make_settings(operating_mode="paper")
        client = _client_with_state(state, settings)

        resp = client.post(
            "/api/v1/actions/review",
            json={"action_ids": ["id-1"], "decision": "approve"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["processed"] == 1
        assert data["execution_results"] == []

    def test_reject_removes_matching_proposed_actions(self):
        """Reject removes matched actions from proposed queue by action.id."""
        from services.portfolio_engine.models import ActionType, PortfolioAction
        from decimal import Decimal

        action1 = PortfolioAction(
            action_type=ActionType.OPEN,
            ticker="AAPL",
            reason="ranked #2",
            target_notional=Decimal("3000"),
            thesis_summary="iPhone cycle",
            risk_approved=True,
        )
        action2 = PortfolioAction(
            action_type=ActionType.OPEN,
            ticker="NVDA",
            reason="ranked #1",
            target_notional=Decimal("5000"),
            thesis_summary="AI chip",
            risk_approved=True,
        )
        state = ApiAppState()
        state.proposed_actions = [action1, action2]
        settings = _make_settings(operating_mode="paper")
        client = _client_with_state(state, settings)

        resp = client.post(
            "/api/v1/actions/review",
            json={"action_ids": [action1.id], "decision": "reject"},
        )
        assert resp.status_code == 200
        assert resp.json()["decision"] == "reject"
        # AAPL removed, NVDA remains
        assert len(state.proposed_actions) == 1
        assert state.proposed_actions[0].ticker == "NVDA"

    def test_kill_switch_blocks_execution(self):
        """Kill switch active → execution engine returns BLOCKED status."""
        from services.portfolio_engine.models import ActionType, PortfolioAction
        from decimal import Decimal

        action = PortfolioAction(
            action_type=ActionType.OPEN,
            ticker="NVDA",
            reason="ranked #1",
            target_notional=Decimal("5000"),
            thesis_summary="AI chip",
            risk_approved=True,
        )
        state = ApiAppState()
        state.proposed_actions = [action]
        state.execution_engine = _make_execution_engine()
        # Enable kill switch in settings
        settings = _make_settings(operating_mode="paper", kill_switch=True)
        # Patch engine settings to have kill_switch active
        state.execution_engine._settings = settings
        client = _client_with_state(state, settings)

        resp = client.post(
            "/api/v1/actions/review",
            json={"action_ids": [action.id], "decision": "approve", "prices": {"NVDA": 500.0}},
        )
        assert resp.status_code == 200
        result = resp.json()["execution_results"][0]
        assert result["status"] == "blocked"


# ---------------------------------------------------------------------------
# TestEvaluationRouter
# ---------------------------------------------------------------------------

class TestEvaluationRouter:
    def test_latest_empty_returns_not_found(self):
        state = ApiAppState()
        client = _client_with_state(state)
        resp = client.get("/api/v1/evaluation/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is False
        assert data["scorecard"] is None

    def test_latest_populated_returns_scorecard(self):
        state = ApiAppState()
        state.latest_scorecard = _make_scorecard()
        client = _client_with_state(state)
        resp = client.get("/api/v1/evaluation/latest")
        data = resp.json()
        assert data["found"] is True
        assert data["scorecard"] is not None

    def test_latest_scorecard_fields_present(self):
        state = ApiAppState()
        state.latest_scorecard = _make_scorecard()
        client = _client_with_state(state)
        sc = client.get("/api/v1/evaluation/latest").json()["scorecard"]
        for key in ["scorecard_date", "equity", "cash", "net_pnl", "hit_rate",
                    "daily_return_pct", "mode", "benchmark_returns"]:
            assert key in sc

    def test_latest_includes_run_id(self):
        state = ApiAppState()
        state.latest_scorecard = _make_scorecard()
        state.evaluation_run_id = "eval-run-42"
        client = _client_with_state(state)
        resp = client.get("/api/v1/evaluation/latest")
        assert resp.json()["run_id"] == "eval-run-42"

    def test_latest_benchmark_returns_populated(self):
        state = ApiAppState()
        state.latest_scorecard = _make_scorecard()
        client = _client_with_state(state)
        sc = client.get("/api/v1/evaluation/latest").json()["scorecard"]
        assert "SPY" in sc["benchmark_returns"]
        assert "QQQ" in sc["benchmark_returns"]

    def test_latest_benchmark_differentials_populated(self):
        state = ApiAppState()
        state.latest_scorecard = _make_scorecard()
        client = _client_with_state(state)
        sc = client.get("/api/v1/evaluation/latest").json()["scorecard"]
        assert "SPY" in sc["benchmark_differentials"]

    def test_history_empty(self):
        state = ApiAppState()
        client = _client_with_state(state)
        resp = client.get("/api/v1/evaluation/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["items"] == []

    def test_history_with_data(self):
        state = ApiAppState()
        state.evaluation_history = [
            _make_scorecard(dt.date(2026, 3, 16)),
            _make_scorecard(dt.date(2026, 3, 17)),
        ]
        client = _client_with_state(state)
        resp = client.get("/api/v1/evaluation/history")
        data = resp.json()
        assert data["count"] == 2
        assert len(data["items"]) == 2

    def test_history_count_matches_items(self):
        state = ApiAppState()
        state.evaluation_history = [_make_scorecard() for _ in range(5)]
        client = _client_with_state(state)
        data = client.get("/api/v1/evaluation/history").json()
        assert data["count"] == len(data["items"])

    def test_scorecard_equity_is_float(self):
        state = ApiAppState()
        state.latest_scorecard = _make_scorecard()
        client = _client_with_state(state)
        sc = client.get("/api/v1/evaluation/latest").json()["scorecard"]
        assert isinstance(sc["equity"], float)


# ---------------------------------------------------------------------------
# TestReportsRouter
# ---------------------------------------------------------------------------

class TestReportsRouter:
    def test_latest_report_empty_returns_not_found(self):
        state = ApiAppState()
        client = _client_with_state(state)
        resp = client.get("/api/v1/reports/daily/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is False
        assert data["report"] is None

    def test_latest_report_populated(self):
        state = ApiAppState()
        state.latest_daily_report = _make_daily_report()
        client = _client_with_state(state)
        resp = client.get("/api/v1/reports/daily/latest")
        data = resp.json()
        assert data["found"] is True
        assert data["report"] is not None

    def test_report_fields_present(self):
        state = ApiAppState()
        state.latest_daily_report = _make_daily_report()
        client = _client_with_state(state)
        rep = client.get("/api/v1/reports/daily/latest").json()["report"]
        for key in ["report_date", "equity", "orders_filled", "reconciliation_clean",
                    "scorecard_grade", "narrative", "benchmark_differentials"]:
            assert key in rep

    def test_report_reconciliation_clean_true_when_no_discrepancies(self):
        state = ApiAppState()
        state.latest_daily_report = _make_daily_report()
        client = _client_with_state(state)
        rep = client.get("/api/v1/reports/daily/latest").json()["report"]
        assert rep["reconciliation_clean"] is True

    def test_report_scorecard_grade_preserved(self):
        state = ApiAppState()
        state.latest_daily_report = _make_daily_report()
        client = _client_with_state(state)
        rep = client.get("/api/v1/reports/daily/latest").json()["report"]
        assert rep["scorecard_grade"] == "B"

    def test_report_narrative_preserved(self):
        state = ApiAppState()
        state.latest_daily_report = _make_daily_report()
        client = _client_with_state(state)
        rep = client.get("/api/v1/reports/daily/latest").json()["report"]
        assert "Two fills" in rep["narrative"]

    def test_report_benchmark_differentials(self):
        state = ApiAppState()
        state.latest_daily_report = _make_daily_report()
        client = _client_with_state(state)
        rep = client.get("/api/v1/reports/daily/latest").json()["report"]
        assert "SPY" in rep["benchmark_differentials"]

    def test_report_history_empty(self):
        state = ApiAppState()
        client = _client_with_state(state)
        resp = client.get("/api/v1/reports/daily/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0

    def test_report_history_with_data(self):
        state = ApiAppState()
        state.report_history = [_make_daily_report(), _make_daily_report()]
        client = _client_with_state(state)
        data = client.get("/api/v1/reports/daily/history").json()
        assert data["count"] == 2
        assert len(data["items"]) == 2

    def test_report_improvement_counts_present(self):
        state = ApiAppState()
        state.latest_daily_report = _make_daily_report()
        client = _client_with_state(state)
        rep = client.get("/api/v1/reports/daily/latest").json()["report"]
        assert rep["improvement_proposals_generated"] == 1
        assert rep["improvement_proposals_promoted"] == 0


# ---------------------------------------------------------------------------
# TestConfigAndRiskRouter
# ---------------------------------------------------------------------------

class TestConfigAndRiskRouter:
    def test_config_active_returns_env(self):
        state = ApiAppState()
        settings = _make_settings(env="development")
        client = _client_with_state(state, settings)
        resp = client.get("/api/v1/config/active")
        assert resp.status_code == 200
        assert resp.json()["env"] == "development"

    def test_config_active_includes_operating_mode(self):
        state = ApiAppState()
        settings = _make_settings(operating_mode="paper")
        client = _client_with_state(state, settings)
        resp = client.get("/api/v1/config/active")
        assert resp.json()["operating_mode"] == "paper"

    def test_config_active_includes_risk_limits(self):
        state = ApiAppState()
        client = _client_with_state(state)
        resp = client.get("/api/v1/config/active")
        data = resp.json()
        assert "max_positions" in data
        assert "daily_loss_limit_pct" in data
        assert "max_single_name_pct" in data

    def test_config_active_includes_promoted_versions(self):
        state = ApiAppState()
        state.promoted_versions = {"signal_engine": "v1.2.0"}
        client = _client_with_state(state)
        resp = client.get("/api/v1/config/active")
        assert resp.json()["promoted_versions"]["signal_engine"] == "v1.2.0"

    def test_config_active_kill_switch_false_by_default(self):
        state = ApiAppState()
        client = _client_with_state(state, _make_settings(kill_switch=False))
        resp = client.get("/api/v1/config/active")
        assert resp.json()["kill_switch"] is False

    def test_risk_status_idle_ok(self):
        state = ApiAppState()
        client = _client_with_state(state)
        resp = client.get("/api/v1/risk/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["loss_limit_status"] == "ok"
        assert data["drawdown_status"] == "ok"

    def test_risk_status_kill_switch_reflected(self):
        state = ApiAppState()
        settings = _make_settings(kill_switch=False)
        client = _client_with_state(state, settings)
        resp = client.get("/api/v1/risk/status")
        assert resp.json()["kill_switch_active"] is False

    def test_risk_status_current_positions_from_state(self):
        state = ApiAppState()
        state.portfolio_state = _make_portfolio_state(tickers=["AAPL", "MSFT"])
        client = _client_with_state(state)
        resp = client.get("/api/v1/risk/status")
        assert resp.json()["current_positions"] == 2

    def test_risk_status_zero_positions_when_no_portfolio(self):
        state = ApiAppState()
        client = _client_with_state(state)
        resp = client.get("/api/v1/risk/status")
        assert resp.json()["current_positions"] == 0

    def test_risk_status_active_warnings_returned(self):
        state = ApiAppState()
        state.active_warnings = ["concentration warning: AAPL > 18%"]
        client = _client_with_state(state)
        resp = client.get("/api/v1/risk/status")
        assert "concentration warning: AAPL > 18%" in resp.json()["active_warnings"]

    def test_risk_status_blocked_action_count_returned(self):
        state = ApiAppState()
        state.blocked_action_count = 3
        client = _client_with_state(state)
        resp = client.get("/api/v1/risk/status")
        assert resp.json()["blocked_action_count"] == 3

    def test_risk_status_drawdown_warning_threshold(self):
        from services.portfolio_engine.models import PortfolioPosition, PortfolioState
        # daily_pnl_pct at 0, drawdown at 82% of the 5% limit = 0.041 → warning
        state = ApiAppState()
        ps = PortfolioState(
            cash=Decimal("50_000"),
            start_of_day_equity=Decimal("100_000"),
            high_water_mark=Decimal("100_000"),  # so drawdown = 50% / 100k... let's mock
        )
        # Override drawdown_pct via patching
        from unittest.mock import PropertyMock, patch
        with patch.object(
            type(ps), "drawdown_pct", new_callable=PropertyMock, return_value=Decimal("0.041")
        ):
            state.portfolio_state = ps
            client = _client_with_state(state, _make_settings(weekly_drawdown_limit_pct=0.05))
            resp = client.get("/api/v1/risk/status")
            assert resp.json()["drawdown_status"] == "warning"


# ---------------------------------------------------------------------------
# TestResponseSchemas
# ---------------------------------------------------------------------------

class TestResponseSchemas:
    def test_recommendation_item_validates(self):
        from apps.api.schemas.recommendations import RecommendationItem
        item = RecommendationItem(
            rank_position=1,
            ticker="AAPL",
            composite_score=0.85,
            portfolio_fit_score=None,
            recommended_action="buy",
            target_horizon="medium_term",
            thesis_summary="AI momentum",
            disconfirming_factors="High valuation",
            sizing_hint_pct=0.05,
            source_reliability_tier="secondary_verified",
            contains_rumor=False,
            as_of=dt.datetime.now(tz=dt.timezone.utc),
            contributing_signals=[],
        )
        assert item.ticker == "AAPL"

    def test_portfolio_response_validates(self):
        from apps.api.schemas.portfolio import PortfolioResponse
        pr = PortfolioResponse(
            cash=90_000.0,
            equity=105_000.0,
            gross_exposure=15_000.0,
            position_count=1,
            drawdown_pct=0.0,
            daily_pnl_pct=0.005,
            positions=[],
            as_of=dt.datetime.now(tz=dt.timezone.utc),
        )
        assert pr.equity == 105_000.0

    def test_daily_scorecard_response_validates(self):
        from apps.api.schemas.evaluation import DailyScorecardResponse
        sc = DailyScorecardResponse(
            scorecard_date=dt.date(2026, 3, 17),
            equity=100_000.0,
            cash=90_000.0,
            gross_exposure=10_000.0,
            position_count=1,
            net_pnl=500.0,
            realized_pnl=0.0,
            unrealized_pnl=500.0,
            daily_return_pct=0.005,
            hit_rate=0.0,
            closed_trade_count=0,
            avg_winner_pct=0.0,
            avg_loser_pct=0.0,
            current_drawdown_pct=0.02,
            max_drawdown_pct=0.05,
            mode="paper",
            benchmark_returns={"SPY": 0.003},
            benchmark_differentials={"SPY": 0.002},
        )
        assert sc.mode == "paper"

    def test_daily_report_response_validates(self):
        from apps.api.schemas.reports import DailyReportResponse
        rep = DailyReportResponse(
            report_date=dt.date(2026, 3, 17),
            equity=105_000.0,
            cash=90_000.0,
            gross_exposure=15_000.0,
            daily_return_pct=0.005,
            orders_submitted=2,
            orders_filled=2,
            orders_cancelled=0,
            orders_rejected=0,
            reconciliation_clean=True,
            avg_slippage_bps=3.5,
            max_slippage_bps=7.0,
            scorecard_grade="B",
            narrative="Good day.",
            benchmark_differentials={"SPY": 0.002},
            improvement_proposals_generated=1,
            improvement_proposals_promoted=0,
        )
        assert rep.scorecard_grade == "B"

    def test_action_review_request_validates(self):
        from apps.api.schemas.actions import ActionReviewRequest
        req = ActionReviewRequest(action_ids=["id-1", "id-2"], decision="approve")
        assert req.decision == "approve"
        assert len(req.action_ids) == 2

    def test_risk_status_response_validates(self):
        from apps.api.schemas.system import RiskStatusResponse
        rs = RiskStatusResponse(
            kill_switch_active=False,
            operating_mode="research",
            max_positions=10,
            current_positions=3,
            loss_limit_status="ok",
            drawdown_status="ok",
            active_warnings=[],
            blocked_action_count=0,
        )
        assert rs.current_positions == 3
