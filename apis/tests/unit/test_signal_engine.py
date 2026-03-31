"""
Gate B — signal_engine tests.

Validates MomentumStrategy and SignalEngineService using synthetic feature
sets — no DB or network required.

Gate B criteria verified here:
  - outputs are explainable (explanation_dict.rationale always populated)
  - sources are tagged by reliability (source_reliability_tier on SignalOutput)
  - rumors are separated from verified facts (contains_rumor = False for OHLCV strategy)
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from services.feature_store.models import ComputedFeature, FeatureSet
from services.signal_engine.models import SignalOutput, SignalType
from services.signal_engine.strategies.momentum import MomentumStrategy


def _make_feature_set(
    ticker: str = "AAPL",
    r1m: float = 0.10,
    r3m: float = 0.22,
    r6m: float = 0.35,
    sma_cross: float = 1.0,
    vol: float = 0.25,
    dv: float = 5e8,
) -> FeatureSet:
    """Build a synthetic FeatureSet for testing."""
    sid = uuid.uuid4()
    now = dt.datetime.utcnow()
    features = [
        ComputedFeature("return_1m", "momentum", Decimal(str(r1m)), now),
        ComputedFeature("return_3m", "momentum", Decimal(str(r3m)), now),
        ComputedFeature("return_6m", "momentum", Decimal(str(r6m)), now),
        ComputedFeature("sma_cross_signal", "trend", Decimal(str(sma_cross)), now),
        ComputedFeature("volatility_20d", "risk", Decimal(str(vol)), now),
        ComputedFeature("dollar_volume_20d", "liquidity", Decimal(str(dv)), now),
        ComputedFeature("sma_20", "trend", Decimal("150.0"), now),
        ComputedFeature("sma_50", "trend", Decimal("145.0"), now),
        ComputedFeature("price_vs_sma20", "trend", Decimal("0.02"), now),
        ComputedFeature("price_vs_sma50", "trend", Decimal("0.04"), now),
    ]
    return FeatureSet(
        security_id=sid,
        ticker=ticker,
        as_of_timestamp=now,
        features=features,
    )


class TestMomentumStrategy:
    """MomentumStrategy unit tests."""

    def test_score_returns_signal_output(self) -> None:
        strategy = MomentumStrategy()
        fs = _make_feature_set()
        output = strategy.score(fs)
        assert isinstance(output, SignalOutput)

    def test_signal_type_is_momentum(self) -> None:
        strategy = MomentumStrategy()
        output = strategy.score(_make_feature_set())
        assert output.signal_type == SignalType.MOMENTUM.value

    def test_bullish_momentum_score_above_half(self) -> None:
        """Strong positive returns → signal_score > 0.5."""
        strategy = MomentumStrategy()
        output = strategy.score(_make_feature_set(r1m=0.18, r3m=0.28, r6m=0.45, sma_cross=1.0))
        assert output.signal_score is not None
        assert output.signal_score > Decimal("0.5")

    def test_bearish_momentum_score_below_half(self) -> None:
        """Strong negative returns → signal_score < 0.5."""
        strategy = MomentumStrategy()
        output = strategy.score(_make_feature_set(r1m=-0.18, r3m=-0.25, r6m=-0.40, sma_cross=-1.0))
        assert output.signal_score is not None
        assert output.signal_score < Decimal("0.5")

    def test_confidence_score_is_in_range(self) -> None:
        strategy = MomentumStrategy()
        output = strategy.score(_make_feature_set())
        assert output.confidence_score is not None
        assert Decimal("0") <= output.confidence_score <= Decimal("1")

    def test_explanation_dict_has_rationale(self) -> None:
        """Gate B: outputs are explainable — rationale must be populated."""
        strategy = MomentumStrategy()
        output = strategy.score(_make_feature_set())
        assert "rationale" in output.explanation_dict
        assert isinstance(output.explanation_dict["rationale"], str)
        assert len(output.explanation_dict["rationale"]) > 10

    def test_explanation_dict_has_driver_features(self) -> None:
        """Gate B: feature breakdown must be present."""
        strategy = MomentumStrategy()
        output = strategy.score(_make_feature_set())
        assert "driver_features" in output.explanation_dict
        assert isinstance(output.explanation_dict["driver_features"], dict)

    def test_source_reliability_tier_tagged(self) -> None:
        """Gate B: source must be tagged on every signal output."""
        strategy = MomentumStrategy()
        output = strategy.score(_make_feature_set())
        assert output.source_reliability_tier == "secondary_verified"

    def test_contains_rumor_is_false(self) -> None:
        """Gate B: OHLCV-only signals never contain rumour content."""
        strategy = MomentumStrategy()
        output = strategy.score(_make_feature_set())
        assert output.contains_rumor is False

    def test_horizon_classification_is_set(self) -> None:
        strategy = MomentumStrategy()
        output = strategy.score(_make_feature_set())
        assert output.horizon_classification is not None
        assert len(output.horizon_classification) > 0

    def test_score_with_all_none_features(self) -> None:
        """Pipeline that returns all-None features → neutral signal, no crash."""
        sid = uuid.uuid4()
        fs = FeatureSet(
            security_id=sid,
            ticker="EMPTY",
            as_of_timestamp=dt.datetime.utcnow(),
            features=[],
        )
        strategy = MomentumStrategy()
        output = strategy.score(fs)
        # Should not raise; signal_score should be close to 0.5 (neutral)
        assert output.signal_score is not None
        assert Decimal("0") <= output.signal_score <= Decimal("1")

    def test_liquidity_score_for_high_volume_stock(self) -> None:
        """Stocks with $1B+ daily dollar volume score near 1.0 liquidity."""
        strategy = MomentumStrategy()
        output = strategy.score(_make_feature_set(dv=1e9))
        assert output.liquidity_score is not None
        assert output.liquidity_score > Decimal("0.5")

    def test_liquidity_score_for_low_volume_stock(self) -> None:
        """Stocks at the $1M ADV floor score near 0.0 liquidity (log scale anchored at $1M)."""
        strategy = MomentumStrategy()
        # At exactly $1M ADV the formula yields 0.0 (floor of the scale)
        output = strategy.score(_make_feature_set(dv=1e6))
        assert output.liquidity_score is not None
        assert output.liquidity_score <= Decimal("0.05")


class TestSignalEngineService:
    """SignalEngineService unit tests — no DB access."""

    def test_score_from_features_returns_outputs(self) -> None:
        from services.signal_engine.service import SignalEngineService

        service = SignalEngineService()
        feature_sets = [_make_feature_set("AAPL"), _make_feature_set("MSFT")]
        outputs = service.score_from_features(feature_sets)
        # One output per (feature_set × strategy); default is now 4 strategies
        assert len(outputs) == len(feature_sets) * len(service._strategies)

    def test_score_from_features_all_have_explanation(self) -> None:
        """Gate B: every signal output has explanation content."""
        from services.signal_engine.service import SignalEngineService

        service = SignalEngineService()
        outputs = service.score_from_features([_make_feature_set("NVDA")])
        for output in outputs:
            assert "rationale" in output.explanation_dict
            assert output.source_reliability_tier != ""

    def test_score_from_features_no_rumor(self) -> None:
        """Gate B: no rumour content in OHLCV-only signals."""
        from services.signal_engine.service import SignalEngineService

        service = SignalEngineService()
        outputs = service.score_from_features([_make_feature_set("TSLA")])
        assert all(not o.contains_rumor for o in outputs)
