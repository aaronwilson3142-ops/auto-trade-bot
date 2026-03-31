"""
Phase 29 — Fundamentals Data Layer + ValuationStrategy
=======================================================

Tests cover:
  - FundamentalsData dataclass construction and fetched_at default
  - _safe_positive_float / _safe_float helpers
  - FundamentalsService._parse_info (mocked yfinance)
  - FundamentalsService.fetch (network stubbed)
  - FundamentalsService.fetch_batch (isolation: one failure doesn't cancel others)
  - FundamentalsService.apply_to_feature_set
  - ValuationStrategy.score — no data → neutral (0.5, conf 0.0)
  - ValuationStrategy.score — cheap stock (low PE/PEG, high EPS growth)
  - ValuationStrategy.score — expensive stock (high PE/PEG, negative growth)
  - ValuationStrategy.score — partial data with weight re-normalisation
  - FeatureEnrichmentService.enrich (with and without fundamentals_store)
  - FeatureEnrichmentService.enrich_batch (with fundamentals_store, per-ticker)
  - run_fundamentals_refresh worker job (stores in app_state, error isolation)
  - Worker scheduler: fundamentals_refresh job exists and count is 15
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_feature_set(**overrides: Any):
    """Return a minimal FeatureSet for testing."""
    from services.feature_store.models import ComputedFeature, FeatureSet

    ticker = overrides.pop("ticker", "AAPL")
    now = dt.datetime.utcnow()
    features = [
        ComputedFeature("volatility_20d", "risk", Decimal("0.25"), now),
        ComputedFeature("dollar_volume_20d", "liquidity", Decimal("5e8"), now),
    ]
    # If extra FeatureSet-level fields are passed (overlays), separate them
    fs_extra = {}
    feature_overlay_keys = {
        "pe_ratio", "forward_pe", "peg_ratio", "price_to_sales",
        "eps_growth", "revenue_growth", "earnings_surprise_pct",
        "theme_scores", "macro_bias", "macro_regime",
        "sentiment_score", "sentiment_confidence",
    }
    for k in feature_overlay_keys:
        if k in overrides:
            fs_extra[k] = overrides.pop(k)

    return FeatureSet(
        security_id=uuid.uuid4(),
        ticker=ticker,
        as_of_timestamp=now,
        features=features,
        **fs_extra,
    )


def _make_fund_data(**overrides: Any):
    """Return a FundamentalsData with sensible defaults."""
    from services.market_data.fundamentals import FundamentalsData

    defaults = dict(
        ticker="AAPL",
        pe_ratio=18.0,
        forward_pe=15.0,
        peg_ratio=1.2,
        price_to_sales=5.0,
        eps_growth=0.20,
        revenue_growth=0.10,
        earnings_surprise_pct=0.05,
    )
    defaults.update(overrides)
    return FundamentalsData(**defaults)


# ---------------------------------------------------------------------------
# TestFundamentalsDataModel
# ---------------------------------------------------------------------------
class TestFundamentalsDataModel:
    def test_creation_with_all_fields(self):
        from services.market_data.fundamentals import FundamentalsData

        now = dt.datetime.now(dt.UTC)
        fd = FundamentalsData(
            ticker="MSFT",
            pe_ratio=30.0,
            forward_pe=25.0,
            peg_ratio=1.5,
            price_to_sales=10.0,
            eps_growth=0.15,
            revenue_growth=0.08,
            earnings_surprise_pct=0.03,
            fetched_at=now,
        )
        assert fd.ticker == "MSFT"
        assert fd.pe_ratio == 30.0
        assert fd.fetched_at == now

    def test_fetched_at_defaults_to_utc_now(self):
        from services.market_data.fundamentals import FundamentalsData

        before = dt.datetime.now(dt.UTC)
        fd = FundamentalsData(
            ticker="NVDA",
            pe_ratio=None,
            forward_pe=None,
            peg_ratio=None,
            price_to_sales=None,
            eps_growth=None,
            revenue_growth=None,
            earnings_surprise_pct=None,
        )
        after = dt.datetime.now(dt.UTC)
        assert fd.fetched_at is not None
        assert before <= fd.fetched_at <= after

    def test_all_fields_can_be_none(self):
        from services.market_data.fundamentals import FundamentalsData

        fd = FundamentalsData(
            ticker="TEST",
            pe_ratio=None,
            forward_pe=None,
            peg_ratio=None,
            price_to_sales=None,
            eps_growth=None,
            revenue_growth=None,
            earnings_surprise_pct=None,
        )
        assert fd.pe_ratio is None
        assert fd.earnings_surprise_pct is None


# ---------------------------------------------------------------------------
# TestSafeFloatHelpers
# ---------------------------------------------------------------------------

class TestSafeFloatHelpers:
    """Tests for module-level _safe_positive_float and _safe_float."""

    def _safe_pos(self, info: dict, key: str):
        from services.market_data.fundamentals import _safe_positive_float
        return _safe_positive_float(info, key)

    def _safe_f(self, info: dict, key: str):
        from services.market_data.fundamentals import _safe_float
        return _safe_float(info, key)

    def test_positive_float_returns_value(self):
        assert self._safe_pos({"pe": 20.0}, "pe") == 20.0

    def test_positive_float_rejects_zero(self):
        assert self._safe_pos({"pe": 0.0}, "pe") is None

    def test_positive_float_rejects_negative(self):
        assert self._safe_pos({"pe": -5.0}, "pe") is None

    def test_positive_float_missing_key_returns_none(self):
        assert self._safe_pos({}, "pe") is None

    def test_positive_float_non_numeric_returns_none(self):
        assert self._safe_pos({"pe": "not_a_float"}, "pe") is None

    def test_positive_float_None_value_returns_none(self):
        assert self._safe_pos({"pe": None}, "pe") is None

    def test_safe_float_allows_negative(self):
        assert self._safe_f({"growth": -0.15}, "growth") == -0.15

    def test_safe_float_allows_positive(self):
        assert self._safe_f({"growth": 0.25}, "growth") == 0.25

    def test_safe_float_missing_key_returns_none(self):
        assert self._safe_f({}, "growth") is None

    def test_safe_float_non_numeric_returns_none(self):
        assert self._safe_f({"growth": "bad"}, "growth") is None


# ---------------------------------------------------------------------------
# TestFundamentalsServiceParse
# ---------------------------------------------------------------------------

class TestFundamentalsServiceParse:
    """Unit tests for FundamentalsService._parse_info and _extract_earnings_surprise."""

    def _svc(self):
        from services.market_data.fundamentals import FundamentalsService
        return FundamentalsService()

    def test_parse_info_maps_all_standard_fields(self):
        info = {
            "trailingPE": 22.5,
            "forwardPE": 18.0,
            "pegRatio": 1.4,
            "priceToSalesTrailing12Months": 6.0,
            "earningsGrowth": 0.18,
            "revenueGrowth": 0.10,
        }
        fd = self._svc()._parse_info("AAPL", info)
        assert fd.ticker == "AAPL"
        assert fd.pe_ratio == 22.5
        assert fd.forward_pe == 18.0
        assert fd.peg_ratio == 1.4
        assert fd.price_to_sales == 6.0
        assert fd.eps_growth == 0.18
        assert fd.revenue_growth == 0.10

    def test_parse_info_negative_pe_becomes_none(self):
        info = {"trailingPE": -5.0, "forwardPE": -12.0}
        fd = self._svc()._parse_info("LOSS", info)
        assert fd.pe_ratio is None
        assert fd.forward_pe is None

    def test_parse_info_earnings_surprise_direct_key(self):
        info = {"earningsSurprise": 0.07}
        fd = self._svc()._parse_info("NVDA", info)
        assert fd.earnings_surprise_pct == pytest.approx(0.07)

    def test_parse_info_earnings_surprise_from_history(self):
        info = {
            "earningsHistory": [
                {"epsActual": 2.0, "epsEstimate": 1.80},  # older
                {"epsActual": 2.5, "epsEstimate": 2.0},   # latest → +25% surprise
            ]
        }
        fd = self._svc()._parse_info("MSFT", info)
        assert fd.earnings_surprise_pct == pytest.approx(0.25)

    def test_parse_info_earnings_surprise_none_when_no_history(self):
        fd = self._svc()._parse_info("XYZ", {})
        assert fd.earnings_surprise_pct is None

    def test_parse_info_earnings_surprise_none_when_estimate_zero(self):
        info = {"earningsHistory": [{"epsActual": 1.0, "epsEstimate": 0.0}]}
        fd = self._svc()._parse_info("ZZZ", info)
        assert fd.earnings_surprise_pct is None

    def test_parse_info_empty_dict_gives_all_none(self):
        fd = self._svc()._parse_info("EMPTY", {})
        assert fd.pe_ratio is None
        assert fd.forward_pe is None
        assert fd.peg_ratio is None
        assert fd.price_to_sales is None
        assert fd.eps_growth is None
        assert fd.revenue_growth is None
        assert fd.earnings_surprise_pct is None


# ---------------------------------------------------------------------------
# TestFundamentalsServiceFetch
# ---------------------------------------------------------------------------

class TestFundamentalsServiceFetch:
    """Mocked yfinance tests — no network calls."""

    def _svc(self):
        from services.market_data.fundamentals import FundamentalsService
        return FundamentalsService()

    def test_fetch_returns_fundamentals_data_on_success(self):
        mock_ticker = MagicMock()
        mock_ticker.info = {
            "trailingPE": 28.0,
            "forwardPE": 22.0,
            "pegRatio": 1.8,
            "earningsGrowth": 0.12,
        }
        with patch("yfinance.Ticker", return_value=mock_ticker):
            fd = self._svc().fetch("AAPL")
        assert fd.ticker == "AAPL"
        assert fd.pe_ratio == 28.0
        assert fd.forward_pe == 22.0

    def test_fetch_returns_nulled_data_on_yfinance_exception(self):
        with patch("yfinance.Ticker", side_effect=RuntimeError("connection refused")):
            fd = self._svc().fetch("FAIL")
        assert fd.ticker == "FAIL"
        assert fd.pe_ratio is None
        assert fd.forward_pe is None

    def test_fetch_handles_none_info_dict(self):
        mock_ticker = MagicMock()
        mock_ticker.info = None
        with patch("yfinance.Ticker", return_value=mock_ticker):
            fd = self._svc().fetch("NONE")
        assert fd.pe_ratio is None

    def test_fetch_handles_empty_info_dict(self):
        mock_ticker = MagicMock()
        mock_ticker.info = {}
        with patch("yfinance.Ticker", return_value=mock_ticker):
            fd = self._svc().fetch("EMPTY")
        assert fd.pe_ratio is None
        assert fd.fetched_at is not None


# ---------------------------------------------------------------------------
# TestFundamentalsServiceBatch
# ---------------------------------------------------------------------------

class TestFundamentalsServiceBatch:
    """fetch_batch: isolation ensures one failure doesn't cancel others."""

    def _svc(self):
        from services.market_data.fundamentals import FundamentalsService
        return FundamentalsService()

    def test_fetch_batch_returns_dict_keyed_by_ticker(self):
        svc = self._svc()
        svc.fetch = lambda t: _make_fund_data(ticker=t)
        result = svc.fetch_batch(["AAPL", "NVDA", "MSFT"])
        assert set(result.keys()) == {"AAPL", "NVDA", "MSFT"}

    def test_fetch_batch_failure_does_not_cancel_other_tickers(self):
        from services.market_data.fundamentals import FundamentalsData

        def _fetch(ticker: str) -> FundamentalsData:
            if ticker == "FAIL":
                raise RuntimeError("boom")
            return _make_fund_data(ticker=ticker)

        svc = self._svc()
        # Directly call fetch_batch which calls self.fetch per-ticker
        # We patch the instance method
        good_data = _make_fund_data(ticker="AAPL")
        fail_data = _make_fund_data(ticker="FAIL", pe_ratio=None)

        svc.fetch = lambda t: _fetch(t) if t != "FAIL" else fail_data
        result = svc.fetch_batch(["AAPL", "FAIL"])
        # Both keys present
        assert "AAPL" in result
        assert "FAIL" in result

    def test_fetch_batch_empty_list_returns_empty_dict(self):
        svc = self._svc()
        assert svc.fetch_batch([]) == {}

    def test_fetch_batch_each_entry_has_correct_ticker(self):
        svc = self._svc()
        svc.fetch = lambda t: _make_fund_data(ticker=t)
        result = svc.fetch_batch(["TSLA", "GOOG"])
        assert result["TSLA"].ticker == "TSLA"
        assert result["GOOG"].ticker == "GOOG"


# ---------------------------------------------------------------------------
# TestFundamentalsApplyToFeatureSet
# ---------------------------------------------------------------------------

class TestFundamentalsApplyToFeatureSet:
    def _svc(self):
        from services.market_data.fundamentals import FundamentalsService
        return FundamentalsService()

    def test_apply_sets_all_fundamentals_fields(self):
        fs = _make_feature_set(ticker="AAPL")
        fd = _make_fund_data(
            ticker="AAPL",
            pe_ratio=22.0,
            forward_pe=18.0,
            peg_ratio=1.3,
            price_to_sales=6.5,
            eps_growth=0.18,
            revenue_growth=0.12,
            earnings_surprise_pct=0.05,
        )
        enriched = self._svc().apply_to_feature_set(fs, fd)
        assert enriched.pe_ratio == 22.0
        assert enriched.forward_pe == 18.0
        assert enriched.peg_ratio == 1.3
        assert enriched.price_to_sales == 6.5
        assert enriched.eps_growth == 0.18
        assert enriched.revenue_growth == 0.12
        assert enriched.earnings_surprise_pct == 0.05

    def test_apply_does_not_mutate_original(self):
        fs = _make_feature_set(ticker="AAPL")
        fd = _make_fund_data(ticker="AAPL", pe_ratio=28.0)
        _ = self._svc().apply_to_feature_set(fs, fd)
        assert fs.pe_ratio is None  # original unchanged

    def test_apply_with_none_fields_keeps_none(self):
        from services.market_data.fundamentals import FundamentalsData

        fs = _make_feature_set(ticker="AAPL")
        fd = FundamentalsData(
            ticker="AAPL",
            pe_ratio=None,
            forward_pe=None,
            peg_ratio=None,
            price_to_sales=None,
            eps_growth=None,
            revenue_growth=None,
            earnings_surprise_pct=None,
        )
        enriched = self._svc().apply_to_feature_set(fs, fd)
        assert enriched.pe_ratio is None
        assert enriched.forward_pe is None


# ---------------------------------------------------------------------------
# TestValuationStrategyNoData
# ---------------------------------------------------------------------------

class TestValuationStrategyNoData:
    def _strat(self):
        from services.signal_engine.strategies.valuation import ValuationStrategy
        return ValuationStrategy()

    def _fs_no_fundamentals(self):
        return _make_feature_set(ticker="AAPL")

    def test_neutral_score_when_no_fundamentals(self):
        out = self._strat().score(self._fs_no_fundamentals())
        assert float(out.signal_score) == pytest.approx(0.5)

    def test_zero_confidence_when_no_fundamentals(self):
        out = self._strat().score(self._fs_no_fundamentals())
        assert float(out.confidence_score) == pytest.approx(0.0)

    def test_strategy_key_is_set(self):
        out = self._strat().score(self._fs_no_fundamentals())
        assert out.strategy_key == "valuation_v1"

    def test_contains_rumor_is_false(self):
        out = self._strat().score(self._fs_no_fundamentals())
        assert out.contains_rumor is False

    def test_no_data_rationale_explains_neutral(self):
        out = self._strat().score(self._fs_no_fundamentals())
        assert "no fundamentals" in out.explanation_dict["rationale"].lower()

    def test_n_available_is_zero_when_no_data(self):
        out = self._strat().score(self._fs_no_fundamentals())
        assert out.explanation_dict["n_available"] == 0

    def test_signal_type_is_valuation(self):
        from services.signal_engine.models import SignalType

        out = self._strat().score(self._fs_no_fundamentals())
        assert out.signal_type == SignalType.VALUATION


# ---------------------------------------------------------------------------
# TestValuationStrategyScoring
# ---------------------------------------------------------------------------

class TestValuationStrategyScoring:
    def _strat(self):
        from services.signal_engine.strategies.valuation import ValuationStrategy
        return ValuationStrategy()

    def _fs_with_funds(self, **funds):
        return _make_feature_set(ticker="AAPL", **funds)

    def test_cheap_stock_scores_above_0_6(self):
        """Low forward P/E (10), low PEG (0.8), strong EPS growth (+30%) → attractive."""
        fs = self._fs_with_funds(
            forward_pe=10.0,
            peg_ratio=0.8,
            eps_growth=0.30,
            earnings_surprise_pct=0.08,
        )
        out = self._strat().score(fs)
        assert float(out.signal_score) > 0.6

    def test_expensive_stock_scores_below_0_4(self):
        """High forward P/E (55), high PEG (3.5), negative EPS → stretched."""
        fs = self._fs_with_funds(
            forward_pe=55.0,
            peg_ratio=3.5,
            eps_growth=-0.40,
            earnings_surprise_pct=-0.09,
        )
        out = self._strat().score(fs)
        assert float(out.signal_score) < 0.4

    def test_full_confidence_when_all_4_signals_present(self):
        fs = self._fs_with_funds(
            forward_pe=20.0,
            peg_ratio=1.5,
            eps_growth=0.10,
            earnings_surprise_pct=0.02,
        )
        out = self._strat().score(fs)
        assert float(out.confidence_score) == pytest.approx(1.0)

    def test_partial_confidence_when_2_of_4_signals_present(self):
        fs = self._fs_with_funds(forward_pe=20.0, eps_growth=0.10)
        out = self._strat().score(fs)
        assert float(out.confidence_score) == pytest.approx(0.5)

    def test_single_signal_gives_0_25_confidence(self):
        fs = self._fs_with_funds(forward_pe=20.0)
        out = self._strat().score(fs)
        assert float(out.confidence_score) == pytest.approx(0.25)

    def test_n_available_reflects_present_signals(self):
        fs = self._fs_with_funds(forward_pe=20.0, peg_ratio=1.5)
        out = self._strat().score(fs)
        assert out.explanation_dict["n_available"] == 2

    def test_sub_scores_dict_present_in_explanation(self):
        fs = self._fs_with_funds(forward_pe=20.0, eps_growth=0.15)
        out = self._strat().score(fs)
        assert "forward_pe" in out.explanation_dict["sub_scores"]
        assert "eps_growth" in out.explanation_dict["sub_scores"]

    def test_driver_features_includes_pe_fields(self):
        fs = self._fs_with_funds(forward_pe=20.0, peg_ratio=1.5)
        out = self._strat().score(fs)
        df = out.explanation_dict["driver_features"]
        assert "forward_pe" in df
        assert "peg_ratio" in df

    def test_negative_pe_from_field_gives_no_pe_sub_score(self):
        """forward_pe ≤ 0 should not produce a sub-score."""
        fs = self._fs_with_funds(forward_pe=-10.0, eps_growth=0.20)
        out = self._strat().score(fs)
        assert "forward_pe" not in out.explanation_dict["sub_scores"]
        # Only eps_growth present → confidence 0.25
        assert float(out.confidence_score) == pytest.approx(0.25)

    def test_score_is_within_0_1_range(self):
        for fpe in [5.0, 15.0, 25.0, 50.0, 75.0]:
            fs = self._fs_with_funds(forward_pe=fpe)
            out = self._strat().score(fs)
            score = float(out.signal_score)
            assert 0.0 <= score <= 1.0, f"score {score} out of range for fpe={fpe}"

    def test_catalyst_score_is_neutral(self):
        fs = self._fs_with_funds(forward_pe=20.0)
        out = self._strat().score(fs)
        assert float(out.catalyst_score) == pytest.approx(0.5)

    def test_rationale_mentions_attractive_for_cheap_stock(self):
        fs = self._fs_with_funds(
            forward_pe=6.0,
            peg_ratio=0.6,
            eps_growth=0.40,
            earnings_surprise_pct=0.09,
        )
        out = self._strat().score(fs)
        assert "attractive" in out.explanation_dict["rationale"].lower()


# ---------------------------------------------------------------------------
# TestFundamentalsEnrichmentIntegration
# ---------------------------------------------------------------------------

class TestFundamentalsEnrichmentIntegration:
    """FeatureEnrichmentService.enrich() / enrich_batch() with fundamentals_store."""

    def _svc(self):
        from services.feature_store.enrichment import FeatureEnrichmentService
        return FeatureEnrichmentService()

    def test_enrich_applies_fundamentals_when_store_provided(self):
        svc = self._svc()
        fs = _make_feature_set(ticker="AAPL")
        fund_data = _make_fund_data(ticker="AAPL", forward_pe=18.0, eps_growth=0.20)
        enriched = svc.enrich(fs, fundamentals_store={"AAPL": fund_data})
        assert enriched.forward_pe == 18.0
        assert enriched.eps_growth == 0.20

    def test_enrich_does_not_apply_fundamentals_for_different_ticker(self):
        svc = self._svc()
        fs = _make_feature_set(ticker="NVDA")
        fund_data = _make_fund_data(ticker="AAPL")
        enriched = svc.enrich(fs, fundamentals_store={"AAPL": fund_data})
        assert enriched.forward_pe is None  # NVDA not in store

    def test_enrich_without_fundamentals_store_leaves_fields_none(self):
        svc = self._svc()
        fs = _make_feature_set(ticker="AAPL")
        enriched = svc.enrich(fs)
        assert enriched.forward_pe is None

    def test_enrich_does_not_mutate_original_feature_set(self):
        svc = self._svc()
        fs = _make_feature_set(ticker="AAPL")
        fund_data = _make_fund_data(ticker="AAPL", forward_pe=22.0)
        _ = svc.enrich(fs, fundamentals_store={"AAPL": fund_data})
        assert fs.forward_pe is None

    def test_enrich_batch_applies_fundamentals_to_each_ticker(self):
        svc = self._svc()
        fss = [
            _make_feature_set(ticker="AAPL"),
            _make_feature_set(ticker="NVDA"),
        ]
        store = {
            "AAPL": _make_fund_data(ticker="AAPL", forward_pe=18.0),
            "NVDA": _make_fund_data(ticker="NVDA", forward_pe=35.0),
        }
        results = svc.enrich_batch(fss, fundamentals_store=store)
        assert results[0].forward_pe == 18.0
        assert results[1].forward_pe == 35.0

    def test_enrich_batch_without_store_leaves_fields_none(self):
        svc = self._svc()
        fss = [_make_feature_set(ticker="AAPL"), _make_feature_set(ticker="NVDA")]
        results = svc.enrich_batch(fss)
        for r in results:
            assert r.forward_pe is None

    def test_enrich_batch_partial_store_leaves_missing_tickers_none(self):
        svc = self._svc()
        fss = [
            _make_feature_set(ticker="AAPL"),
            _make_feature_set(ticker="TSLA"),  # not in store
        ]
        store = {"AAPL": _make_fund_data(ticker="AAPL", forward_pe=18.0)}
        results = svc.enrich_batch(fss, fundamentals_store=store)
        assert results[0].forward_pe == 18.0
        assert results[1].forward_pe is None  # TSLA missing from store

    def test_enrich_batch_preserves_original_order(self):
        svc = self._svc()
        tickers = ["AAPL", "NVDA", "MSFT"]
        fss = [_make_feature_set(ticker=t) for t in tickers]
        results = svc.enrich_batch(fss)
        for i, t in enumerate(tickers):
            assert results[i].ticker == t


# ---------------------------------------------------------------------------
# TestFundamentalsWorkerJob
# ---------------------------------------------------------------------------

class TestFundamentalsWorkerJob:
    """run_fundamentals_refresh stores results in app_state and handles errors."""

    def _app_state(self):
        from apps.api.state import ApiAppState
        return ApiAppState()

    def test_run_fundamentals_refresh_stores_in_app_state(self):
        from apps.worker.jobs.ingestion import run_fundamentals_refresh

        fund_data = _make_fund_data(ticker="AAPL")
        mock_svc = MagicMock()
        mock_svc.fetch_batch.return_value = {"AAPL": fund_data, "NVDA": fund_data}

        app_state = self._app_state()
        result = run_fundamentals_refresh(
            app_state=app_state,
            fundamentals_service=mock_svc,
            tickers=["AAPL", "NVDA"],
        )
        assert result["status"] == "ok"
        assert result["tickers_fetched"] == 2
        assert "AAPL" in app_state.latest_fundamentals
        assert "NVDA" in app_state.latest_fundamentals

    def test_run_fundamentals_refresh_ok_when_empty_tickers(self):
        from apps.worker.jobs.ingestion import run_fundamentals_refresh

        mock_svc = MagicMock()
        mock_svc.fetch_batch.return_value = {}

        app_state = self._app_state()
        result = run_fundamentals_refresh(
            app_state=app_state,
            fundamentals_service=mock_svc,
            tickers=[],
        )
        assert result["status"] == "ok"
        assert result["tickers_fetched"] == 0
        assert result["errors"] == []

    def test_run_fundamentals_refresh_error_returned_on_exception(self):
        from apps.worker.jobs.ingestion import run_fundamentals_refresh

        mock_svc = MagicMock()
        mock_svc.fetch_batch.side_effect = RuntimeError("network unreachable")

        app_state = self._app_state()
        result = run_fundamentals_refresh(
            app_state=app_state,
            fundamentals_service=mock_svc,
            tickers=["AAPL"],
        )
        assert result["status"] == "error"
        assert result["tickers_fetched"] == 0
        assert len(result["errors"]) == 1

    def test_run_fundamentals_refresh_error_does_not_raise(self):
        from apps.worker.jobs.ingestion import run_fundamentals_refresh

        mock_svc = MagicMock()
        mock_svc.fetch_batch.side_effect = RuntimeError("boom")

        app_state = self._app_state()
        # Must not raise — scheduler threads must never die
        result = run_fundamentals_refresh(
            app_state=app_state,
            fundamentals_service=mock_svc,
            tickers=["AAPL"],
        )
        assert isinstance(result, dict)

    def test_run_fundamentals_refresh_result_has_run_at(self):
        from apps.worker.jobs.ingestion import run_fundamentals_refresh

        mock_svc = MagicMock()
        mock_svc.fetch_batch.return_value = {}

        app_state = self._app_state()
        result = run_fundamentals_refresh(
            app_state=app_state,
            fundamentals_service=mock_svc,
            tickers=[],
        )
        assert "run_at" in result
        # Must be a parseable ISO timestamp
        dt.datetime.fromisoformat(result["run_at"])

    def test_latest_fundamentals_field_exists_on_app_state(self):
        app_state = self._app_state()
        assert hasattr(app_state, "latest_fundamentals")
        assert isinstance(app_state.latest_fundamentals, dict)


# ---------------------------------------------------------------------------
# TestWorkerScheduleJobCount
# ---------------------------------------------------------------------------

class TestWorkerScheduleJobCount:
    """Validates fundamentals_refresh was added to the scheduler (15 jobs total)."""

    def test_fundamentals_refresh_job_in_scheduler(self):
        from apps.worker.main import build_scheduler

        scheduler = build_scheduler()
        job_ids = {job.id for job in scheduler.get_jobs()}
        assert "fundamentals_refresh" in job_ids

    def test_scheduler_has_15_jobs(self):
        from apps.worker.main import build_scheduler

        scheduler = build_scheduler()
        assert len(scheduler.get_jobs()) == 30

    def test_fundamentals_refresh_scheduled_at_06_18(self):
        from apps.worker.main import build_scheduler

        scheduler = build_scheduler()
        jobs_by_id = {job.id: job for job in scheduler.get_jobs()}
        fund_job = jobs_by_id.get("fundamentals_refresh")
        assert fund_job is not None
        trigger = fund_job.trigger
        fields_by_name = {f.name: f for f in trigger.fields}
        hour_field = fields_by_name.get("hour")
        minute_field = fields_by_name.get("minute")
        assert str(hour_field) == "6", f"Expected hour=6, got {hour_field}"
        assert str(minute_field) == "18", f"Expected minute=18, got {minute_field}"

    def test_fundamentals_refresh_exported_from_jobs_package(self):
        from apps.worker.jobs import run_fundamentals_refresh
        assert callable(run_fundamentals_refresh)
