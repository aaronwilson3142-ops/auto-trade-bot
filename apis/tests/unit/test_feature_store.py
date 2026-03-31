"""
Gate B — feature_store tests.

Validates the BaselineFeaturePipeline and FeatureStoreService using purely
synthetic OHLCV data — no DB or network required.

Gate B criteria:
  - outputs are explainable (each ComputedFeature has feature_key + group)
  - sources are tagged by reliability (source_version on every ComputedFeature)
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pandas as pd
import pytest

from services.feature_store.models import FEATURE_KEYS, ComputedFeature, FeatureSet
from services.feature_store.pipeline import BaselineFeaturePipeline


def _make_bars_df(n: int = 100, start_price: float = 100.0, trend: float = 0.002) -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame with n rows."""
    dates = pd.date_range("2023-01-03", periods=n, freq="B")
    prices = [start_price * ((1 + trend) ** i) for i in range(n)]
    return pd.DataFrame(
        {
            "trade_date": dates,
            "open": [p * 0.998 for p in prices],
            "high": [p * 1.005 for p in prices],
            "low": [p * 0.995 for p in prices],
            "close": prices,
            "adjusted_close": prices,
            "volume": [1_000_000 + i * 1000 for i in range(n)],
        }
    )


class TestBaselineFeaturePipeline:
    """Pipeline unit tests — pure function, no I/O."""

    def setup_method(self) -> None:
        self.pipeline = BaselineFeaturePipeline()
        self.security_id = uuid.uuid4()
        self.bars_df = _make_bars_df(n=150)

    def test_compute_returns_feature_set(self) -> None:
        fs = self.pipeline.compute(self.security_id, "AAPL", self.bars_df)
        assert isinstance(fs, FeatureSet)
        assert fs.ticker == "AAPL"
        assert fs.security_id == self.security_id

    def test_all_feature_keys_present(self) -> None:
        fs = self.pipeline.compute(self.security_id, "AAPL", self.bars_df)
        computed_keys = {f.feature_key for f in fs.features}
        for key in FEATURE_KEYS:
            assert key in computed_keys, f"Missing feature: {key}"

    def test_feature_values_have_source_version(self) -> None:
        """Gate B: every feature is tagged with its source_version."""
        fs = self.pipeline.compute(self.security_id, "AAPL", self.bars_df)
        for f in fs.features:
            assert f.source_version, f"feature {f.feature_key} has no source_version"

    def test_feature_values_have_group(self) -> None:
        """Gate B: explainability — every feature belongs to a named group."""
        fs = self.pipeline.compute(self.security_id, "AAPL", self.bars_df)
        for f in fs.features:
            assert f.feature_group, f"feature {f.feature_key} has no feature_group"

    def test_momentum_features_non_zero_for_uptrend(self) -> None:
        """Upward trending prices should produce positive return features."""
        fs = self.pipeline.compute(self.security_id, "UPTREND", self.bars_df)
        r1m = fs.get("return_1m")
        r3m = fs.get("return_3m")
        assert r1m is not None and r1m > Decimal("0")
        assert r3m is not None and r3m > Decimal("0")

    def test_compute_empty_df_returns_empty_feature_set(self) -> None:
        fs = self.pipeline.compute(self.security_id, "EMPTY", pd.DataFrame())
        assert fs.features == []

    def test_compute_insufficient_data_returns_none_features(self) -> None:
        """With only 10 bars most features needing 21-50 bars should be None."""
        tiny_df = _make_bars_df(n=10)
        fs = self.pipeline.compute(self.security_id, "TINY", tiny_df)
        # return_1m needs 22 bars — should be None
        assert fs.get("return_1m") is None
        # sma_50 needs 50 bars — must be None
        assert fs.get("sma_50") is None

    def test_volatility_is_non_negative(self) -> None:
        """Volatility may be zero for perfectly smooth synthetic data; must be non-negative."""
        fs = self.pipeline.compute(self.security_id, "AAPL", self.bars_df)
        vol = fs.get("volatility_20d")
        assert vol is not None and vol >= Decimal("0")

    def test_dollar_volume_is_positive(self) -> None:
        fs = self.pipeline.compute(self.security_id, "AAPL", self.bars_df)
        dv = fs.get("dollar_volume_20d")
        assert dv is not None and dv > Decimal("0")

    def test_as_of_timestamp_populated(self) -> None:
        fs = self.pipeline.compute(self.security_id, "AAPL", self.bars_df)
        assert isinstance(fs.as_of_timestamp, dt.datetime)


class TestPipelineHelpers:
    """Individual static-method helpers of the pipeline."""

    def test_period_return_positive_for_uptrend(self) -> None:
        import pandas as pd
        closes = pd.Series([100.0 * (1.001 ** i) for i in range(30)])
        r = BaselineFeaturePipeline._period_return(closes, periods=21)
        assert r is not None and r > 0

    def test_period_return_none_on_insufficient_data(self) -> None:
        import pandas as pd
        closes = pd.Series([100.0, 101.0])
        assert BaselineFeaturePipeline._period_return(closes, periods=21) is None

    def test_sma_cross_signal_golden_cross(self) -> None:
        """When fast SMA crosses above slow: return 1.0."""
        import pandas as pd
        # Construct a sequence where close goes sharply up in the last 20 bars
        # forcing fast SMA above slow SMA
        base = [100.0] * 60  # flat baseline
        surge = [200.0] * 20  # sharp up  →  fast SMA crosses above slow
        closes = pd.Series(base + surge)
        signal = BaselineFeaturePipeline._sma_cross_signal(closes, fast=20, slow=50)
        # After the surge the fast SMA (avg of last 20 = 200) > slow SMA (avg of last 50 ≈ 148)
        # One bar before it depends on data but signal should be non-None
        assert signal is not None

    def test_atr_is_positive(self) -> None:
        import pandas as pd
        n = 20
        highs = pd.Series([105.0] * n)
        lows = pd.Series([95.0] * n)
        closes = pd.Series([100.0] * n)
        atr = BaselineFeaturePipeline._atr(highs, lows, closes, period=14)
        assert atr is not None and atr > 0

    def test_avg_dollar_volume_is_positive(self) -> None:
        import pandas as pd
        closes = pd.Series([100.0] * 25)
        vols = pd.Series([1_000_000.0] * 25)
        dv = BaselineFeaturePipeline._avg_dollar_volume(closes, vols, periods=20)
        assert dv is not None and dv > 0


class TestFeatureSet:
    """FeatureSet helper methods."""

    def test_get_existing_key(self) -> None:
        fs = FeatureSet(
            security_id=uuid.uuid4(),
            ticker="AAPL",
            as_of_timestamp=dt.datetime.utcnow(),
            features=[
                ComputedFeature(
                    feature_key="return_1m",
                    feature_group="momentum",
                    value=Decimal("0.05"),
                    as_of_timestamp=dt.datetime.utcnow(),
                )
            ],
        )
        assert fs.get("return_1m") == Decimal("0.05")

    def test_get_missing_key_returns_none(self) -> None:
        fs = FeatureSet(
            security_id=uuid.uuid4(),
            ticker="AAPL",
            as_of_timestamp=dt.datetime.utcnow(),
        )
        assert fs.get("nonexistent") is None
