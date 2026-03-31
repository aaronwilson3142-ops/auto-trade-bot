"""market_data domain models.

Provides normalized bar and liquidity metrics used by the feature pipeline
and ranking engine.  All data originates from yfinance (secondary_verified).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

SOURCE_KEY = "yfinance"
RELIABILITY_TIER = "secondary_verified"


@dataclass
class NormalizedBar:
    """A single daily bar with adjusted-close prices."""
    ticker: str
    trade_date: dt.date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adjusted_close: Decimal
    volume: int
    vwap: Decimal | None = None  # computed when intraday data unavailable: (H+L+C)/3

    @property
    def dollar_volume(self) -> Decimal:
        """Approximate daily dollar traded volume using adjusted close."""
        return self.adjusted_close * Decimal(self.volume)


@dataclass
class LiquidityMetrics:
    """Rolling liquidity summary for a security."""
    ticker: str
    as_of: dt.date
    avg_dollar_volume_20d: Decimal | None = None   # 20-day avg dollar volume
    avg_dollar_volume_60d: Decimal | None = None   # 60-day avg dollar volume
    avg_volume_20d: int | None = None              # 20-day avg shares
    price_range_pct_20d: Decimal | None = None     # (H-L)/close rolling avg
    liquidity_tier: str = "unknown"                   # "high", "mid", "low", "micro"

    @property
    def is_liquid_enough(self) -> bool:
        """True if avg_dollar_volume_20d >= $1 M threshold."""
        if self.avg_dollar_volume_20d is None:
            return False
        return self.avg_dollar_volume_20d >= Decimal("1_000_000")


@dataclass
class MarketSnapshot:
    """Latest market state for a single security."""
    ticker: str
    as_of: dt.datetime
    latest_bar: NormalizedBar | None = None
    liquidity: LiquidityMetrics | None = None
    bars_1y: list[NormalizedBar] = field(default_factory=list)  # last 252 bars
    source_key: str = SOURCE_KEY
    reliability_tier: str = RELIABILITY_TIER

    @property
    def latest_price(self) -> Decimal | None:
        if self.latest_bar:
            return self.latest_bar.adjusted_close
        return None

