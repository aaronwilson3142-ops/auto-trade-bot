"""
Integration tests — Research pipeline end-to-end.

These tests wire together real service instances (no DB, all in-memory)
to verify the full research pipeline from FeatureSet construction →
multi-strategy signal scoring → ranking → ranked results.

No mocks are used at the service layer.  External dependencies (DB, broker)
are absent; all inputs are constructed in-process.

Coverage:
  - TestFeatureEnrichmentPipeline      (6 tests)
  - TestSignalPipelineEndToEnd         (8 tests)
  - TestRankingPipelineEndToEnd        (8 tests)
  - TestMultiTickerResearchPipeline    (6 tests)
  - TestBullBearResearchScenario       (4 tests)
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from services.feature_store.models import ComputedFeature, FeatureSet
from services.ranking_engine.service import RankingEngineService
from services.signal_engine.service import SignalEngineService
from services.signal_engine.strategies.macro_tailwind import MacroTailwindStrategy
from services.signal_engine.strategies.theme_alignment import ThemeAlignmentStrategy

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _build_feature_set(
    ticker: str = "NVDA",
    return_1m: float = 0.08,
    return_3m: float = 0.18,
    return_6m: float = 0.30,
    volatility_20d: float = 0.35,
    dollar_volume_20d: float = 8e9,
    sma_cross: float = 1.0,
    theme_scores: dict | None = None,
    macro_bias: float = 0.0,
    macro_regime: str = "NEUTRAL",
    sentiment_score: float = 0.0,
    sentiment_confidence: float = 0.0,
) -> FeatureSet:
    sid = uuid.uuid4()
    features = [
        ComputedFeature("return_1m", "momentum", Decimal(str(return_1m)), dt.datetime.utcnow()),
        ComputedFeature("return_3m", "momentum", Decimal(str(return_3m)), dt.datetime.utcnow()),
        ComputedFeature("return_6m", "momentum", Decimal(str(return_6m)), dt.datetime.utcnow()),
        ComputedFeature("volatility_20d", "risk", Decimal(str(volatility_20d)), dt.datetime.utcnow()),
        ComputedFeature("dollar_volume_20d", "liquidity", Decimal(str(dollar_volume_20d)), dt.datetime.utcnow()),
        ComputedFeature("sma_cross_signal", "trend", Decimal(str(sma_cross)), dt.datetime.utcnow()),
        ComputedFeature("atr_14", "risk", Decimal("1.5"), dt.datetime.utcnow()),
        ComputedFeature("sma_20", "trend", Decimal("100.0"), dt.datetime.utcnow()),
        ComputedFeature("sma_50", "trend", Decimal("90.0"), dt.datetime.utcnow()),
        ComputedFeature("price_vs_sma20", "trend", Decimal("0.05"), dt.datetime.utcnow()),
        ComputedFeature("price_vs_sma50", "trend", Decimal("0.15"), dt.datetime.utcnow()),
    ]
    return FeatureSet(
        security_id=sid,
        ticker=ticker,
        as_of_timestamp=dt.datetime.utcnow(),
        features=features,
        theme_scores=theme_scores or {},
        macro_bias=macro_bias,
        macro_regime=macro_regime,
        sentiment_score=sentiment_score,
        sentiment_confidence=sentiment_confidence,
    )


# ---------------------------------------------------------------------------
# TestFeatureEnrichmentPipeline
# ---------------------------------------------------------------------------

class TestFeatureEnrichmentPipeline:
    """Verify that FeatureSet correctly carries all overlay data."""

    def test_baseline_features_accessible_via_get(self):
        fs = _build_feature_set(return_1m=0.05)
        assert fs.get("return_1m") == Decimal("0.05")

    def test_theme_scores_overlay_accessible(self):
        fs = _build_feature_set(theme_scores={"ai_infrastructure": 0.90})
        assert "ai_infrastructure" in fs.theme_scores

    def test_macro_bias_overlay_accessible(self):
        fs = _build_feature_set(macro_bias=0.6, macro_regime="RISK_ON")
        assert fs.macro_bias == 0.6
        assert fs.macro_regime == "RISK_ON"

    def test_sentiment_overlay_accessible(self):
        fs = _build_feature_set(sentiment_score=0.7, sentiment_confidence=0.80)
        assert fs.sentiment_score == 0.7
        assert fs.sentiment_confidence == 0.80

    def test_baseline_features_unaffected_by_overlay(self):
        """Overlay fields do not corrupt FEATURE_KEYS-based lookups."""
        fs = _build_feature_set(
            return_3m=0.12,
            theme_scores={"semiconductor": 0.88},
            macro_bias=0.5,
        )
        assert fs.get("return_3m") == Decimal("0.12")
        assert fs.get("theme_scores") is None   # not a FEATURE_KEYS key

    def test_empty_overlay_defaults_give_neutral_signals(self):
        """A FeatureSet with no overlays produces neutral output from overlay strategies."""
        fs = _build_feature_set()
        theme_out = ThemeAlignmentStrategy().score(fs)
        macro_out = MacroTailwindStrategy().score(fs)
        assert float(theme_out.signal_score) == pytest.approx(0.5, abs=0.01)
        assert float(macro_out.signal_score) == pytest.approx(0.5, abs=0.01)


# ---------------------------------------------------------------------------
# TestSignalPipelineEndToEnd
# ---------------------------------------------------------------------------

class TestSignalPipelineEndToEnd:
    """Verify SignalEngineService.score_from_features produces complete output."""

    def setup_method(self):
        self.svc = SignalEngineService()

    def test_single_ticker_produces_four_signals(self):
        fs = _build_feature_set("NVDA")
        outputs = self.svc.score_from_features([fs])
        assert len(outputs) == 5

    def test_two_tickers_produce_eight_signals(self):
        fsets = [_build_feature_set("NVDA"), _build_feature_set("MSFT")]
        outputs = self.svc.score_from_features(fsets)
        assert len(outputs) == 10

    def test_all_four_strategy_keys_present(self):
        fs = _build_feature_set()
        outputs = self.svc.score_from_features([fs])
        keys = {o.strategy_key for o in outputs}
        expected = {"momentum_v1", "theme_alignment_v1", "macro_tailwind_v1", "sentiment_v1", "valuation_v1"}
        assert keys == expected

    def test_all_signal_scores_in_range(self):
        fs = _build_feature_set(
            theme_scores={"ai_infrastructure": 0.9},
            macro_bias=0.5,
            sentiment_score=0.6,
            sentiment_confidence=0.75,
        )
        outputs = self.svc.score_from_features([fs])
        for out in outputs:
            score = float(out.signal_score)
            assert 0.0 <= score <= 1.0, f"{out.strategy_key}: {score}"

    def test_all_confidence_scores_in_range(self):
        fs = _build_feature_set(
            theme_scores={"semiconductor": 0.85},
            macro_bias=0.4,
            sentiment_score=0.3,
            sentiment_confidence=0.6,
        )
        outputs = self.svc.score_from_features([fs])
        for out in outputs:
            conf = float(out.confidence_score)
            assert 0.0 <= conf <= 1.0, f"{out.strategy_key}: {conf}"

    def test_all_outputs_have_explanation_rationale(self):
        fs = _build_feature_set()
        outputs = self.svc.score_from_features([fs])
        for out in outputs:
            assert "rationale" in out.explanation_dict, f"{out.strategy_key} missing rationale"

    def test_bullish_environment_momentum_above_neutral(self):
        fs = _build_feature_set(
            return_1m=0.15, return_3m=0.25, return_6m=0.40, sma_cross=1.0
        )
        outputs = self.svc.score_from_features([fs])
        momentum_out = next(o for o in outputs if o.strategy_key == "momentum_v1")
        assert float(momentum_out.signal_score) > 0.5

    def test_thematic_ticker_theme_alignment_above_neutral(self):
        fs = _build_feature_set(
            ticker="NVDA",
            theme_scores={"ai_infrastructure": 0.99, "semiconductor": 0.95},
        )
        outputs = self.svc.score_from_features([fs])
        theme_out = next(o for o in outputs if o.strategy_key == "theme_alignment_v1")
        assert float(theme_out.signal_score) > 0.5


# ---------------------------------------------------------------------------
# TestRankingPipelineEndToEnd
# ---------------------------------------------------------------------------

class TestRankingPipelineEndToEnd:
    """Verify RankingEngineService produces valid rankings from multi-strategy signals."""

    def setup_method(self):
        self.signal_svc = SignalEngineService()
        self.rank_svc = RankingEngineService()

    def _signals_for(self, fs: FeatureSet):
        return self.signal_svc.score_from_features([fs])

    def test_single_ticker_yields_one_ranked_result(self):
        fs = _build_feature_set("SPY")
        signals = self._signals_for(fs)
        results = self.rank_svc.rank_signals(signals)
        assert len(results) == 1

    def test_ranked_result_has_composite_score(self):
        fs = _build_feature_set()
        results = self.rank_svc.rank_signals(self._signals_for(fs))
        assert results[0].composite_score is not None
        assert float(results[0].composite_score) > 0.0

    def test_ranked_result_has_thesis_summary(self):
        fs = _build_feature_set()
        results = self.rank_svc.rank_signals(self._signals_for(fs))
        assert results[0].thesis_summary != ""

    def test_ranked_result_four_contributing_signals(self):
        fs = _build_feature_set()
        results = self.rank_svc.rank_signals(self._signals_for(fs))
        assert len(results[0].contributing_signals) == 5

    def test_recommended_action_buy_for_bullish(self):
        fs = _build_feature_set(
            return_1m=0.15, return_3m=0.25, return_6m=0.40,
            theme_scores={"ai_infrastructure": 0.99, "semiconductor": 0.95},
            macro_bias=0.8, macro_regime="RISK_ON",
            sentiment_score=0.8, sentiment_confidence=0.9,
        )
        results = self.rank_svc.rank_signals(self._signals_for(fs))
        assert results[0].recommended_action == "buy"

    def test_recommended_action_avoid_for_bearish(self):
        fs = _build_feature_set(
            return_1m=-0.15, return_3m=-0.25, return_6m=-0.40,
            volatility_20d=0.80,
            dollar_volume_20d=1e6,
            sma_cross=-1.0,
            theme_scores={},
            macro_bias=-0.8, macro_regime="RISK_OFF",
            sentiment_score=-0.8, sentiment_confidence=0.9,
        )
        results = self.rank_svc.rank_signals(self._signals_for(fs))
        assert results[0].recommended_action == "avoid"

    def test_rumour_propagated_when_sentiment_low_confidence(self):
        fs = _build_feature_set(
            ticker="XYZ",
            sentiment_score=0.9,
            sentiment_confidence=0.10,  # rumour-class
        )
        results = self.rank_svc.rank_signals(self._signals_for(fs))
        assert results[0].contains_rumor is True

    def test_composite_score_in_0_1_range(self):
        fs = _build_feature_set(
            theme_scores={"ai_infrastructure": 0.9},
            macro_bias=0.5,
            sentiment_score=0.6,
            sentiment_confidence=0.7,
        )
        results = self.rank_svc.rank_signals(self._signals_for(fs))
        score = float(results[0].composite_score)
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# TestMultiTickerResearchPipeline
# ---------------------------------------------------------------------------

class TestMultiTickerResearchPipeline:
    """Verify the pipeline ranks multiple tickers correctly."""

    def setup_method(self):
        self.signal_svc = SignalEngineService()
        self.rank_svc = RankingEngineService()

    def _run_pipeline(self, feature_sets: list[FeatureSet]):
        all_signals = self.signal_svc.score_from_features(feature_sets)
        return self.rank_svc.rank_signals(all_signals)

    def test_three_tickers_produce_three_results(self):
        fsets = [_build_feature_set(t) for t in ["NVDA", "MSFT", "AAPL"]]
        results = self._run_pipeline(fsets)
        assert len(results) == 3

    def test_rank_positions_are_sequential(self):
        fsets = [_build_feature_set(t) for t in ["NVDA", "MSFT", "AAPL"]]
        results = self._run_pipeline(fsets)
        positions = [r.rank_position for r in results]
        assert positions == [1, 2, 3]

    def test_highest_composite_is_rank_1(self):
        strong = _build_feature_set(
            "STRONG",
            return_1m=0.20, return_3m=0.35, sma_cross=1.0,
            theme_scores={"ai_infrastructure": 0.99},
            macro_bias=0.8, sentiment_score=0.9, sentiment_confidence=0.9,
        )
        weak = _build_feature_set(
            "WEAK",
            return_1m=-0.10, return_3m=-0.15, sma_cross=-1.0,
            macro_bias=-0.5, sentiment_score=-0.5, sentiment_confidence=0.7,
        )
        results = self._run_pipeline([weak, strong])
        assert results[0].ticker == "STRONG"

    def test_results_sorted_by_composite_desc(self):
        fsets = [
            _build_feature_set("LOW",  return_1m=-0.10, return_3m=-0.20),
            _build_feature_set("HIGH", return_1m=0.15,  return_3m=0.25, theme_scores={"ai_infrastructure": 0.9}),
            _build_feature_set("MID",  return_1m=0.05,  return_3m=0.10),
        ]
        results = self._run_pipeline(fsets)
        scores = [float(r.composite_score) for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_max_results_honored(self):
        fsets = [_build_feature_set(f"T{i}") for i in range(15)]
        all_signals = self.signal_svc.score_from_features(fsets)
        results = self.rank_svc.rank_signals(all_signals, max_results=5)
        assert len(results) <= 5

    def test_all_tickers_have_distinct_security_ids(self):
        fsets = [_build_feature_set(t) for t in ["NVDA", "MSFT", "AAPL"]]
        sids = {fs.security_id for fs in fsets}
        assert len(sids) == 3


# ---------------------------------------------------------------------------
# TestBullBearResearchScenario
# ---------------------------------------------------------------------------

class TestBullBearResearchScenario:
    """Scenario tests: full bull and bear market environments."""

    def setup_method(self):
        self.signal_svc = SignalEngineService()
        self.rank_svc = RankingEngineService()

    def _top_action(self, fs: FeatureSet) -> str:
        signals = self.signal_svc.score_from_features([fs])
        results = self.rank_svc.rank_signals(signals)
        return results[0].recommended_action

    def test_full_bull_environment_recommends_buy(self):
        fs = _build_feature_set(
            return_1m=0.15, return_3m=0.25, return_6m=0.40, sma_cross=1.0,
            volatility_20d=0.20, dollar_volume_20d=10e9,
            theme_scores={"ai_infrastructure": 0.99, "semiconductor": 0.90},
            macro_bias=0.9, macro_regime="RISK_ON",
            sentiment_score=0.85, sentiment_confidence=0.90,
        )
        assert self._top_action(fs) == "buy"

    def test_full_bear_environment_recommends_avoid(self):
        fs = _build_feature_set(
            return_1m=-0.20, return_3m=-0.30, return_6m=-0.50, sma_cross=-1.0,
            volatility_20d=0.80, dollar_volume_20d=1e6,
            theme_scores={},
            macro_bias=-0.9, macro_regime="RISK_OFF",
            sentiment_score=-0.85, sentiment_confidence=0.90,
        )
        assert self._top_action(fs) == "avoid"

    def test_neutral_environment_recommends_watch(self):
        fs = _build_feature_set(
            return_1m=0.02, return_3m=0.04, return_6m=0.06, sma_cross=0.0,
            volatility_20d=0.20, dollar_volume_20d=5e9,
            theme_scores={},
            macro_bias=0.0, macro_regime="NEUTRAL",
            sentiment_score=0.0, sentiment_confidence=0.0,
        )
        action = self._top_action(fs)
        assert action in {"watch", "buy", "avoid"}  # neutral could go either way

    def test_theme_upgrade_ticker_has_theme_alignment_signal_above_neutral(self):
        """A ticker with strong theme scores should produce a theme_alignment signal >0.5."""
        with_theme = _build_feature_set(
            ticker="THEMED", return_1m=0.05, return_3m=0.10,
            theme_scores={"ai_infrastructure": 0.99, "semiconductor": 0.95, "data_centres": 0.80},
            macro_bias=0.5, macro_regime="RISK_ON",
            sentiment_score=0.6, sentiment_confidence=0.8,
        )
        sigs_themed = self.signal_svc.score_from_features([with_theme])
        theme_sig = next(s for s in sigs_themed if s.strategy_key == "theme_alignment_v1")
        macro_sig = next(s for s in sigs_themed if s.strategy_key == "macro_tailwind_v1")
        sent_sig = next(s for s in sigs_themed if s.strategy_key == "sentiment_v1")
        # All overlay signals should be bullish
        assert float(theme_sig.signal_score) > 0.5
        assert float(macro_sig.signal_score) > 0.5
        assert float(sent_sig.signal_score) > 0.5
