"""
BaselineFeaturePipeline — computes the MVP feature set from OHLCV bars.

Input:   pandas DataFrame with columns: trade_date, open, high, low, close,
         adjusted_close, volume.  Index should be integer or date; will be
         sorted ascending by trade_date internally.

Output:  FeatureSet with all FEATURE_KEYS populated (None if insufficient data).

The pipeline is stateless / pure-function style so it is trivially testable
without a database.  The FeatureStoreService owns DB persistence.
"""
from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

import pandas as pd

from services.feature_store.models import (
    FEATURE_GROUP_MAP,
    FEATURE_KEYS,
    ComputedFeature,
    FeatureSet,
)

logger = logging.getLogger(__name__)

_SOURCE_VERSION = "baseline_v1"
_QUANTIZE = Decimal("0.000001")


def _d(value: Optional[float]) -> Optional[Decimal]:
    """Convert float to Decimal, returning None for NaN / None."""
    if value is None:
        return None
    import math
    if math.isnan(value) or math.isinf(value):
        return None
    return Decimal(str(value)).quantize(_QUANTIZE, rounding=ROUND_HALF_UP)


class BaselineFeaturePipeline:
    """Computes the baseline feature set from a OHLCV DataFrame.

    All logic is implemented as standalone helper methods that operate on a
    cleaned pandas Series so individual features can be unit-tested in
    isolation.
    """

    SOURCE_VERSION: str = _SOURCE_VERSION

    def compute(
        self,
        security_id: object,
        ticker: str,
        bars_df: pd.DataFrame,
        as_of: Optional[dt.datetime] = None,
    ) -> FeatureSet:
        """Compute all features for the most recent date in *bars_df*.

        Args:
            security_id: UUID of the security in the ORM.
            ticker:      Human-readable symbol for logging.
            bars_df:     Must contain columns: trade_date, close, high, low,
                         adjusted_close, volume.  Indexed arbitrarily.
            as_of:       Timestamp to stamp the feature set.  Defaults to UTC
                         midnight of the last trade_date in bars_df.

        Returns:
            FeatureSet with ComputedFeature entries for each FEATURE_KEYS member.
            Features that cannot be computed (insufficient history) are None.
        """
        if bars_df is None or bars_df.empty:
            logger.warning("Empty DataFrame passed to pipeline for %s; skipping.", ticker)
            return FeatureSet(
                security_id=security_id,
                ticker=ticker,
                as_of_timestamp=as_of or dt.datetime.utcnow(),
                source_version=_SOURCE_VERSION,
            )

        df = bars_df.copy()
        # Ensure sorted ascending
        if "trade_date" in df.columns:
            df = df.sort_values("trade_date").reset_index(drop=True)

        # Use adjusted_close when available, fall back to close
        price_col = "adjusted_close" if "adjusted_close" in df.columns else "close"
        closes: pd.Series = pd.to_numeric(df[price_col], errors="coerce").astype(float)
        highs: pd.Series = pd.to_numeric(df.get("high", pd.Series(dtype=float)), errors="coerce").astype(float)
        lows: pd.Series = pd.to_numeric(df.get("low", pd.Series(dtype=float)), errors="coerce").astype(float)
        volumes: pd.Series = pd.to_numeric(df.get("volume", pd.Series(dtype=float)), errors="coerce").astype(float)

        last_close = closes.iloc[-1] if not closes.empty else None

        if as_of is None:
            last_date = df["trade_date"].iloc[-1] if "trade_date" in df.columns else dt.date.today()
            if hasattr(last_date, "to_pydatetime"):
                as_of = last_date.to_pydatetime()
            elif isinstance(last_date, dt.date):
                as_of = dt.datetime.combine(last_date, dt.time.min)
            else:
                as_of = dt.datetime.utcnow()

        raw: dict[str, Optional[float]] = {}

        # ── Momentum: n-period returns ──────────────────────────────────────
        raw["return_1m"] = self._period_return(closes, periods=21)
        raw["return_3m"] = self._period_return(closes, periods=63)
        raw["return_6m"] = self._period_return(closes, periods=126)

        # ── Risk: annualised volatility + ATR ───────────────────────────────
        raw["volatility_20d"] = self._volatility(closes, periods=20)
        raw["atr_14"] = self._atr(highs, lows, closes, period=14)

        # ── Liquidity: avg dollar volume ────────────────────────────────────
        raw["dollar_volume_20d"] = self._avg_dollar_volume(closes, volumes, periods=20)

        # ── Trend: SMAs and cross signal ────────────────────────────────────
        sma20 = self._sma(closes, period=20)
        sma50 = self._sma(closes, period=50)
        raw["sma_20"] = sma20
        raw["sma_50"] = sma50
        raw["sma_cross_signal"] = self._sma_cross_signal(closes, fast=20, slow=50)
        raw["price_vs_sma20"] = (
            (last_close - sma20) / sma20 if last_close and sma20 and sma20 != 0 else None
        )
        raw["price_vs_sma50"] = (
            (last_close - sma50) / sma50 if last_close and sma50 and sma50 != 0 else None
        )

        features = [
            ComputedFeature(
                feature_key=key,
                feature_group=FEATURE_GROUP_MAP[key],
                value=_d(raw.get(key)),
                as_of_timestamp=as_of,
                source_version=_SOURCE_VERSION,
            )
            for key in FEATURE_KEYS
        ]

        return FeatureSet(
            security_id=security_id,
            ticker=ticker,
            as_of_timestamp=as_of,
            features=features,
            source_version=_SOURCE_VERSION,
        )

    # ------------------------------------------------------------------
    # Individual feature helpers (public so tests can call them directly)
    # ------------------------------------------------------------------

    @staticmethod
    def _period_return(closes: pd.Series, periods: int) -> Optional[float]:
        """Simple return over *periods* trading days."""
        if len(closes) <= periods:
            return None
        past = closes.iloc[-(periods + 1)]
        now = closes.iloc[-1]
        if pd.isna(past) or pd.isna(now) or past == 0:
            return None
        return float((now - past) / past)

    @staticmethod
    def _volatility(closes: pd.Series, periods: int = 20) -> Optional[float]:
        """Annualised volatility of log returns over *periods* days."""
        if len(closes) < periods + 1:
            return None
        log_ret = closes.pct_change().dropna()
        if len(log_ret) < periods:
            return None
        vol = log_ret.iloc[-periods:].std()
        if pd.isna(vol):
            return None
        return float(vol * (252 ** 0.5))  # annualise

    @staticmethod
    def _atr(
        highs: pd.Series,
        lows: pd.Series,
        closes: pd.Series,
        period: int = 14,
    ) -> Optional[float]:
        """Average True Range over *period* days."""
        if len(closes) < period + 1 or highs.empty or lows.empty:
            return None
        tr = pd.concat([
            highs - lows,
            (highs - closes.shift(1)).abs(),
            (lows - closes.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr = tr.iloc[-period:].mean()
        return None if pd.isna(atr) else float(atr)

    @staticmethod
    def _avg_dollar_volume(
        closes: pd.Series,
        volumes: pd.Series,
        periods: int = 20,
    ) -> Optional[float]:
        """Average daily dollar volume over *periods* days."""
        if len(closes) < periods or len(volumes) < periods:
            return None
        dv = closes * volumes
        avg = dv.iloc[-periods:].mean()
        return None if pd.isna(avg) else float(avg)

    @staticmethod
    def _sma(closes: pd.Series, period: int) -> Optional[float]:
        """Simple moving average of the last *period* closes."""
        if len(closes) < period:
            return None
        val = closes.iloc[-period:].mean()
        return None if pd.isna(val) else float(val)

    @staticmethod
    def _sma_cross_signal(
        closes: pd.Series,
        fast: int = 20,
        slow: int = 50,
    ) -> Optional[float]:
        """Return 1.0 (golden cross), -1.0 (death cross), or 0.0 (no recent cross).

        A cross is detected when the fast SMA crossed the slow SMA between
        the previous bar and the current bar.
        """
        if len(closes) < slow + 1:
            return None

        def _sma_at(s: pd.Series, end_idx: int, period: int) -> Optional[float]:
            start = end_idx - period
            if start < 0:
                return None
            vals = s.iloc[start:end_idx]
            return float(vals.mean()) if len(vals) == period else None

        n = len(closes)
        fast_now = _sma_at(closes, n, fast)
        slow_now = _sma_at(closes, n, slow)
        fast_prev = _sma_at(closes, n - 1, fast)
        slow_prev = _sma_at(closes, n - 1, slow)

        if any(v is None for v in [fast_now, slow_now, fast_prev, slow_prev]):
            return 0.0

        crossed_above = fast_prev <= slow_prev and fast_now > slow_now  # type: ignore[operator]
        crossed_below = fast_prev >= slow_prev and fast_now < slow_now  # type: ignore[operator]

        if crossed_above:
            return 1.0
        if crossed_below:
            return -1.0
        return 0.0
