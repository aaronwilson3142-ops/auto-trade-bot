"""backtest domain models."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


@dataclass
class DayResult:
    """Simulation state at the end of a single trading day."""
    date: dt.date
    signals_generated: int = 0
    rankings_produced: int = 0
    positions_opened: int = 0
    positions_closed: int = 0
    portfolio_value: Decimal = Decimal("0")
    cash: Decimal = Decimal("0")
    daily_pnl: Decimal = Decimal("0")
    cumulative_pnl: Decimal = Decimal("0")
    drawdown_pct: float = 0.0
    active_positions: int = 0
    transaction_costs: Decimal = Decimal("0")


@dataclass
class BacktestResult:
    """Aggregated results from a completed backtest run."""
    start_date: dt.date
    end_date: dt.date
    initial_cash: Decimal
    final_portfolio_value: Decimal = Decimal("0")
    total_return_pct: float = 0.0
    sharpe_ratio: Optional[float] = None
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_transaction_costs: Decimal = Decimal("0")
    days_simulated: int = 0
    day_results: list[DayResult] = field(default_factory=list)

    @property
    def net_profit(self) -> Decimal:
        return self.final_portfolio_value - self.initial_cash
