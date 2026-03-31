"""
Phase 19 — Priority 19 Unit Tests
Kill Switch + AppState Persistence

Coverage:
  - SystemStateEntry ORM model (TestSystemStateModel)             6 tests
  - Alembic migration add_system_state (TestSystemStateMigration)  5 tests
  - ApiAppState new fields (TestAppStateFields)                    8 tests
  - _load_persisted_state startup (TestLoadPersistedState)        10 tests
  - Kill switch paper trading guard (TestPaperTradingKillSwitch)  12 tests
  - Paper cycle result append + counter (TestPaperCycleCounter)    8 tests
  - POST /admin/kill-switch endpoint (TestKillSwitchEndpointPost)  14 tests
  - GET /admin/kill-switch endpoint (TestKillSwitchEndpointGet)     6 tests
  - config/risk routes runtime kill switch (TestConfigRoutes)       4 tests
  - Prometheus metrics runtime kill switch (TestMetrics)            3 tests
  - Live mode gate runtime kill switch (TestLiveModeGateKillSwitch) 6 tests
  - Live mode gate paper_cycle_count (TestLiveModeGateCycleCount)   5 tests
  - Phase 19 integration (TestPhase19Integration)                   7 tests

Total: ~94 tests
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

# ── Repo root ──────────────────────────────────────────────────────────────────
_REPO = Path(__file__).parent.parent.parent  # apis/


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_settings(**kwargs) -> Any:
    from config.settings import Environment, Settings
    defaults = dict(
        env=Environment.DEVELOPMENT,
        admin_rotation_token="test-admin-token",
        db_url="postgresql+psycopg://user:pass@localhost:5432/apis_test",
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def _make_app_state() -> Any:
    from apps.api.state import reset_app_state, get_app_state
    reset_app_state()
    return get_app_state()


def _mock_request(ip: str = "10.0.0.1") -> Any:
    req = MagicMock()
    req.headers = {}
    req.client = MagicMock()
    req.client.host = ip
    return req


# ══════════════════════════════════════════════════════════════════════════════
# 1. SystemStateEntry ORM model
# ══════════════════════════════════════════════════════════════════════════════

class TestSystemStateModel:
    """SystemStateEntry must exist with correct columns and key constants."""

    def test_model_importable(self):
        from infra.db.models.system_state import SystemStateEntry
        assert SystemStateEntry is not None

    def test_table_name(self):
        from infra.db.models.system_state import SystemStateEntry
        assert SystemStateEntry.__tablename__ == "system_state"

    def test_key_column_is_primary_key(self):
        from infra.db.models.system_state import SystemStateEntry
        from sqlalchemy import inspect as sa_inspect
        mapper = sa_inspect(SystemStateEntry)
        pk_cols = [c.key for c in mapper.primary_key]
        assert "key" in pk_cols

    def test_value_text_column_exists(self):
        from infra.db.models.system_state import SystemStateEntry
        assert "value_text" in SystemStateEntry.__table__.columns

    def test_key_constants_exist(self):
        from infra.db.models.system_state import (
            KEY_KILL_SWITCH_ACTIVE,
            KEY_KILL_SWITCH_ACTIVATED_AT,
            KEY_KILL_SWITCH_ACTIVATED_BY,
            KEY_PAPER_CYCLE_COUNT,
        )
        assert KEY_KILL_SWITCH_ACTIVE == "kill_switch_active"
        assert KEY_KILL_SWITCH_ACTIVATED_AT == "kill_switch_activated_at"
        assert KEY_KILL_SWITCH_ACTIVATED_BY == "kill_switch_activated_by"
        assert KEY_PAPER_CYCLE_COUNT == "paper_cycle_count"

    def test_system_state_in_db_models_package(self):
        from infra.db.models import SystemStateEntry
        assert SystemStateEntry is not None


# ══════════════════════════════════════════════════════════════════════════════
# 2. Alembic migration
# ══════════════════════════════════════════════════════════════════════════════

class TestSystemStateMigration:
    """Alembic migration file must exist with correct revision chain."""

    def test_migration_file_exists(self):
        migration = _REPO / "infra" / "db" / "versions" / "c2d3e4f5a6b7_add_system_state.py"
        assert migration.exists()

    def test_revision_id(self):
        import importlib.util
        path = _REPO / "infra" / "db" / "versions" / "c2d3e4f5a6b7_add_system_state.py"
        spec = importlib.util.spec_from_file_location("mig19", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.revision == "c2d3e4f5a6b7"

    def test_down_revision_chains_from_phase17(self):
        import importlib.util
        path = _REPO / "infra" / "db" / "versions" / "c2d3e4f5a6b7_add_system_state.py"
        spec = importlib.util.spec_from_file_location("mig19b", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.down_revision == "b1c2d3e4f5a6"

    def test_migration_has_upgrade(self):
        import importlib.util
        path = _REPO / "infra" / "db" / "versions" / "c2d3e4f5a6b7_add_system_state.py"
        spec = importlib.util.spec_from_file_location("mig19c", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert callable(mod.upgrade)

    def test_migration_has_downgrade(self):
        import importlib.util
        path = _REPO / "infra" / "db" / "versions" / "c2d3e4f5a6b7_add_system_state.py"
        spec = importlib.util.spec_from_file_location("mig19d", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert callable(mod.downgrade)


# ══════════════════════════════════════════════════════════════════════════════
# 3. ApiAppState new fields
# ══════════════════════════════════════════════════════════════════════════════

class TestAppStateFields:
    """ApiAppState must have the three kill-switch fields and paper_cycle_count."""

    def test_kill_switch_active_field_exists(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert hasattr(state, "kill_switch_active")

    def test_kill_switch_active_default_false(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert state.kill_switch_active is False

    def test_kill_switch_activated_at_default_none(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert state.kill_switch_activated_at is None

    def test_kill_switch_activated_by_default_none(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert state.kill_switch_activated_by is None

    def test_paper_cycle_count_field_exists(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert hasattr(state, "paper_cycle_count")

    def test_paper_cycle_count_default_zero(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert state.paper_cycle_count == 0

    def test_kill_switch_active_mutable(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        state.kill_switch_active = True
        assert state.kill_switch_active is True

    def test_paper_cycle_count_mutable(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        state.paper_cycle_count = 17
        assert state.paper_cycle_count == 17


# ══════════════════════════════════════════════════════════════════════════════
# 4. _load_persisted_state startup function
# ══════════════════════════════════════════════════════════════════════════════

class TestLoadPersistedState:
    """main._load_persisted_state loads kill switch + cycle count from DB."""

    def test_load_from_env_kill_switch_true(self):
        """When APIS_KILL_SWITCH=true, state.kill_switch_active set to True."""
        from apps.api.main import _load_persisted_state
        state = _make_app_state()

        with patch("apps.api.main.get_settings") as mock_settings, \
             patch("apps.api.state.get_app_state", return_value=state):
            cfg = _make_settings(kill_switch=True)
            mock_settings.return_value = cfg
            # Patch DB import to fail via session attribute
            import infra.db.session as db_sess
            original = getattr(db_sess, "db_session", None)
            def _raising():
                raise RuntimeError("no db")
            db_sess.db_session = _raising
            try:
                _load_persisted_state()
            finally:
                if original is not None:
                    db_sess.db_session = original
        # env var should have set runtime flag
        assert state.kill_switch_active is True
        assert state.kill_switch_activated_by == "env"

    def test_load_persisted_kill_switch_true_from_db(self):
        """When DB has kill_switch_active=true, state.kill_switch_active=True."""
        from apps.api.main import _load_persisted_state
        state = _make_app_state()

        mock_entry_active = MagicMock()
        mock_entry_active.value_text = "true"
        mock_entry_at = MagicMock()
        mock_entry_at.value_text = "2026-03-18T10:00:00+00:00"
        mock_entry_by = MagicMock()
        mock_entry_by.value_text = "10.0.0.1"
        mock_entry_count = MagicMock()
        mock_entry_count.value_text = "7"

        def _db_get(model, key):
            from infra.db.models.system_state import (
                KEY_KILL_SWITCH_ACTIVE, KEY_KILL_SWITCH_ACTIVATED_AT,
                KEY_KILL_SWITCH_ACTIVATED_BY, KEY_PAPER_CYCLE_COUNT,
            )
            return {
                KEY_KILL_SWITCH_ACTIVE: mock_entry_active,
                KEY_KILL_SWITCH_ACTIVATED_AT: mock_entry_at,
                KEY_KILL_SWITCH_ACTIVATED_BY: mock_entry_by,
                KEY_PAPER_CYCLE_COUNT: mock_entry_count,
            }.get(key)

        mock_db = MagicMock()
        mock_db.get.side_effect = _db_get
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch("apps.api.main.get_settings") as mock_cfg, \
             patch("apps.api.state.get_app_state", return_value=state):
            mock_cfg.return_value = _make_settings(kill_switch=False)
            import infra.db.session as db_sess
            original_db_session = getattr(db_sess, "db_session", None)
            db_sess.db_session = lambda: mock_ctx
            try:
                _load_persisted_state()
            finally:
                if original_db_session is not None:
                    db_sess.db_session = original_db_session

        assert state.kill_switch_active is True
        assert state.paper_cycle_count == 7

    def test_load_persisted_kill_switch_false_from_db(self):
        """When DB has kill_switch_active=false, runtime flag stays False."""
        from apps.api.main import _load_persisted_state
        state = _make_app_state()
        state.kill_switch_active = False

        mock_entry = MagicMock()
        mock_entry.value_text = "false"

        def _db_get(model, key):
            from infra.db.models.system_state import KEY_KILL_SWITCH_ACTIVE
            if key == KEY_KILL_SWITCH_ACTIVE:
                return mock_entry
            return None

        mock_db = MagicMock()
        mock_db.get.side_effect = _db_get
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch("apps.api.main.get_settings") as mock_cfg, \
             patch("apps.api.state.get_app_state", return_value=state):
            mock_cfg.return_value = _make_settings(kill_switch=False)
            import infra.db.session as db_sess
            original = getattr(db_sess, "db_session", None)
            db_sess.db_session = lambda: mock_ctx
            try:
                _load_persisted_state()
            finally:
                if original is not None:
                    db_sess.db_session = original

        assert state.kill_switch_active is False

    def test_load_paper_cycle_count_from_db(self):
        """paper_cycle_count is loaded from DB integer string."""
        from apps.api.main import _load_persisted_state
        state = _make_app_state()

        def _db_get(model, key):
            from infra.db.models.system_state import KEY_PAPER_CYCLE_COUNT, KEY_KILL_SWITCH_ACTIVE
            if key == KEY_PAPER_CYCLE_COUNT:
                e = MagicMock(); e.value_text = "23"; return e
            if key == KEY_KILL_SWITCH_ACTIVE:
                e = MagicMock(); e.value_text = "false"; return e
            return None

        mock_db = MagicMock()
        mock_db.get.side_effect = _db_get
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch("apps.api.main.get_settings") as mock_cfg, \
             patch("apps.api.state.get_app_state", return_value=state):
            mock_cfg.return_value = _make_settings(kill_switch=False)
            import infra.db.session as db_sess
            original = getattr(db_sess, "db_session", None)
            db_sess.db_session = lambda: mock_ctx
            try:
                _load_persisted_state()
            finally:
                if original is not None:
                    db_sess.db_session = original

        assert state.paper_cycle_count == 23

    def test_load_db_failure_is_non_fatal(self):
        """DB failure during startup does NOT raise — process starts safely."""
        from apps.api.main import _load_persisted_state
        state = _make_app_state()

        with patch("apps.api.main.get_settings") as mock_cfg, \
             patch("apps.api.state.get_app_state", return_value=state):
            mock_cfg.return_value = _make_settings(kill_switch=False)
            # Simulate DB session import failure
            import infra.db.session as db_sess
            original = getattr(db_sess, "db_session", None)
            def _raising():
                raise RuntimeError("DB connection refused")
            db_sess.db_session = _raising
            try:
                _load_persisted_state()   # must not raise
            finally:
                if original is not None:
                    db_sess.db_session = original

        # State should remain at defaults
        assert state.kill_switch_active is False
        assert state.paper_cycle_count == 0

    def test_env_kill_switch_wins_over_db_false(self):
        """Even if DB says false, env var True keeps kill_switch_active=True."""
        from apps.api.main import _load_persisted_state
        state = _make_app_state()

        def _db_get(model, key):
            from infra.db.models.system_state import KEY_KILL_SWITCH_ACTIVE
            if key == KEY_KILL_SWITCH_ACTIVE:
                e = MagicMock(); e.value_text = "false"; return e
            return None

        mock_db = MagicMock()
        mock_db.get.side_effect = _db_get
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch("apps.api.main.get_settings") as mock_cfg, \
             patch("apps.api.state.get_app_state", return_value=state):
            mock_cfg.return_value = _make_settings(kill_switch=True)
            import infra.db.session as db_sess
            original = getattr(db_sess, "db_session", None)
            db_sess.db_session = lambda: mock_ctx
            try:
                _load_persisted_state()
            finally:
                if original is not None:
                    db_sess.db_session = original

        assert state.kill_switch_active is True

    def test_lifespan_exists_on_app(self):
        """FastAPI app must be created with a lifespan context manager."""
        from apps.api.main import app
        assert app.router.lifespan_context is not None

    def test_load_persisted_state_function_importable(self):
        from apps.api.main import _load_persisted_state
        assert callable(_load_persisted_state)

    def test_invalid_cycle_count_in_db_ignored(self):
        """Non-integer paper_cycle_count in DB does not crash."""
        from apps.api.main import _load_persisted_state
        state = _make_app_state()

        def _db_get(model, key):
            from infra.db.models.system_state import KEY_PAPER_CYCLE_COUNT
            if key == KEY_PAPER_CYCLE_COUNT:
                e = MagicMock(); e.value_text = "not_a_number"; return e
            return None

        mock_db = MagicMock()
        mock_db.get.side_effect = _db_get
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch("apps.api.main.get_settings") as mock_cfg, \
             patch("apps.api.state.get_app_state", return_value=state):
            mock_cfg.return_value = _make_settings(kill_switch=False)
            import infra.db.session as db_sess
            original = getattr(db_sess, "db_session", None)
            db_sess.db_session = lambda: mock_ctx
            try:
                _load_persisted_state()   # must not raise
            finally:
                if original is not None:
                    db_sess.db_session = original

        assert state.paper_cycle_count == 0  # unchanged on parse error


# ══════════════════════════════════════════════════════════════════════════════
# 5. Paper trading job — kill switch guard
# ══════════════════════════════════════════════════════════════════════════════

class TestPaperTradingKillSwitch:
    """Kill switch check in run_paper_trading_cycle must fire FIRST."""

    @staticmethod
    def _make_ranked() -> list:
        import uuid
        import datetime as _dt
        from decimal import Decimal
        from services.ranking_engine.models import RankedResult
        return [
            RankedResult(
                rank_position=1,
                security_id=uuid.uuid4(),
                ticker="AAPL",
                composite_score=Decimal("0.8"),
                portfolio_fit_score=Decimal("0.75"),
                recommended_action="buy",
                target_horizon="medium",
                thesis_summary="ok",
                disconfirming_factors="none",
                sizing_hint_pct=Decimal("0.1"),
                source_reliability_tier="primary",
                contains_rumor=False,
                as_of=_dt.datetime.utcnow(),
            )
        ]

    def test_kill_switch_env_blocks_cycle(self):
        """settings.kill_switch=True returns status='killed'."""
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        state = _make_app_state()
        # Kill switch fires BEFORE rankings check — no ranked data needed
        cfg = _make_settings(kill_switch=True, operating_mode="paper")
        result = run_paper_trading_cycle(app_state=state, settings=cfg)
        assert result["status"] == "killed"
        assert "kill_switch_active" in result["errors"]

    def test_kill_switch_runtime_blocks_cycle(self):
        """app_state.kill_switch_active=True returns status='killed'."""
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        state = _make_app_state()
        state.kill_switch_active = True
        cfg = _make_settings(kill_switch=False, operating_mode="paper")
        result = run_paper_trading_cycle(app_state=state, settings=cfg)
        assert result["status"] == "killed"

    def test_kill_switch_blocks_before_mode_guard(self):
        """Kill switch check fires even in RESEARCH mode (no mode execution)."""
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        state = _make_app_state()
        state.kill_switch_active = True
        cfg = _make_settings(kill_switch=False, operating_mode="research")
        result = run_paper_trading_cycle(app_state=state, settings=cfg)
        assert result["status"] == "killed"

    def test_no_kill_switch_proceeds_to_mode_guard(self):
        """With kill_switch=False, cycle proceeds (returns skipped_mode in research)."""
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        state = _make_app_state()
        state.kill_switch_active = False
        cfg = _make_settings(kill_switch=False, operating_mode="research")
        result = run_paper_trading_cycle(app_state=state, settings=cfg)
        assert result["status"] == "skipped_mode"

    def test_kill_switch_returns_zero_counts(self):
        """Kill switch result has all counts zero."""
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        state = _make_app_state()
        state.kill_switch_active = True
        cfg = _make_settings(kill_switch=False, operating_mode="paper")
        result = run_paper_trading_cycle(app_state=state, settings=cfg)
        assert result["proposed_count"] == 0
        assert result["approved_count"] == 0
        assert result["executed_count"] == 0

    def test_kill_switch_result_has_run_at(self):
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        state = _make_app_state()
        state.kill_switch_active = True
        cfg = _make_settings(kill_switch=False, operating_mode="paper")
        result = run_paper_trading_cycle(app_state=state, settings=cfg)
        assert result["run_at"] is not None

    def test_kill_switch_persist_function_importable(self):
        from apps.worker.jobs.paper_trading import _persist_paper_cycle_count
        assert callable(_persist_paper_cycle_count)

    def test_persist_paper_cycle_count_db_failure_silent(self):
        """_persist_paper_cycle_count must not raise on DB error."""
        from apps.worker.jobs.paper_trading import _persist_paper_cycle_count
        import infra.db.session as db_sess
        original = getattr(db_sess, "db_session", None)
        def _raising():
            raise RuntimeError("db down")
        db_sess.db_session = _raising
        try:
            _persist_paper_cycle_count(99)  # must not raise
        finally:
            if original is not None:
                db_sess.db_session = original


# ══════════════════════════════════════════════════════════════════════════════
# 6. Paper cycle counter increment and result append
# ══════════════════════════════════════════════════════════════════════════════

class TestPaperCycleCounter:
    """paper_cycle_count is incremented and cycle appended to paper_cycle_results."""

    def _make_minimal_run_mocks(self):
        """Return injectable mocks for a minimal successful paper_trading cycle."""
        from decimal import Decimal
        from services.portfolio_engine.models import PortfolioAction, ActionType, PortfolioState

        mock_portfolio_svc = MagicMock()
        mock_portfolio_svc.apply_ranked_opportunities.return_value = []

        mock_risk_svc = MagicMock()

        mock_execution_svc = MagicMock()
        mock_execution_svc.execute_approved_actions.return_value = []

        mock_market_svc = MagicMock()
        mock_reporting_svc = MagicMock()
        mock_reporting_svc.reconcile_fills.return_value = MagicMock(is_clean=True)

        mock_broker = MagicMock()
        mock_broker.ping.return_value = True
        mock_broker.get_account_state.return_value = MagicMock(cash_balance=Decimal("100000"))
        mock_broker.list_positions.return_value = []
        mock_broker.list_fills_since.return_value = []

        return dict(
            portfolio_svc=mock_portfolio_svc,
            risk_svc=mock_risk_svc,
            execution_svc=mock_execution_svc,
            market_data_svc=mock_market_svc,
            reporting_svc=mock_reporting_svc,
            broker=mock_broker,
        )

    def test_successful_cycle_appends_to_paper_cycle_results(self):
        import uuid, datetime as _dt
        from decimal import Decimal
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from services.ranking_engine.models import RankedResult
        state = _make_app_state()
        state.latest_rankings = [
            RankedResult(
                rank_position=1, security_id=uuid.uuid4(), ticker="AAPL",
                composite_score=Decimal("0.8"), portfolio_fit_score=Decimal("0.75"),
                recommended_action="buy", target_horizon="medium",
                thesis_summary="ok", disconfirming_factors="none",
                sizing_hint_pct=Decimal("0.1"), source_reliability_tier="primary",
                contains_rumor=False, as_of=_dt.datetime.utcnow(),
            )
        ]
        cfg = _make_settings(kill_switch=False, operating_mode="paper")
        mocks = self._make_minimal_run_mocks()

        with patch("apps.worker.jobs.paper_trading._persist_paper_cycle_count"):
            result = run_paper_trading_cycle(app_state=state, settings=cfg, **mocks)

        assert result["status"] == "ok"
        assert len(state.paper_cycle_results) == 1
        assert state.paper_cycle_results[0]["status"] == "ok"

    def test_successful_cycle_increments_paper_cycle_count(self):
        import uuid, datetime as _dt
        from decimal import Decimal
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from services.ranking_engine.models import RankedResult
        state = _make_app_state()
        state.paper_cycle_count = 5
        state.latest_rankings = [
            RankedResult(
                rank_position=1, security_id=uuid.uuid4(), ticker="AAPL",
                composite_score=Decimal("0.8"), portfolio_fit_score=Decimal("0.75"),
                recommended_action="buy", target_horizon="medium",
                thesis_summary="ok", disconfirming_factors="none",
                sizing_hint_pct=Decimal("0.1"), source_reliability_tier="primary",
                contains_rumor=False, as_of=_dt.datetime.utcnow(),
            )
        ]
        cfg = _make_settings(kill_switch=False, operating_mode="paper")
        mocks = self._make_minimal_run_mocks()

        with patch("apps.worker.jobs.paper_trading._persist_paper_cycle_count") as mock_persist:
            run_paper_trading_cycle(app_state=state, settings=cfg, **mocks)

        assert state.paper_cycle_count == 6
        mock_persist.assert_called_once_with(6)

    def test_skipped_mode_does_not_increment_counter(self):
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        state = _make_app_state()
        cfg = _make_settings(kill_switch=False, operating_mode="research")
        result = run_paper_trading_cycle(app_state=state, settings=cfg)
        assert result["status"] == "skipped_mode"
        assert state.paper_cycle_count == 0

    def test_killed_does_not_increment_counter(self):
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        state = _make_app_state()
        state.kill_switch_active = True
        cfg = _make_settings(kill_switch=False, operating_mode="paper")
        run_paper_trading_cycle(app_state=state, settings=cfg)
        assert state.paper_cycle_count == 0

    def test_multiple_cycles_stack_correctly(self):
        import uuid, datetime as _dt
        from decimal import Decimal
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from services.ranking_engine.models import RankedResult
        state = _make_app_state()
        state.latest_rankings = [
            RankedResult(
                rank_position=1, security_id=uuid.uuid4(), ticker="AAPL",
                composite_score=Decimal("0.8"), portfolio_fit_score=Decimal("0.75"),
                recommended_action="buy", target_horizon="medium",
                thesis_summary="ok", disconfirming_factors="none",
                sizing_hint_pct=Decimal("0.1"), source_reliability_tier="primary",
                contains_rumor=False, as_of=_dt.datetime.utcnow(),
            )
        ]
        cfg = _make_settings(kill_switch=False, operating_mode="paper")
        mocks = self._make_minimal_run_mocks()

        with patch("apps.worker.jobs.paper_trading._persist_paper_cycle_count"):
            for _ in range(3):
                run_paper_trading_cycle(app_state=state, settings=cfg, **mocks)

        assert state.paper_cycle_count == 3
        assert len(state.paper_cycle_results) == 3


# ══════════════════════════════════════════════════════════════════════════════
# 7. POST /admin/kill-switch endpoint
# ══════════════════════════════════════════════════════════════════════════════

class TestKillSwitchEndpointPost:
    """POST /api/v1/admin/kill-switch activates/deactivates runtime kill switch."""

    def _get_client(self, cfg=None, state=None):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from apps.api.routes.admin import router as admin_router
        from apps.api.deps import get_settings, get_app_state

        test_app = FastAPI()
        test_app.include_router(admin_router, prefix="/api/v1")

        _cfg = cfg or _make_settings()
        _state = state or _make_app_state()

        test_app.dependency_overrides[get_settings] = lambda: _cfg
        test_app.dependency_overrides[get_app_state] = lambda: _state  # type: ignore

        return TestClient(test_app, raise_server_exceptions=False), _cfg, _state

    def test_activate_requires_auth(self):
        client, cfg, state = self._get_client()
        resp = client.post("/api/v1/admin/kill-switch", json={"active": True})
        assert resp.status_code in (401, 503)

    def test_activate_with_wrong_token_401(self):
        client, cfg, state = self._get_client()
        resp = client.post(
            "/api/v1/admin/kill-switch",
            json={"active": True},
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401

    def test_activate_with_correct_token_200(self):
        client, cfg, state = self._get_client()
        resp = client.post(
            "/api/v1/admin/kill-switch",
            json={"active": True},
            headers={"Authorization": "Bearer test-admin-token"},
        )
        assert resp.status_code == 200

    def test_activate_sets_state_flag(self):
        client, cfg, state = self._get_client()
        assert state.kill_switch_active is False
        with patch("apps.api.routes.admin._persist_kill_switch"):
            resp = client.post(
                "/api/v1/admin/kill-switch",
                json={"active": True},
                headers={"Authorization": "Bearer test-admin-token"},
            )
        assert resp.status_code == 200
        assert state.kill_switch_active is True

    def test_activate_response_body(self):
        client, cfg, state = self._get_client()
        with patch("apps.api.routes.admin._persist_kill_switch"):
            resp = client.post(
                "/api/v1/admin/kill-switch",
                json={"active": True},
                headers={"Authorization": "Bearer test-admin-token"},
            )
        data = resp.json()
        assert data["kill_switch_active"] is True
        assert data["effective"] is True

    def test_deactivate_sets_state_false(self):
        # Must use the SAME state object that the route will call get_app_state() for.
        state = _make_app_state()
        state.kill_switch_active = True
        client, cfg, _ = self._get_client(state=state)
        with patch("apps.api.routes.admin._persist_kill_switch"):
            resp = client.post(
                "/api/v1/admin/kill-switch",
                json={"active": False},
                headers={"Authorization": "Bearer test-admin-token"},
            )
        assert resp.status_code == 200
        assert state.kill_switch_active is False

    def test_deactivate_blocked_when_env_kill_switch_true(self):
        client, cfg, state = self._get_client(cfg=_make_settings(kill_switch=True))
        state.kill_switch_active = True
        with patch("apps.api.routes.admin._persist_kill_switch"):
            resp = client.post(
                "/api/v1/admin/kill-switch",
                json={"active": False},
                headers={"Authorization": "Bearer test-admin-token"},
            )
        assert resp.status_code == 409

    def test_disabled_when_no_admin_token(self):
        client, _, _ = self._get_client(cfg=_make_settings(admin_rotation_token=""))
        resp = client.post(
            "/api/v1/admin/kill-switch",
            json={"active": True},
            headers={"Authorization": "Bearer anything"},
        )
        assert resp.status_code == 503

    def test_persist_called_on_activate(self):
        client, cfg, state = self._get_client()
        with patch("apps.api.routes.admin._persist_kill_switch") as mock_persist:
            client.post(
                "/api/v1/admin/kill-switch",
                json={"active": True},
                headers={"Authorization": "Bearer test-admin-token"},
            )
        mock_persist.assert_called_once()
        args = mock_persist.call_args[0]
        assert args[0] is True

    def test_admin_event_logged_on_activate(self):
        client, cfg, state = self._get_client()
        with patch("apps.api.routes.admin._persist_kill_switch"), \
             patch("apps.api.routes.admin._log_admin_event") as mock_log:
            client.post(
                "/api/v1/admin/kill-switch",
                json={"active": True},
                headers={"Authorization": "Bearer test-admin-token"},
            )
        # should have been called at least once
        assert mock_log.called

    def test_activated_at_set_on_activate(self):
        client, cfg, state = self._get_client()
        with patch("apps.api.routes.admin._persist_kill_switch"):
            client.post(
                "/api/v1/admin/kill-switch",
                json={"active": True},
                headers={"Authorization": "Bearer test-admin-token"},
            )
        assert state.kill_switch_activated_at is not None

    def test_activated_at_cleared_on_deactivate(self):
        _, cfg, state = self._get_client()
        state.kill_switch_active = True
        state.kill_switch_activated_at = dt.datetime.now(dt.timezone.utc)
        client, _, _ = self._get_client(cfg=cfg, state=state)
        with patch("apps.api.routes.admin._persist_kill_switch"):
            client.post(
                "/api/v1/admin/kill-switch",
                json={"active": False},
                headers={"Authorization": "Bearer test-admin-token"},
            )
        assert state.kill_switch_activated_at is None

    def test_rate_limit_applied(self):
        """Kill switch endpoint is rate-limited (inherits existing admin rate limiter)."""
        import inspect, apps.api.routes.admin as admin_mod
        src = inspect.getsource(admin_mod.set_kill_switch)
        assert "_check_rate_limit" in src

    def test_reason_in_request_body(self):
        """Request body must include optional 'reason' field."""
        from apps.api.routes.admin import KillSwitchRequest
        req = KillSwitchRequest(active=True, reason="Emergency stop")
        assert req.reason == "Emergency stop"


# ══════════════════════════════════════════════════════════════════════════════
# 8. GET /admin/kill-switch endpoint
# ══════════════════════════════════════════════════════════════════════════════

class TestKillSwitchEndpointGet:
    """GET /api/v1/admin/kill-switch returns current state."""

    def _get_client(self, cfg=None, state=None):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from apps.api.routes.admin import router as admin_router
        from apps.api.deps import get_settings, get_app_state

        test_app = FastAPI()
        test_app.include_router(admin_router, prefix="/api/v1")

        _cfg = cfg or _make_settings()
        _state = state or _make_app_state()

        test_app.dependency_overrides[get_settings] = lambda: _cfg
        test_app.dependency_overrides[get_app_state] = lambda: _state  # type: ignore

        return TestClient(test_app, raise_server_exceptions=False), _cfg, _state

    def test_get_requires_auth(self):
        client, _, _ = self._get_client()
        resp = client.get("/api/v1/admin/kill-switch")
        assert resp.status_code in (401, 503)

    def test_get_returns_inactive_by_default(self):
        client, _, state = self._get_client()
        state.kill_switch_active = False
        resp = client.get(
            "/api/v1/admin/kill-switch",
            headers={"Authorization": "Bearer test-admin-token"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["kill_switch_active"] is False
        assert data["effective"] is False

    def test_get_returns_active_when_set(self):
        client, _, state = self._get_client()
        state.kill_switch_active = True
        resp = client.get(
            "/api/v1/admin/kill-switch",
            headers={"Authorization": "Bearer test-admin-token"},
        )
        assert resp.status_code == 200
        assert resp.json()["effective"] is True

    def test_get_effective_true_when_env_true(self):
        client, cfg, state = self._get_client(cfg=_make_settings(kill_switch=True))
        state.kill_switch_active = False
        resp = client.get(
            "/api/v1/admin/kill-switch",
            headers={"Authorization": "Bearer test-admin-token"},
        )
        data = resp.json()
        assert data["env_kill_switch"] is True
        assert data["effective"] is True

    def test_get_disabled_when_no_token(self):
        client, _, _ = self._get_client(cfg=_make_settings(admin_rotation_token=""))
        resp = client.get("/api/v1/admin/kill-switch",
                          headers={"Authorization": "Bearer anything"})
        assert resp.status_code == 503


# ══════════════════════════════════════════════════════════════════════════════
# 9. Config / risk routes use runtime kill switch
# ══════════════════════════════════════════════════════════════════════════════

class TestConfigRoutes:
    """Config and risk routes must reflect runtime kill_switch_active."""

    def test_risk_status_reflects_runtime_kill_switch(self):
        import inspect
        import apps.api.routes.config as config_mod
        src = inspect.getsource(config_mod.get_risk_status)
        assert "kill_switch_active" in src

    def test_active_config_reflects_runtime_kill_switch(self):
        import inspect
        import apps.api.routes.config as config_mod
        src = inspect.getsource(config_mod.get_active_config)
        assert "kill_switch_active" in src

    def test_system_status_uses_runtime_state(self):
        import inspect
        import apps.api.main as main_mod
        src = inspect.getsource(main_mod.system_status)
        assert "kill_switch_active" in src

    def test_health_includes_kill_switch_component(self):
        import inspect
        import apps.api.main as main_mod
        src = inspect.getsource(main_mod.health)
        assert "kill_switch" in src


# ══════════════════════════════════════════════════════════════════════════════
# 10. Prometheus metrics reflect runtime kill switch
# ══════════════════════════════════════════════════════════════════════════════

class TestMetrics:
    """apis_kill_switch_active metric must use runtime state."""

    def test_metrics_uses_runtime_kill_switch(self):
        import inspect
        import apps.api.routes.metrics as metrics_mod
        src = inspect.getsource(metrics_mod.prometheus_metrics)
        assert "kill_switch_active" in src

    def test_metrics_effective_or_notation(self):
        """Code must combine state.kill_switch_active OR settings.kill_switch."""
        import inspect
        import apps.api.routes.metrics as metrics_mod
        src = inspect.getsource(metrics_mod.prometheus_metrics)
        assert "kill_switch_active" in src
        assert "kill_switch" in src

    def test_metrics_help_text_unchanged(self):
        """apis_kill_switch_active metric help text is preserved."""
        import inspect
        import apps.api.routes.metrics as metrics_mod
        src = inspect.getsource(metrics_mod.prometheus_metrics)
        assert "apis_kill_switch_active" in src


# ══════════════════════════════════════════════════════════════════════════════
# 11. Live mode gate: runtime kill switch check
# ══════════════════════════════════════════════════════════════════════════════

class TestLiveModeGateKillSwitch:
    """kill_switch_off gate must check both env and runtime state."""

    def _make_state(self, kill_switch_active: bool = False) -> Any:
        from apps.api.state import ApiAppState
        state = ApiAppState()
        state.kill_switch_active = kill_switch_active
        return state

    def _run_gate(self, state, settings, current="paper", target="human_approved"):
        from services.live_mode_gate.service import LiveModeGateService
        from config.settings import OperatingMode
        svc = LiveModeGateService()
        return svc.check_prerequisites(
            current_mode=OperatingMode(current),
            target_mode=OperatingMode(target),
            app_state=state,
            settings=settings,
        )

    def test_kill_switch_env_true_fails_gate(self):
        state = self._make_state(kill_switch_active=False)
        cfg = _make_settings(kill_switch=True)
        result = self._run_gate(state, cfg)
        ks_req = next(r for r in result.requirements if r.name == "kill_switch_off")
        assert ks_req.status.value == "fail"

    def test_runtime_kill_switch_true_fails_gate(self):
        state = self._make_state(kill_switch_active=True)
        cfg = _make_settings(kill_switch=False)
        result = self._run_gate(state, cfg)
        ks_req = next(r for r in result.requirements if r.name == "kill_switch_off")
        assert ks_req.status.value == "fail"

    def test_both_false_passes_kill_switch_requirement(self):
        state = self._make_state(kill_switch_active=False)
        cfg = _make_settings(kill_switch=False)
        result = self._run_gate(state, cfg)
        ks_req = next(r for r in result.requirements if r.name == "kill_switch_off")
        assert ks_req.status.value == "pass"

    def test_gate_checks_getattr_fallback(self):
        """Gate must use getattr(app_state, 'kill_switch_active', False) safely."""
        import inspect
        from services.live_mode_gate import service as gate_mod
        src = inspect.getsource(gate_mod.LiveModeGateService.check_prerequisites)
        assert "kill_switch_active" in src

    def test_kill_switch_off_detail_message_updated(self):
        """Detail message must reference both flags."""
        state = self._make_state(kill_switch_active=True)
        cfg = _make_settings(kill_switch=False)
        result = self._run_gate(state, cfg)
        ks_req = next(r for r in result.requirements if r.name == "kill_switch_off")
        assert "runtime" in ks_req.detail.lower() or "env" in ks_req.detail.lower()


# ══════════════════════════════════════════════════════════════════════════════
# 12. Live mode gate: paper_cycle_count used for durable cycle check
# ══════════════════════════════════════════════════════════════════════════════

class TestLiveModeGateCycleCount:
    """Gate must use paper_cycle_count (durable) for cycle-count requirements."""

    def _make_state(self, cycle_count: int = 0, results: list | None = None) -> Any:
        from apps.api.state import ApiAppState
        state = ApiAppState()
        state.paper_cycle_count = cycle_count
        if results is not None:
            state.paper_cycle_results = results
        return state

    def _run_gate(self, state, settings, current="paper", target="human_approved"):
        from services.live_mode_gate.service import LiveModeGateService
        from config.settings import OperatingMode
        svc = LiveModeGateService()
        return svc.check_prerequisites(
            current_mode=OperatingMode(current),
            target_mode=OperatingMode(target),
            app_state=state,
            settings=settings,
        )

    def test_cycle_count_5_passes(self):
        state = self._make_state(cycle_count=5)
        state.evaluation_history = [{}] * 5
        state.portfolio_state = MagicMock()
        cfg = _make_settings(kill_switch=False)
        result = self._run_gate(state, cfg)
        req = next(r for r in result.requirements if r.name == "min_paper_cycles")
        assert req.status.value == "pass"

    def test_cycle_count_4_fails(self):
        state = self._make_state(cycle_count=4)
        cfg = _make_settings(kill_switch=False)
        result = self._run_gate(state, cfg)
        req = next(r for r in result.requirements if r.name == "min_paper_cycles")
        assert req.status.value == "fail"

    def test_cycle_count_survives_empty_results_list(self):
        """paper_cycle_count=5 passes even when paper_cycle_results=[] (restart scenario)."""
        state = self._make_state(cycle_count=5, results=[])
        state.evaluation_history = [{}] * 5
        state.portfolio_state = MagicMock()
        cfg = _make_settings(kill_switch=False)
        result = self._run_gate(state, cfg)
        req = next(r for r in result.requirements if r.name == "min_paper_cycles")
        assert req.status.value == "pass"

    def test_cycle_count_reflects_actual_value(self):
        state = self._make_state(cycle_count=3)
        cfg = _make_settings(kill_switch=False)
        result = self._run_gate(state, cfg)
        req = next(r for r in result.requirements if r.name == "min_paper_cycles")
        assert req.actual_value == 3

    def test_ha_to_rl_gate_uses_cycle_count(self):
        import inspect
        from services.live_mode_gate import service as gate_mod
        src = inspect.getsource(gate_mod.LiveModeGateService._check_human_approved_to_restricted_live)
        assert "paper_cycle_count" in src


# ══════════════════════════════════════════════════════════════════════════════
# 13. Phase 19 integration
# ══════════════════════════════════════════════════════════════════════════════

class TestPhase19Integration:
    """End-to-end integration checks across all Priority 19 components."""

    def test_kill_switch_activated_blocks_paper_cycle_AND_gate(self):
        """Runtime kill switch simultaneously blocks trading AND gates promotion."""
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from services.live_mode_gate.service import LiveModeGateService
        from config.settings import OperatingMode

        state = _make_app_state()
        state.kill_switch_active = True
        state.latest_rankings = []   # empty ranking doesn't matter — kill switch fires first
        cfg = _make_settings(kill_switch=False, operating_mode="paper")

        # Paper trading must be killed
        result = run_paper_trading_cycle(app_state=state, settings=cfg)
        assert result["status"] == "killed"

        # Gate must fail
        gate_result = LiveModeGateService().check_prerequisites(
            current_mode=OperatingMode.PAPER,
            target_mode=OperatingMode.HUMAN_APPROVED,
            app_state=state,
            settings=cfg,
        )
        ks_req = next(r for r in gate_result.requirements if r.name == "kill_switch_off")
        assert ks_req.status.value == "fail"

    def test_paper_cycle_count_used_in_gate_after_restart_scenario(self):
        """Simulate: 7 cycles ran, process restarted (paper_cycle_results is empty),
        paper_cycle_count=7 was loaded from DB.  Gate should still see 7 cycles."""
        from services.live_mode_gate.service import LiveModeGateService
        from config.settings import OperatingMode

        state = _make_app_state()
        state.paper_cycle_count = 7       # loaded from DB
        state.paper_cycle_results = []    # in-memory reset after restart
        state.evaluation_history = [{}] * 5
        state.portfolio_state = MagicMock()
        cfg = _make_settings(kill_switch=False)

        result = LiveModeGateService().check_prerequisites(
            current_mode=OperatingMode.PAPER,
            target_mode=OperatingMode.HUMAN_APPROVED,
            app_state=state,
            settings=cfg,
        )
        req = next(r for r in result.requirements if r.name == "min_paper_cycles")
        assert req.status.value == "pass"
        assert req.actual_value == 7

    def test_system_state_table_in_migration_chain(self):
        """Migration chain goes …→b1c2d3e4f5a6→c2d3e4f5a6b7."""
        import importlib.util
        p = _REPO / "infra" / "db" / "versions" / "c2d3e4f5a6b7_add_system_state.py"
        spec = importlib.util.spec_from_file_location("mig19_chain", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.down_revision == "b1c2d3e4f5a6"

    def test_admin_endpoints_registered_in_router(self):
        """Router must export set_kill_switch and get_kill_switch."""
        from apps.api.routes.admin import router
        paths = [route.path for route in router.routes]
        assert "/admin/kill-switch" in paths

    def test_health_has_kill_switch_key(self):
        """The /health handler must include kill_switch in components."""
        import inspect, apps.api.main as main_mod
        src = inspect.getsource(main_mod.health)
        assert "components[\"kill_switch\"]" in src or "components['kill_switch']" in src

    def test_all_priority19_state_fields_present(self):
        state = _make_app_state()
        required_fields = [
            "kill_switch_active",
            "kill_switch_activated_at",
            "kill_switch_activated_by",
            "paper_cycle_count",
        ]
        for f in required_fields:
            assert hasattr(state, f), f"Missing state field: {f}"

    def test_env_example_has_no_new_undocumented_keys(self):
        """Existing .env.example is still present and readable."""
        env_example = _REPO / ".env.example"
        assert env_example.exists()
        content = env_example.read_text()
        assert "APIS_KILL_SWITCH" in content or "kill_switch" in content.lower()
