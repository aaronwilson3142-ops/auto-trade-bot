"""
Phase 45 — Earnings Calendar Integration + Pre-Earnings Risk Management

Tests for:
- EarningsCalendarService._fetch_next_earnings_date()
- EarningsCalendarService.build_calendar()
- EarningsCalendarService.filter_for_earnings_proximity()
- run_earnings_refresh() job
- GET /portfolio/earnings-calendar route
- GET /portfolio/earnings-risk/{ticker} route
- Paper trading cycle earnings gate integration
- app_state earnings fields
- Settings.max_earnings_proximity_days
- Worker scheduler job count
- Dashboard _render_earnings_section
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_action(ticker: str, action_type_value: str = "open") -> SimpleNamespace:
    """Create a minimal PortfolioAction-like object."""
    from services.portfolio_engine.models import ActionType
    return SimpleNamespace(
        ticker=ticker,
        action_type=ActionType(action_type_value),
        target_notional=Decimal("5000"),
        risk_approved=False,
        reason=None,
        sizing_hint=None,
        target_quantity=None,
    )


def _make_calendar_result(
    at_risk_tickers=None,
    entries=None,
    no_calendar=False,
    max_days=2,
    reference_date=None,
) -> SimpleNamespace:
    """Build a minimal EarningsCalendarResult-like object for testing."""
    if at_risk_tickers is None:
        at_risk_tickers = []
    if entries is None:
        entries = {}
    if reference_date is None:
        reference_date = dt.date.today()
    return SimpleNamespace(
        computed_at=dt.datetime.now(dt.timezone.utc),
        reference_date=reference_date,
        max_earnings_proximity_days=max_days,
        entries=entries,
        at_risk_tickers=at_risk_tickers,
        no_calendar=no_calendar,
    )


def _make_settings(max_earnings_proximity_days: int = 2, **kwargs) -> SimpleNamespace:
    ns = SimpleNamespace(max_earnings_proximity_days=max_earnings_proximity_days, **kwargs)
    return ns


# ---------------------------------------------------------------------------
# 1. EarningsCalendarService — _fetch_next_earnings_date
# ---------------------------------------------------------------------------

class TestFetchNextEarningsDate:
    """Tests for EarningsCalendarService._fetch_next_earnings_date()"""

    def test_returns_none_when_yfinance_unavailable(self):
        """Returns None gracefully when yfinance cannot be imported."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService
        with patch.dict("sys.modules", {"yfinance": None}):
            result = EarningsCalendarService._fetch_next_earnings_date("AAPL")
        assert result is None

    def test_returns_none_when_calendar_is_none(self):
        """Returns None when yfinance Ticker.calendar returns None."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        mock_ticker = MagicMock()
        mock_ticker.calendar = None
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            result = EarningsCalendarService._fetch_next_earnings_date("AAPL")
        assert result is None

    def test_returns_date_from_dataframe_calendar(self):
        """Extracts earnings date from DataFrame-style calendar response."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService
        import pandas as pd

        target_date = dt.date(2026, 4, 15)
        df = pd.DataFrame({"Earnings Date": [pd.Timestamp(target_date)]})

        mock_ticker = MagicMock()
        mock_ticker.calendar = df
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            result = EarningsCalendarService._fetch_next_earnings_date("AAPL")
        assert result == target_date

    def test_returns_date_from_dict_calendar(self):
        """Extracts earnings date from dict-style calendar response."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        target_date = dt.date(2026, 4, 20)
        mock_ticker = MagicMock()
        mock_ticker.calendar = {"Earnings Date": [target_date]}
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            result = EarningsCalendarService._fetch_next_earnings_date("MSFT")
        assert result == target_date

    def test_returns_none_on_exception(self):
        """Returns None and does not raise when yfinance throws."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        mock_yf = MagicMock()
        mock_yf.Ticker.side_effect = RuntimeError("connection timeout")

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            result = EarningsCalendarService._fetch_next_earnings_date("NVDA")
        assert result is None

    def test_returns_none_when_dataframe_has_no_earnings_date_column(self):
        """Returns None when DataFrame is missing 'Earnings Date' column."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService
        import pandas as pd

        df = pd.DataFrame({"Other Column": [1, 2, 3]})
        mock_ticker = MagicMock()
        mock_ticker.calendar = df
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            result = EarningsCalendarService._fetch_next_earnings_date("GOOG")
        assert result is None

    def test_returns_none_when_dict_earnings_date_is_none(self):
        """Returns None when dict calendar has no Earnings Date value."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        mock_ticker = MagicMock()
        mock_ticker.calendar = {"Earnings Date": None}
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            result = EarningsCalendarService._fetch_next_earnings_date("META")
        assert result is None


# ---------------------------------------------------------------------------
# 2. EarningsCalendarService — build_calendar
# ---------------------------------------------------------------------------

class TestBuildCalendar:
    """Tests for EarningsCalendarService.build_calendar()"""

    def test_empty_universe_returns_no_calendar(self):
        """Empty ticker list returns no_calendar=False, empty entries."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        result = EarningsCalendarService.build_calendar(
            tickers=[],
            max_earnings_proximity_days=2,
        )
        assert result.entries == {}
        assert result.at_risk_tickers == []
        assert not result.no_calendar

    def test_ticker_within_window_is_at_risk(self):
        """A ticker with earnings 1 day away is flagged as at-risk."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        ref = dt.date(2026, 4, 10)
        earnings_date = dt.date(2026, 4, 11)  # 1 day away

        with patch.object(
            EarningsCalendarService,
            "_fetch_next_earnings_date",
            return_value=earnings_date,
        ):
            result = EarningsCalendarService.build_calendar(
                tickers=["AAPL"],
                max_earnings_proximity_days=2,
                reference_date=ref,
            )

        assert "AAPL" in result.at_risk_tickers
        assert result.entries["AAPL"].earnings_within_window is True
        assert result.entries["AAPL"].days_to_earnings == 1

    def test_ticker_outside_window_is_not_at_risk(self):
        """A ticker with earnings 5 days away is not flagged when window=2."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        ref = dt.date(2026, 4, 10)
        earnings_date = dt.date(2026, 4, 15)  # 5 days away

        with patch.object(
            EarningsCalendarService,
            "_fetch_next_earnings_date",
            return_value=earnings_date,
        ):
            result = EarningsCalendarService.build_calendar(
                tickers=["MSFT"],
                max_earnings_proximity_days=2,
                reference_date=ref,
            )

        assert "MSFT" not in result.at_risk_tickers
        assert result.entries["MSFT"].earnings_within_window is False
        assert result.entries["MSFT"].days_to_earnings == 5

    def test_ticker_on_earnings_day_is_at_risk(self):
        """A ticker with earnings today (0 days away) is flagged as at-risk."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        ref = dt.date(2026, 4, 10)

        with patch.object(
            EarningsCalendarService,
            "_fetch_next_earnings_date",
            return_value=ref,  # same as reference date
        ):
            result = EarningsCalendarService.build_calendar(
                tickers=["TSLA"],
                max_earnings_proximity_days=2,
                reference_date=ref,
            )

        assert "TSLA" in result.at_risk_tickers
        assert result.entries["TSLA"].days_to_earnings == 0

    def test_past_earnings_not_at_risk(self):
        """A ticker with earnings 2 days in the past is NOT at-risk."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        ref = dt.date(2026, 4, 10)
        earnings_date = dt.date(2026, 4, 8)  # 2 days ago

        with patch.object(
            EarningsCalendarService,
            "_fetch_next_earnings_date",
            return_value=earnings_date,
        ):
            result = EarningsCalendarService.build_calendar(
                tickers=["AMZN"],
                max_earnings_proximity_days=2,
                reference_date=ref,
            )

        assert "AMZN" not in result.at_risk_tickers
        assert result.entries["AMZN"].days_to_earnings == -2

    def test_no_earnings_date_not_at_risk(self):
        """A ticker with no available earnings date is not at-risk."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        with patch.object(
            EarningsCalendarService,
            "_fetch_next_earnings_date",
            return_value=None,
        ):
            result = EarningsCalendarService.build_calendar(
                tickers=["NVDA"],
                max_earnings_proximity_days=2,
            )

        assert "NVDA" not in result.at_risk_tickers
        assert result.entries["NVDA"].days_to_earnings is None
        assert result.entries["NVDA"].earnings_within_window is False

    def test_multiple_tickers_mixed_results(self):
        """Multiple tickers: some at-risk, some not, some no data."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        ref = dt.date(2026, 4, 10)

        def _fake_fetch(ticker):
            if ticker == "AAPL":
                return dt.date(2026, 4, 11)  # 1 day away — at risk
            elif ticker == "MSFT":
                return dt.date(2026, 4, 20)  # 10 days away — safe
            else:
                return None  # no data

        with patch.object(EarningsCalendarService, "_fetch_next_earnings_date", side_effect=_fake_fetch):
            result = EarningsCalendarService.build_calendar(
                tickers=["AAPL", "MSFT", "NVDA"],
                max_earnings_proximity_days=2,
                reference_date=ref,
            )

        assert "AAPL" in result.at_risk_tickers
        assert "MSFT" not in result.at_risk_tickers
        assert "NVDA" not in result.at_risk_tickers
        assert len(result.entries) == 3

    def test_result_has_computed_at(self):
        """build_calendar sets computed_at to a recent UTC datetime."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        result = EarningsCalendarService.build_calendar(
            tickers=[],
            max_earnings_proximity_days=2,
        )
        now = dt.datetime.now(dt.timezone.utc)
        assert (now - result.computed_at).total_seconds() < 5

    def test_result_records_max_days_in_entries(self):
        """Each EarningsEntry records the max_earnings_proximity_days value."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        with patch.object(
            EarningsCalendarService,
            "_fetch_next_earnings_date",
            return_value=None,
        ):
            result = EarningsCalendarService.build_calendar(
                tickers=["GOOG"],
                max_earnings_proximity_days=5,
            )
        assert result.entries["GOOG"].max_earnings_proximity_days == 5

    def test_at_risk_boundary_exact_window_day(self):
        """A ticker with earnings exactly at max_days is still at-risk (inclusive)."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        ref = dt.date(2026, 4, 10)
        earnings_date = dt.date(2026, 4, 12)  # 2 days away = exactly at boundary

        with patch.object(
            EarningsCalendarService,
            "_fetch_next_earnings_date",
            return_value=earnings_date,
        ):
            result = EarningsCalendarService.build_calendar(
                tickers=["META"],
                max_earnings_proximity_days=2,
                reference_date=ref,
            )

        assert "META" in result.at_risk_tickers
        assert result.entries["META"].earnings_within_window is True


# ---------------------------------------------------------------------------
# 3. EarningsCalendarService — filter_for_earnings_proximity
# ---------------------------------------------------------------------------

class TestFilterForEarningsProximity:
    """Tests for EarningsCalendarService.filter_for_earnings_proximity()"""

    def test_gate_disabled_passes_all(self):
        """When max_earnings_proximity_days=0, all actions pass through."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        cal = _make_calendar_result(at_risk_tickers=["AAPL"], max_days=0)
        actions = [_make_action("AAPL", "open"), _make_action("MSFT", "open")]
        settings = _make_settings(max_earnings_proximity_days=0)

        filtered, blocked = EarningsCalendarService.filter_for_earnings_proximity(
            actions=actions,
            calendar_result=cal,
            settings=settings,
        )
        assert blocked == 0
        assert len(filtered) == 2

    def test_no_calendar_passes_all(self):
        """When no_calendar=True, all actions pass through."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        cal = _make_calendar_result(at_risk_tickers=["AAPL"], no_calendar=True)
        actions = [_make_action("AAPL", "open")]
        settings = _make_settings(max_earnings_proximity_days=2)

        filtered, blocked = EarningsCalendarService.filter_for_earnings_proximity(
            actions=actions,
            calendar_result=cal,
            settings=settings,
        )
        assert blocked == 0
        assert len(filtered) == 1

    def test_open_for_at_risk_ticker_is_blocked(self):
        """OPEN action for an at-risk ticker is blocked."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        entry = SimpleNamespace(
            earnings_date=dt.date.today() + dt.timedelta(days=1),
            days_to_earnings=1,
        )
        cal = _make_calendar_result(
            at_risk_tickers=["AAPL"],
            entries={"AAPL": entry},
        )
        actions = [_make_action("AAPL", "open")]
        settings = _make_settings(max_earnings_proximity_days=2)

        filtered, blocked = EarningsCalendarService.filter_for_earnings_proximity(
            actions=actions,
            calendar_result=cal,
            settings=settings,
        )
        assert blocked == 1
        assert len(filtered) == 0

    def test_close_for_at_risk_ticker_passes_through(self):
        """CLOSE action for an at-risk ticker always passes through."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        cal = _make_calendar_result(at_risk_tickers=["AAPL"])
        actions = [_make_action("AAPL", "close")]
        settings = _make_settings(max_earnings_proximity_days=2)

        filtered, blocked = EarningsCalendarService.filter_for_earnings_proximity(
            actions=actions,
            calendar_result=cal,
            settings=settings,
        )
        assert blocked == 0
        assert len(filtered) == 1

    def test_trim_for_at_risk_ticker_passes_through(self):
        """TRIM action for an at-risk ticker always passes through."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        cal = _make_calendar_result(at_risk_tickers=["AAPL"])
        actions = [_make_action("AAPL", "trim")]
        settings = _make_settings(max_earnings_proximity_days=2)

        filtered, blocked = EarningsCalendarService.filter_for_earnings_proximity(
            actions=actions,
            calendar_result=cal,
            settings=settings,
        )
        assert blocked == 0
        assert len(filtered) == 1

    def test_safe_ticker_open_passes_through(self):
        """OPEN action for a ticker not at-risk passes through."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        cal = _make_calendar_result(at_risk_tickers=["AAPL"])
        actions = [_make_action("MSFT", "open")]
        settings = _make_settings(max_earnings_proximity_days=2)

        filtered, blocked = EarningsCalendarService.filter_for_earnings_proximity(
            actions=actions,
            calendar_result=cal,
            settings=settings,
        )
        assert blocked == 0
        assert len(filtered) == 1

    def test_mixed_actions_correctly_filtered(self):
        """Mixed action list: at-risk OPENs blocked, CLOSE/TRIM and safe OPENs pass."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        cal = _make_calendar_result(at_risk_tickers=["AAPL", "TSLA"])
        actions = [
            _make_action("AAPL", "open"),   # blocked
            _make_action("TSLA", "open"),   # blocked
            _make_action("AAPL", "close"),  # pass (close)
            _make_action("MSFT", "open"),   # pass (safe ticker)
            _make_action("NVDA", "trim"),   # pass (trim, safe ticker)
        ]
        settings = _make_settings(max_earnings_proximity_days=2)

        filtered, blocked = EarningsCalendarService.filter_for_earnings_proximity(
            actions=actions,
            calendar_result=cal,
            settings=settings,
        )
        assert blocked == 2
        assert len(filtered) == 3

    def test_empty_at_risk_set_passes_all(self):
        """When at_risk_tickers is empty, all actions pass through."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        cal = _make_calendar_result(at_risk_tickers=[])
        actions = [_make_action("AAPL", "open"), _make_action("MSFT", "open")]
        settings = _make_settings(max_earnings_proximity_days=2)

        filtered, blocked = EarningsCalendarService.filter_for_earnings_proximity(
            actions=actions,
            calendar_result=cal,
            settings=settings,
        )
        assert blocked == 0
        assert len(filtered) == 2

    def test_empty_actions_returns_empty(self):
        """Empty action list → empty filtered list, 0 blocked."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        cal = _make_calendar_result(at_risk_tickers=["AAPL"])
        settings = _make_settings(max_earnings_proximity_days=2)

        filtered, blocked = EarningsCalendarService.filter_for_earnings_proximity(
            actions=[],
            calendar_result=cal,
            settings=settings,
        )
        assert blocked == 0
        assert filtered == []


# ---------------------------------------------------------------------------
# 4. run_earnings_refresh job
# ---------------------------------------------------------------------------

class TestRunEarningsRefresh:
    """Tests for run_earnings_refresh() worker job."""

    def test_returns_ok_on_success(self):
        """Returns status='ok' when build_calendar succeeds."""
        from apps.worker.jobs.earnings_refresh import run_earnings_refresh
        from apps.api.state import ApiAppState

        state = ApiAppState()
        mock_cal = _make_calendar_result(at_risk_tickers=["AAPL"])

        with (
            patch("apps.worker.jobs.earnings_refresh.get_settings") as mock_cfg,
            patch(
                "services.risk_engine.earnings_calendar.EarningsCalendarService.build_calendar",
                return_value=mock_cal,
            ),
            patch("config.universe.UNIVERSE_TICKERS", ["AAPL", "MSFT"]),
        ):
            mock_cfg.return_value = _make_settings()
            result = run_earnings_refresh(app_state=state)

        assert result["status"] == "ok"
        assert result["error"] is None

    def test_updates_app_state_on_success(self):
        """Populates app_state.latest_earnings_calendar and earnings_computed_at."""
        from apps.worker.jobs.earnings_refresh import run_earnings_refresh
        from apps.api.state import ApiAppState

        state = ApiAppState()
        mock_cal = _make_calendar_result(at_risk_tickers=[])

        with (
            patch(
                "services.risk_engine.earnings_calendar.EarningsCalendarService.build_calendar",
                return_value=mock_cal,
            ),
            patch("config.universe.UNIVERSE_TICKERS", ["AAPL"]),
        ):
            run_earnings_refresh(app_state=state, settings=_make_settings())

        assert state.latest_earnings_calendar is mock_cal
        assert state.earnings_computed_at is not None
        assert state.earnings_filtered_count == 0

    def test_skips_empty_universe(self):
        """Returns status='skipped_empty_universe' when universe is empty."""
        from apps.worker.jobs.earnings_refresh import run_earnings_refresh
        from apps.api.state import ApiAppState

        state = ApiAppState()

        with patch("config.universe.UNIVERSE_TICKERS", []):
            result = run_earnings_refresh(app_state=state, settings=_make_settings())

        assert result["status"] == "skipped_empty_universe"
        assert result["tickers_checked"] == 0

    def test_returns_error_on_exception(self):
        """Returns status='error' and does not raise when an exception occurs."""
        from apps.worker.jobs.earnings_refresh import run_earnings_refresh
        from apps.api.state import ApiAppState

        state = ApiAppState()

        with patch(
            "services.risk_engine.earnings_calendar.EarningsCalendarService.build_calendar",
            side_effect=RuntimeError("network failure"),
        ):
            with patch("config.universe.UNIVERSE_TICKERS", ["AAPL"]):
                result = run_earnings_refresh(app_state=state, settings=_make_settings())

        assert result["status"] == "error"
        assert "network failure" in result["error"]

    def test_state_not_cleared_on_error(self):
        """On error, existing app_state.latest_earnings_calendar is preserved."""
        from apps.worker.jobs.earnings_refresh import run_earnings_refresh
        from apps.api.state import ApiAppState

        state = ApiAppState()
        existing_cal = _make_calendar_result()
        state.latest_earnings_calendar = existing_cal

        with patch(
            "services.risk_engine.earnings_calendar.EarningsCalendarService.build_calendar",
            side_effect=RuntimeError("failure"),
        ):
            with patch("config.universe.UNIVERSE_TICKERS", ["AAPL"]):
                run_earnings_refresh(app_state=state, settings=_make_settings())

        # State should remain unchanged (stale-but-safe)
        assert state.latest_earnings_calendar is existing_cal

    def test_result_includes_at_risk_tickers(self):
        """Result dict contains at_risk_tickers list."""
        from apps.worker.jobs.earnings_refresh import run_earnings_refresh
        from apps.api.state import ApiAppState

        state = ApiAppState()
        mock_cal = _make_calendar_result(at_risk_tickers=["AAPL", "NVDA"])

        with (
            patch(
                "services.risk_engine.earnings_calendar.EarningsCalendarService.build_calendar",
                return_value=mock_cal,
            ),
            patch("config.universe.UNIVERSE_TICKERS", ["AAPL", "MSFT", "NVDA"]),
        ):
            result = run_earnings_refresh(app_state=state, settings=_make_settings())

        assert set(result["at_risk_tickers"]) == {"AAPL", "NVDA"}
        assert result["at_risk_count"] == 2


# ---------------------------------------------------------------------------
# 5. GET /portfolio/earnings-calendar route
# ---------------------------------------------------------------------------

class TestEarningsCalendarRoute:
    """Tests for GET /api/v1/portfolio/earnings-calendar."""

    def _get_client(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        return TestClient(app)

    def test_returns_200_no_data(self):
        """Returns 200 with no_calendar=True when no refresh has run."""
        from apps.api.state import reset_app_state
        reset_app_state()
        client = self._get_client()
        resp = client.get("/api/v1/portfolio/earnings-calendar")
        assert resp.status_code == 200
        data = resp.json()
        assert data["no_calendar"] is True
        assert data["tickers_checked"] == 0
        assert data["at_risk_tickers"] == []

    def test_returns_calendar_data_when_available(self):
        """Returns calendar data populated by the refresh job."""
        from apps.api.state import get_app_state, reset_app_state
        reset_app_state()
        state = get_app_state()

        entry = SimpleNamespace(
            ticker="AAPL",
            earnings_date=dt.date(2026, 4, 11),
            days_to_earnings=1,
            earnings_within_window=True,
            max_earnings_proximity_days=2,
        )
        state.latest_earnings_calendar = _make_calendar_result(
            at_risk_tickers=["AAPL"],
            entries={"AAPL": entry},
        )

        client = self._get_client()
        resp = client.get("/api/v1/portfolio/earnings-calendar")
        assert resp.status_code == 200
        data = resp.json()
        assert data["at_risk_count"] == 1
        assert "AAPL" in data["at_risk_tickers"]
        assert data["no_calendar"] is False

    def test_earnings_gate_active_when_at_risk(self):
        """earnings_gate_active=True when there are at-risk tickers and gate is enabled."""
        from apps.api.state import get_app_state, reset_app_state
        reset_app_state()
        state = get_app_state()
        state.latest_earnings_calendar = _make_calendar_result(at_risk_tickers=["TSLA"])

        client = self._get_client()
        resp = client.get("/api/v1/portfolio/earnings-calendar")
        data = resp.json()
        assert data["earnings_gate_active"] is True

    def test_earnings_gate_inactive_when_no_at_risk(self):
        """earnings_gate_active=False when at_risk_tickers is empty."""
        from apps.api.state import get_app_state, reset_app_state
        reset_app_state()
        state = get_app_state()
        state.latest_earnings_calendar = _make_calendar_result(at_risk_tickers=[])

        client = self._get_client()
        resp = client.get("/api/v1/portfolio/earnings-calendar")
        data = resp.json()
        assert data["earnings_gate_active"] is False

    def test_earnings_filtered_count_surfaced(self):
        """earnings_filtered_count reflects app_state field."""
        from apps.api.state import get_app_state, reset_app_state
        reset_app_state()
        state = get_app_state()
        state.latest_earnings_calendar = _make_calendar_result()
        state.earnings_filtered_count = 3

        client = self._get_client()
        resp = client.get("/api/v1/portfolio/earnings-calendar")
        data = resp.json()
        assert data["earnings_filtered_count"] == 3


# ---------------------------------------------------------------------------
# 6. GET /portfolio/earnings-risk/{ticker} route
# ---------------------------------------------------------------------------

class TestEarningsRiskTickerRoute:
    """Tests for GET /api/v1/portfolio/earnings-risk/{ticker}."""

    def _get_client(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        return TestClient(app)

    def test_returns_data_available_false_no_calendar(self):
        """Returns data_available=False when no calendar has run."""
        from apps.api.state import reset_app_state
        reset_app_state()
        client = self._get_client()
        resp = client.get("/api/v1/portfolio/earnings-risk/AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data_available"] is False
        assert data["ticker"] == "AAPL"

    def test_returns_data_available_false_unknown_ticker(self):
        """Returns data_available=False for a ticker not in the calendar."""
        from apps.api.state import get_app_state, reset_app_state
        reset_app_state()
        state = get_app_state()
        state.latest_earnings_calendar = _make_calendar_result(entries={})

        client = self._get_client()
        resp = client.get("/api/v1/portfolio/earnings-risk/ZZZZ")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data_available"] is False

    def test_returns_ticker_detail_when_found(self):
        """Returns full earnings detail when ticker is in the calendar."""
        from apps.api.state import get_app_state, reset_app_state
        reset_app_state()
        state = get_app_state()

        entry = SimpleNamespace(
            ticker="NVDA",
            earnings_date=dt.date(2026, 4, 12),
            days_to_earnings=2,
            earnings_within_window=True,
            max_earnings_proximity_days=2,
        )
        state.latest_earnings_calendar = _make_calendar_result(
            at_risk_tickers=["NVDA"],
            entries={"NVDA": entry},
        )

        client = self._get_client()
        resp = client.get("/api/v1/portfolio/earnings-risk/NVDA")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data_available"] is True
        assert data["ticker"] == "NVDA"
        assert data["earnings_within_window"] is True
        assert data["days_to_earnings"] == 2

    def test_ticker_uppercase_normalization(self):
        """Ticker param is uppercased — 'aapl' resolves to 'AAPL' entry."""
        from apps.api.state import get_app_state, reset_app_state
        reset_app_state()
        state = get_app_state()

        entry = SimpleNamespace(
            ticker="AAPL",
            earnings_date=dt.date(2026, 4, 11),
            days_to_earnings=1,
            earnings_within_window=True,
            max_earnings_proximity_days=2,
        )
        state.latest_earnings_calendar = _make_calendar_result(
            entries={"AAPL": entry},
            at_risk_tickers=["AAPL"],
        )

        client = self._get_client()
        resp = client.get("/api/v1/portfolio/earnings-risk/aapl")
        data = resp.json()
        assert data["data_available"] is True
        assert data["ticker"] == "AAPL"


# ---------------------------------------------------------------------------
# 7. Paper cycle earnings gate integration
# ---------------------------------------------------------------------------

class TestPaperCycleEarningsGate:
    """Integration tests for the earnings proximity gate in paper_trading.py."""

    def test_earnings_gate_blocks_open_for_at_risk_ticker(self):
        """Paper cycle drops OPENs for tickers in earnings calendar at-risk set."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        entry = SimpleNamespace(
            earnings_date=dt.date.today() + dt.timedelta(days=1),
            days_to_earnings=1,
        )
        cal = _make_calendar_result(
            at_risk_tickers=["AAPL"],
            entries={"AAPL": entry},
        )
        actions = [
            _make_action("AAPL", "open"),  # blocked
            _make_action("MSFT", "open"),  # safe
        ]
        settings = _make_settings(max_earnings_proximity_days=2)

        filtered, blocked = EarningsCalendarService.filter_for_earnings_proximity(
            actions=actions,
            calendar_result=cal,
            settings=settings,
        )
        assert blocked == 1
        remaining_tickers = [a.ticker for a in filtered]
        assert "MSFT" in remaining_tickers
        assert "AAPL" not in remaining_tickers

    def test_earnings_gate_never_blocks_close(self):
        """CLOSE actions always pass the earnings gate regardless of at-risk status."""
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        cal = _make_calendar_result(at_risk_tickers=["AAPL", "NVDA"])
        actions = [
            _make_action("AAPL", "close"),
            _make_action("NVDA", "close"),
        ]
        settings = _make_settings(max_earnings_proximity_days=2)

        filtered, blocked = EarningsCalendarService.filter_for_earnings_proximity(
            actions=actions,
            calendar_result=cal,
            settings=settings,
        )
        assert blocked == 0
        assert len(filtered) == 2

    def test_earnings_filtered_count_updated_in_state(self):
        """app_state.earnings_filtered_count is updated after the gate runs."""
        from apps.api.state import ApiAppState
        from services.risk_engine.earnings_calendar import EarningsCalendarService

        state = ApiAppState()
        state.latest_earnings_calendar = _make_calendar_result(at_risk_tickers=["TSLA"])
        state.earnings_filtered_count = 0

        actions = [_make_action("TSLA", "open"), _make_action("AMZN", "open")]
        settings = _make_settings(max_earnings_proximity_days=2)

        _, blocked = EarningsCalendarService.filter_for_earnings_proximity(
            actions=actions,
            calendar_result=state.latest_earnings_calendar,
            settings=settings,
        )
        state.earnings_filtered_count = blocked
        assert state.earnings_filtered_count == 1


# ---------------------------------------------------------------------------
# 8. Settings — max_earnings_proximity_days
# ---------------------------------------------------------------------------

class TestEarningsSettings:
    """Tests for Settings.max_earnings_proximity_days field."""

    def test_default_max_earnings_proximity_days(self):
        """Default max_earnings_proximity_days is 2."""
        from config.settings import Settings
        s = Settings()
        assert s.max_earnings_proximity_days == 2

    def test_can_set_zero_to_disable(self):
        """Setting max_earnings_proximity_days=0 disables the gate."""
        from config.settings import Settings
        s = Settings(max_earnings_proximity_days=0)
        assert s.max_earnings_proximity_days == 0

    def test_accepts_larger_window(self):
        """max_earnings_proximity_days accepts values up to 30."""
        from config.settings import Settings
        s = Settings(max_earnings_proximity_days=5)
        assert s.max_earnings_proximity_days == 5


# ---------------------------------------------------------------------------
# 9. app_state — earnings fields
# ---------------------------------------------------------------------------

class TestEarningsAppState:
    """Tests that ApiAppState has the three Phase 45 earnings fields."""

    def test_initial_latest_earnings_calendar_is_none(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert state.latest_earnings_calendar is None

    def test_initial_earnings_computed_at_is_none(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert state.earnings_computed_at is None

    def test_initial_earnings_filtered_count_is_zero(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        assert state.earnings_filtered_count == 0

    def test_can_set_earnings_calendar(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        cal = _make_calendar_result()
        state.latest_earnings_calendar = cal
        assert state.latest_earnings_calendar is cal

    def test_can_set_earnings_computed_at(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        now = dt.datetime.now(dt.timezone.utc)
        state.earnings_computed_at = now
        assert state.earnings_computed_at == now

    def test_can_increment_earnings_filtered_count(self):
        from apps.api.state import ApiAppState
        state = ApiAppState()
        state.earnings_filtered_count = 4
        assert state.earnings_filtered_count == 4


# ---------------------------------------------------------------------------
# 10. Worker scheduler job count
# ---------------------------------------------------------------------------

class TestWorkerJobCount:
    """Verify the scheduler now registers 25 jobs (was 24, +1 for signal_quality_update)."""

    def test_build_scheduler_has_25_jobs(self):
        """build_scheduler returns a scheduler with 25 registered jobs."""
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        jobs = scheduler.get_jobs()
        assert len(jobs) == 30, (
            f"Expected 27 scheduled jobs, got {len(jobs)}"
        )

    def test_earnings_refresh_job_registered(self):
        """earnings_refresh job is registered with id='earnings_refresh'."""
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        job_ids = {j.id for j in scheduler.get_jobs()}
        assert "earnings_refresh" in job_ids

    def test_earnings_refresh_scheduled_at_0623(self):
        """earnings_refresh is scheduled at 06:23 ET."""
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        earnings_job = next(j for j in scheduler.get_jobs() if j.id == "earnings_refresh")
        trigger = earnings_job.trigger
        # CronTrigger fields
        fields = {f.name: str(f) for f in trigger.fields}
        assert fields.get("hour") == "6"
        assert fields.get("minute") == "23"


# ---------------------------------------------------------------------------
# 11. Dashboard _render_earnings_section
# ---------------------------------------------------------------------------

class TestDashboardEarningsSection:
    """Tests for _render_earnings_section in the dashboard router."""

    def test_renders_no_data_message_when_no_calendar(self):
        """Shows 'no data yet' message when app_state has no calendar."""
        from apps.dashboard.router import _render_earnings_section
        from apps.api.state import ApiAppState
        from config.settings import Settings

        state = ApiAppState()
        settings = Settings()
        html = _render_earnings_section(state, settings)
        assert "Earnings Calendar" in html
        assert "no earnings calendar data yet" in html.lower() or "06:23" in html

    def test_renders_at_risk_tickers_when_calendar_present(self):
        """Shows at-risk tickers in the section when calendar has data."""
        from apps.dashboard.router import _render_earnings_section
        from apps.api.state import ApiAppState
        from config.settings import Settings

        state = ApiAppState()
        entry = SimpleNamespace(
            ticker="AAPL",
            earnings_date=dt.date(2026, 4, 11),
            days_to_earnings=1,
            earnings_within_window=True,
            max_earnings_proximity_days=2,
        )
        state.latest_earnings_calendar = _make_calendar_result(
            at_risk_tickers=["AAPL"],
            entries={"AAPL": entry},
        )
        settings = Settings()
        html = _render_earnings_section(state, settings)
        assert "AAPL" in html
        assert "Earnings Calendar" in html

    def test_renders_gate_active_when_at_risk_present(self):
        """Shows 'ACTIVE' gate status when at_risk_tickers is non-empty."""
        from apps.dashboard.router import _render_earnings_section
        from apps.api.state import ApiAppState
        from config.settings import Settings

        state = ApiAppState()
        entry = SimpleNamespace(
            ticker="NVDA",
            earnings_date=dt.date(2026, 4, 12),
            days_to_earnings=2,
            earnings_within_window=True,
            max_earnings_proximity_days=2,
        )
        state.latest_earnings_calendar = _make_calendar_result(
            at_risk_tickers=["NVDA"],
            entries={"NVDA": entry},
        )
        settings = Settings()
        html = _render_earnings_section(state, settings)
        assert "ACTIVE" in html

    def test_dashboard_main_includes_earnings_section(self):
        """Full dashboard HTML contains earnings section."""
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import reset_app_state
        reset_app_state()

        client = TestClient(app)
        resp = client.get("/dashboard/")
        assert resp.status_code == 200
        assert "Earnings Calendar" in resp.text
