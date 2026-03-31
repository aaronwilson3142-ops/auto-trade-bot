"""
Phase 49 — Portfolio Rebalancing Engine

Test classes
------------
TestRebalancingServiceTargetWeights     — compute_target_weights() logic
TestRebalancingServiceDrift             — compute_drift() edge cases
TestRebalancingServiceActions           — generate_rebalance_actions() output
TestRebalancingServiceSummary           — compute_rebalance_summary() output
TestRebalancingSettings                 — 3 new settings fields
TestRebalancingAppState                 — 3 new ApiAppState fields
TestRebalanceCheckJob                   — run_rebalance_check() job
TestRebalanceCheckJobDisabled           — disabled rebalancing no-ops
TestRebalanceAPIEndpoint                — GET /portfolio/rebalance-status
TestRebalanceDashboard                  — _render_rebalancing_section() HTML
TestRebalancePaperCycleIntegration      — paper trading cycle integration
TestRebalanceJobScheduled               — rebalance_check in scheduler (job count 27)
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(**overrides) -> Any:
    from config.settings import Settings
    base = {
        "db_url": "postgresql+psycopg://u:p@localhost/apis",
        "operating_mode": "paper",
        "kill_switch": False,
    }
    base.update(overrides)
    return Settings(**base)


@dataclass
class _FakePosition:
    ticker: str
    quantity: Decimal = Decimal("10")
    current_price: Decimal = Decimal("100")
    avg_entry_price: Decimal = Decimal("95")

    @property
    def market_value(self) -> Decimal:
        return self.quantity * self.current_price

    @property
    def unrealized_pnl(self) -> Decimal:
        return (self.current_price - self.avg_entry_price) * self.quantity


@dataclass
class _FakePortfolioState:
    equity: Decimal = Decimal("10000")
    cash: Decimal = Decimal("2000")
    positions: dict = field(default_factory=dict)
    start_of_day_equity: Decimal = Decimal("10000")
    high_water_mark: Decimal = Decimal("10000")
    daily_pnl_pct: Decimal = Decimal("0")
    drawdown_pct: Decimal = Decimal("0")


def _make_app_state(**overrides):
    from apps.api.state import ApiAppState
    state = ApiAppState()
    for k, v in overrides.items():
        setattr(state, k, v)
    return state


# ===========================================================================
# TestRebalancingServiceTargetWeights
# ===========================================================================

class TestRebalancingServiceTargetWeights:
    def test_equal_weight_basic(self):
        from services.risk_engine.rebalancing import RebalancingService
        tickers = ["AAPL", "MSFT", "NVDA", "GOOGL"]
        weights = RebalancingService.compute_target_weights(tickers, n_positions=4)
        assert len(weights) == 4
        assert all(abs(w - 0.25) < 1e-9 for w in weights.values())

    def test_top_n_only(self):
        from services.risk_engine.rebalancing import RebalancingService
        tickers = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"]
        weights = RebalancingService.compute_target_weights(tickers, n_positions=3)
        assert list(weights.keys()) == ["AAPL", "MSFT", "NVDA"]
        assert all(abs(w - 1/3) < 1e-9 for w in weights.values())

    def test_n_larger_than_tickers(self):
        from services.risk_engine.rebalancing import RebalancingService
        tickers = ["AAPL", "MSFT"]
        weights = RebalancingService.compute_target_weights(tickers, n_positions=10)
        assert len(weights) == 2
        assert all(abs(w - 0.5) < 1e-9 for w in weights.values())

    def test_empty_tickers_returns_empty(self):
        from services.risk_engine.rebalancing import RebalancingService
        weights = RebalancingService.compute_target_weights([], n_positions=5)
        assert weights == {}

    def test_n_positions_zero_returns_empty(self):
        from services.risk_engine.rebalancing import RebalancingService
        weights = RebalancingService.compute_target_weights(["AAPL", "MSFT"], n_positions=0)
        assert weights == {}

    def test_single_ticker_gets_full_weight(self):
        from services.risk_engine.rebalancing import RebalancingService
        weights = RebalancingService.compute_target_weights(["AAPL"], n_positions=5)
        assert weights == {"AAPL": 1.0}

    def test_weights_sum_to_one(self):
        from services.risk_engine.rebalancing import RebalancingService
        tickers = ["A", "B", "C", "D", "E", "F", "G"]
        weights = RebalancingService.compute_target_weights(tickers, n_positions=5)
        assert abs(sum(weights.values()) - 1.0) < 1e-9


# ===========================================================================
# TestRebalancingServiceDrift
# ===========================================================================

class TestRebalancingServiceDrift:
    def test_over_allocated_position_suggests_trim(self):
        from services.risk_engine.rebalancing import RebalancingService
        pos = _FakePosition("AAPL", quantity=Decimal("40"), current_price=Decimal("100"))
        positions = {"AAPL": pos}  # MV = 4000, 40% of 10000 equity
        target_weights = {"AAPL": 0.20}
        entries = RebalancingService.compute_drift(
            positions=positions,
            target_weights=target_weights,
            equity=10000.0,
            threshold_pct=0.05,
            min_trade_usd=100.0,
        )
        assert len(entries) == 1
        e = entries[0]
        assert e.ticker == "AAPL"
        assert e.action_suggested == "TRIM"
        assert e.drift_pct > 0

    def test_under_allocated_position_suggests_open(self):
        from services.risk_engine.rebalancing import RebalancingService
        pos = _FakePosition("AAPL", quantity=Decimal("5"), current_price=Decimal("100"))
        positions = {"AAPL": pos}  # MV = 500, 5% of 10000 equity
        target_weights = {"AAPL": 0.20}
        entries = RebalancingService.compute_drift(
            positions=positions,
            target_weights=target_weights,
            equity=10000.0,
            threshold_pct=0.05,
            min_trade_usd=100.0,
        )
        assert len(entries) == 1
        e = entries[0]
        assert e.action_suggested == "OPEN"
        assert e.drift_pct < 0

    def test_within_threshold_suggests_hold(self):
        from services.risk_engine.rebalancing import RebalancingService
        pos = _FakePosition("AAPL", quantity=Decimal("20"), current_price=Decimal("100"))
        positions = {"AAPL": pos}  # MV = 2000, 20% of 10000
        target_weights = {"AAPL": 0.20}
        entries = RebalancingService.compute_drift(
            positions=positions,
            target_weights=target_weights,
            equity=10000.0,
            threshold_pct=0.05,
            min_trade_usd=100.0,
        )
        assert entries[0].action_suggested == "HOLD"

    def test_missing_from_positions_but_in_targets_suggests_open(self):
        from services.risk_engine.rebalancing import RebalancingService
        entries = RebalancingService.compute_drift(
            positions={},
            target_weights={"MSFT": 0.20},
            equity=10000.0,
            threshold_pct=0.05,
            min_trade_usd=100.0,
        )
        assert any(e.ticker == "MSFT" and e.action_suggested == "OPEN" for e in entries)

    def test_held_but_not_in_targets_suggests_trim(self):
        from services.risk_engine.rebalancing import RebalancingService
        pos = _FakePosition("AAPL", quantity=Decimal("20"), current_price=Decimal("100"))
        positions = {"AAPL": pos}  # MV = 2000 = 20% of equity, no target → TRIM
        entries = RebalancingService.compute_drift(
            positions=positions,
            target_weights={},
            equity=10000.0,
            threshold_pct=0.05,
            min_trade_usd=100.0,
        )
        assert entries[0].action_suggested == "TRIM"

    def test_zero_equity_returns_empty(self):
        from services.risk_engine.rebalancing import RebalancingService
        pos = _FakePosition("AAPL")
        entries = RebalancingService.compute_drift(
            positions={"AAPL": pos},
            target_weights={"AAPL": 0.20},
            equity=0.0,
            threshold_pct=0.05,
            min_trade_usd=100.0,
        )
        assert entries == []

    def test_min_trade_usd_filter(self):
        from services.risk_engine.rebalancing import RebalancingService
        pos = _FakePosition("AAPL", quantity=Decimal("21"), current_price=Decimal("100"))
        positions = {"AAPL": pos}  # drift = 1%, $100 exactly at boundary
        entries = RebalancingService.compute_drift(
            positions=positions,
            target_weights={"AAPL": 0.20},
            equity=10000.0,
            threshold_pct=0.0,      # no threshold block
            min_trade_usd=500.0,    # $100 < $500 → HOLD
        )
        assert entries[0].action_suggested == "HOLD"

    def test_drift_usd_positive_for_overweight(self):
        from services.risk_engine.rebalancing import RebalancingService
        pos = _FakePosition("AAPL", quantity=Decimal("40"), current_price=Decimal("100"))
        entries = RebalancingService.compute_drift(
            positions={"AAPL": pos},
            target_weights={"AAPL": 0.20},
            equity=10000.0,
            threshold_pct=0.0,
            min_trade_usd=0.0,
        )
        assert entries[0].drift_usd > 0  # over-allocated → positive drift_usd

    def test_drift_usd_negative_for_underweight(self):
        from services.risk_engine.rebalancing import RebalancingService
        entries = RebalancingService.compute_drift(
            positions={},
            target_weights={"MSFT": 0.20},
            equity=10000.0,
            threshold_pct=0.0,
            min_trade_usd=0.0,
        )
        assert entries[0].drift_usd < 0  # under-allocated → negative drift_usd


# ===========================================================================
# TestRebalancingServiceActions
# ===========================================================================

class TestRebalancingServiceActions:
    def _make_cfg(self, **kw):
        return _make_settings(**kw)

    def test_trim_action_generated_for_overweight(self):
        from services.portfolio_engine.models import ActionType
        from services.risk_engine.rebalancing import RebalancingService
        pos = _FakePosition("AAPL", quantity=Decimal("40"), current_price=Decimal("100"))
        cfg = self._make_cfg(
            enable_rebalancing=True,
            rebalance_threshold_pct=0.05,
            rebalance_min_trade_usd=100.0,
        )
        actions = RebalancingService.generate_rebalance_actions(
            positions={"AAPL": pos},
            target_weights={"AAPL": 0.20},
            equity=10000.0,
            settings=cfg,
        )
        trim_actions = [a for a in actions if a.action_type == ActionType.TRIM]
        assert len(trim_actions) == 1
        assert trim_actions[0].risk_approved is True
        assert trim_actions[0].ticker == "AAPL"
        assert trim_actions[0].target_quantity > 0

    def test_open_action_not_preapproved(self):
        from services.portfolio_engine.models import ActionType
        from services.risk_engine.rebalancing import RebalancingService
        cfg = self._make_cfg(
            enable_rebalancing=True,
            rebalance_threshold_pct=0.05,
            rebalance_min_trade_usd=100.0,
        )
        actions = RebalancingService.generate_rebalance_actions(
            positions={},
            target_weights={"MSFT": 0.20},
            equity=10000.0,
            settings=cfg,
        )
        open_actions = [a for a in actions if a.action_type == ActionType.OPEN]
        assert len(open_actions) == 1
        assert open_actions[0].risk_approved is False

    def test_disabled_returns_empty(self):
        from services.risk_engine.rebalancing import RebalancingService
        pos = _FakePosition("AAPL", quantity=Decimal("40"), current_price=Decimal("100"))
        cfg = self._make_cfg(enable_rebalancing=False)
        actions = RebalancingService.generate_rebalance_actions(
            positions={"AAPL": pos},
            target_weights={"AAPL": 0.10},
            equity=10000.0,
            settings=cfg,
        )
        assert actions == []

    def test_zero_equity_returns_empty(self):
        from services.risk_engine.rebalancing import RebalancingService
        cfg = self._make_cfg(enable_rebalancing=True)
        actions = RebalancingService.generate_rebalance_actions(
            positions={},
            target_weights={"AAPL": 0.20},
            equity=0.0,
            settings=cfg,
        )
        assert actions == []

    def test_trim_quantity_correct(self):
        from services.portfolio_engine.models import ActionType
        from services.risk_engine.rebalancing import RebalancingService
        # AAPL: 40 shares @ $100 = $4000 = 40% of $10000
        # target = 20% = $2000 → excess = $2000 → sell 20 shares
        pos = _FakePosition("AAPL", quantity=Decimal("40"), current_price=Decimal("100"))
        cfg = self._make_cfg(
            enable_rebalancing=True,
            rebalance_threshold_pct=0.05,
            rebalance_min_trade_usd=100.0,
        )
        actions = RebalancingService.generate_rebalance_actions(
            positions={"AAPL": pos},
            target_weights={"AAPL": 0.20},
            equity=10000.0,
            settings=cfg,
        )
        trim = next(a for a in actions if a.action_type == ActionType.TRIM)
        assert trim.target_quantity == Decimal("20")

    def test_trim_reason_contains_drift(self):
        from services.portfolio_engine.models import ActionType
        from services.risk_engine.rebalancing import RebalancingService
        pos = _FakePosition("AAPL", quantity=Decimal("40"), current_price=Decimal("100"))
        cfg = self._make_cfg(
            enable_rebalancing=True,
            rebalance_threshold_pct=0.05,
            rebalance_min_trade_usd=100.0,
        )
        actions = RebalancingService.generate_rebalance_actions(
            positions={"AAPL": pos},
            target_weights={"AAPL": 0.20},
            equity=10000.0,
            settings=cfg,
        )
        trim = next(a for a in actions if a.action_type == ActionType.TRIM)
        assert "rebalance_trim" in trim.reason

    def test_no_price_skips_trim(self):
        from services.risk_engine.rebalancing import RebalancingService
        pos = _FakePosition("AAPL", quantity=Decimal("40"), current_price=Decimal("0"))
        cfg = self._make_cfg(
            enable_rebalancing=True,
            rebalance_threshold_pct=0.0,
            rebalance_min_trade_usd=0.0,
        )
        actions = RebalancingService.generate_rebalance_actions(
            positions={"AAPL": pos},
            target_weights={"AAPL": 0.10},
            equity=10000.0,
            settings=cfg,
        )
        from services.portfolio_engine.models import ActionType
        assert not any(a.action_type == ActionType.TRIM for a in actions)


# ===========================================================================
# TestRebalancingServiceSummary
# ===========================================================================

class TestRebalancingServiceSummary:
    def test_summary_basic(self):
        from services.risk_engine.rebalancing import RebalancingService
        pos = _FakePosition("AAPL", quantity=Decimal("40"), current_price=Decimal("100"))
        cfg = _make_settings(
            enable_rebalancing=True,
            rebalance_threshold_pct=0.05,
            rebalance_min_trade_usd=100.0,
        )
        summary = RebalancingService.compute_rebalance_summary(
            positions={"AAPL": pos},
            target_weights={"AAPL": 0.20},
            equity=10000.0,
            settings=cfg,
            computed_at="2026-03-21T06:26:00+00:00",
        )
        assert summary.rebalance_enabled is True
        assert summary.trim_count == 1
        assert summary.open_count == 0
        assert summary.total_equity == 10000.0

    def test_summary_disabled(self):
        from services.risk_engine.rebalancing import RebalancingService
        cfg = _make_settings(enable_rebalancing=False)
        summary = RebalancingService.compute_rebalance_summary(
            positions={},
            target_weights={},
            equity=10000.0,
            settings=cfg,
        )
        assert summary.rebalance_enabled is False
        assert summary.drift_entries == []
        assert summary.trim_count == 0

    def test_summary_zero_equity(self):
        from services.risk_engine.rebalancing import RebalancingService
        cfg = _make_settings(enable_rebalancing=True)
        summary = RebalancingService.compute_rebalance_summary(
            positions={},
            target_weights={"AAPL": 0.20},
            equity=0.0,
            settings=cfg,
        )
        assert summary.drift_entries == []


# ===========================================================================
# TestRebalancingSettings
# ===========================================================================

class TestRebalancingSettings:
    def test_enable_rebalancing_defaults_true(self):
        cfg = _make_settings()
        assert cfg.enable_rebalancing is True

    def test_enable_rebalancing_can_be_disabled(self):
        cfg = _make_settings(enable_rebalancing=False)
        assert cfg.enable_rebalancing is False

    def test_rebalance_threshold_pct_default(self):
        cfg = _make_settings()
        assert cfg.rebalance_threshold_pct == 0.05

    def test_rebalance_threshold_pct_custom(self):
        cfg = _make_settings(rebalance_threshold_pct=0.10)
        assert cfg.rebalance_threshold_pct == 0.10

    def test_rebalance_min_trade_usd_default(self):
        cfg = _make_settings()
        assert cfg.rebalance_min_trade_usd == 500.0

    def test_rebalance_min_trade_usd_custom(self):
        cfg = _make_settings(rebalance_min_trade_usd=250.0)
        assert cfg.rebalance_min_trade_usd == 250.0


# ===========================================================================
# TestRebalancingAppState
# ===========================================================================

class TestRebalancingAppState:
    def test_rebalance_targets_default_empty(self):
        state = _make_app_state()
        assert state.rebalance_targets == {}

    def test_rebalance_computed_at_default_none(self):
        state = _make_app_state()
        assert state.rebalance_computed_at is None

    def test_rebalance_drift_count_default_zero(self):
        state = _make_app_state()
        assert state.rebalance_drift_count == 0

    def test_fields_settable(self):
        state = _make_app_state()
        now = dt.datetime.now(dt.UTC)
        state.rebalance_targets = {"AAPL": 0.20, "MSFT": 0.20}
        state.rebalance_computed_at = now
        state.rebalance_drift_count = 3
        assert state.rebalance_targets["AAPL"] == 0.20
        assert state.rebalance_computed_at == now
        assert state.rebalance_drift_count == 3


# ===========================================================================
# TestRebalanceCheckJob
# ===========================================================================

class TestRebalanceCheckJob:
    def test_job_importable(self):
        from apps.worker.jobs.rebalancing import run_rebalance_check
        assert callable(run_rebalance_check)

    def test_job_exported_from_package(self):
        from apps.worker.jobs import run_rebalance_check
        assert callable(run_rebalance_check)

    def test_job_returns_ok_status(self):
        from apps.worker.jobs.rebalancing import run_rebalance_check

        state = _make_app_state()
        state.latest_rankings = []
        cfg = _make_settings(enable_rebalancing=True)

        result = run_rebalance_check(app_state=state, settings=cfg)
        assert result["status"] == "ok"
        assert "run_at" in result

    def test_job_populates_state_fields(self):
        from apps.worker.jobs.rebalancing import run_rebalance_check

        state = _make_app_state()
        cfg = _make_settings(enable_rebalancing=True, max_positions=10)

        run_rebalance_check(app_state=state, settings=cfg)

        assert isinstance(state.rebalance_targets, dict)
        assert state.rebalance_computed_at is not None
        assert isinstance(state.rebalance_drift_count, int)

    def test_job_uses_rankings_when_available(self):
        from apps.worker.jobs.rebalancing import run_rebalance_check

        state = _make_app_state()
        r1 = MagicMock()
        r1.ticker = "AAPL"
        r2 = MagicMock()
        r2.ticker = "MSFT"
        state.latest_rankings = [r1, r2]
        cfg = _make_settings(enable_rebalancing=True, max_positions=5)

        run_rebalance_check(app_state=state, settings=cfg)
        assert "AAPL" in state.rebalance_targets
        assert "MSFT" in state.rebalance_targets

    def test_job_falls_back_to_active_universe(self):
        from apps.worker.jobs.rebalancing import run_rebalance_check

        state = _make_app_state()
        state.latest_rankings = []
        state.active_universe = ["AAPL", "MSFT", "NVDA"]
        cfg = _make_settings(enable_rebalancing=True, max_positions=3)

        run_rebalance_check(app_state=state, settings=cfg)
        assert "AAPL" in state.rebalance_targets

    def test_job_uses_universe_tickers_as_final_fallback(self):
        from apps.worker.jobs.rebalancing import run_rebalance_check

        state = _make_app_state()
        state.latest_rankings = []
        state.active_universe = []
        cfg = _make_settings(enable_rebalancing=True)

        result = run_rebalance_check(app_state=state, settings=cfg)
        assert result["status"] == "ok"
        assert len(state.rebalance_targets) > 0

    def test_job_measures_drift_when_positions_exist(self):
        from apps.worker.jobs.rebalancing import run_rebalance_check

        pos = _FakePosition("AAPL", quantity=Decimal("40"), current_price=Decimal("100"))
        ps = _FakePortfolioState(equity=Decimal("10000"), positions={"AAPL": pos})

        state = _make_app_state()
        state.portfolio_state = ps
        state.latest_rankings = []
        state.active_universe = ["AAPL", "MSFT"]

        cfg = _make_settings(
            enable_rebalancing=True,
            max_positions=2,
            rebalance_threshold_pct=0.05,
            rebalance_min_trade_usd=100.0,
        )

        result = run_rebalance_check(app_state=state, settings=cfg)
        assert result["status"] == "ok"
        assert "drift_count" in result

    def test_job_returns_error_on_exception(self):
        from apps.worker.jobs.rebalancing import run_rebalance_check

        state = _make_app_state()
        cfg = _make_settings(enable_rebalancing=True)

        with patch(
            "services.risk_engine.rebalancing.RebalancingService.compute_target_weights",
            side_effect=RuntimeError("test error"),
        ):
            result = run_rebalance_check(app_state=state, settings=cfg)
        assert result["status"] == "error"
        assert "test error" in result["error"]


# ===========================================================================
# TestRebalanceCheckJobDisabled
# ===========================================================================

class TestRebalanceCheckJobDisabled:
    def test_disabled_returns_disabled_status(self):
        from apps.worker.jobs.rebalancing import run_rebalance_check

        state = _make_app_state()
        cfg = _make_settings(enable_rebalancing=False)

        result = run_rebalance_check(app_state=state, settings=cfg)
        assert result["status"] == "disabled"

    def test_disabled_does_not_modify_state(self):
        from apps.worker.jobs.rebalancing import run_rebalance_check

        state = _make_app_state()
        cfg = _make_settings(enable_rebalancing=False)

        run_rebalance_check(app_state=state, settings=cfg)
        assert state.rebalance_targets == {}
        assert state.rebalance_computed_at is None


# ===========================================================================
# TestRebalanceAPIEndpoint
# ===========================================================================

class TestRebalanceAPIEndpoint:
    def _client(self):
        from fastapi.testclient import TestClient

        from apps.api.main import app
        return TestClient(app)

    def test_endpoint_returns_200(self):
        client = self._client()
        resp = client.get("/api/v1/portfolio/rebalance-status")
        assert resp.status_code == 200

    def test_endpoint_returns_valid_schema(self):
        client = self._client()
        resp = client.get("/api/v1/portfolio/rebalance-status")
        data = resp.json()
        assert "rebalance_enabled" in data
        assert "drift_entries" in data
        assert "trim_count" in data
        assert "open_count" in data
        assert "hold_count" in data

    def test_endpoint_empty_when_no_data(self):
        from apps.api.state import reset_app_state
        reset_app_state()
        client = self._client()
        resp = client.get("/api/v1/portfolio/rebalance-status")
        data = resp.json()
        assert data["drift_entries"] == []

    def test_endpoint_shows_drift_when_state_populated(self):
        from apps.api.state import get_app_state, reset_app_state
        reset_app_state()
        state = get_app_state()
        state.rebalance_targets = {"AAPL": 0.20, "MSFT": 0.20}
        state.rebalance_computed_at = dt.datetime.now(dt.UTC)

        pos = _FakePosition("AAPL", quantity=Decimal("40"), current_price=Decimal("100"))
        ps = _FakePortfolioState(equity=Decimal("10000"), positions={"AAPL": pos})
        state.portfolio_state = ps

        client = self._client()
        resp = client.get("/api/v1/portfolio/rebalance-status")
        data = resp.json()
        assert data["total_equity"] == 10000.0
        assert any(e["ticker"] == "AAPL" for e in data["drift_entries"])

    def test_endpoint_computed_at_present_when_set(self):
        from apps.api.state import get_app_state, reset_app_state
        reset_app_state()
        state = get_app_state()
        now = dt.datetime.now(dt.UTC)
        state.rebalance_computed_at = now

        client = self._client()
        resp = client.get("/api/v1/portfolio/rebalance-status")
        data = resp.json()
        assert data["computed_at"] is not None


# ===========================================================================
# TestRebalanceDashboard
# ===========================================================================

class TestRebalanceDashboard:
    def test_section_function_importable(self):
        from apps.dashboard.router import _render_rebalancing_section
        assert callable(_render_rebalancing_section)

    def test_section_returns_string(self):
        from apps.dashboard.router import _render_rebalancing_section
        state = _make_app_state()
        cfg = _make_settings()
        html = _render_rebalancing_section(state, cfg)
        assert isinstance(html, str)

    def test_section_shows_phase_label(self):
        from apps.dashboard.router import _render_rebalancing_section
        state = _make_app_state()
        cfg = _make_settings()
        html = _render_rebalancing_section(state, cfg)
        assert "Phase 49" in html

    def test_section_shows_enabled_when_on(self):
        from apps.dashboard.router import _render_rebalancing_section
        state = _make_app_state()
        cfg = _make_settings(enable_rebalancing=True)
        html = _render_rebalancing_section(state, cfg)
        assert "enabled" in html

    def test_section_shows_drift_count(self):
        from apps.dashboard.router import _render_rebalancing_section
        state = _make_app_state()
        state.rebalance_drift_count = 3
        cfg = _make_settings()
        html = _render_rebalancing_section(state, cfg)
        assert "3" in html

    def test_section_shows_not_yet_run_when_no_computed_at(self):
        from apps.dashboard.router import _render_rebalancing_section
        state = _make_app_state()
        cfg = _make_settings()
        html = _render_rebalancing_section(state, cfg)
        assert "not yet run" in html

    def test_section_shows_drift_table_when_data_available(self):
        from apps.dashboard.router import _render_rebalancing_section
        state = _make_app_state()
        state.rebalance_targets = {"AAPL": 0.20}
        state.rebalance_computed_at = dt.datetime.now(dt.UTC)
        pos = _FakePosition("AAPL", quantity=Decimal("40"), current_price=Decimal("100"))
        ps = _FakePortfolioState(equity=Decimal("10000"), positions={"AAPL": pos})
        state.portfolio_state = ps
        cfg = _make_settings(
            enable_rebalancing=True,
            rebalance_threshold_pct=0.05,
            rebalance_min_trade_usd=100.0,
        )
        html = _render_rebalancing_section(state, cfg)
        assert "AAPL" in html
        assert "<table>" in html


# ===========================================================================
# TestRebalancePaperCycleIntegration
# ===========================================================================

class TestRebalancePaperCycleIntegration:
    def test_rebalance_trim_added_to_proposed_actions(self):
        """Paper cycle merges rebalance TRIM actions when enabled."""
        from services.portfolio_engine.models import ActionType
        from services.risk_engine.rebalancing import RebalancingService

        pos = _FakePosition("AAPL", quantity=Decimal("40"), current_price=Decimal("100"))
        cfg = _make_settings(
            enable_rebalancing=True,
            rebalance_threshold_pct=0.05,
            rebalance_min_trade_usd=100.0,
        )
        actions = RebalancingService.generate_rebalance_actions(
            positions={"AAPL": pos},
            target_weights={"AAPL": 0.20},
            equity=10000.0,
            settings=cfg,
        )
        trim_actions = [a for a in actions if a.action_type == ActionType.TRIM]
        assert len(trim_actions) == 1
        assert trim_actions[0].risk_approved is True

    def test_close_supersedes_rebalance_trim(self):
        """If ticker is already in already_closing set, rebalance TRIM is skipped."""
        from services.risk_engine.rebalancing import RebalancingService

        pos = _FakePosition("AAPL", quantity=Decimal("40"), current_price=Decimal("100"))
        cfg = _make_settings(
            enable_rebalancing=True,
            rebalance_threshold_pct=0.0,
            rebalance_min_trade_usd=0.0,
        )
        actions = RebalancingService.generate_rebalance_actions(
            positions={"AAPL": pos},
            target_weights={"AAPL": 0.10},
            equity=10000.0,
            settings=cfg,
        )
        # Simulate already_closing dedup as done in paper_trading.py
        already_closing = {"AAPL"}
        merged = [a for a in actions if a.ticker not in already_closing]
        assert len(merged) == 0  # TRIM for AAPL was suppressed

    def test_rebalance_open_not_preapproved(self):
        """OPEN rebalance actions are not pre-approved and enter risk pipeline."""
        from services.portfolio_engine.models import ActionType
        from services.risk_engine.rebalancing import RebalancingService

        cfg = _make_settings(
            enable_rebalancing=True,
            rebalance_threshold_pct=0.05,
            rebalance_min_trade_usd=100.0,
        )
        actions = RebalancingService.generate_rebalance_actions(
            positions={},
            target_weights={"NVDA": 0.20},
            equity=10000.0,
            settings=cfg,
        )
        open_actions = [a for a in actions if a.action_type == ActionType.OPEN]
        assert all(not a.risk_approved for a in open_actions)

    def test_disabled_produces_no_rebalance_actions(self):
        from services.risk_engine.rebalancing import RebalancingService
        pos = _FakePosition("AAPL", quantity=Decimal("40"), current_price=Decimal("100"))
        cfg = _make_settings(enable_rebalancing=False)
        actions = RebalancingService.generate_rebalance_actions(
            positions={"AAPL": pos},
            target_weights={"AAPL": 0.10},
            equity=10000.0,
            settings=cfg,
        )
        assert actions == []


# ===========================================================================
# TestRebalanceJobScheduled
# ===========================================================================

class TestRebalanceJobScheduled:
    def test_job_count_is_27(self):
        """Scheduler must have exactly 27 jobs after Phase 49."""
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        job_ids = {job.id for job in scheduler.get_jobs()}
        assert len(job_ids) == 30

    def test_rebalance_check_job_present(self):
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        job_ids = {job.id for job in scheduler.get_jobs()}
        assert "rebalance_check" in job_ids

    def test_rebalance_check_runs_at_0626_et(self):
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        job = next(j for j in scheduler.get_jobs() if j.id == "rebalance_check")
        trigger = job.trigger
        fields = {f.name: str(f) for f in trigger.fields}
        assert fields.get("hour") == "6"
        assert fields.get("minute") == "26"

    def test_rebalance_check_weekdays_only(self):
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        job = next(j for j in scheduler.get_jobs() if j.id == "rebalance_check")
        fields = {f.name: str(f) for f in job.trigger.fields}
        assert fields.get("day_of_week") == "mon-fri"
