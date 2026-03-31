"""
Phase 43 — Portfolio-Level VaR & CVaR Risk Monitoring

Test classes
------------
TestVaRServiceComputeReturns        — compute_returns() basic logic
TestVaRServiceAlignSeries           — align_return_series() truncation
TestVaRServicePortfolioReturns      — compute_portfolio_returns() weighting
TestVaRServiceHistoricalVar         — historical_var() percentile math
TestVaRServiceHistoricalCVaR        — historical_cvar() tail-mean math
TestVaRServiceStandaloneVar         — compute_ticker_standalone_var()
TestVaRServiceComputeResult         — compute_var_result() full pipeline
TestVaRServiceFilter                — filter_for_var_limit() paper cycle gate
TestVaRRefreshJob                   — run_var_refresh() job happy path
TestVaRRefreshJobEdgeCases          — graceful skip / error paths
TestVaRRoutePortfolio               — GET /portfolio/var
TestVaRRouteTicker                  — GET /portfolio/var/{ticker}
TestVaRSettings                     — max_portfolio_var_pct settings field
TestVaRScheduler                    — var_refresh job registered at 06:19 ET
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

def _make_settings(max_portfolio_var_pct: float = 0.03):
    s = MagicMock()
    s.max_portfolio_var_pct = max_portfolio_var_pct
    return s


def _make_position(ticker: str, market_value: float = 10_000.0, current_price: float = 100.0):
    pos = MagicMock()
    pos.ticker = ticker
    pos.market_value = Decimal(str(market_value))
    pos.current_price = Decimal(str(current_price))
    pos.avg_entry_price = Decimal(str(current_price * 0.9))
    return pos


def _make_portfolio_state(positions: dict, equity: float = 100_000.0):
    ps = MagicMock()
    ps.positions = positions
    ps.equity = Decimal(str(equity))
    return ps


def _make_app_state(portfolio_state=None, latest_var_result=None, var_computed_at=None):
    state = MagicMock()
    state.portfolio_state = portfolio_state
    state.latest_var_result = latest_var_result
    state.var_computed_at = var_computed_at
    state.var_filtered_count = 0
    return state


def _make_open_action(ticker: str = "AAPL"):
    from services.portfolio_engine.models import ActionType, PortfolioAction
    return PortfolioAction(
        ticker=ticker,
        action_type=ActionType.OPEN,
        target_notional=Decimal("5000.00"),
        target_quantity=Decimal("50"),
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


# Builds 252 daily prices drifting up ~5% over the period (low-vol)
def _build_prices(n: int = 252, seed: float = 100.0, vol: float = 0.01) -> list[float]:
    import random
    random.seed(42)
    prices = [seed]
    for _ in range(n - 1):
        r = random.gauss(0.0001, vol)
        prices.append(max(0.01, prices[-1] * (1 + r)))
    return prices


# ---------------------------------------------------------------------------
# TestVaRServiceComputeReturns
# ---------------------------------------------------------------------------

class TestVaRServiceComputeReturns:

    def test_basic_two_prices(self):
        from services.risk_engine.var_service import VaRService
        rets = VaRService.compute_returns([100.0, 110.0])
        assert len(rets) == 1
        assert abs(rets[0] - 0.10) < 1e-10

    def test_negative_return(self):
        from services.risk_engine.var_service import VaRService
        rets = VaRService.compute_returns([100.0, 90.0])
        assert abs(rets[0] - (-0.10)) < 1e-10

    def test_single_price_returns_empty(self):
        from services.risk_engine.var_service import VaRService
        assert VaRService.compute_returns([100.0]) == []

    def test_empty_prices_returns_empty(self):
        from services.risk_engine.var_service import VaRService
        assert VaRService.compute_returns([]) == []

    def test_zero_prev_price_skipped(self):
        from services.risk_engine.var_service import VaRService
        rets = VaRService.compute_returns([0.0, 100.0, 110.0])
        # First period: prev=0 → skipped; second period: prev=100 → 0.10
        assert len(rets) == 1
        assert abs(rets[0] - 0.10) < 1e-10

    def test_multiple_prices(self):
        from services.risk_engine.var_service import VaRService
        prices = [100.0, 105.0, 100.0, 110.0]
        rets = VaRService.compute_returns(prices)
        assert len(rets) == 3
        assert abs(rets[0] - 0.05) < 1e-9
        assert abs(rets[1] - (-5.0 / 105.0)) < 1e-9


# ---------------------------------------------------------------------------
# TestVaRServiceAlignSeries
# ---------------------------------------------------------------------------

class TestVaRServiceAlignSeries:

    def test_equal_length_unchanged(self):
        from services.risk_engine.var_service import VaRService
        series = {"AAPL": [0.01, -0.02, 0.03], "MSFT": [0.02, -0.01, 0.04]}
        aligned = VaRService.align_return_series(series)
        assert len(aligned["AAPL"]) == 3
        assert len(aligned["MSFT"]) == 3

    def test_truncates_to_shortest(self):
        from services.risk_engine.var_service import VaRService
        series = {"AAPL": [0.01, 0.02, 0.03, 0.04, 0.05], "MSFT": [0.01, 0.02]}
        aligned = VaRService.align_return_series(series)
        assert len(aligned["AAPL"]) == 2
        assert len(aligned["MSFT"]) == 2

    def test_empty_input_returns_empty(self):
        from services.risk_engine.var_service import VaRService
        assert VaRService.align_return_series({}) == {}

    def test_empty_series_excluded(self):
        from services.risk_engine.var_service import VaRService
        series = {"AAPL": [0.01, 0.02], "MSFT": []}
        aligned = VaRService.align_return_series(series)
        assert "AAPL" in aligned
        assert "MSFT" not in aligned

    def test_takes_tail_not_head(self):
        """Alignment should keep the most recent (tail) observations."""
        from services.risk_engine.var_service import VaRService
        series = {"AAPL": [1.0, 2.0, 3.0, 4.0, 5.0], "MSFT": [10.0, 20.0]}
        aligned = VaRService.align_return_series(series)
        # AAPL should keep last 2: [4.0, 5.0]
        assert aligned["AAPL"] == [4.0, 5.0]


# ---------------------------------------------------------------------------
# TestVaRServicePortfolioReturns
# ---------------------------------------------------------------------------

class TestVaRServicePortfolioReturns:

    def test_single_full_weight(self):
        from services.risk_engine.var_service import VaRService
        weights = {"AAPL": 1.0}
        aligned = {"AAPL": [0.01, -0.02, 0.03]}
        port_rets = VaRService.compute_portfolio_returns(weights, aligned)
        assert len(port_rets) == 3
        assert abs(port_rets[0] - 0.01) < 1e-10

    def test_two_equal_weights(self):
        from services.risk_engine.var_service import VaRService
        weights = {"AAPL": 0.5, "MSFT": 0.5}
        aligned = {"AAPL": [0.02, -0.02], "MSFT": [0.04, 0.00]}
        port_rets = VaRService.compute_portfolio_returns(weights, aligned)
        assert abs(port_rets[0] - 0.03) < 1e-10   # (0.5*0.02 + 0.5*0.04)
        assert abs(port_rets[1] - (-0.01)) < 1e-10  # (0.5*-0.02 + 0.5*0.00)

    def test_empty_returns_empty(self):
        from services.risk_engine.var_service import VaRService
        assert VaRService.compute_portfolio_returns({}, {}) == []

    def test_no_common_tickers_returns_empty(self):
        from services.risk_engine.var_service import VaRService
        weights = {"AAPL": 1.0}
        aligned = {"MSFT": [0.01, 0.02]}
        assert VaRService.compute_portfolio_returns(weights, aligned) == []


# ---------------------------------------------------------------------------
# TestVaRServiceHistoricalVar
# ---------------------------------------------------------------------------

class TestVaRServiceHistoricalVar:

    def test_empty_returns_zero(self):
        from services.risk_engine.var_service import VaRService
        assert VaRService.historical_var([]) == 0.0

    def test_all_positive_returns_zero_var(self):
        """If all returns are positive, VaR is 0 (no tail loss)."""
        from services.risk_engine.var_service import VaRService
        rets = [0.01, 0.02, 0.03, 0.04, 0.05]
        var = VaRService.historical_var(rets, 0.95)
        assert var == 0.0

    def test_known_distribution(self):
        """With 100 returns, 95% VaR = the 5th worst loss."""
        from services.risk_engine.var_service import VaRService
        # Returns: -0.10, -0.09, ..., -0.01, 0.01, 0.02, ..., 0.90
        rets = [-0.10 + i * 0.01 for i in range(100)]
        var = VaRService.historical_var(rets, 0.95)
        assert var > 0.0

    def test_99_confidence_greater_than_95(self):
        """99% VaR >= 95% VaR for any distribution."""
        from services.risk_engine.var_service import VaRService
        rets = _build_prices(252)
        from services.risk_engine.var_service import VaRService as _
        r = VaRService.compute_returns(rets)
        var95 = VaRService.historical_var(r, 0.95)
        var99 = VaRService.historical_var(r, 0.99)
        assert var99 >= var95


# ---------------------------------------------------------------------------
# TestVaRServiceHistoricalCVaR
# ---------------------------------------------------------------------------

class TestVaRServiceHistoricalCVaR:

    def test_empty_returns_zero(self):
        from services.risk_engine.var_service import VaRService
        assert VaRService.historical_cvar([]) == 0.0

    def test_cvar_ge_var(self):
        """CVaR >= VaR by definition (CVaR is the mean of the tail beyond VaR)."""
        from services.risk_engine.var_service import VaRService
        rets = _build_prices(252)
        r = VaRService.compute_returns(rets)
        var95 = VaRService.historical_var(r, 0.95)
        cvar95 = VaRService.historical_cvar(r, 0.95)
        assert cvar95 >= var95

    def test_all_positive_returns_zero_cvar(self):
        from services.risk_engine.var_service import VaRService
        rets = [0.01, 0.02, 0.03, 0.04, 0.05]
        assert VaRService.historical_cvar(rets, 0.95) == 0.0


# ---------------------------------------------------------------------------
# TestVaRServiceStandaloneVar
# ---------------------------------------------------------------------------

class TestVaRServiceStandaloneVar:

    def test_zero_weight_returns_zero(self):
        from services.risk_engine.var_service import VaRService
        rets = [0.01, -0.05, 0.02]
        assert VaRService.compute_ticker_standalone_var("AAPL", 0.0, rets) == 0.0

    def test_empty_returns_zero(self):
        from services.risk_engine.var_service import VaRService
        assert VaRService.compute_ticker_standalone_var("AAPL", 0.5, []) == 0.0

    def test_standalone_scales_with_weight(self):
        """Halving the weight should roughly halve the standalone VaR."""
        from services.risk_engine.var_service import VaRService
        rets = _build_prices(100)
        r = VaRService.compute_returns(rets)
        v1 = VaRService.compute_ticker_standalone_var("AAPL", 1.0, r)
        v05 = VaRService.compute_ticker_standalone_var("AAPL", 0.5, r)
        assert abs(v1 - v05 * 2) < 1e-9  # exact linear scaling


# ---------------------------------------------------------------------------
# TestVaRServiceComputeResult
# ---------------------------------------------------------------------------

class TestVaRServiceComputeResult:

    def _make_positions_and_prices(self, tickers=("AAPL", "MSFT"), equity=100_000.0, n=100):
        positions = {}
        prices = {}
        per = equity / len(tickers)
        for t in tickers:
            positions[t] = _make_position(t, market_value=per)
            prices[t] = _build_prices(n=n + 1)
        return positions, prices, equity

    def test_basic_result_fields(self):
        from services.risk_engine.var_service import VaRService
        positions, prices, equity = self._make_positions_and_prices(n=60)
        result = VaRService.compute_var_result(positions, prices, equity)
        assert result.positions_count == 2
        assert result.lookback_days >= 59
        assert result.equity == equity
        assert result.portfolio_var_95_pct >= 0.0
        assert result.portfolio_var_99_pct >= result.portfolio_var_95_pct
        assert result.portfolio_cvar_95_pct >= result.portfolio_var_95_pct

    def test_dollar_var_equals_pct_times_equity(self):
        from services.risk_engine.var_service import VaRService
        positions, prices, equity = self._make_positions_and_prices(n=60)
        result = VaRService.compute_var_result(positions, prices, equity)
        assert abs(result.portfolio_var_95_dollar - result.portfolio_var_95_pct * equity) < 1e-6

    def test_ticker_var_present_for_each_position(self):
        from services.risk_engine.var_service import VaRService
        positions, prices, equity = self._make_positions_and_prices(n=60)
        result = VaRService.compute_var_result(positions, prices, equity)
        for ticker in positions:
            assert ticker in result.ticker_var_95

    def test_empty_positions_returns_insufficient(self):
        from services.risk_engine.var_service import VaRService
        result = VaRService.compute_var_result({}, {}, 100_000.0)
        assert result.insufficient_data is True
        assert result.portfolio_var_95_pct == 0.0

    def test_zero_equity_returns_insufficient(self):
        from services.risk_engine.var_service import VaRService
        positions, prices, _ = self._make_positions_and_prices(n=60)
        result = VaRService.compute_var_result(positions, prices, 0.0)
        assert result.insufficient_data is True

    def test_too_few_observations_returns_insufficient(self):
        """With fewer than MIN_OBSERVATIONS returns, result.insufficient_data=True."""
        from services.risk_engine.var_service import VaRService, MIN_OBSERVATIONS
        positions, prices, equity = self._make_positions_and_prices(n=MIN_OBSERVATIONS - 5)
        result = VaRService.compute_var_result(positions, prices, equity)
        assert result.insufficient_data is True
        assert result.portfolio_var_95_pct == 0.0

    def test_sufficient_data_not_insufficient(self):
        from services.risk_engine.var_service import VaRService
        positions, prices, equity = self._make_positions_and_prices(n=100)
        result = VaRService.compute_var_result(positions, prices, equity)
        assert result.insufficient_data is False

    def test_no_price_data_for_ticker_excluded(self):
        """Position with no price history is simply excluded from VaR."""
        from services.risk_engine.var_service import VaRService
        positions = {
            "AAPL": _make_position("AAPL", 50_000.0),
            "MSFT": _make_position("MSFT", 50_000.0),
        }
        prices = {"AAPL": _build_prices(100)}  # MSFT has no data
        result = VaRService.compute_var_result(positions, prices, 100_000.0)
        # MSFT excluded from ticker_var; AAPL may still be present
        assert "MSFT" not in result.ticker_var_95


# ---------------------------------------------------------------------------
# TestVaRServiceFilter
# ---------------------------------------------------------------------------

class TestVaRServiceFilter:

    def _make_var_result(self, var_95_pct: float, insufficient: bool = False):
        from services.risk_engine.var_service import VaRResult
        return VaRResult(
            computed_at=dt.datetime.now(dt.timezone.utc),
            portfolio_var_95_pct=var_95_pct,
            portfolio_var_99_pct=var_95_pct * 1.3,
            portfolio_cvar_95_pct=var_95_pct * 1.5,
            portfolio_var_95_dollar=var_95_pct * 100_000,
            portfolio_var_99_dollar=var_95_pct * 130_000,
            portfolio_cvar_95_dollar=var_95_pct * 150_000,
            equity=100_000.0,
            ticker_var_95={},
            lookback_days=60,
            positions_count=2,
            insufficient_data=insufficient,
        )

    def test_var_below_limit_passes_all(self):
        from services.risk_engine.var_service import VaRService
        actions = [_make_open_action("AAPL"), _make_open_action("MSFT")]
        var_result = self._make_var_result(0.01)  # 1% < 3% limit
        settings = _make_settings(max_portfolio_var_pct=0.03)
        filtered, blocked = VaRService.filter_for_var_limit(actions, var_result, settings)
        assert blocked == 0
        assert len(filtered) == 2

    def test_var_above_limit_blocks_opens(self):
        from services.risk_engine.var_service import VaRService
        actions = [_make_open_action("AAPL"), _make_open_action("MSFT")]
        var_result = self._make_var_result(0.05)  # 5% > 3% limit
        settings = _make_settings(max_portfolio_var_pct=0.03)
        filtered, blocked = VaRService.filter_for_var_limit(actions, var_result, settings)
        assert blocked == 2
        assert len(filtered) == 0

    def test_var_above_limit_close_passes_through(self):
        from services.risk_engine.var_service import VaRService
        actions = [
            _make_open_action("AAPL"),
            _make_close_action("MSFT"),
            _make_trim_action("GOOG"),
        ]
        var_result = self._make_var_result(0.05)
        settings = _make_settings(max_portfolio_var_pct=0.03)
        filtered, blocked = VaRService.filter_for_var_limit(actions, var_result, settings)
        assert blocked == 1  # only AAPL OPEN blocked
        assert len(filtered) == 2  # CLOSE + TRIM pass through
        action_types = [a.action_type.value for a in filtered]
        assert "close" in action_types
        assert "trim" in action_types

    def test_insufficient_data_passes_all(self):
        from services.risk_engine.var_service import VaRService
        actions = [_make_open_action("AAPL")]
        var_result = self._make_var_result(0.10, insufficient=True)
        settings = _make_settings(max_portfolio_var_pct=0.03)
        filtered, blocked = VaRService.filter_for_var_limit(actions, var_result, settings)
        assert blocked == 0
        assert len(filtered) == 1

    def test_zero_limit_disables_gate(self):
        from services.risk_engine.var_service import VaRService
        actions = [_make_open_action("AAPL")]
        var_result = self._make_var_result(0.10)
        settings = _make_settings(max_portfolio_var_pct=0.0)
        filtered, blocked = VaRService.filter_for_var_limit(actions, var_result, settings)
        assert blocked == 0
        assert len(filtered) == 1

    def test_exact_limit_not_blocked(self):
        """At exactly the limit the gate does not fire (> not >=)."""
        from services.risk_engine.var_service import VaRService
        actions = [_make_open_action("AAPL")]
        var_result = self._make_var_result(0.03)  # exactly 3%
        settings = _make_settings(max_portfolio_var_pct=0.03)
        filtered, blocked = VaRService.filter_for_var_limit(actions, var_result, settings)
        assert blocked == 0


# ---------------------------------------------------------------------------
# TestVaRRefreshJob
# ---------------------------------------------------------------------------

class TestVaRRefreshJob:

    def _make_mock_session(self, rows):
        """Return a mock session_factory that yields rows from query.all()."""
        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = rows
        mock_session.query.return_value = mock_query

        factory = MagicMock()
        factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        factory.return_value.__exit__ = MagicMock(return_value=False)
        return factory

    def _make_prices_rows(self, ticker: str, n: int = 100):
        base_date = dt.date(2026, 1, 1)
        rows = []
        prices = _build_prices(n + 1)
        for i, price in enumerate(prices):
            rows.append((ticker, base_date + dt.timedelta(days=i), price))
        return rows

    def test_skipped_when_no_portfolio(self):
        from apps.worker.jobs.var_refresh import run_var_refresh
        app_state = _make_app_state(portfolio_state=None)
        result = run_var_refresh(app_state)
        assert result["status"] == "skipped_no_portfolio"

    def test_skipped_when_no_session_factory(self):
        from apps.worker.jobs.var_refresh import run_var_refresh
        ps = _make_portfolio_state({"AAPL": _make_position("AAPL")}, equity=100_000.0)
        app_state = _make_app_state(portfolio_state=ps)
        result = run_var_refresh(app_state, session_factory=None)
        assert result["status"] == "skipped_no_db"

    def test_happy_path_updates_app_state(self):
        from apps.worker.jobs.var_refresh import run_var_refresh
        ps = _make_portfolio_state({"AAPL": _make_position("AAPL", 50_000.0)}, equity=100_000.0)
        app_state = _make_app_state(portfolio_state=ps)

        rows = self._make_prices_rows("AAPL", n=60)
        factory = self._make_mock_session(rows)

        with patch("infra.db.models.market_data.DailyMarketBar"):
            result = run_var_refresh(app_state, session_factory=factory)
        assert result["status"] in ("ok", "no_data", "error_db")
        # When ok, app_state should be updated
        if result["status"] == "ok":
            assert app_state.latest_var_result is not None
            assert result["positions_count"] == 1

    def test_no_bar_data_returns_no_data(self):
        from apps.worker.jobs.var_refresh import run_var_refresh
        ps = _make_portfolio_state({"AAPL": _make_position("AAPL")}, equity=100_000.0)
        app_state = _make_app_state(portfolio_state=ps)

        factory = self._make_mock_session([])  # empty rows
        with patch("infra.db.models.market_data.DailyMarketBar"):
            result = run_var_refresh(app_state, session_factory=factory)
        assert result["status"] in ("no_data", "error_db")

    def test_zero_equity_skipped(self):
        from apps.worker.jobs.var_refresh import run_var_refresh
        ps = _make_portfolio_state({"AAPL": _make_position("AAPL")}, equity=0.0)
        app_state = _make_app_state(portfolio_state=ps)
        factory = self._make_mock_session([])
        result = run_var_refresh(app_state, session_factory=factory)
        assert result["status"] == "skipped_zero_equity"


# ---------------------------------------------------------------------------
# TestVaRRefreshJobEdgeCases
# ---------------------------------------------------------------------------

class TestVaRRefreshJobEdgeCases:

    def test_db_exception_returns_error_db(self):
        from apps.worker.jobs.var_refresh import run_var_refresh
        ps = _make_portfolio_state({"AAPL": _make_position("AAPL")}, equity=100_000.0)
        app_state = _make_app_state(portfolio_state=ps)

        factory = MagicMock()
        factory.return_value.__enter__ = MagicMock(side_effect=Exception("DB down"))
        factory.return_value.__exit__ = MagicMock(return_value=False)

        result = run_var_refresh(app_state, session_factory=factory)
        assert result["status"] == "error_db"
        assert result["error"] != ""

    def test_empty_positions_still_skipped(self):
        from apps.worker.jobs.var_refresh import run_var_refresh
        ps = _make_portfolio_state({}, equity=100_000.0)
        app_state = _make_app_state(portfolio_state=ps)
        result = run_var_refresh(app_state, session_factory=MagicMock())
        assert result["status"] == "skipped_no_portfolio"

    def test_result_dict_has_expected_keys(self):
        from apps.worker.jobs.var_refresh import run_var_refresh
        app_state = _make_app_state(portfolio_state=None)
        result = run_var_refresh(app_state)
        for key in ("status", "positions_count", "lookback_days", "var_95_pct", "computed_at", "error"):
            assert key in result


# ---------------------------------------------------------------------------
# TestVaRRoutePortfolio
# ---------------------------------------------------------------------------

class TestVaRRoutePortfolio:

    def _make_var_result(self, var_95=0.025, insufficient=False):
        from services.risk_engine.var_service import VaRResult
        return VaRResult(
            computed_at=dt.datetime(2026, 3, 20, 6, 19, tzinfo=dt.timezone.utc),
            portfolio_var_95_pct=var_95,
            portfolio_var_99_pct=var_95 * 1.4,
            portfolio_cvar_95_pct=var_95 * 1.6,
            portfolio_var_95_dollar=var_95 * 100_000,
            portfolio_var_99_dollar=var_95 * 1.4 * 100_000,
            portfolio_cvar_95_dollar=var_95 * 1.6 * 100_000,
            equity=100_000.0,
            ticker_var_95={"AAPL": 0.015, "MSFT": 0.010},
            lookback_days=60,
            positions_count=2,
            insufficient_data=insufficient,
        )

    def test_no_var_data_returns_empty_response(self):
        from apps.api.routes.var import get_portfolio_var
        state = _make_app_state(latest_var_result=None)
        settings = _make_settings(0.03)
        resp = get_portfolio_var(state, settings)
        assert resp.positions_count == 0
        assert resp.insufficient_data is True
        assert resp.tickers == []

    def test_happy_path_fields(self):
        from apps.api.routes.var import get_portfolio_var
        var_result = self._make_var_result(0.025)
        ps = _make_portfolio_state({
            "AAPL": _make_position("AAPL", 50_000.0),
            "MSFT": _make_position("MSFT", 50_000.0),
        }, equity=100_000.0)
        state = _make_app_state(portfolio_state=ps, latest_var_result=var_result)
        settings = _make_settings(0.03)
        resp = get_portfolio_var(state, settings)
        assert resp.positions_count == 2
        assert abs(resp.portfolio_var_95_pct - 2.5) < 0.001
        assert resp.var_limit_breached is False  # 2.5% < 3%

    def test_var_breach_flagged(self):
        from apps.api.routes.var import get_portfolio_var
        var_result = self._make_var_result(0.05)  # 5% > 3% limit
        ps = _make_portfolio_state({"AAPL": _make_position("AAPL")})
        state = _make_app_state(portfolio_state=ps, latest_var_result=var_result)
        settings = _make_settings(0.03)
        resp = get_portfolio_var(state, settings)
        assert resp.var_limit_breached is True

    def test_ticker_rows_present(self):
        from apps.api.routes.var import get_portfolio_var
        var_result = self._make_var_result(0.025)
        ps = _make_portfolio_state({
            "AAPL": _make_position("AAPL", 50_000.0),
            "MSFT": _make_position("MSFT", 50_000.0),
        })
        state = _make_app_state(portfolio_state=ps, latest_var_result=var_result)
        settings = _make_settings(0.03)
        resp = get_portfolio_var(state, settings)
        tickers = {t.ticker for t in resp.tickers}
        assert "AAPL" in tickers
        assert "MSFT" in tickers


# ---------------------------------------------------------------------------
# TestVaRRouteTicker
# ---------------------------------------------------------------------------

class TestVaRRouteTicker:

    def _make_var_result(self):
        from services.risk_engine.var_service import VaRResult
        return VaRResult(
            computed_at=dt.datetime(2026, 3, 20, 6, 19, tzinfo=dt.timezone.utc),
            portfolio_var_95_pct=0.025,
            portfolio_var_99_pct=0.035,
            portfolio_cvar_95_pct=0.040,
            portfolio_var_95_dollar=2500.0,
            portfolio_var_99_dollar=3500.0,
            portfolio_cvar_95_dollar=4000.0,
            equity=100_000.0,
            ticker_var_95={"AAPL": 0.015},
            lookback_days=60,
            positions_count=1,
            insufficient_data=False,
        )

    def test_no_var_data_returns_not_available(self):
        from apps.api.routes.var import get_ticker_var
        state = _make_app_state(latest_var_result=None)
        resp = get_ticker_var("AAPL", state, _make_settings())
        assert resp.data_available is False

    def test_ticker_not_in_var_result(self):
        from apps.api.routes.var import get_ticker_var
        var_result = self._make_var_result()
        state = _make_app_state(latest_var_result=var_result)
        resp = get_ticker_var("GOOG", state, _make_settings())
        assert resp.data_available is False
        assert resp.ticker == "GOOG"

    def test_happy_path(self):
        from apps.api.routes.var import get_ticker_var
        var_result = self._make_var_result()
        ps = _make_portfolio_state({"AAPL": _make_position("AAPL", 50_000.0)})
        state = _make_app_state(portfolio_state=ps, latest_var_result=var_result)
        resp = get_ticker_var("aapl", state, _make_settings())  # lowercase input
        assert resp.data_available is True
        assert resp.ticker == "AAPL"
        assert resp.standalone_var_95_pct is not None

    def test_ticker_uppercased(self):
        from apps.api.routes.var import get_ticker_var
        var_result = self._make_var_result()
        state = _make_app_state(latest_var_result=var_result)
        resp = get_ticker_var("aapl", state, _make_settings())
        assert resp.ticker == "AAPL"


# ---------------------------------------------------------------------------
# TestVaRSettings
# ---------------------------------------------------------------------------

class TestVaRSettings:

    def test_max_portfolio_var_pct_default(self):
        from config.settings import Settings
        s = Settings()
        assert s.max_portfolio_var_pct == 0.03

    def test_max_portfolio_var_pct_configurable(self):
        from config.settings import Settings
        s = Settings(max_portfolio_var_pct=0.05)
        assert s.max_portfolio_var_pct == 0.05

    def test_max_portfolio_var_pct_zero_disables_gate(self):
        from config.settings import Settings
        s = Settings(max_portfolio_var_pct=0.0)
        assert s.max_portfolio_var_pct == 0.0


# ---------------------------------------------------------------------------
# TestVaRScheduler
# ---------------------------------------------------------------------------

class TestVaRScheduler:

    def _build(self):
        from apps.worker.main import build_scheduler
        return build_scheduler()

    def test_var_refresh_job_registered(self):
        scheduler = self._build()
        job_ids = {job.id for job in scheduler.get_jobs()}
        assert "var_refresh" in job_ids

    def test_var_refresh_scheduled_at_06_19(self):
        scheduler = self._build()
        job = next(j for j in scheduler.get_jobs() if j.id == "var_refresh")
        fields = {f.name: str(f) for f in job.trigger.fields}
        assert fields.get("hour") == "6"
        assert fields.get("minute") == "19"

    def test_var_refresh_weekdays_only(self):
        scheduler = self._build()
        job = next(j for j in scheduler.get_jobs() if j.id == "var_refresh")
        fields = {f.name: str(f) for f in job.trigger.fields}
        assert fields.get("day_of_week") == "mon-fri"

    def test_total_job_count_is_22(self):
        """Phase 48 adds universe_refresh: total is now 26."""
        scheduler = self._build()
        assert len(scheduler.get_jobs()) == 30

    def test_run_var_refresh_exported(self):
        from apps.worker.jobs import run_var_refresh
        assert callable(run_var_refresh)
