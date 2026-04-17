"""Deep-Dive Plan Step 2 Rec 1 — broker-adapter health invariant tests."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest

from services.broker_adapter.health import (
    BrokerAdapterHealthError,
    check_broker_adapter_health,
)


# ── Stubs ────────────────────────────────────────────────────────────────────


class _Settings:
    def __init__(
        self,
        enabled: bool = True,
        tolerance: float = 0.01,
    ) -> None:
        self.broker_health_invariant_enabled = enabled
        self.broker_health_position_drift_tolerance = tolerance


class _AppState:
    def __init__(self, adapter: Any | None = None) -> None:
        self.broker_adapter = adapter
        self.kill_switch_active = False


class _FakeAdapter:
    def __init__(self, positions_by_ticker: dict[str, Decimal] | None = None):
        self._positions = positions_by_ticker or {}

    @property
    def positions_by_ticker(self) -> dict[str, Decimal]:
        return self._positions


@dataclass
class _FakeRow:
    ticker: str
    quantity: Decimal | None


class _FakeResult:
    """Stubby SQLAlchemy Result that answers either scalar_one_or_none() or .all()."""

    def __init__(
        self,
        *,
        scalar: int | None = None,
        rows: list[tuple] | None = None,
    ) -> None:
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self) -> int | None:
        return self._scalar

    def all(self) -> list[tuple]:
        return self._rows


class _FakeSession:
    def __init__(
        self,
        *,
        count: int = 0,
        rows: list[tuple] | None = None,
    ) -> None:
        self._count = count
        self._rows = rows or []

    def execute(self, _stmt) -> _FakeResult:
        return _FakeResult(scalar=self._count, rows=self._rows)


def _session_factory(count: int = 0, rows: list[tuple] | None = None):
    @contextmanager
    def _factory():
        yield _FakeSession(count=count, rows=rows)

    return _factory


# ── Tests ────────────────────────────────────────────────────────────────────


def test_healthy_state_passes_through():
    app_state = _AppState(adapter=_FakeAdapter())
    settings = _Settings()
    result = check_broker_adapter_health(
        app_state,
        settings,
        db_session_factory=_session_factory(count=0),
    )
    assert result.ok is True
    assert result.adapter_present is True
    assert result.db_position_count == 0
    assert result.drift_tickers == []
    assert app_state.kill_switch_active is False


def test_disabled_flag_is_noop():
    app_state = _AppState(adapter=None)
    settings = _Settings(enabled=False)

    def _should_not_be_called():
        raise AssertionError("db_session_factory invoked when flag off")

    result = check_broker_adapter_health(
        app_state,
        settings,
        db_session_factory=_should_not_be_called,
    )
    assert result.ok is True
    assert result.reason == "disabled"


def test_adapter_missing_with_live_positions_raises_and_fires_ks():
    app_state = _AppState(adapter=None)
    settings = _Settings()

    kill_switch_calls: list[str] = []

    def _fire(reason: str) -> None:
        kill_switch_calls.append(reason)

    with pytest.raises(BrokerAdapterHealthError):
        check_broker_adapter_health(
            app_state,
            settings,
            db_session_factory=_session_factory(count=3),
            fire_kill_switch_fn=_fire,
        )

    assert len(kill_switch_calls) == 1
    assert "broker_adapter_missing_with_live_positions" in kill_switch_calls[0]


def test_default_kill_switch_sets_app_state_flag():
    app_state = _AppState(adapter=None)
    settings = _Settings()

    with pytest.raises(BrokerAdapterHealthError):
        check_broker_adapter_health(
            app_state,
            settings,
            db_session_factory=_session_factory(count=1),
        )

    assert app_state.kill_switch_active is True


def test_drift_is_warned_but_not_fatal():
    adapter = _FakeAdapter(positions_by_ticker={"AAPL": Decimal("100")})
    app_state = _AppState(adapter=adapter)
    settings = _Settings(tolerance=0.01)

    rows = [("AAPL", Decimal("90"))]
    result = check_broker_adapter_health(
        app_state,
        settings,
        db_session_factory=_session_factory(count=1, rows=rows),
    )

    assert result.ok is True
    assert result.adapter_present is True
    assert result.db_position_count == 1
    assert "AAPL" in result.drift_tickers
    assert app_state.kill_switch_active is False


def test_drift_within_tolerance_is_clean():
    adapter = _FakeAdapter(positions_by_ticker={"MSFT": Decimal("100.001")})
    app_state = _AppState(adapter=adapter)
    settings = _Settings(tolerance=0.01)

    rows = [("MSFT", Decimal("100"))]
    result = check_broker_adapter_health(
        app_state,
        settings,
        db_session_factory=_session_factory(count=1, rows=rows),
    )

    assert result.ok is True
    assert result.drift_tickers == []


def test_db_query_failure_does_not_block_cycle():
    app_state = _AppState(adapter=_FakeAdapter())
    settings = _Settings()

    def _broken_factory():
        raise RuntimeError("db down")

    result = check_broker_adapter_health(
        app_state,
        settings,
        db_session_factory=_broken_factory,
    )
    assert result.ok is True
    assert result.db_position_count == 0
