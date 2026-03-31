"""
Phase 21 unit tests — Multi-Strategy Signal Engine Enhancement.

Coverage:
  - TestFeatureSetOverlayFields        (8 tests)
  - TestSignalTypeEnum                 (5 tests)
  - TestThemeAlignmentStrategyBasic    (10 tests)
  - TestThemeAlignmentStrategyScoring  (8 tests)
  - TestMacroTailwindStrategyBasic     (10 tests)
  - TestMacroTailwindStrategyRegimes   (8 tests)
  - TestSentimentStrategyBasic         (10 tests)
  - TestSentimentStrategyReliability   (8 tests)
  - TestSentimentStrategyRumourFlag    (5 tests)
  - TestStrategiesInit                 (4 tests)
  - TestSignalEngineServiceDefaults    (6 tests)
  - TestMultiStrategyScoring           (8 tests)
  - TestRankingWithMultipleStrategies  (6 tests)
  - TestPhase21Integration             (6 tests)

Total target: ≥ 102 tests
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from services.feature_store.models import ComputedFeature, FeatureSet
from services.signal_engine.models import HorizonClassification, SignalType
from services.signal_engine.strategies.macro_tailwind import MacroTailwindStrategy
from services.signal_engine.strategies.momentum import MomentumStrategy
from services.signal_engine.strategies.sentiment import SentimentStrategy
from services.signal_engine.strategies.theme_alignment import ThemeAlignmentStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_feature_set(
    ticker: str = "NVDA",
    return_1m: float = 0.05,
    return_3m: float = 0.12,
    return_6m: float = 0.20,
    volatility_20d: float = 0.30,
    dollar_volume_20d: float = 5e9,
    sma_cross_signal: float = 1.0,
    theme_scores: dict | None = None,
    macro_bias: float = 0.0,
    macro_regime: str = "NEUTRAL",
    sentiment_score: float = 0.0,
    sentiment_confidence: float = 0.0,
) -> FeatureSet:
    security_id = uuid.uuid4()
    features = [
        ComputedFeature("return_1m", "momentum", Decimal(str(return_1m)), dt.datetime.utcnow()),
        ComputedFeature("return_3m", "momentum", Decimal(str(return_3m)), dt.datetime.utcnow()),
        ComputedFeature("return_6m", "momentum", Decimal(str(return_6m)), dt.datetime.utcnow()),
        ComputedFeature("volatility_20d", "risk", Decimal(str(volatility_20d)), dt.datetime.utcnow()),
        ComputedFeature("dollar_volume_20d", "liquidity", Decimal(str(dollar_volume_20d)), dt.datetime.utcnow()),
        ComputedFeature("sma_cross_signal", "trend", Decimal(str(sma_cross_signal)), dt.datetime.utcnow()),
    ]
    return FeatureSet(
        security_id=security_id,
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
# TestFeatureSetOverlayFields
# ---------------------------------------------------------------------------

class TestFeatureSetOverlayFields:
    def test_default_theme_scores_empty_dict(self):
        fs = _make_feature_set()
        assert fs.theme_scores == {}

    def test_default_macro_bias_zero(self):
        fs = _make_feature_set()
        assert fs.macro_bias == 0.0

    def test_default_macro_regime_neutral(self):
        fs = _make_feature_set()
        assert fs.macro_regime == "NEUTRAL"

    def test_default_sentiment_score_zero(self):
        fs = _make_feature_set()
        assert fs.sentiment_score == 0.0

    def test_default_sentiment_confidence_zero(self):
        fs = _make_feature_set()
        assert fs.sentiment_confidence == 0.0

    def test_custom_theme_scores_set(self):
        fs = _make_feature_set(theme_scores={"ai_infrastructure": 0.9, "semiconductor": 0.85})
        assert fs.theme_scores["ai_infrastructure"] == 0.9
        assert fs.theme_scores["semiconductor"] == 0.85

    def test_custom_macro_bias(self):
        fs = _make_feature_set(macro_bias=0.6, macro_regime="RISK_ON")
        assert fs.macro_bias == 0.6
        assert fs.macro_regime == "RISK_ON"

    def test_custom_sentiment_fields(self):
        fs = _make_feature_set(sentiment_score=0.8, sentiment_confidence=0.75)
        assert fs.sentiment_score == 0.8
        assert fs.sentiment_confidence == 0.75

    def test_feature_set_backward_compatible_get(self):
        fs = _make_feature_set(return_1m=0.03)
        val = fs.get("return_1m")
        assert val == Decimal("0.03")

    def test_overlay_fields_independent_of_features_list(self):
        """Adding overlay fields does not affect FEATURE_KEYS or baseline get()."""
        from services.feature_store.models import FEATURE_KEYS
        assert "theme_scores" not in FEATURE_KEYS
        assert "macro_bias" not in FEATURE_KEYS


# ---------------------------------------------------------------------------
# TestSignalTypeEnum
# ---------------------------------------------------------------------------

class TestSignalTypeEnum:
    def test_momentum_value(self):
        assert SignalType.MOMENTUM.value == "momentum"

    def test_sentiment_value(self):
        assert SignalType.SENTIMENT.value == "sentiment"

    def test_theme_alignment_value(self):
        assert SignalType.THEME_ALIGNMENT.value == "theme_alignment"

    def test_macro_tailwind_value(self):
        assert SignalType.MACRO_TAILWIND.value == "macro_tailwind"

    def test_all_original_values_preserved(self):
        original = {"momentum", "valuation", "quality", "sentiment", "macro", "composite"}
        values = {st.value for st in SignalType}
        assert original.issubset(values)


# ---------------------------------------------------------------------------
# TestThemeAlignmentStrategyBasic
# ---------------------------------------------------------------------------

class TestThemeAlignmentStrategyBasic:
    def setup_method(self):
        self.strategy = ThemeAlignmentStrategy()

    def test_strategy_key(self):
        assert self.strategy.STRATEGY_KEY == "theme_alignment_v1"

    def test_strategy_family(self):
        assert self.strategy.STRATEGY_FAMILY == "theme_alignment"

    def test_config_version(self):
        assert self.strategy.CONFIG_VERSION == "1.0"

    def test_empty_theme_scores_returns_neutral(self):
        fs = _make_feature_set(ticker="AAPL", theme_scores={})
        out = self.strategy.score(fs)
        assert float(out.signal_score) == 0.5

    def test_empty_theme_scores_zero_confidence(self):
        fs = _make_feature_set(ticker="AAPL", theme_scores={})
        out = self.strategy.score(fs)
        assert float(out.confidence_score) == 0.0

    def test_returns_signal_output_type(self):
        from services.signal_engine.models import SignalOutput
        fs = _make_feature_set()
        out = self.strategy.score(fs)
        assert isinstance(out, SignalOutput)

    def test_signal_type_is_theme_alignment(self):
        fs = _make_feature_set()
        out = self.strategy.score(fs)
        assert out.signal_type == "theme_alignment"

    def test_contains_rumor_always_false(self):
        fs = _make_feature_set(theme_scores={"ai_infrastructure": 0.9})
        out = self.strategy.score(fs)
        assert out.contains_rumor is False

    def test_reliability_tier_secondary_verified(self):
        fs = _make_feature_set(theme_scores={"semiconductor": 0.8})
        out = self.strategy.score(fs)
        assert out.source_reliability_tier == "secondary_verified"

    def test_horizon_positional(self):
        fs = _make_feature_set(theme_scores={"ai_infrastructure": 0.7})
        out = self.strategy.score(fs)
        assert out.horizon_classification == HorizonClassification.POSITIONAL.value


# ---------------------------------------------------------------------------
# TestThemeAlignmentStrategyScoring
# ---------------------------------------------------------------------------

class TestThemeAlignmentStrategyScoring:
    def setup_method(self):
        self.strategy = ThemeAlignmentStrategy()

    def test_single_high_theme_bullish(self):
        fs = _make_feature_set(theme_scores={"ai_infrastructure": 0.99})
        out = self.strategy.score(fs)
        assert float(out.signal_score) > 0.5

    def test_single_low_theme_score_approaches_neutral(self):
        fs = _make_feature_set(theme_scores={"ai_infrastructure": 0.1})
        out = self.strategy.score(fs)
        assert float(out.signal_score) < 0.5

    def test_multiple_themes_boost_confidence(self):
        fs = _make_feature_set(theme_scores={
            "ai_infrastructure": 0.85,
            "semiconductor": 0.90,
            "cloud_computing": 0.75,
        })
        out = self.strategy.score(fs)
        assert float(out.confidence_score) >= 1.0

    def test_two_themes_partial_confidence(self):
        fs = _make_feature_set(theme_scores={
            "ai_infrastructure": 0.80,
            "semiconductor": 0.85,
        })
        out = self.strategy.score(fs)
        # 2 / 3 = 0.666...
        assert 0.60 <= float(out.confidence_score) <= 0.70

    def test_explanation_dict_has_active_themes(self):
        fs = _make_feature_set(theme_scores={"ai_infrastructure": 0.99})
        out = self.strategy.score(fs)
        assert "active_themes" in out.explanation_dict
        assert "ai_infrastructure" in out.explanation_dict["active_themes"]

    def test_explanation_dict_has_rationale(self):
        fs = _make_feature_set(ticker="NVDA", theme_scores={"ai_infrastructure": 0.99})
        out = self.strategy.score(fs)
        assert "NVDA" in out.explanation_dict["rationale"]

    def test_below_threshold_theme_ignored(self):
        fs = _make_feature_set(theme_scores={"ai_infrastructure": 0.01})
        out = self.strategy.score(fs)
        # 0.01 < _MIN_THEME_SCORE=0.05 → treated as empty
        assert float(out.signal_score) == 0.5
        assert float(out.confidence_score) == 0.0

    def test_mixed_above_below_threshold(self):
        fs = _make_feature_set(theme_scores={
            "ai_infrastructure": 0.90,
            "ignored_theme": 0.01,
        })
        out = self.strategy.score(fs)
        # Only one theme counts
        assert float(out.confidence_score) < 0.67


# ---------------------------------------------------------------------------
# TestMacroTailwindStrategyBasic
# ---------------------------------------------------------------------------

class TestMacroTailwindStrategyBasic:
    def setup_method(self):
        self.strategy = MacroTailwindStrategy()

    def test_strategy_key(self):
        assert self.strategy.STRATEGY_KEY == "macro_tailwind_v1"

    def test_strategy_family(self):
        assert self.strategy.STRATEGY_FAMILY == "macro_tailwind"

    def test_config_version(self):
        assert self.strategy.CONFIG_VERSION == "1.0"

    def test_zero_bias_neutral_regime_returns_neutral(self):
        fs = _make_feature_set(macro_bias=0.0, macro_regime="NEUTRAL")
        out = self.strategy.score(fs)
        assert float(out.signal_score) == pytest.approx(0.5, abs=0.01)

    def test_zero_bias_neutral_confidence_zero(self):
        fs = _make_feature_set(macro_bias=0.0, macro_regime="NEUTRAL")
        out = self.strategy.score(fs)
        assert float(out.confidence_score) == 0.0

    def test_positive_bias_bullish_signal(self):
        fs = _make_feature_set(macro_bias=0.8, macro_regime="NEUTRAL")
        out = self.strategy.score(fs)
        assert float(out.signal_score) > 0.5

    def test_negative_bias_bearish_signal(self):
        fs = _make_feature_set(macro_bias=-0.8, macro_regime="NEUTRAL")
        out = self.strategy.score(fs)
        assert float(out.signal_score) < 0.5

    def test_signal_type_macro_tailwind(self):
        fs = _make_feature_set(macro_bias=0.5)
        out = self.strategy.score(fs)
        assert out.signal_type == "macro_tailwind"

    def test_contains_rumor_always_false(self):
        fs = _make_feature_set(macro_bias=0.9, macro_regime="RISK_ON")
        out = self.strategy.score(fs)
        assert out.contains_rumor is False

    def test_reliability_secondary_verified(self):
        fs = _make_feature_set(macro_bias=0.5)
        out = self.strategy.score(fs)
        assert out.source_reliability_tier == "secondary_verified"

    def test_horizon_positional(self):
        fs = _make_feature_set(macro_bias=0.4)
        out = self.strategy.score(fs)
        assert out.horizon_classification == HorizonClassification.POSITIONAL.value

    def test_explanation_has_bias_raw(self):
        fs = _make_feature_set(macro_bias=0.6)
        out = self.strategy.score(fs)
        assert "macro_bias_raw" in out.explanation_dict

    def test_explanation_has_regime(self):
        fs = _make_feature_set(macro_bias=0.6, macro_regime="RISK_ON")
        out = self.strategy.score(fs)
        assert out.explanation_dict["macro_regime"] == "RISK_ON"


# ---------------------------------------------------------------------------
# TestMacroTailwindStrategyRegimes
# ---------------------------------------------------------------------------

class TestMacroTailwindStrategyRegimes:
    def setup_method(self):
        self.strategy = MacroTailwindStrategy()

    def test_risk_on_boosts_score(self):
        neutral = _make_feature_set(macro_bias=0.5, macro_regime="NEUTRAL")
        risk_on = _make_feature_set(macro_bias=0.5, macro_regime="RISK_ON")
        out_n = self.strategy.score(neutral)
        out_r = self.strategy.score(risk_on)
        assert float(out_r.signal_score) > float(out_n.signal_score)

    def test_risk_off_lowers_score(self):
        neutral = _make_feature_set(macro_bias=0.5, macro_regime="NEUTRAL")
        risk_off = _make_feature_set(macro_bias=0.5, macro_regime="RISK_OFF")
        out_n = self.strategy.score(neutral)
        out_r = self.strategy.score(risk_off)
        assert float(out_r.signal_score) < float(out_n.signal_score)

    def test_stagflation_lowers_score(self):
        neutral = _make_feature_set(macro_bias=0.5, macro_regime="NEUTRAL")
        stagflation = _make_feature_set(macro_bias=0.5, macro_regime="STAGFLATION")
        out_n = self.strategy.score(neutral)
        out_s = self.strategy.score(stagflation)
        assert float(out_s.signal_score) < float(out_n.signal_score)

    def test_bias_plus_one_risk_on_clamped_at_one(self):
        fs = _make_feature_set(macro_bias=1.0, macro_regime="RISK_ON")
        out = self.strategy.score(fs)
        assert float(out.signal_score) <= 1.0

    def test_bias_minus_one_risk_off_clamped_at_zero(self):
        fs = _make_feature_set(macro_bias=-1.0, macro_regime="RISK_OFF")
        out = self.strategy.score(fs)
        assert float(out.signal_score) >= 0.0

    def test_confidence_equals_abs_bias(self):
        fs = _make_feature_set(macro_bias=0.7)
        out = self.strategy.score(fs)
        assert float(out.confidence_score) == pytest.approx(0.7, abs=0.001)

    def test_full_positive_bias_near_max(self):
        fs = _make_feature_set(macro_bias=1.0, macro_regime="NEUTRAL")
        out = self.strategy.score(fs)
        assert float(out.signal_score) == pytest.approx(1.0, abs=0.01)

    def test_full_negative_bias_near_zero(self):
        fs = _make_feature_set(macro_bias=-1.0, macro_regime="NEUTRAL")
        out = self.strategy.score(fs)
        assert float(out.signal_score) == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# TestSentimentStrategyBasic
# ---------------------------------------------------------------------------

class TestSentimentStrategyBasic:
    def setup_method(self):
        self.strategy = SentimentStrategy()

    def test_strategy_key(self):
        assert self.strategy.STRATEGY_KEY == "sentiment_v1"

    def test_strategy_family(self):
        assert self.strategy.STRATEGY_FAMILY == "sentiment"

    def test_config_version(self):
        assert self.strategy.CONFIG_VERSION == "1.0"

    def test_zero_confidence_returns_neutral_score(self):
        fs = _make_feature_set(sentiment_score=0.9, sentiment_confidence=0.0)
        out = self.strategy.score(fs)
        assert float(out.signal_score) == pytest.approx(0.5, abs=0.01)

    def test_zero_confidence_zero_confidence_score(self):
        fs = _make_feature_set(sentiment_score=0.9, sentiment_confidence=0.0)
        out = self.strategy.score(fs)
        assert float(out.confidence_score) == 0.0

    def test_positive_sentiment_high_confidence_bullish(self):
        fs = _make_feature_set(sentiment_score=0.8, sentiment_confidence=0.9)
        out = self.strategy.score(fs)
        assert float(out.signal_score) > 0.5

    def test_negative_sentiment_high_confidence_bearish(self):
        fs = _make_feature_set(sentiment_score=-0.8, sentiment_confidence=0.9)
        out = self.strategy.score(fs)
        assert float(out.signal_score) < 0.5

    def test_signal_type_sentiment(self):
        fs = _make_feature_set(sentiment_score=0.5, sentiment_confidence=0.8)
        out = self.strategy.score(fs)
        assert out.signal_type == "sentiment"

    def test_explanation_has_rationale(self):
        fs = _make_feature_set(ticker="SPY", sentiment_score=0.5, sentiment_confidence=0.8)
        out = self.strategy.score(fs)
        assert "SPY" in out.explanation_dict["rationale"]

    def test_explanation_has_raw_sentiment(self):
        fs = _make_feature_set(sentiment_score=0.6, sentiment_confidence=0.7)
        out = self.strategy.score(fs)
        assert "raw_sentiment_score" in out.explanation_dict

    def test_horizon_swing(self):
        fs = _make_feature_set(sentiment_score=0.5, sentiment_confidence=0.8)
        out = self.strategy.score(fs)
        assert out.horizon_classification == HorizonClassification.SWING.value

    def test_confidence_score_matches_input_confidence(self):
        fs = _make_feature_set(sentiment_score=0.4, sentiment_confidence=0.65)
        out = self.strategy.score(fs)
        assert float(out.confidence_score) == pytest.approx(0.65, abs=0.001)

    def test_no_sentiment_data_neutral(self):
        fs = _make_feature_set()
        out = self.strategy.score(fs)
        assert float(out.signal_score) == pytest.approx(0.5, abs=0.01)


# ---------------------------------------------------------------------------
# TestSentimentStrategyReliability
# ---------------------------------------------------------------------------

class TestSentimentStrategyReliability:
    def setup_method(self):
        self.strategy = SentimentStrategy()

    def test_high_confidence_primary_verified(self):
        fs = _make_feature_set(sentiment_score=0.5, sentiment_confidence=0.75)
        out = self.strategy.score(fs)
        assert out.source_reliability_tier == "primary_verified"

    def test_medium_confidence_secondary_verified(self):
        fs = _make_feature_set(sentiment_score=0.5, sentiment_confidence=0.50)
        out = self.strategy.score(fs)
        assert out.source_reliability_tier == "secondary_verified"

    def test_low_confidence_unverified(self):
        fs = _make_feature_set(sentiment_score=0.5, sentiment_confidence=0.15)
        out = self.strategy.score(fs)
        assert out.source_reliability_tier == "unverified"

    def test_zero_confidence_unverified(self):
        fs = _make_feature_set(sentiment_score=0.5, sentiment_confidence=0.0)
        out = self.strategy.score(fs)
        assert out.source_reliability_tier == "unverified"

    def test_exactly_high_threshold_primary(self):
        fs = _make_feature_set(sentiment_score=0.5, sentiment_confidence=0.70)
        out = self.strategy.score(fs)
        assert out.source_reliability_tier == "primary_verified"

    def test_exactly_medium_threshold_secondary(self):
        fs = _make_feature_set(sentiment_score=0.5, sentiment_confidence=0.30)
        out = self.strategy.score(fs)
        assert out.source_reliability_tier == "secondary_verified"

    def test_signal_weighted_towards_neutral_at_low_confidence(self):
        fs_hi = _make_feature_set(sentiment_score=0.8, sentiment_confidence=1.0)
        fs_lo = _make_feature_set(sentiment_score=0.8, sentiment_confidence=0.25)
        out_hi = self.strategy.score(fs_hi)
        out_lo = self.strategy.score(fs_lo)
        # low confidence → score closer to neutral
        assert abs(float(out_lo.signal_score) - 0.5) < abs(float(out_hi.signal_score) - 0.5)

    def test_full_positive_high_confidence_approaches_max(self):
        fs = _make_feature_set(sentiment_score=1.0, sentiment_confidence=1.0)
        out = self.strategy.score(fs)
        assert float(out.signal_score) > 0.9


# ---------------------------------------------------------------------------
# TestSentimentStrategyRumourFlag
# ---------------------------------------------------------------------------

class TestSentimentStrategyRumourFlag:
    def setup_method(self):
        self.strategy = SentimentStrategy()

    def test_low_confidence_high_sentiment_is_rumour(self):
        fs = _make_feature_set(sentiment_score=0.8, sentiment_confidence=0.15)
        out = self.strategy.score(fs)
        assert out.contains_rumor is True

    def test_high_confidence_not_rumour(self):
        fs = _make_feature_set(sentiment_score=0.8, sentiment_confidence=0.80)
        out = self.strategy.score(fs)
        assert out.contains_rumor is False

    def test_medium_confidence_not_rumour(self):
        fs = _make_feature_set(sentiment_score=0.8, sentiment_confidence=0.40)
        out = self.strategy.score(fs)
        assert out.contains_rumor is False

    def test_zero_sentiment_not_rumour_even_low_confidence(self):
        fs = _make_feature_set(sentiment_score=0.0, sentiment_confidence=0.10)
        out = self.strategy.score(fs)
        assert out.contains_rumor is False

    def test_negative_sentiment_low_confidence_is_rumour(self):
        fs = _make_feature_set(sentiment_score=-0.7, sentiment_confidence=0.10)
        out = self.strategy.score(fs)
        assert out.contains_rumor is True


# ---------------------------------------------------------------------------
# TestStrategiesInit
# ---------------------------------------------------------------------------

class TestStrategiesInit:
    def test_import_all_strategies(self):
        from services.signal_engine.strategies import (
            MacroTailwindStrategy,
            MomentumStrategy,
            SentimentStrategy,
            ThemeAlignmentStrategy,
        )
        assert MomentumStrategy is not None
        assert ThemeAlignmentStrategy is not None
        assert MacroTailwindStrategy is not None
        assert SentimentStrategy is not None

    def test_all_exported_in_all(self):
        from services.signal_engine import strategies
        assert "MomentumStrategy" in strategies.__all__
        assert "ThemeAlignmentStrategy" in strategies.__all__
        assert "MacroTailwindStrategy" in strategies.__all__
        assert "SentimentStrategy" in strategies.__all__

    def test_all_strategies_have_score_method(self):
        from services.signal_engine.strategies import (
            MacroTailwindStrategy,
            MomentumStrategy,
            SentimentStrategy,
            ThemeAlignmentStrategy,
        )
        for cls in [MomentumStrategy, ThemeAlignmentStrategy, MacroTailwindStrategy, SentimentStrategy]:
            inst = cls()
            assert callable(getattr(inst, "score", None)), f"{cls.__name__} missing .score()"

    def test_all_strategies_have_required_class_attrs(self):
        from services.signal_engine.strategies import (
            MacroTailwindStrategy,
            MomentumStrategy,
            SentimentStrategy,
            ThemeAlignmentStrategy,
        )
        for cls in [MomentumStrategy, ThemeAlignmentStrategy, MacroTailwindStrategy, SentimentStrategy]:
            assert hasattr(cls, "STRATEGY_KEY"), f"{cls.__name__} missing STRATEGY_KEY"
            assert hasattr(cls, "STRATEGY_FAMILY"), f"{cls.__name__} missing STRATEGY_FAMILY"
            assert hasattr(cls, "CONFIG_VERSION"), f"{cls.__name__} missing CONFIG_VERSION"


# ---------------------------------------------------------------------------
# TestSignalEngineServiceDefaults
# ---------------------------------------------------------------------------

class TestSignalEngineServiceDefaults:
    def test_default_strategies_count_is_four(self):
        from services.signal_engine.service import SignalEngineService
        svc = SignalEngineService()
        assert len(svc._strategies) == 5

    def test_default_includes_momentum(self):
        from services.signal_engine.service import SignalEngineService
        svc = SignalEngineService()
        keys = [s.STRATEGY_KEY for s in svc._strategies]
        assert "momentum_v1" in keys

    def test_default_includes_theme_alignment(self):
        from services.signal_engine.service import SignalEngineService
        svc = SignalEngineService()
        keys = [s.STRATEGY_KEY for s in svc._strategies]
        assert "theme_alignment_v1" in keys

    def test_default_includes_macro_tailwind(self):
        from services.signal_engine.service import SignalEngineService
        svc = SignalEngineService()
        keys = [s.STRATEGY_KEY for s in svc._strategies]
        assert "macro_tailwind_v1" in keys

    def test_default_includes_sentiment(self):
        from services.signal_engine.service import SignalEngineService
        svc = SignalEngineService()
        keys = [s.STRATEGY_KEY for s in svc._strategies]
        assert "sentiment_v1" in keys

    def test_custom_strategies_override_default(self):
        from services.signal_engine.service import SignalEngineService
        svc = SignalEngineService(strategies=[MomentumStrategy()])
        assert len(svc._strategies) == 1
        assert svc._strategies[0].STRATEGY_KEY == "momentum_v1"


# ---------------------------------------------------------------------------
# TestMultiStrategyScoring
# ---------------------------------------------------------------------------

class TestMultiStrategyScoring:
    """Verify all 4 strategies produce valid output for the same FeatureSet."""

    def setup_method(self):
        self.strategies = [
            MomentumStrategy(),
            ThemeAlignmentStrategy(),
            MacroTailwindStrategy(),
            SentimentStrategy(),
        ]
        self.fs = _make_feature_set(
            ticker="NVDA",
            theme_scores={"ai_infrastructure": 0.99, "semiconductor": 0.95},
            macro_bias=0.6,
            macro_regime="RISK_ON",
            sentiment_score=0.7,
            sentiment_confidence=0.80,
        )

    def test_all_strategies_produce_output(self):
        for strat in self.strategies:
            out = strat.score(self.fs)
            assert out is not None

    def test_all_outputs_have_valid_signal_score(self):
        for strat in self.strategies:
            out = strat.score(self.fs)
            score = float(out.signal_score)
            assert 0.0 <= score <= 1.0, f"{strat.STRATEGY_KEY}: score {score} out of range"

    def test_all_outputs_correct_ticker(self):
        for strat in self.strategies:
            out = strat.score(self.fs)
            assert out.ticker == "NVDA"

    def test_all_outputs_correct_security_id(self):
        for strat in self.strategies:
            out = strat.score(self.fs)
            assert out.security_id == self.fs.security_id

    def test_all_outputs_have_explanation_with_rationale(self):
        for strat in self.strategies:
            out = strat.score(self.fs)
            assert "rationale" in out.explanation_dict, f"{strat.STRATEGY_KEY} missing rationale"

    def test_all_outputs_have_strategy_key_in_explanation(self):
        for strat in self.strategies:
            out = strat.score(self.fs)
            assert "strategy_key" in out.explanation_dict

    def test_bullish_environment_all_above_neutral(self):
        """With positive momentum, themes, macro, and sentiment, all strategies give >0.5."""
        for strat in self.strategies:
            out = strat.score(self.fs)
            # Note: zero-bias neutral strategies still give 0.5, not below
            assert float(out.signal_score) >= 0.5, (
                f"{strat.STRATEGY_KEY}: expected ≥0.5, got {float(out.signal_score):.4f}"
            )

    def test_no_strategy_exceeds_1_or_goes_below_0(self):
        for strat in self.strategies:
            out = strat.score(self.fs)
            assert 0.0 <= float(out.signal_score) <= 1.0
            assert 0.0 <= float(out.confidence_score) <= 1.0


# ---------------------------------------------------------------------------
# TestRankingWithMultipleStrategies
# ---------------------------------------------------------------------------

class TestRankingWithMultipleStrategies:
    """Verify ranking engine handles multi-strategy signal lists correctly."""

    def _build_signals(self, ticker: str = "NVDA") -> list:
        security_id = uuid.uuid4()
        fs = _make_feature_set(
            ticker=ticker,
            theme_scores={"ai_infrastructure": 0.99},
            macro_bias=0.5,
            macro_regime="RISK_ON",
            sentiment_score=0.6,
            sentiment_confidence=0.75,
        )
        fs.security_id = security_id
        strategies = [
            MomentumStrategy(),
            ThemeAlignmentStrategy(),
            MacroTailwindStrategy(),
            SentimentStrategy(),
        ]
        return [s.score(fs) for s in strategies]

    def test_ranking_engine_accepts_multi_strategy_list(self):
        from services.ranking_engine.service import RankingEngineService
        svc = RankingEngineService()
        signals = self._build_signals()
        results = svc.rank_signals(signals)
        assert len(results) == 1

    def test_ranked_result_has_contributing_signals(self):
        from services.ranking_engine.service import RankingEngineService
        svc = RankingEngineService()
        signals = self._build_signals()
        results = svc.rank_signals(signals)
        assert len(results[0].contributing_signals) == 4

    def test_ranked_result_ticker_correct(self):
        from services.ranking_engine.service import RankingEngineService
        svc = RankingEngineService()
        signals = self._build_signals("MSFT")
        results = svc.rank_signals(signals)
        assert results[0].ticker == "MSFT"

    def test_composite_score_in_range(self):
        from services.ranking_engine.service import RankingEngineService
        svc = RankingEngineService()
        signals = self._build_signals()
        results = svc.rank_signals(signals)
        score = float(results[0].composite_score)
        assert 0.0 <= score <= 1.0

    def test_multiple_tickers_ranked_correctly(self):
        from services.ranking_engine.service import RankingEngineService
        svc = RankingEngineService()
        nvda_signals = self._build_signals("NVDA")
        bearish_fs = _make_feature_set(
            ticker="WEAK",
            return_1m=-0.10,
            return_3m=-0.20,
            return_6m=-0.30,
            theme_scores={},
            macro_bias=-0.6,
            sentiment_score=-0.7,
            sentiment_confidence=0.8,
        )
        bearish_sec = uuid.uuid4()
        bearish_fs.security_id = bearish_sec
        bearish_signals = [s.score(bearish_fs) for s in [
            MomentumStrategy(), ThemeAlignmentStrategy(),
            MacroTailwindStrategy(), SentimentStrategy()
        ]]
        all_signals = nvda_signals + bearish_signals
        results = svc.rank_signals(all_signals, max_results=2)
        assert len(results) == 2
        # NVDA should rank above bearish
        assert results[0].ticker == "NVDA"

    def test_rumour_flag_propagated_from_sentiment_strategy(self):
        from services.ranking_engine.service import RankingEngineService
        svc = RankingEngineService()
        fs = _make_feature_set(
            ticker="XYZ",
            sentiment_score=0.9,
            sentiment_confidence=0.10,  # low confidence → rumour
        )
        signals = [SentimentStrategy().score(fs)]
        results = svc.rank_signals(signals)
        assert results[0].contains_rumor is True


# ---------------------------------------------------------------------------
# TestPhase21Integration
# ---------------------------------------------------------------------------

class TestPhase21Integration:
    """End-to-end verifications of the full new signal stack."""

    def test_feature_set_full_overlay_roundtrip(self):
        """FeatureSet with overlay fields can be constructed and read back."""
        fs = FeatureSet(
            security_id=uuid.uuid4(),
            ticker="AMD",
            as_of_timestamp=dt.datetime.utcnow(),
            theme_scores={"semiconductor": 0.88, "ai_infrastructure": 0.82},
            macro_bias=0.4,
            macro_regime="RISK_ON",
            sentiment_score=0.5,
            sentiment_confidence=0.65,
        )
        assert fs.theme_scores["semiconductor"] == pytest.approx(0.88)
        assert fs.macro_bias == pytest.approx(0.4)
        assert fs.macro_regime == "RISK_ON"
        assert fs.sentiment_score == pytest.approx(0.5)
        assert fs.sentiment_confidence == pytest.approx(0.65)

    def test_all_four_strategy_keys_distinct(self):
        keys = {
            MomentumStrategy.STRATEGY_KEY,
            ThemeAlignmentStrategy.STRATEGY_KEY,
            MacroTailwindStrategy.STRATEGY_KEY,
            SentimentStrategy.STRATEGY_KEY,
        }
        assert len(keys) == 4

    def test_all_four_signal_types_distinct(self):
        """Each strategy emits a distinct signal_type value."""
        fs = _make_feature_set(
            theme_scores={"ai_infrastructure": 0.9},
            macro_bias=0.5,
            sentiment_score=0.6,
            sentiment_confidence=0.7,
        )
        types = {
            MomentumStrategy().score(fs).signal_type,
            ThemeAlignmentStrategy().score(fs).signal_type,
            MacroTailwindStrategy().score(fs).signal_type,
            SentimentStrategy().score(fs).signal_type,
        }
        assert len(types) == 4

    def test_bear_case_all_strategies_below_neutral(self):
        """All strategies should score below 0.5 in a fully bearish environment."""
        fs = _make_feature_set(
            ticker="BEAR",
            return_1m=-0.15,
            return_3m=-0.25,
            return_6m=-0.40,
            theme_scores={},
            macro_bias=-0.8,
            macro_regime="RISK_OFF",
            sentiment_score=-0.9,
            sentiment_confidence=0.85,
        )
        strats = [MomentumStrategy(), MacroTailwindStrategy(), SentimentStrategy()]
        for strat in strats:
            out = strat.score(fs)
            assert float(out.signal_score) < 0.5, (
                f"{strat.STRATEGY_KEY}: expected <0.5, got {float(out.signal_score):.4f}"
            )

    def test_signal_engine_service_score_from_features_runs_all_strategies(self):
        """SignalEngineService.score_from_features calls all 4 strategies."""
        from services.signal_engine.service import SignalEngineService
        svc = SignalEngineService()
        fs = _make_feature_set(
            theme_scores={"ai_infrastructure": 0.9},
            macro_bias=0.5,
            sentiment_score=0.6,
            sentiment_confidence=0.8,
        )
        outputs = svc.score_from_features([fs])
        assert len(outputs) == 5  # 5 strategies now (Phase 29 added ValuationStrategy)
        keys = {o.strategy_key for o in outputs}
        assert "momentum_v1" in keys
        assert "theme_alignment_v1" in keys
        assert "macro_tailwind_v1" in keys
        assert "sentiment_v1" in keys

    def test_signal_engine_service_score_from_features_all_valid(self):
        from services.signal_engine.service import SignalEngineService
        svc = SignalEngineService()
        fs = _make_feature_set()
        outputs = svc.score_from_features([fs])
        for out in outputs:
            assert 0.0 <= float(out.signal_score) <= 1.0
