"""
Evaluation Engine Service — daily grading, benchmarks, drawdown, attribution.

All computation is pure in-memory (no DB dependency), making it fully
testable without a database.

Public API:
  grade_closed_trade(trade)              → PositionGrade
  compute_drawdown_metrics(equity_curve) → DrawdownMetrics
  compute_attribution(closed_trades)     → PerformanceAttribution
  generate_daily_scorecard(...)          → DailyScorecard
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Optional

from services.evaluation_engine.config import EvaluationConfig
from services.evaluation_engine.models import (
    AttributionRecord,
    BenchmarkComparison,
    DailyScorecard,
    DrawdownMetrics,
    PerformanceAttribution,
    PositionGrade,
    TradeRecord,
)
from services.portfolio_engine.models import PortfolioSnapshot


class EvaluationEngineService:
    """Compute daily scorecard, benchmarks, drawdown, and attribution."""

    def __init__(self, config: Optional[EvaluationConfig] = None) -> None:
        self._config = config or EvaluationConfig()

    # ── Per-trade grading ──────────────────────────────────────────────────────

    def grade_closed_trade(self, trade: TradeRecord) -> PositionGrade:
        """Assign a letter grade and compute P&L metrics for a closed trade."""
        pnl_pct = trade.realized_pnl_pct
        thresholds = self._config.grade_thresholds

        if pnl_pct >= thresholds["A"]:
            grade = "A"
        elif pnl_pct >= thresholds["B"]:
            grade = "B"
        elif pnl_pct >= thresholds["C"]:
            grade = "C"
        elif pnl_pct >= thresholds["D"]:
            grade = "D"
        else:
            grade = "F"

        return PositionGrade(
            ticker=trade.ticker,
            strategy_key=trade.strategy_key,
            realized_pnl=trade.realized_pnl,
            realized_pnl_pct=pnl_pct,
            holding_days=trade.holding_days,
            is_winner=trade.is_winner,
            exit_reason=trade.exit_reason,
            grade=grade,
        )

    # ── Drawdown metrics ───────────────────────────────────────────────────────

    def compute_drawdown_metrics(
        self, equity_curve: list[Decimal]
    ) -> DrawdownMetrics:
        """Compute max and current drawdown from an ordered equity curve.

        Args:
            equity_curve: Chronologically ordered portfolio equity values.
                          May contain at least one element.

        Returns:
            DrawdownMetrics with max_drawdown, current_drawdown, high_water_mark,
            and recovery_time_est_days (None when in drawdown).
        """
        if not equity_curve:
            return DrawdownMetrics(
                max_drawdown=Decimal("0"),
                current_drawdown=Decimal("0"),
                high_water_mark=Decimal("0"),
                recovery_time_est_days=None,
            )

        hwm = equity_curve[0]
        max_dd = Decimal("0")

        for equity in equity_curve:
            if equity > hwm:
                hwm = equity
            if hwm > Decimal("0"):
                dd = ((hwm - equity) / hwm).quantize(Decimal("0.0001"))
            else:
                dd = Decimal("0")
            if dd > max_dd:
                max_dd = dd

        current_equity = equity_curve[-1]
        if hwm > Decimal("0"):
            current_dd = ((hwm - current_equity) / hwm).quantize(Decimal("0.0001"))
            # Ensure non-negative (floating-point guard)
            current_dd = max(Decimal("0"), current_dd)
        else:
            current_dd = Decimal("0")

        recovery_est = 0 if current_dd == Decimal("0") else None

        return DrawdownMetrics(
            max_drawdown=max_dd,
            current_drawdown=current_dd,
            high_water_mark=hwm,
            recovery_time_est_days=recovery_est,
        )

    # ── Attribution ────────────────────────────────────────────────────────────

    def compute_attribution(
        self, closed_trades: list[TradeRecord]
    ) -> PerformanceAttribution:
        """Group trades by ticker, strategy, and theme; compute P&L attribution.

        Trades without a theme are omitted from by_theme attribution.
        """
        ticker_map: dict[str, list[TradeRecord]] = {}
        strategy_map: dict[str, list[TradeRecord]] = {}
        theme_map: dict[str, list[TradeRecord]] = {}

        for trade in closed_trades:
            ticker_map.setdefault(trade.ticker, []).append(trade)
            strategy_map.setdefault(trade.strategy_key or "unknown", []).append(trade)
            if trade.theme:
                theme_map.setdefault(trade.theme, []).append(trade)

        def _make_record(
            dimension: str, key: str, trades: list[TradeRecord]
        ) -> AttributionRecord:
            wins = sum(1 for t in trades if t.is_winner)
            total_pnl = sum(
                (t.realized_pnl for t in trades), Decimal("0")
            )
            n = len(trades)
            hit_rate = (
                (Decimal(wins) / Decimal(n)).quantize(Decimal("0.0001"))
                if n > 0
                else Decimal("0")
            )
            return AttributionRecord(
                dimension=dimension,
                key=key,
                realized_pnl=total_pnl,
                trade_count=n,
                win_count=wins,
                hit_rate=hit_rate,
            )

        return PerformanceAttribution(
            by_ticker=[
                _make_record("ticker", k, v) for k, v in ticker_map.items()
            ],
            by_strategy=[
                _make_record("strategy", k, v) for k, v in strategy_map.items()
            ],
            by_theme=[
                _make_record("theme", k, v) for k, v in theme_map.items()
            ],
        )

    # ── Daily scorecard ────────────────────────────────────────────────────────

    def generate_daily_scorecard(
        self,
        snapshot: PortfolioSnapshot,
        closed_today: list[TradeRecord],
        benchmark_returns: dict[str, Decimal],
        equity_curve: list[Decimal],
    ) -> DailyScorecard:
        """Generate the complete daily evaluation scorecard.

        Args:
            snapshot:          End-of-day portfolio snapshot.
            closed_today:      Trades closed during the session being graded.
            benchmark_returns: Fractional daily returns keyed by ticker
                               e.g. {"SPY": Decimal("0.005")}.
            equity_curve:      Chronological equity values including today,
                               used for drawdown computation.

        Returns:
            DailyScorecard populated with all Gate D fields.
        """
        # ── P&L ───────────────────────────────────────────────────────────────
        realized_pnl = sum(
            (t.realized_pnl for t in closed_today), Decimal("0")
        )
        unrealized_pnl = sum(
            (p.unrealized_pnl for p in snapshot.positions), Decimal("0")
        )
        net_pnl = realized_pnl + unrealized_pnl
        daily_return_pct = snapshot.daily_pnl_pct

        # ── Trade statistics ───────────────────────────────────────────────────
        closed_count = len(closed_today)
        winners = [t for t in closed_today if t.is_winner]
        losers = [t for t in closed_today if not t.is_winner]

        if closed_count > 0:
            hit_rate = (
                Decimal(len(winners)) / Decimal(closed_count)
            ).quantize(Decimal("0.0001"))
        else:
            hit_rate = Decimal("0")

        avg_winner_pct = (
            (
                sum(t.realized_pnl_pct for t in winners) / Decimal(len(winners))
            ).quantize(Decimal("0.000001"))
            if winners
            else Decimal("0")
        )
        avg_loser_pct = (
            (
                sum(t.realized_pnl_pct for t in losers) / Decimal(len(losers))
            ).quantize(Decimal("0.000001"))
            if losers
            else Decimal("0")
        )

        # ── Drawdown ───────────────────────────────────────────────────────────
        dd_metrics = self.compute_drawdown_metrics(equity_curve)

        # ── Benchmarks ─────────────────────────────────────────────────────────
        differentials = {
            ticker: (daily_return_pct - bm_return).quantize(Decimal("0.0001"))
            for ticker, bm_return in benchmark_returns.items()
        }
        benchmark_comparison = BenchmarkComparison(
            portfolio_return=daily_return_pct,
            benchmark_returns=benchmark_returns,
            differentials=differentials,
        )

        # ── Attribution ────────────────────────────────────────────────────────
        attribution = self.compute_attribution(closed_today)

        return DailyScorecard(
            scorecard_date=snapshot.snapshot_at.date(),
            equity=snapshot.equity,
            cash=snapshot.cash,
            gross_exposure=snapshot.gross_exposure,
            position_count=snapshot.position_count,
            net_pnl=net_pnl.quantize(Decimal("0.01")),
            realized_pnl=realized_pnl.quantize(Decimal("0.01")),
            unrealized_pnl=unrealized_pnl.quantize(Decimal("0.01")),
            daily_return_pct=daily_return_pct,
            closed_trade_count=closed_count,
            hit_rate=hit_rate,
            avg_winner_pct=avg_winner_pct,
            avg_loser_pct=avg_loser_pct,
            current_drawdown_pct=dd_metrics.current_drawdown,
            max_drawdown_pct=dd_metrics.max_drawdown,
            benchmark_comparison=benchmark_comparison,
            attribution=attribution,
            mode=snapshot.mode,
        )
