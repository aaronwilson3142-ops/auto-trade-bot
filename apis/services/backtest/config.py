"""backtest engine configuration."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


@dataclass
class BacktestConfig:
    """Parameters for a historical simulation run.

    Args:
        start_date:          First date to simulate (inclusive).
        end_date:            Last date to simulate (inclusive).
        tickers:             List of equity symbols to trade.
        initial_cash:        Starting portfolio cash in USD.
        transaction_cost_bps: Round-trip transaction cost in basis points.
                              Default 10 bps (0.10%) per trade.
        slippage_bps:        Fill slippage assumption in basis points.
                              Default 5 bps above/below close price.
        max_positions:       Maximum concurrent open positions.
        max_single_name_pct: Maximum portfolio weight per position (0–1).
        min_score_threshold: Minimum composite score to open a position.
    """
    start_date: dt.date
    end_date: dt.date
    tickers: list[str] = field(default_factory=list)
    initial_cash: Decimal = Decimal("100_000")
    transaction_cost_bps: float = 10.0
    slippage_bps: float = 5.0
    max_positions: int = 10
    max_single_name_pct: float = 0.15
    min_score_threshold: float = 0.3

    def validate(self) -> None:
        """Raise ValueError for invalid parameter combinations."""
        if self.start_date >= self.end_date:
            raise ValueError("start_date must be before end_date")
        if self.initial_cash <= Decimal("0"):
            raise ValueError("initial_cash must be positive")
        if not (0 < self.max_single_name_pct <= 1.0):
            raise ValueError("max_single_name_pct must be in (0, 1]")
        if not self.tickers:
            raise ValueError("tickers list must not be empty")
