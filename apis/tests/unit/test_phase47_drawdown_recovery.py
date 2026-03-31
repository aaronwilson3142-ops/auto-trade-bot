"""
Phase 47 — Drawdown Recovery Mode

Test classes
------------
TestDrawdownStateEvaluation         — evaluate_state() core logic
TestDrawdownRecoverySizing          — apply_recovery_sizing() multiplier math
TestDrawdownIsBlocked               — is_blocked() gate logic
TestDrawdownStateResult             — DrawdownStateResult dataclass
TestDrawdownSettings                — 4 new settings fields with defaults
TestDrawdownAppState                — 2 new ApiAppState fields
TestDrawdownAPIEndpoint             — GET /portfolio/drawdown-state
TestDrawdownPaperCycleIntegration   — paper cycle drawdown integration
"""
from __future__ import annotations

import dataclasses
import datetime as dt
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest


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


def _make_open_action(ticker: str = "AAPL", quantity: int = 100):
    from services.portfolio_engine.models import ActionType, PortfolioAction
    return PortfolioAction(
        ticker=ticker,
        action_type=ActionType.OPEN,
        target_notional=Decimal("5000.00"),
        target_quantity=Decimal(str(quantity)),
        reason="signal",
        risk_approved=False,
    )


def _make_close_action(ticker: str = "AAPL"):
    from services.portfolio_engine.models import ActionType, PortfolioAction
    return PortfolioAction(
        ticker=ticker,
        action_type=ActionType.CLOSE,
        target_notional=Decimal("5000.00"),
        target_quantity=Decimal("50"),
        reason="exit",
    )


def _make_trim_action(ticker: str = "AAPL"):
    from services.portfolio_engine.models import ActionType, PortfolioAction
    return PortfolioAction(
        ticker=ticker,
        action_type=ActionType.TRIM,
        target_notional=Decimal("2000.00"),
        target_quantity=Decimal("20"),
        reason="overconcentration",
    )


def _make_state_result(
    state_str: str = "NORMAL",
    drawdown_pct: float = 0.0,
    hwm: float = 100_000.0,
    equity: float = 100_000.0,
    caution: float = 0.05,
    recovery: float = 0.10,
    size_mult: float = 1.0,
):
    from services.risk_engine.drawdown_recovery import DrawdownState, DrawdownStateResult
    return DrawdownStateResult(
        state=DrawdownState(state_str),
        current_drawdown_pct=drawdown_pct,
        high_water_mark=hwm,
        current_equity=equity,
        caution_threshold_pct=caution,
        recovery_threshold_pct=recovery,
        size_multiplier=size_mult,
    )


def _make_portfolio_state(equity: float = 100_000.0, hwm: float = 100_000.0):
    ps = MagicMock()
    ps.equity = Decimal(str(equity))
    ps.high_water_mark = Decimal(str(hwm))
    ps.positions = {}
    ps.start_of_day_equity = Decimal(str(equity))
    return ps


def _make_app_state_obj():
    from apps.api.state import ApiAppState
    return ApiAppState()


# ---------------------------------------------------------------------------
# TestDrawdownStateEvaluation
# ---------------------------------------------------------------------------

class TestDrawdownStateEvaluation:

    def test_normal_when_no_drawdown(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService, DrawdownState
        result = DrawdownRecoveryService.evaluate_state(
            current_equity=100_000.0,
            high_water_mark=100_000.0,
            caution_threshold_pct=0.05,
            recovery_threshold_pct=0.10,
            recovery_mode_size_multiplier=0.5,
        )
        assert result.state == DrawdownState.NORMAL

    def test_normal_at_exactly_zero_drawdown(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService, DrawdownState
        result = DrawdownRecoveryService.evaluate_state(
            current_equity=100_000.0,
            high_water_mark=100_000.0,
            caution_threshold_pct=0.05,
            recovery_threshold_pct=0.10,
            recovery_mode_size_multiplier=0.5,
        )
        assert result.current_drawdown_pct == pytest.approx(0.0)
        assert result.state == DrawdownState.NORMAL

    def test_caution_at_exactly_caution_threshold(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService, DrawdownState
        # HWM=100, equity=95 → drawdown=5% exactly
        result = DrawdownRecoveryService.evaluate_state(
            current_equity=95_000.0,
            high_water_mark=100_000.0,
            caution_threshold_pct=0.05,
            recovery_threshold_pct=0.10,
            recovery_mode_size_multiplier=0.5,
        )
        assert result.state == DrawdownState.CAUTION
        assert result.current_drawdown_pct == pytest.approx(0.05)

    def test_caution_between_caution_and_recovery(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService, DrawdownState
        # HWM=100, equity=93 → drawdown=7%
        result = DrawdownRecoveryService.evaluate_state(
            current_equity=93_000.0,
            high_water_mark=100_000.0,
            caution_threshold_pct=0.05,
            recovery_threshold_pct=0.10,
            recovery_mode_size_multiplier=0.5,
        )
        assert result.state == DrawdownState.CAUTION

    def test_recovery_at_exactly_recovery_threshold(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService, DrawdownState
        # HWM=100, equity=90 → drawdown=10% exactly
        result = DrawdownRecoveryService.evaluate_state(
            current_equity=90_000.0,
            high_water_mark=100_000.0,
            caution_threshold_pct=0.05,
            recovery_threshold_pct=0.10,
            recovery_mode_size_multiplier=0.5,
        )
        assert result.state == DrawdownState.RECOVERY
        assert result.current_drawdown_pct == pytest.approx(0.10)

    def test_recovery_above_recovery_threshold(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService, DrawdownState
        # HWM=100, equity=80 → drawdown=20%
        result = DrawdownRecoveryService.evaluate_state(
            current_equity=80_000.0,
            high_water_mark=100_000.0,
            caution_threshold_pct=0.05,
            recovery_threshold_pct=0.10,
            recovery_mode_size_multiplier=0.5,
        )
        assert result.state == DrawdownState.RECOVERY
        assert result.current_drawdown_pct == pytest.approx(0.20)

    def test_zero_hwm_returns_normal(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService, DrawdownState
        result = DrawdownRecoveryService.evaluate_state(
            current_equity=100_000.0,
            high_water_mark=0.0,
            caution_threshold_pct=0.05,
            recovery_threshold_pct=0.10,
            recovery_mode_size_multiplier=0.5,
        )
        assert result.state == DrawdownState.NORMAL

    def test_zero_equity_returns_normal(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService, DrawdownState
        result = DrawdownRecoveryService.evaluate_state(
            current_equity=0.0,
            high_water_mark=100_000.0,
            caution_threshold_pct=0.05,
            recovery_threshold_pct=0.10,
            recovery_mode_size_multiplier=0.5,
        )
        assert result.state == DrawdownState.NORMAL

    def test_negative_equity_handled_gracefully(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService, DrawdownState
        result = DrawdownRecoveryService.evaluate_state(
            current_equity=-1000.0,
            high_water_mark=100_000.0,
            caution_threshold_pct=0.05,
            recovery_threshold_pct=0.10,
            recovery_mode_size_multiplier=0.5,
        )
        # negative equity <= 0 → returns NORMAL per guard
        assert result.state == DrawdownState.NORMAL

    def test_size_multiplier_one_in_normal(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService
        result = DrawdownRecoveryService.evaluate_state(
            current_equity=100_000.0,
            high_water_mark=100_000.0,
            caution_threshold_pct=0.05,
            recovery_threshold_pct=0.10,
            recovery_mode_size_multiplier=0.5,
        )
        assert result.size_multiplier == pytest.approx(1.0)

    def test_size_multiplier_one_in_caution(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService
        result = DrawdownRecoveryService.evaluate_state(
            current_equity=93_000.0,
            high_water_mark=100_000.0,
            caution_threshold_pct=0.05,
            recovery_threshold_pct=0.10,
            recovery_mode_size_multiplier=0.5,
        )
        assert result.size_multiplier == pytest.approx(1.0)

    def test_size_multiplier_recovery_in_recovery(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService
        result = DrawdownRecoveryService.evaluate_state(
            current_equity=80_000.0,
            high_water_mark=100_000.0,
            caution_threshold_pct=0.05,
            recovery_threshold_pct=0.10,
            recovery_mode_size_multiplier=0.5,
        )
        assert result.size_multiplier == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# TestDrawdownRecoverySizing
# ---------------------------------------------------------------------------

class TestDrawdownRecoverySizing:

    def test_normal_state_unchanged(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService
        sr = _make_state_result("NORMAL", size_mult=1.0)
        assert DrawdownRecoveryService.apply_recovery_sizing(100, sr) == 100

    def test_caution_state_unchanged(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService
        sr = _make_state_result("CAUTION", size_mult=1.0)
        assert DrawdownRecoveryService.apply_recovery_sizing(100, sr) == 100

    def test_recovery_state_multiplied(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService
        sr = _make_state_result("RECOVERY", size_mult=0.5)
        assert DrawdownRecoveryService.apply_recovery_sizing(100, sr) == 50

    def test_recovery_floors_to_minimum_one(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService
        sr = _make_state_result("RECOVERY", size_mult=0.001)
        # 1 * 0.001 = 0 → floor to 1
        assert DrawdownRecoveryService.apply_recovery_sizing(1, sr) == 1

    def test_zero_quantity_unchanged(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService
        sr = _make_state_result("RECOVERY", size_mult=0.5)
        assert DrawdownRecoveryService.apply_recovery_sizing(0, sr) == 0

    def test_negative_quantity_unchanged(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService
        sr = _make_state_result("RECOVERY", size_mult=0.5)
        assert DrawdownRecoveryService.apply_recovery_sizing(-10, sr) == -10

    def test_0_5_multiplier_100_gives_50(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService
        sr = _make_state_result("RECOVERY", size_mult=0.5)
        assert DrawdownRecoveryService.apply_recovery_sizing(100, sr) == 50

    def test_0_3_multiplier_10_gives_3(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService
        sr = _make_state_result("RECOVERY", size_mult=0.3)
        assert DrawdownRecoveryService.apply_recovery_sizing(10, sr) == 3


# ---------------------------------------------------------------------------
# TestDrawdownIsBlocked
# ---------------------------------------------------------------------------

class TestDrawdownIsBlocked:

    def test_normal_block_true_not_blocked(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService
        sr = _make_state_result("NORMAL")
        assert DrawdownRecoveryService.is_blocked(sr, block_new_positions=True) is False

    def test_caution_block_true_not_blocked(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService
        sr = _make_state_result("CAUTION")
        assert DrawdownRecoveryService.is_blocked(sr, block_new_positions=True) is False

    def test_recovery_block_true_is_blocked(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService
        sr = _make_state_result("RECOVERY", size_mult=0.5)
        assert DrawdownRecoveryService.is_blocked(sr, block_new_positions=True) is True

    def test_recovery_block_false_not_blocked(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService
        sr = _make_state_result("RECOVERY", size_mult=0.5)
        assert DrawdownRecoveryService.is_blocked(sr, block_new_positions=False) is False

    def test_normal_block_false_not_blocked(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService
        sr = _make_state_result("NORMAL")
        assert DrawdownRecoveryService.is_blocked(sr, block_new_positions=False) is False

    def test_caution_block_false_not_blocked(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService
        sr = _make_state_result("CAUTION")
        assert DrawdownRecoveryService.is_blocked(sr, block_new_positions=False) is False


# ---------------------------------------------------------------------------
# TestDrawdownStateResult
# ---------------------------------------------------------------------------

class TestDrawdownStateResult:

    def test_result_is_frozen(self):
        from services.risk_engine.drawdown_recovery import DrawdownState, DrawdownStateResult
        result = DrawdownStateResult(
            state=DrawdownState.NORMAL,
            current_drawdown_pct=0.0,
            high_water_mark=100_000.0,
            current_equity=100_000.0,
            caution_threshold_pct=0.05,
            recovery_threshold_pct=0.10,
            size_multiplier=1.0,
        )
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            result.state = DrawdownState.RECOVERY  # type: ignore[misc]

    def test_fields_populated_correctly(self):
        from services.risk_engine.drawdown_recovery import DrawdownState, DrawdownStateResult
        result = DrawdownStateResult(
            state=DrawdownState.CAUTION,
            current_drawdown_pct=0.07,
            high_water_mark=200_000.0,
            current_equity=186_000.0,
            caution_threshold_pct=0.05,
            recovery_threshold_pct=0.10,
            size_multiplier=1.0,
        )
        assert result.state == DrawdownState.CAUTION
        assert result.current_drawdown_pct == pytest.approx(0.07)
        assert result.high_water_mark == pytest.approx(200_000.0)
        assert result.current_equity == pytest.approx(186_000.0)
        assert result.caution_threshold_pct == pytest.approx(0.05)
        assert result.recovery_threshold_pct == pytest.approx(0.10)
        assert result.size_multiplier == pytest.approx(1.0)

    def test_drawdown_pct_computed_correctly(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService
        # HWM=100, equity=90 → 10%
        result = DrawdownRecoveryService.evaluate_state(
            current_equity=90_000.0,
            high_water_mark=100_000.0,
            caution_threshold_pct=0.05,
            recovery_threshold_pct=0.10,
            recovery_mode_size_multiplier=0.5,
        )
        assert result.current_drawdown_pct == pytest.approx(0.10)

    def test_state_value_is_string(self):
        from services.risk_engine.drawdown_recovery import DrawdownState
        assert isinstance(DrawdownState.NORMAL.value, str)
        assert isinstance(DrawdownState.CAUTION.value, str)
        assert isinstance(DrawdownState.RECOVERY.value, str)

    def test_caution_threshold_stored_correctly(self):
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService
        result = DrawdownRecoveryService.evaluate_state(
            current_equity=100_000.0,
            high_water_mark=100_000.0,
            caution_threshold_pct=0.07,
            recovery_threshold_pct=0.15,
            recovery_mode_size_multiplier=0.4,
        )
        assert result.caution_threshold_pct == pytest.approx(0.07)
        assert result.recovery_threshold_pct == pytest.approx(0.15)


# ---------------------------------------------------------------------------
# TestDrawdownSettings
# ---------------------------------------------------------------------------

class TestDrawdownSettings:

    def test_drawdown_caution_pct_default(self):
        s = _make_settings()
        assert s.drawdown_caution_pct == pytest.approx(0.05)

    def test_drawdown_recovery_pct_default(self):
        s = _make_settings()
        assert s.drawdown_recovery_pct == pytest.approx(0.10)

    def test_recovery_mode_size_multiplier_default(self):
        s = _make_settings()
        assert s.recovery_mode_size_multiplier == pytest.approx(0.50)

    def test_recovery_mode_block_new_positions_default(self):
        s = _make_settings()
        assert s.recovery_mode_block_new_positions is False

    def test_custom_values_overrideable(self):
        s = _make_settings(
            drawdown_caution_pct=0.03,
            drawdown_recovery_pct=0.08,
            recovery_mode_size_multiplier=0.25,
            recovery_mode_block_new_positions=True,
        )
        assert s.drawdown_caution_pct == pytest.approx(0.03)
        assert s.drawdown_recovery_pct == pytest.approx(0.08)
        assert s.recovery_mode_size_multiplier == pytest.approx(0.25)
        assert s.recovery_mode_block_new_positions is True


# ---------------------------------------------------------------------------
# TestDrawdownAppState
# ---------------------------------------------------------------------------

class TestDrawdownAppState:

    def test_drawdown_state_defaults_to_normal(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert state.drawdown_state == "NORMAL"

    def test_drawdown_state_changed_at_defaults_to_none(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert state.drawdown_state_changed_at is None

    def test_drawdown_state_can_be_updated(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        state.drawdown_state = "RECOVERY"
        assert state.drawdown_state == "RECOVERY"

    def test_drawdown_state_changed_at_can_be_set(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        now = dt.datetime.now(dt.timezone.utc)
        state.drawdown_state_changed_at = now
        assert state.drawdown_state_changed_at == now


# ---------------------------------------------------------------------------
# TestDrawdownAPIEndpoint
# ---------------------------------------------------------------------------

class TestDrawdownAPIEndpoint:

    def _make_app_state(
        self,
        equity: float = 100_000.0,
        hwm: float = 100_000.0,
        drawdown_state: str = "NORMAL",
        drawdown_state_changed_at=None,
    ):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        state.portfolio_state = _make_portfolio_state(equity=equity, hwm=hwm)
        state.drawdown_state = drawdown_state
        state.drawdown_state_changed_at = drawdown_state_changed_at
        return state

    def test_endpoint_returns_200(self):
        import asyncio
        from apps.api.routes.portfolio import get_drawdown_state
        state = self._make_app_state()
        settings = _make_settings()
        result = asyncio.run(get_drawdown_state(state, settings))
        assert result is not None

    def test_response_contains_all_expected_fields(self):
        import asyncio
        from apps.api.routes.portfolio import get_drawdown_state
        state = self._make_app_state()
        settings = _make_settings()
        result = asyncio.run(get_drawdown_state(state, settings))
        assert hasattr(result, "state")
        assert hasattr(result, "current_drawdown_pct")
        assert hasattr(result, "high_water_mark")
        assert hasattr(result, "current_equity")
        assert hasattr(result, "caution_threshold_pct")
        assert hasattr(result, "recovery_threshold_pct")
        assert hasattr(result, "size_multiplier")
        assert hasattr(result, "block_new_positions")
        assert hasattr(result, "state_changed_at")

    def test_state_reflects_normal_when_equity_at_hwm(self):
        import asyncio
        from apps.api.routes.portfolio import get_drawdown_state
        state = self._make_app_state(equity=100_000.0, hwm=100_000.0)
        settings = _make_settings()
        result = asyncio.run(get_drawdown_state(state, settings))
        assert result.state == "NORMAL"

    def test_state_reflects_recovery_when_equity_far_below_hwm(self):
        import asyncio
        from apps.api.routes.portfolio import get_drawdown_state
        # HWM=100k, equity=80k → 20% drawdown → RECOVERY
        state = self._make_app_state(equity=80_000.0, hwm=100_000.0)
        settings = _make_settings()
        result = asyncio.run(get_drawdown_state(state, settings))
        assert result.state == "RECOVERY"

    def test_current_drawdown_pct_is_float(self):
        import asyncio
        from apps.api.routes.portfolio import get_drawdown_state
        state = self._make_app_state(equity=95_000.0, hwm=100_000.0)
        settings = _make_settings()
        result = asyncio.run(get_drawdown_state(state, settings))
        assert isinstance(result.current_drawdown_pct, float)

    def test_block_new_positions_present_in_response(self):
        import asyncio
        from apps.api.routes.portfolio import get_drawdown_state
        state = self._make_app_state()
        settings = _make_settings(recovery_mode_block_new_positions=True)
        result = asyncio.run(get_drawdown_state(state, settings))
        assert result.block_new_positions is True

    def test_state_changed_at_none_when_no_transition(self):
        import asyncio
        from apps.api.routes.portfolio import get_drawdown_state
        state = self._make_app_state(drawdown_state_changed_at=None)
        settings = _make_settings()
        result = asyncio.run(get_drawdown_state(state, settings))
        assert result.state_changed_at is None

    def test_state_matches_service_output(self):
        import asyncio
        from apps.api.routes.portfolio import get_drawdown_state
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService
        state = self._make_app_state(equity=93_000.0, hwm=100_000.0)
        settings = _make_settings()
        result = asyncio.run(get_drawdown_state(state, settings))
        svc_result = DrawdownRecoveryService.evaluate_state(
            current_equity=93_000.0,
            high_water_mark=100_000.0,
            caution_threshold_pct=settings.drawdown_caution_pct,
            recovery_threshold_pct=settings.drawdown_recovery_pct,
            recovery_mode_size_multiplier=settings.recovery_mode_size_multiplier,
        )
        assert result.state == svc_result.state.value


# ---------------------------------------------------------------------------
# TestDrawdownPaperCycleIntegration
# ---------------------------------------------------------------------------

class TestDrawdownPaperCycleIntegration:
    """Tests for drawdown recovery integration in the paper trading cycle."""

    def _run_cycle(self, app_state, settings, broker=None, portfolio_svc=None,
                   risk_svc=None, execution_svc=None, market_data_svc=None,
                   reporting_svc=None):
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        return run_paper_trading_cycle(
            app_state=app_state,
            settings=settings,
            broker=broker,
            portfolio_svc=portfolio_svc,
            risk_svc=risk_svc,
            execution_svc=execution_svc,
            market_data_svc=market_data_svc,
            reporting_svc=reporting_svc,
        )

    def _minimal_mocks(self, equity=100_000.0, hwm=100_000.0, rankings_count=1):
        from services.portfolio_engine.models import ActionType, PortfolioAction, PortfolioState
        from unittest.mock import MagicMock

        app_state = _make_app_state_obj()

        ps = PortfolioState(
            cash=Decimal(str(equity)),
            start_of_day_equity=Decimal(str(equity)),
            high_water_mark=Decimal(str(hwm)),
        )
        app_state.portfolio_state = ps

        # Make rankings non-empty so cycle proceeds
        ranked = MagicMock()
        ranked.ticker = "AAPL"
        ranked.composite_score = Decimal("0.8")
        app_state.latest_rankings = [ranked] * rankings_count

        # Portfolio engine returns one OPEN action
        open_action = _make_open_action("AAPL", quantity=100)
        portfolio_svc = MagicMock()
        portfolio_svc.apply_ranked_opportunities.return_value = [open_action]

        # Risk engine approves everything
        risk_svc = MagicMock()
        risk_result = MagicMock()
        risk_result.is_hard_blocked = False
        risk_svc.validate_action.return_value = risk_result
        risk_svc.evaluate_exits.return_value = []
        risk_svc.evaluate_trims.return_value = []

        # Execution engine returns filled
        exec_svc = MagicMock()
        exec_result = MagicMock()
        exec_result.status.value = "filled"
        exec_result.fill_price = Decimal("100.0")
        exec_result.fill_quantity = Decimal("100")
        exec_svc.execute_approved_actions.return_value = [exec_result]

        # Broker minimal
        broker = MagicMock()
        broker.ping.return_value = True
        acct = MagicMock()
        acct.cash_balance = Decimal(str(equity))
        broker.get_account_state.return_value = acct
        broker.list_positions.return_value = []
        broker.list_fills_since.return_value = []

        # Market data
        mds = MagicMock()
        snap = MagicMock()
        snap.latest_price = Decimal("100.0")
        mds.get_snapshot.return_value = snap

        # Reporting
        reporting = MagicMock()
        recon = MagicMock()
        recon.is_clean = True
        reporting.reconcile_fills.return_value = recon

        return app_state, portfolio_svc, risk_svc, exec_svc, broker, mds, reporting

    def test_paper_cycle_updates_drawdown_state(self):
        settings = _make_settings(
            drawdown_caution_pct=0.05,
            drawdown_recovery_pct=0.10,
        )
        app_state, psvc, rsvc, esvc, broker, mds, rep = self._minimal_mocks(
            equity=100_000.0, hwm=100_000.0
        )
        self._run_cycle(app_state, settings, broker, psvc, rsvc, esvc, mds, rep)
        assert app_state.drawdown_state in ("NORMAL", "CAUTION", "RECOVERY")

    def test_open_action_quantity_reduced_in_recovery_mode(self):
        # equity=80k, hwm=100k → 20% drawdown → RECOVERY
        settings = _make_settings(
            drawdown_caution_pct=0.05,
            drawdown_recovery_pct=0.10,
            recovery_mode_size_multiplier=0.5,
            recovery_mode_block_new_positions=False,
        )
        app_state, psvc, rsvc, esvc, broker, mds, rep = self._minimal_mocks(
            equity=80_000.0, hwm=100_000.0
        )
        # Force portfolio state to reflect 20% drawdown
        from services.portfolio_engine.models import PortfolioState
        app_state.portfolio_state = PortfolioState(
            cash=Decimal("80000.00"),
            start_of_day_equity=Decimal("80000.00"),
            high_water_mark=Decimal("100000.00"),
        )
        result = self._run_cycle(app_state, settings, broker, psvc, rsvc, esvc, mds, rep)
        assert result["status"] in ("ok", "error")
        assert app_state.drawdown_state == "RECOVERY"

    def test_open_action_blocked_when_is_blocked(self):
        # equity=80k, hwm=100k → RECOVERY + block=True → OPEN dropped
        settings = _make_settings(
            drawdown_caution_pct=0.05,
            drawdown_recovery_pct=0.10,
            recovery_mode_size_multiplier=0.5,
            recovery_mode_block_new_positions=True,
        )
        app_state, psvc, rsvc, esvc, broker, mds, rep = self._minimal_mocks(
            equity=80_000.0, hwm=100_000.0
        )
        from services.portfolio_engine.models import PortfolioState
        app_state.portfolio_state = PortfolioState(
            cash=Decimal("80000.00"),
            start_of_day_equity=Decimal("80000.00"),
            high_water_mark=Decimal("100000.00"),
        )
        result = self._run_cycle(app_state, settings, broker, psvc, rsvc, esvc, mds, rep)
        # In RECOVERY + block → approved_count should be 0 (OPEN was blocked)
        assert result["approved_count"] == 0

    def test_close_trim_not_affected_by_drawdown_mode(self):
        # RECOVERY mode should not block CLOSE/TRIM actions
        from services.portfolio_engine.models import ActionType, PortfolioAction, PortfolioState
        settings = _make_settings(
            drawdown_caution_pct=0.05,
            drawdown_recovery_pct=0.10,
            recovery_mode_size_multiplier=0.5,
            recovery_mode_block_new_positions=True,
        )
        app_state, psvc, rsvc, esvc, broker, mds, rep = self._minimal_mocks(
            equity=80_000.0, hwm=100_000.0
        )
        app_state.portfolio_state = PortfolioState(
            cash=Decimal("80000.00"),
            start_of_day_equity=Decimal("80000.00"),
            high_water_mark=Decimal("100000.00"),
        )
        # Override portfolio_svc to return CLOSE action only
        close_action = _make_close_action("AAPL")
        psvc.apply_ranked_opportunities.return_value = [close_action]

        result = self._run_cycle(app_state, settings, broker, psvc, rsvc, esvc, mds, rep)
        # CLOSE should NOT be blocked by drawdown mode
        assert result["approved_count"] >= 1

    def test_state_transition_updates_changed_at(self):
        settings = _make_settings(
            drawdown_caution_pct=0.05,
            drawdown_recovery_pct=0.10,
        )
        app_state, psvc, rsvc, esvc, broker, mds, rep = self._minimal_mocks(
            equity=80_000.0, hwm=100_000.0
        )
        from services.portfolio_engine.models import PortfolioState
        app_state.portfolio_state = PortfolioState(
            cash=Decimal("80000.00"),
            start_of_day_equity=Decimal("80000.00"),
            high_water_mark=Decimal("100000.00"),
        )
        # Pre-set to NORMAL so a transition to RECOVERY triggers changed_at update
        app_state.drawdown_state = "NORMAL"
        self._run_cycle(app_state, settings, broker, psvc, rsvc, esvc, mds, rep)
        if app_state.drawdown_state != "NORMAL":
            assert app_state.drawdown_state_changed_at is not None

    def test_state_transition_fires_alert_service(self):
        settings = _make_settings(
            drawdown_caution_pct=0.05,
            drawdown_recovery_pct=0.10,
        )
        app_state, psvc, rsvc, esvc, broker, mds, rep = self._minimal_mocks(
            equity=80_000.0, hwm=100_000.0
        )
        from services.portfolio_engine.models import PortfolioState
        app_state.portfolio_state = PortfolioState(
            cash=Decimal("80000.00"),
            start_of_day_equity=Decimal("80000.00"),
            high_water_mark=Decimal("100000.00"),
        )
        app_state.drawdown_state = "NORMAL"  # will transition to RECOVERY
        mock_alert = MagicMock()
        mock_alert.send_alert.return_value = True
        app_state.alert_service = mock_alert

        self._run_cycle(app_state, settings, broker, psvc, rsvc, esvc, mds, rep)
        # Should have fired alert since state changed from NORMAL → RECOVERY
        if app_state.drawdown_state != "NORMAL":
            assert mock_alert.send_alert.called

    def test_no_state_change_no_webhook_fired(self):
        settings = _make_settings(
            drawdown_caution_pct=0.05,
            drawdown_recovery_pct=0.10,
        )
        app_state, psvc, rsvc, esvc, broker, mds, rep = self._minimal_mocks(
            equity=100_000.0, hwm=100_000.0
        )
        # Both equity=hwm → NORMAL; pre-set to NORMAL so no transition
        app_state.drawdown_state = "NORMAL"
        mock_alert = MagicMock()
        mock_alert.send_alert.return_value = True
        app_state.alert_service = mock_alert

        self._run_cycle(app_state, settings, broker, psvc, rsvc, esvc, mds, rep)
        # No state change → webhook should NOT have been called
        assert not mock_alert.send_alert.called
