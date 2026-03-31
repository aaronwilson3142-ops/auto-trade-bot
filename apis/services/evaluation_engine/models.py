"""
Evaluation engine domain models (plain dataclasses, no ORM dependency).

These models represent the outputs of daily grading, benchmark comparison,
drawdown analysis, and performance attribution.  They feed:
  - evaluation_engine/service.py  — computation
  - tests/unit/test_evaluation_engine.py  — Gate D QA
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

# ── Closed-trade input record ──────────────────────────────────────────────────

@dataclass
class TradeRecord:
    """A fully closed trade submitted to the evaluation engine."""

    ticker: str
    strategy_key: str
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    entry_time: dt.datetime
    exit_time: dt.datetime
    exit_reason: str = ""
    thesis_summary: str = ""
    theme: str = ""
    sector: str = ""
    contains_rumor: bool = False

    @property
    def realized_pnl(self) -> Decimal:
        return ((self.exit_price - self.entry_price) * self.quantity).quantize(
            Decimal("0.01")
        )

    @property
    def realized_pnl_pct(self) -> Decimal:
        cost = self.entry_price * self.quantity
        if cost == Decimal("0"):
            return Decimal("0")
        return (self.realized_pnl / cost).quantize(Decimal("0.000001"))

    @property
    def is_winner(self) -> bool:
        return self.realized_pnl > Decimal("0")

    @property
    def holding_days(self) -> int:
        delta = self.exit_time - self.entry_time
        return max(0, delta.days)


# ── Per-trade grade ────────────────────────────────────────────────────────────

@dataclass
class PositionGrade:
    """Evaluation of a single closed trade.

    Grade thresholds (by realized_pnl_pct):
      A  >= +5 %
      B  >= +2 %
      C  >=  0 %
      D  >= -3 %
      F   < -3 %
    """

    ticker: str
    strategy_key: str
    realized_pnl: Decimal
    realized_pnl_pct: Decimal
    holding_days: int
    is_winner: bool
    exit_reason: str
    grade: str  # "A" | "B" | "C" | "D" | "F"


# ── Benchmark comparison ────────────────────────────────────────────────────────

@dataclass
class BenchmarkComparison:
    """Portfolio daily return vs external benchmarks.

    All values are fractional (0.01 = 1 %).
    """

    portfolio_return: Decimal
    benchmark_returns: dict[str, Decimal]   # {"SPY": 0.005, "QQQ": 0.003, ...}
    differentials: dict[str, Decimal]       # portfolio_return - benchmark_return


# ── Drawdown metrics ───────────────────────────────────────────────────────────

@dataclass
class DrawdownMetrics:
    """Max and current drawdown derived from an equity curve."""

    max_drawdown: Decimal           # highest peak-to-trough fraction seen
    current_drawdown: Decimal       # fraction below current high-water mark
    high_water_mark: Decimal        # highest equity value seen in the curve
    recovery_time_est_days: int | None  # None when no recovery estimate available


# ── Attribution ────────────────────────────────────────────────────────────────

@dataclass
class AttributionRecord:
    """P&L attribution for one slice of a dimension (ticker, strategy, or theme)."""

    dimension: str      # "ticker" | "strategy" | "theme"
    key: str            # dimension value, e.g. "AAPL", "momentum", "AI infrastructure"
    realized_pnl: Decimal
    trade_count: int
    win_count: int
    hit_rate: Decimal   # win_count / trade_count


@dataclass
class PerformanceAttribution:
    """Full multi-dimensional performance attribution."""

    by_ticker: list[AttributionRecord]
    by_strategy: list[AttributionRecord]
    by_theme: list[AttributionRecord]


# ── Daily scorecard ────────────────────────────────────────────────────────────

@dataclass
class DailyScorecard:
    """Complete daily portfolio evaluation — the primary Gate D output."""

    scorecard_date: dt.date

    # Portfolio state snapshot
    equity: Decimal
    cash: Decimal
    gross_exposure: Decimal
    position_count: int

    # P&L summary
    net_pnl: Decimal            # realized_pnl + unrealized_pnl
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    daily_return_pct: Decimal   # (equity - start_of_day_equity) / start_of_day_equity

    # Trade statistics (closed trades only)
    closed_trade_count: int
    hit_rate: Decimal           # winners / closed_trade_count  (0 when none)
    avg_winner_pct: Decimal     # average realized_pnl_pct of winning trades
    avg_loser_pct: Decimal      # average realized_pnl_pct of losing trades (≤ 0)

    # Risk
    current_drawdown_pct: Decimal
    max_drawdown_pct: Decimal

    # Benchmark comparison
    benchmark_comparison: BenchmarkComparison

    # Attribution
    attribution: PerformanceAttribution

    mode: str = "paper"
