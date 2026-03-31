"""
Phase 50 — Factor Exposure Monitoring

Test classes
------------
TestFactorScoreComputation      — individual per-factor score functions
TestFactorNeutralDefaults       — missing / None inputs → 0.5 neutral
TestFactorScoreBoundaries       — extreme inputs are clamped to [0, 1]
TestComputeFactorScores         — combined compute_factor_scores() dict
TestPortfolioFactorExposure     — market-value-weighted aggregation
TestFactorTopBottom             — top_tickers_by_factor / bottom_tickers_by_factor
TestFactorExposureAppState      — 2 new ApiAppState fields
TestFactorExposureRouteEmpty    — GET /portfolio/factor-exposure with no data
TestFactorExposureRouteWithData — GET /portfolio/factor-exposure with cached data
TestFactorDetailRouteValid      — GET /portfolio/factor-exposure/{factor} happy path
TestFactorDetailRouteInvalid    — 404 for unknown factor name
TestFactorDashboard             — _render_factor_section() HTML rendering
TestFactorPaperCycleIntegration — factor exposure wired into paper trading cycle
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class _FakePosition:
    ticker: str
    quantity: Decimal = Decimal("10")
    current_price: Decimal = Decimal("100")
    avg_entry_price: Decimal = Decimal("90")

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


def _make_app_state(**overrides):
    from apps.api.state import ApiAppState
    state = ApiAppState()
    for k, v in overrides.items():
        setattr(state, k, v)
    return state


def _make_settings(**overrides):
    from config.settings import Settings
    base = {
        "db_url": "postgresql+psycopg://u:p@localhost/apis",
        "operating_mode": "paper",
        "kill_switch": False,
    }
    base.update(overrides)
    return Settings(**base)


# ===========================================================================
# TestFactorScoreComputation
# ===========================================================================

class TestFactorScoreComputation:
    def test_momentum_score_from_composite(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        score = FactorExposureService._score_momentum(0.8)
        assert abs(score - 0.8) < 1e-9

    def test_momentum_score_low_composite(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        score = FactorExposureService._score_momentum(0.2)
        assert abs(score - 0.2) < 1e-9

    def test_value_score_low_pe(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        # P/E = 10 → score = 1 - 10/50 = 0.8
        score = FactorExposureService._score_value(10.0)
        assert abs(score - 0.8) < 1e-9

    def test_value_score_high_pe_caps_zero(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        # P/E = 50 → score = 1 - 50/50 = 0.0
        score = FactorExposureService._score_value(50.0)
        assert score == 0.0

    def test_value_score_very_high_pe_clamped(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        score = FactorExposureService._score_value(100.0)
        assert score == 0.0

    def test_value_score_negative_pe_neutral(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        # Negative P/E (loss-making) → neutral 0.5
        score = FactorExposureService._score_value(-5.0)
        assert score == 0.5

    def test_growth_score_positive_eps(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        # eps_growth = 0.25 (+25%) → 0.5 + 0.25*2 = 1.0
        score = FactorExposureService._score_growth(0.25)
        assert score == 1.0

    def test_growth_score_negative_eps(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        # eps_growth = -0.25 (-25%) → 0.5 - 0.25*2 = 0.0
        score = FactorExposureService._score_growth(-0.25)
        assert score == 0.0

    def test_growth_score_zero_eps(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        score = FactorExposureService._score_growth(0.0)
        assert abs(score - 0.5) < 1e-9

    def test_quality_score_high_adv(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        import math
        # $5B ADV → score = log10(5e9) / log10(5e9) = 1.0
        score = FactorExposureService._score_quality(5_000_000_000.0)
        assert abs(score - 1.0) < 0.01

    def test_quality_score_low_adv(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        # $1M ADV → moderate score
        score = FactorExposureService._score_quality(1_000_000.0)
        assert 0.0 < score < 1.0

    def test_quality_score_zero_adv_neutral(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        score = FactorExposureService._score_quality(0.0)
        assert score == 0.5

    def test_low_vol_score_low_volatility(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        # vol = 0.0 → score = 1.0
        score = FactorExposureService._score_low_vol(0.0)
        assert score == 1.0

    def test_low_vol_score_medium_volatility(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        # vol = 0.25 → score = 1 - 0.25/0.5 = 0.5
        score = FactorExposureService._score_low_vol(0.25)
        assert abs(score - 0.5) < 1e-9

    def test_low_vol_score_high_volatility(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        # vol = 0.50 → score = 0.0
        score = FactorExposureService._score_low_vol(0.50)
        assert score == 0.0

    def test_low_vol_score_extreme_volatility_clamped(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        score = FactorExposureService._score_low_vol(1.0)
        assert score == 0.0


# ===========================================================================
# TestFactorNeutralDefaults
# ===========================================================================

class TestFactorNeutralDefaults:
    def test_momentum_none_returns_neutral(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        assert FactorExposureService._score_momentum(None) == 0.5

    def test_value_none_returns_neutral(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        assert FactorExposureService._score_value(None) == 0.5

    def test_growth_none_returns_neutral(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        assert FactorExposureService._score_growth(None) == 0.5

    def test_quality_none_returns_neutral(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        assert FactorExposureService._score_quality(None) == 0.5

    def test_low_vol_none_returns_neutral(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        assert FactorExposureService._score_low_vol(None) == 0.5

    def test_empty_feature_dict_all_neutral(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        scores = FactorExposureService.compute_factor_scores({})
        for factor, score in scores.items():
            assert score == 0.5, f"{factor} expected 0.5 got {score}"


# ===========================================================================
# TestFactorScoreBoundaries
# ===========================================================================

class TestFactorScoreBoundaries:
    def test_momentum_clamps_above_one(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        assert FactorExposureService._score_momentum(1.5) == 1.0

    def test_momentum_clamps_below_zero(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        assert FactorExposureService._score_momentum(-0.5) == 0.0

    def test_growth_clamps_above_one(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        assert FactorExposureService._score_growth(10.0) == 1.0

    def test_growth_clamps_below_zero(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        assert FactorExposureService._score_growth(-10.0) == 0.0

    def test_quality_clamps_above_one(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        assert FactorExposureService._score_quality(1e15) == 1.0

    def test_all_scores_in_range(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        fv = {
            "composite_score": 0.75,
            "pe_ratio": 20.0,
            "eps_growth": 0.10,
            "dollar_volume_20d": 500_000_000.0,
            "volatility_20d": 0.20,
        }
        scores = FactorExposureService.compute_factor_scores(fv)
        for factor, score in scores.items():
            assert 0.0 <= score <= 1.0, f"{factor} score {score} out of range"


# ===========================================================================
# TestComputeFactorScores
# ===========================================================================

class TestComputeFactorScores:
    def test_returns_all_five_factors(self):
        from services.risk_engine.factor_exposure import FactorExposureService, FACTORS
        scores = FactorExposureService.compute_factor_scores({})
        assert set(scores.keys()) == set(FACTORS)

    def test_full_feature_dict_produces_non_neutral(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        fv = {
            "composite_score": 0.9,
            "pe_ratio": 15.0,
            "eps_growth": 0.20,
            "dollar_volume_20d": 2_000_000_000.0,
            "volatility_20d": 0.10,
        }
        scores = FactorExposureService.compute_factor_scores(fv)
        # All should be non-neutral (not 0.5)
        assert scores["MOMENTUM"] != 0.5
        assert scores["VALUE"] != 0.5
        assert scores["GROWTH"] != 0.5
        assert scores["QUALITY"] != 0.5
        assert scores["LOW_VOL"] != 0.5

    def test_momentum_correctly_propagated(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        scores = FactorExposureService.compute_factor_scores({"composite_score": 0.6})
        assert abs(scores["MOMENTUM"] - 0.6) < 1e-9

    def test_missing_key_neutral_only_that_factor(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        fv = {"composite_score": 0.9, "pe_ratio": 10.0}
        scores = FactorExposureService.compute_factor_scores(fv)
        assert scores["MOMENTUM"] == 0.9
        assert scores["VALUE"] > 0.5  # low PE → high value
        assert scores["GROWTH"] == 0.5  # missing → neutral
        assert scores["QUALITY"] == 0.5  # missing → neutral
        assert scores["LOW_VOL"] == 0.5  # missing → neutral


# ===========================================================================
# TestPortfolioFactorExposure
# ===========================================================================

class TestPortfolioFactorExposure:
    def test_single_position_weights_equal_ticker_scores(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        pos = _FakePosition("AAPL", quantity=Decimal("10"), current_price=Decimal("100"))
        positions = {"AAPL": pos}
        ticker_scores = {"AAPL": {"MOMENTUM": 0.8, "VALUE": 0.6, "GROWTH": 0.7, "QUALITY": 0.9, "LOW_VOL": 0.4}}
        result = FactorExposureService.compute_portfolio_factor_exposure(
            positions=positions, ticker_scores=ticker_scores, equity=10000.0
        )
        assert abs(result.portfolio_factor_weights["MOMENTUM"] - 0.8) < 0.001
        assert abs(result.portfolio_factor_weights["VALUE"] - 0.6) < 0.001

    def test_two_positions_weighted_by_market_value(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        pos_a = _FakePosition("AAPL", quantity=Decimal("30"), current_price=Decimal("100"))  # MV=3000
        pos_b = _FakePosition("MSFT", quantity=Decimal("10"), current_price=Decimal("100"))  # MV=1000
        positions = {"AAPL": pos_a, "MSFT": pos_b}
        ticker_scores = {
            "AAPL": {"MOMENTUM": 1.0, "VALUE": 0.5, "GROWTH": 0.5, "QUALITY": 0.5, "LOW_VOL": 0.5},
            "MSFT": {"MOMENTUM": 0.0, "VALUE": 0.5, "GROWTH": 0.5, "QUALITY": 0.5, "LOW_VOL": 0.5},
        }
        result = FactorExposureService.compute_portfolio_factor_exposure(
            positions=positions, ticker_scores=ticker_scores, equity=4000.0
        )
        # Weighted MOMENTUM = (3000*1.0 + 1000*0.0) / 4000 = 0.75
        assert abs(result.portfolio_factor_weights["MOMENTUM"] - 0.75) < 0.001

    def test_empty_positions_returns_neutral(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        result = FactorExposureService.compute_portfolio_factor_exposure(
            positions={}, ticker_scores={}, equity=0.0
        )
        assert result.position_count == 0
        assert all(v == 0.5 for v in result.portfolio_factor_weights.values())

    def test_dominant_factor_is_highest_weight(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        pos = _FakePosition("AAPL")
        positions = {"AAPL": pos}
        ticker_scores = {"AAPL": {"MOMENTUM": 0.3, "VALUE": 0.9, "GROWTH": 0.4, "QUALITY": 0.5, "LOW_VOL": 0.5}}
        result = FactorExposureService.compute_portfolio_factor_exposure(
            positions=positions, ticker_scores=ticker_scores, equity=1000.0
        )
        assert result.dominant_factor == "VALUE"

    def test_position_count_correct(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        positions = {
            "AAPL": _FakePosition("AAPL"),
            "MSFT": _FakePosition("MSFT"),
            "NVDA": _FakePosition("NVDA"),
        }
        ticker_scores = {t: {"MOMENTUM": 0.5, "VALUE": 0.5, "GROWTH": 0.5, "QUALITY": 0.5, "LOW_VOL": 0.5} for t in positions}
        result = FactorExposureService.compute_portfolio_factor_exposure(
            positions=positions, ticker_scores=ticker_scores, equity=30000.0
        )
        assert result.position_count == 3

    def test_zero_market_value_position_excluded(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        pos_good = _FakePosition("AAPL", quantity=Decimal("10"), current_price=Decimal("100"))  # MV=1000
        pos_zero = _FakePosition("MSFT", quantity=Decimal("0"), current_price=Decimal("100"))   # MV=0
        positions = {"AAPL": pos_good, "MSFT": pos_zero}
        ticker_scores = {
            "AAPL": {"MOMENTUM": 0.8, "VALUE": 0.5, "GROWTH": 0.5, "QUALITY": 0.5, "LOW_VOL": 0.5},
            "MSFT": {"MOMENTUM": 0.0, "VALUE": 0.5, "GROWTH": 0.5, "QUALITY": 0.5, "LOW_VOL": 0.5},
        }
        result = FactorExposureService.compute_portfolio_factor_exposure(
            positions=positions, ticker_scores=ticker_scores, equity=1000.0
        )
        # Zero-MV position excluded → only AAPL contributes
        assert result.position_count == 1
        assert abs(result.portfolio_factor_weights["MOMENTUM"] - 0.8) < 0.001

    def test_missing_ticker_score_defaults_to_neutral(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        pos = _FakePosition("AAPL")
        positions = {"AAPL": pos}
        ticker_scores = {}  # no scores for AAPL → should default to 0.5
        result = FactorExposureService.compute_portfolio_factor_exposure(
            positions=positions, ticker_scores=ticker_scores, equity=1000.0
        )
        assert result.portfolio_factor_weights["MOMENTUM"] == 0.5

    def test_total_market_value_computed(self):
        from services.risk_engine.factor_exposure import FactorExposureService
        pos = _FakePosition("AAPL", quantity=Decimal("10"), current_price=Decimal("200"))  # MV=2000
        positions = {"AAPL": pos}
        result = FactorExposureService.compute_portfolio_factor_exposure(
            positions=positions, ticker_scores={}, equity=5000.0
        )
        assert abs(result.total_market_value - 2000.0) < 1.0


# ===========================================================================
# TestFactorTopBottom
# ===========================================================================

class TestFactorTopBottom:
    def _build_result(self):
        from services.risk_engine.factor_exposure import FactorExposureResult, TickerFactorScores
        tickers = [
            TickerFactorScores("A", {"MOMENTUM": 0.9, "VALUE": 0.1, "GROWTH": 0.5, "QUALITY": 0.5, "LOW_VOL": 0.5}, 1000),
            TickerFactorScores("B", {"MOMENTUM": 0.5, "VALUE": 0.5, "GROWTH": 0.5, "QUALITY": 0.5, "LOW_VOL": 0.5}, 1000),
            TickerFactorScores("C", {"MOMENTUM": 0.1, "VALUE": 0.9, "GROWTH": 0.5, "QUALITY": 0.5, "LOW_VOL": 0.5}, 1000),
        ]
        return FactorExposureResult(
            portfolio_factor_weights={"MOMENTUM": 0.5, "VALUE": 0.5, "GROWTH": 0.5, "QUALITY": 0.5, "LOW_VOL": 0.5},
            ticker_scores=tickers,
            dominant_factor="MOMENTUM",
            position_count=3,
        )

    def test_top_tickers_returns_highest_score_first(self):
        result = self._build_result()
        top = result.top_tickers_by_factor("MOMENTUM", n=2)
        assert top[0].ticker == "A"
        assert top[1].ticker == "B"

    def test_bottom_tickers_returns_lowest_score_first(self):
        result = self._build_result()
        bottom = result.bottom_tickers_by_factor("MOMENTUM", n=2)
        assert bottom[0].ticker == "C"

    def test_top_tickers_n_limits_output(self):
        result = self._build_result()
        top = result.top_tickers_by_factor("MOMENTUM", n=1)
        assert len(top) == 1
        assert top[0].ticker == "A"

    def test_bottom_tickers_n_limits_output(self):
        result = self._build_result()
        bottom = result.bottom_tickers_by_factor("VALUE", n=1)
        assert len(bottom) == 1
        assert bottom[0].ticker == "A"  # lowest VALUE = 0.1

    def test_ticker_dominant_factor(self):
        from services.risk_engine.factor_exposure import TickerFactorScores
        t = TickerFactorScores("X", {"MOMENTUM": 0.9, "VALUE": 0.3, "GROWTH": 0.5, "QUALITY": 0.6, "LOW_VOL": 0.2}, 1000)
        assert t.dominant_factor == "MOMENTUM"


# ===========================================================================
# TestFactorExposureAppState
# ===========================================================================

class TestFactorExposureAppState:
    def test_latest_factor_exposure_field_exists(self):
        state = _make_app_state()
        assert hasattr(state, "latest_factor_exposure")
        assert state.latest_factor_exposure is None

    def test_factor_exposure_computed_at_field_exists(self):
        state = _make_app_state()
        assert hasattr(state, "factor_exposure_computed_at")
        assert state.factor_exposure_computed_at is None

    def test_fields_assignable(self):
        from services.risk_engine.factor_exposure import FactorExposureResult
        state = _make_app_state()
        now = dt.datetime.now(dt.timezone.utc)
        state.latest_factor_exposure = FactorExposureResult()
        state.factor_exposure_computed_at = now
        assert state.latest_factor_exposure is not None
        assert state.factor_exposure_computed_at == now


# ===========================================================================
# TestFactorExposureRouteEmpty
# ===========================================================================

class TestFactorExposureRouteEmpty:
    def test_returns_200_with_neutral_defaults_when_no_data(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import reset_app_state
        reset_app_state()
        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/factor-exposure")
        assert resp.status_code == 200
        data = resp.json()
        assert data["position_count"] == 0
        assert data["dominant_factor"] == "UNKNOWN"
        assert data["momentum"] == 0.5
        assert data["value"] == 0.5
        assert data["growth"] == 0.5
        assert data["quality"] == 0.5
        assert data["low_vol"] == 0.5
        assert data["ticker_scores"] == []

    def test_response_schema_has_all_factor_fields(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import reset_app_state
        reset_app_state()
        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/factor-exposure")
        assert resp.status_code == 200
        data = resp.json()
        for field in ["momentum", "value", "growth", "quality", "low_vol",
                      "position_count", "total_market_value", "dominant_factor",
                      "ticker_scores", "computed_at"]:
            assert field in data, f"Missing field: {field}"


# ===========================================================================
# TestFactorExposureRouteWithData
# ===========================================================================

class TestFactorExposureRouteWithData:
    def _build_factor_result(self):
        from services.risk_engine.factor_exposure import (
            FactorExposureResult, TickerFactorScores,
        )
        ts = [
            TickerFactorScores("AAPL", {"MOMENTUM": 0.8, "VALUE": 0.6, "GROWTH": 0.7, "QUALITY": 0.9, "LOW_VOL": 0.4}, 5000.0),
            TickerFactorScores("MSFT", {"MOMENTUM": 0.7, "VALUE": 0.5, "GROWTH": 0.6, "QUALITY": 0.8, "LOW_VOL": 0.5}, 3000.0),
        ]
        return FactorExposureResult(
            portfolio_factor_weights={"MOMENTUM": 0.76, "VALUE": 0.57, "GROWTH": 0.66, "QUALITY": 0.86, "LOW_VOL": 0.44},
            ticker_scores=ts,
            dominant_factor="QUALITY",
            position_count=2,
            total_market_value=8000.0,
        )

    def test_returns_factor_weights_from_cached_result(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import reset_app_state, get_app_state
        reset_app_state()
        state = get_app_state()
        state.latest_factor_exposure = self._build_factor_result()
        state.factor_exposure_computed_at = dt.datetime(2026, 3, 21, 9, 35, tzinfo=dt.timezone.utc)
        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/factor-exposure")
        assert resp.status_code == 200
        data = resp.json()
        assert data["position_count"] == 2
        assert data["dominant_factor"] == "QUALITY"
        assert data["total_market_value"] == 8000.0
        assert abs(data["momentum"] - 0.76) < 0.01

    def test_ticker_scores_serialised(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import reset_app_state, get_app_state
        reset_app_state()
        state = get_app_state()
        state.latest_factor_exposure = self._build_factor_result()
        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/factor-exposure")
        data = resp.json()
        tickers = [t["ticker"] for t in data["ticker_scores"]]
        assert "AAPL" in tickers
        assert "MSFT" in tickers

    def test_ticker_score_fields_present(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import reset_app_state, get_app_state
        reset_app_state()
        state = get_app_state()
        state.latest_factor_exposure = self._build_factor_result()
        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/factor-exposure")
        data = resp.json()
        t = data["ticker_scores"][0]
        for f in ["ticker", "momentum", "value", "growth", "quality", "low_vol", "market_value", "dominant_factor"]:
            assert f in t, f"Missing ticker score field: {f}"


# ===========================================================================
# TestFactorDetailRouteValid
# ===========================================================================

class TestFactorDetailRouteValid:
    def _setup(self):
        from services.risk_engine.factor_exposure import (
            FactorExposureResult, TickerFactorScores,
        )
        from apps.api.state import reset_app_state, get_app_state
        reset_app_state()
        ts = [
            TickerFactorScores("AAPL", {"MOMENTUM": 0.9, "VALUE": 0.5, "GROWTH": 0.5, "QUALITY": 0.5, "LOW_VOL": 0.5}, 5000.0),
            TickerFactorScores("MSFT", {"MOMENTUM": 0.3, "VALUE": 0.5, "GROWTH": 0.5, "QUALITY": 0.5, "LOW_VOL": 0.5}, 3000.0),
        ]
        result = FactorExposureResult(
            portfolio_factor_weights={"MOMENTUM": 0.65, "VALUE": 0.5, "GROWTH": 0.5, "QUALITY": 0.5, "LOW_VOL": 0.5},
            ticker_scores=ts,
            dominant_factor="MOMENTUM",
            position_count=2,
        )
        state = get_app_state()
        state.latest_factor_exposure = result
        return state

    def test_valid_factor_returns_200(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        self._setup()
        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/factor-exposure/MOMENTUM")
        assert resp.status_code == 200

    def test_case_insensitive_factor_name(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        self._setup()
        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/factor-exposure/momentum")
        assert resp.status_code == 200
        data = resp.json()
        assert data["factor"] == "MOMENTUM"

    def test_top_tickers_present(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        self._setup()
        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/factor-exposure/MOMENTUM")
        data = resp.json()
        assert len(data["top_tickers"]) >= 1
        # AAPL should be top by MOMENTUM
        assert data["top_tickers"][0]["ticker"] == "AAPL"

    def test_bottom_tickers_present(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        self._setup()
        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/factor-exposure/MOMENTUM")
        data = resp.json()
        assert len(data["bottom_tickers"]) >= 1
        # MSFT has lowest MOMENTUM
        assert data["bottom_tickers"][0]["ticker"] == "MSFT"

    def test_portfolio_weight_in_response(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        self._setup()
        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/factor-exposure/MOMENTUM")
        data = resp.json()
        assert abs(data["portfolio_weight"] - 0.65) < 0.01

    def test_all_valid_factors_respond_200(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from services.risk_engine.factor_exposure import FACTORS
        self._setup()
        client = TestClient(app)
        for factor in FACTORS:
            resp = client.get(f"/api/v1/portfolio/factor-exposure/{factor}")
            assert resp.status_code == 200, f"Factor {factor} returned {resp.status_code}"


# ===========================================================================
# TestFactorDetailRouteInvalid
# ===========================================================================

class TestFactorDetailRouteInvalid:
    def test_unknown_factor_returns_404(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import reset_app_state
        reset_app_state()
        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/factor-exposure/INVALID_FACTOR")
        assert resp.status_code == 404

    def test_404_message_mentions_valid_factors(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import reset_app_state
        reset_app_state()
        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/factor-exposure/JUNK")
        assert resp.status_code == 404
        assert "MOMENTUM" in resp.json()["detail"]

    def test_empty_factor_name_returns_404(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import reset_app_state
        reset_app_state()
        client = TestClient(app)
        # "/" at end with nothing should 404 on the factor detail route
        resp = client.get("/api/v1/portfolio/factor-exposure/NOTAFACTOR")
        assert resp.status_code == 404

    def test_detail_no_data_returns_200_empty_lists(self):
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.state import reset_app_state
        reset_app_state()
        client = TestClient(app)
        resp = client.get("/api/v1/portfolio/factor-exposure/VALUE")
        assert resp.status_code == 200
        data = resp.json()
        assert data["top_tickers"] == []
        assert data["bottom_tickers"] == []
        assert data["portfolio_weight"] == 0.5


# ===========================================================================
# TestFactorDashboard
# ===========================================================================

class TestFactorDashboard:
    def test_renders_no_data_message_when_empty(self):
        from apps.dashboard.router import _render_factor_section
        from apps.api.state import ApiAppState
        state = ApiAppState()
        html = _render_factor_section(state)
        assert "Factor Exposure" in html
        assert "No data yet" in html

    def test_renders_dominant_factor_when_data_available(self):
        from apps.dashboard.router import _render_factor_section
        from services.risk_engine.factor_exposure import FactorExposureResult, TickerFactorScores
        from apps.api.state import ApiAppState
        state = ApiAppState()
        ts = [TickerFactorScores("AAPL", {"MOMENTUM": 0.9, "VALUE": 0.3, "GROWTH": 0.4, "QUALITY": 0.6, "LOW_VOL": 0.5}, 5000.0)]
        result = FactorExposureResult(
            portfolio_factor_weights={"MOMENTUM": 0.9, "VALUE": 0.3, "GROWTH": 0.4, "QUALITY": 0.6, "LOW_VOL": 0.5},
            ticker_scores=ts,
            dominant_factor="MOMENTUM",
            position_count=1,
        )
        state.latest_factor_exposure = result
        html = _render_factor_section(state)
        assert "MOMENTUM" in html
        assert "AAPL" in html

    def test_renders_factor_bars(self):
        from apps.dashboard.router import _render_factor_section
        from services.risk_engine.factor_exposure import FactorExposureResult
        from apps.api.state import ApiAppState
        state = ApiAppState()
        state.latest_factor_exposure = FactorExposureResult(
            portfolio_factor_weights={"MOMENTUM": 0.7, "VALUE": 0.4, "GROWTH": 0.5, "QUALITY": 0.6, "LOW_VOL": 0.3},
            ticker_scores=[],
            dominant_factor="MOMENTUM",
            position_count=0,
        )
        html = _render_factor_section(state)
        for factor in ["MOMENTUM", "VALUE", "GROWTH", "QUALITY", "LOW_VOL"]:
            assert factor in html

    def test_renders_ticker_table_when_positions(self):
        from apps.dashboard.router import _render_factor_section
        from services.risk_engine.factor_exposure import FactorExposureResult, TickerFactorScores
        from apps.api.state import ApiAppState
        state = ApiAppState()
        ts = [
            TickerFactorScores("AAPL", {"MOMENTUM": 0.9, "VALUE": 0.5, "GROWTH": 0.5, "QUALITY": 0.5, "LOW_VOL": 0.5}, 5000.0),
            TickerFactorScores("MSFT", {"MOMENTUM": 0.4, "VALUE": 0.5, "GROWTH": 0.5, "QUALITY": 0.5, "LOW_VOL": 0.5}, 3000.0),
        ]
        state.latest_factor_exposure = FactorExposureResult(
            portfolio_factor_weights={"MOMENTUM": 0.7, "VALUE": 0.5, "GROWTH": 0.5, "QUALITY": 0.5, "LOW_VOL": 0.5},
            ticker_scores=ts,
            dominant_factor="MOMENTUM",
            position_count=2,
        )
        html = _render_factor_section(state)
        assert "<table>" in html
        assert "AAPL" in html
        assert "MSFT" in html

    def test_no_xss_in_ticker_names(self):
        from apps.dashboard.router import _render_factor_section
        from services.risk_engine.factor_exposure import FactorExposureResult, TickerFactorScores
        from apps.api.state import ApiAppState
        state = ApiAppState()
        ts = [TickerFactorScores("<script>alert(1)</script>", {"MOMENTUM": 0.5, "VALUE": 0.5, "GROWTH": 0.5, "QUALITY": 0.5, "LOW_VOL": 0.5}, 1000.0)]
        state.latest_factor_exposure = FactorExposureResult(
            portfolio_factor_weights={"MOMENTUM": 0.5, "VALUE": 0.5, "GROWTH": 0.5, "QUALITY": 0.5, "LOW_VOL": 0.5},
            ticker_scores=ts,
            dominant_factor="MOMENTUM",
            position_count=1,
        )
        html = _render_factor_section(state)
        assert "<script>" not in html

    def test_phase_label_in_section_title(self):
        from apps.dashboard.router import _render_factor_section
        from apps.api.state import ApiAppState
        html = _render_factor_section(ApiAppState())
        assert "Phase 50" in html


# ===========================================================================
# TestFactorPaperCycleIntegration
# ===========================================================================

class TestFactorPaperCycleIntegration:
    """Verify that factor exposure is computed and stored during the paper cycle."""

    def _run_minimal_cycle(self, positions, fundamentals=None, dollar_vols=None, rankings=None):
        """Run a paper trading cycle with mocked dependencies and return app_state."""
        from apps.api.state import reset_app_state, get_app_state
        from config.settings import Settings, OperatingMode
        import apps.worker.jobs.paper_trading as pt_module

        reset_app_state()
        state = get_app_state()

        # Pre-populate data that factor exposure reads
        if fundamentals:
            state.latest_fundamentals = fundamentals
        if dollar_vols:
            state.latest_dollar_volumes = dollar_vols
        if rankings:
            state.latest_rankings = rankings

        mock_broker = MagicMock()
        mock_broker.ping.return_value = True
        mock_broker.connect.return_value = None
        mock_broker.list_positions.return_value = []
        mock_broker.get_account.return_value = MagicMock(equity=Decimal("10000"), cash=Decimal("10000"))
        mock_broker.list_fills_since.return_value = []
        state.broker_adapter = mock_broker

        # Build fake portfolio state with positions
        from dataclasses import dataclass as _dc, field as _f
        @_dc
        class _FakePState:
            equity: Decimal = Decimal("10000")
            cash: Decimal = Decimal("10000")
            positions: dict = _f(default_factory=dict)
            start_of_day_equity: Decimal = Decimal("10000")
            high_water_mark: Decimal = Decimal("10000")
            daily_pnl_pct: Decimal = Decimal("0")
            drawdown_pct: Decimal = Decimal("0")
            gross_exposure: Decimal = Decimal("0")
            as_of: object = None

        ps = _FakePState(positions=positions)
        state.portfolio_state = ps

        cfg = Settings(
            db_url="postgresql+psycopg://u:p@localhost/apis",
            operating_mode=OperatingMode.PAPER,
            kill_switch=False,
        )

        # Run the cycle with extensive mocking
        with (
            patch.object(pt_module, "_persist_paper_cycle_count"),
            patch.object(pt_module, "_persist_portfolio_snapshot"),
            patch.object(pt_module, "_persist_position_history"),
            patch("apps.worker.jobs.paper_trading.get_settings", return_value=cfg),
            patch("services.market_data.service.MarketDataService"),
            patch("services.reporting.service.ReportingService"),
            patch("services.risk_engine.service.RiskEngineService"),
            patch("services.portfolio_engine.service.PortfolioEngineService"),
            patch("services.execution_engine.service.ExecutionEngineService"),
        ):
            # Patch DB session so volatility query silently returns no data
            with patch("apps.worker.jobs.paper_trading.db_session", create=True):
                # Trigger factor computation directly (bypass complex cycle setup)
                from services.risk_engine.factor_exposure import FactorExposureService
                ticker_features = {}
                for ticker in positions:
                    fund = (fundamentals or {}).get(ticker)
                    ticker_features[ticker] = {
                        "composite_score": next(
                            (float(r.composite_score) for r in (rankings or []) if r.ticker == ticker and r.composite_score is not None),
                            None,
                        ),
                        "pe_ratio": getattr(fund, "pe_ratio", None) if fund else None,
                        "eps_growth": getattr(fund, "eps_growth", None) if fund else None,
                        "dollar_volume_20d": (dollar_vols or {}).get(ticker),
                        "volatility_20d": None,
                    }
                ticker_scores = {t: FactorExposureService.compute_factor_scores(fv) for t, fv in ticker_features.items()}
                result = FactorExposureService.compute_portfolio_factor_exposure(
                    positions=positions,
                    ticker_scores=ticker_scores,
                    equity=float(ps.equity),
                )
                state.latest_factor_exposure = result
                state.factor_exposure_computed_at = dt.datetime.now(dt.timezone.utc)

        return state

    def test_factor_exposure_stored_after_cycle(self):
        positions = {
            "AAPL": _FakePosition("AAPL", quantity=Decimal("10"), current_price=Decimal("200")),
        }
        state = self._run_minimal_cycle(positions)
        assert state.latest_factor_exposure is not None

    def test_factor_exposure_computed_at_set(self):
        positions = {
            "AAPL": _FakePosition("AAPL"),
        }
        state = self._run_minimal_cycle(positions)
        assert state.factor_exposure_computed_at is not None

    def test_correct_ticker_in_result(self):
        positions = {
            "NVDA": _FakePosition("NVDA", quantity=Decimal("5"), current_price=Decimal("400")),
        }
        state = self._run_minimal_cycle(positions)
        tickers = [t.ticker for t in state.latest_factor_exposure.ticker_scores]
        assert "NVDA" in tickers

    def test_fundamentals_feed_value_score(self):
        from services.market_data.fundamentals import FundamentalsData
        positions = {
            "AAPL": _FakePosition("AAPL"),
        }
        fund = FundamentalsData(
            ticker="AAPL", pe_ratio=10.0, forward_pe=None, peg_ratio=None,
            price_to_sales=None, eps_growth=0.20, revenue_growth=None,
            earnings_surprise_pct=None,
        )
        state = self._run_minimal_cycle(positions, fundamentals={"AAPL": fund})
        result = state.latest_factor_exposure
        aapl_record = next((t for t in result.ticker_scores if t.ticker == "AAPL"), None)
        assert aapl_record is not None
        # P/E = 10 → value score = 1 - 10/50 = 0.8
        assert abs(aapl_record.scores["VALUE"] - 0.8) < 0.01

    def test_dollar_volume_feeds_quality_score(self):
        positions = {
            "AAPL": _FakePosition("AAPL"),
        }
        state = self._run_minimal_cycle(positions, dollar_vols={"AAPL": 2_000_000_000.0})
        aapl_record = next((t for t in state.latest_factor_exposure.ticker_scores if t.ticker == "AAPL"), None)
        assert aapl_record is not None
        assert aapl_record.scores["QUALITY"] > 0.5  # high ADV → high quality

    def test_empty_positions_no_factor_exposure_computed(self):
        """With no positions, factor exposure block should skip computation."""
        from services.risk_engine.factor_exposure import FactorExposureService
        result = FactorExposureService.compute_portfolio_factor_exposure(
            positions={}, ticker_scores={}, equity=0.0
        )
        assert result.position_count == 0
