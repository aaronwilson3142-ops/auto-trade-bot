"""market_data utility helpers.

Stateless pure functions for price normalisation and liquidity tier
classification.  No I/O or DB access.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation

import pandas as pd

from services.market_data.models import LiquidityMetrics, NormalizedBar

_Q = Decimal("0.000001")


def _d(value: object) -> Decimal | None:
    """Safely convert any numeric value to Decimal."""
    if value is None:
        return None
    try:
        import math
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def df_to_normalized_bars(ticker: str, df: pd.DataFrame) -> list[NormalizedBar]:
    """Convert a yfinance OHLCV DataFrame into NormalizedBar objects.

    The DataFrame should have columns: Open, High, Low, Close, Adj Close,
    Volume and a DatetimeIndex.  Missing Adj Close falls back to Close.
    """
    bars: list[NormalizedBar] = []
    adj_col = "Adj Close" if "Adj Close" in df.columns else "Close"
    for ts, row in df.iterrows():
        trade_date = ts.date() if hasattr(ts, "date") else ts
        open_ = _d(row.get("Open"))
        high = _d(row.get("High"))
        low = _d(row.get("Low"))
        close = _d(row.get("Close"))
        adj_close = _d(row.get(adj_col)) or close
        volume = int(row.get("Volume", 0) or 0)
        if open_ is None or high is None or low is None or close is None:
            continue
        vwap = _d((float(high) + float(low) + float(adj_close)) / 3.0)
        bars.append(
            NormalizedBar(
                ticker=ticker,
                trade_date=trade_date,
                open=open_,
                high=high,
                low=low,
                close=close,
                adjusted_close=adj_close,
                volume=volume,
                vwap=vwap,
            )
        )
    return sorted(bars, key=lambda b: b.trade_date)


def classify_liquidity_tier(
    avg_dollar_volume: Decimal | None,
    high_threshold: float = 100_000_000.0,
    mid_threshold: float = 10_000_000.0,
    low_threshold: float = 1_000_000.0,
) -> str:
    """Return a liquidity tier label based on average daily dollar volume."""
    if avg_dollar_volume is None:
        return "unknown"
    v = float(avg_dollar_volume)
    if v >= high_threshold:
        return "high"
    if v >= mid_threshold:
        return "mid"
    if v >= low_threshold:
        return "low"
    return "micro"


def compute_liquidity_metrics(
    ticker: str,
    bars: list[NormalizedBar],
    *,
    short_window: int = 20,
    long_window: int = 60,
    high_threshold: float = 100_000_000.0,
    mid_threshold: float = 10_000_000.0,
    low_threshold: float = 1_000_000.0,
) -> LiquidityMetrics:
    """Compute rolling liquidity stats from a sorted bar list."""
    as_of = bars[-1].trade_date if bars else dt.date.today()
    recent_short = bars[-short_window:] if len(bars) >= short_window else bars
    recent_long = bars[-long_window:] if len(bars) >= long_window else bars

    def _avg_dv(b_list: list[NormalizedBar]) -> Decimal | None:
        if not b_list:
            return None
        total = sum(float(b.dollar_volume) for b in b_list)
        return _d(total / len(b_list))

    def _avg_vol(b_list: list[NormalizedBar]) -> int | None:
        if not b_list:
            return None
        return int(sum(b.volume for b in b_list) / len(b_list))

    def _avg_range_pct(b_list: list[NormalizedBar]) -> Decimal | None:
        if not b_list:
            return None
        pcts = []
        for b in b_list:
            if b.close and float(b.close) > 0:
                pcts.append((float(b.high) - float(b.low)) / float(b.close))
        if not pcts:
            return None
        return _d(sum(pcts) / len(pcts))

    avg_dv_short = _avg_dv(recent_short)
    avg_dv_long = _avg_dv(recent_long)
    tier = classify_liquidity_tier(
        avg_dv_short,
        high_threshold=high_threshold,
        mid_threshold=mid_threshold,
        low_threshold=low_threshold,
    )
    return LiquidityMetrics(
        ticker=ticker,
        as_of=as_of,
        avg_dollar_volume_20d=avg_dv_short,
        avg_dollar_volume_60d=avg_dv_long,
        avg_volume_20d=_avg_vol(recent_short),
        price_range_pct_20d=_avg_range_pct(recent_short),
        liquidity_tier=tier,
    )

