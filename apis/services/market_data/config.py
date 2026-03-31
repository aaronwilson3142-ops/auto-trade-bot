"""market_data service configuration."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MarketDataConfig:
    """Tunable parameters for the market data service."""
    # Default yfinance fetch period for 1-year snapshots
    default_period: str = "1y"
    # Number of bars used for 20-day liquidity calculations
    liquidity_window_short: int = 20
    # Number of bars used for 60-day liquidity calculations
    liquidity_window_long: int = 60
    # Dollar volume thresholds for liquidity tier classification
    high_liquidity_threshold: float = 100_000_000.0   # $100 M/day
    mid_liquidity_threshold: float = 10_000_000.0     # $10 M/day
    low_liquidity_threshold: float = 1_000_000.0      # $1 M/day
    # Number of concurrent tickers to fetch in one yfinance bulk call
    bulk_batch_size: int = 20

