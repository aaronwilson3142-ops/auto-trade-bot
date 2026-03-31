"""
Gate D — Evaluation Engine Tests.

Verifies:
  - grade_closed_trade: correct letter grades by P&L %, all grade bands
  - compute_drawdown_metrics: max drawdown, current drawdown, high-water mark,
    recovery_time_est, single-element curve, all-up curve
  - compute_attribution: grouping by ticker / strategy / theme,
    hit_rate arithmetic, missing-theme omission
  - generate_daily_scorecard: fully populated scorecard, benchmarks diffential,
    attribution fields, zero-trade edge case
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from services.evaluation_engine.models import TradeRecord
from services.evaluation_engine.service import EvaluationEngineService
from services.portfolio_engine.models import PortfolioPosition, PortfolioSnapshot

# ─────────────────────── helpers ─────────────────────────────────────────────

_NOW = dt.datetime(2026, 3, 17, 16, 0, 0)
_TODAY = _NOW.date()


def _svc() -> EvaluationEngineService:
    return EvaluationEngineService()


def _trade(
    ticker: str = "AAPL",
    entry: str = "100.00",
    exit_: str = "110.00",
    qty: str = "100",
    strategy: str = "momentum",
    theme: str = "technology",
    days_ago: int = 5,
    exit_reason: str = "thesis_met",
) -> TradeRecord:
    entry_time = _NOW - dt.timedelta(days=days_ago)
    return TradeRecord(
        ticker=ticker,
        strategy_key=strategy,
        entry_price=Decimal(entry),
        exit_price=Decimal(exit_),
        quantity=Decimal(qty),
        entry_time=entry_time,
        exit_time=_NOW,
        exit_reason=exit_reason,
        theme=theme,
    )


def _snapshot(
    cash: str = "90000",
    equity_snapshot: str = "100000",
    start_of_day: str = "98000",
    positions: list[PortfolioPosition] | None = None,
) -> PortfolioSnapshot:
    if positions is None:
        positions = []
    cash_d = Decimal(cash)
    equity_d = Decimal(equity_snapshot)
    sod_d = Decimal(start_of_day)
    daily_pnl = (
        ((equity_d - sod_d) / sod_d).quantize(Decimal("0.0001"))
        if sod_d != Decimal("0")
        else Decimal("0")
    )
    return PortfolioSnapshot(
        snapshot_at=_NOW,
        cash=cash_d,
        equity=equity_d,
        gross_exposure=equity_d - cash_d,
        position_count=len(positions),
        drawdown_pct=Decimal("0"),
        daily_pnl_pct=daily_pnl,
        positions=positions,
        mode="paper",
    )


# ═════════════════════ TestGradeClosedTrade ═══════════════════════════════════

class TestGradeClosedTrade:
    """Tests for EvaluationEngineService.grade_closed_trade."""

    def test_grade_A_at_threshold(self):
        # +5 % return → grade A
        trade = _trade(entry="100", exit_="105", qty="100")
        grade = _svc().grade_closed_trade(trade)
        assert grade.grade == "A"

    def test_grade_A_above_threshold(self):
        trade = _trade(entry="100", exit_="120", qty="50")
        grade = _svc().grade_closed_trade(trade)
        assert grade.grade == "A"

    def test_grade_B(self):
        # +3 % → grade B
        trade = _trade(entry="100", exit_="103", qty="100")
        grade = _svc().grade_closed_trade(trade)
        assert grade.grade == "B"

    def test_grade_C_breakeven(self):
        # 0 % return → grade C
        trade = _trade(entry="100", exit_="100", qty="100")
        grade = _svc().grade_closed_trade(trade)
        assert grade.grade == "C"

    def test_grade_D(self):
        # -2 % → grade D
        trade = _trade(entry="100", exit_="98", qty="100")
        grade = _svc().grade_closed_trade(trade)
        assert grade.grade == "D"

    def test_grade_F(self):
        # -5 % → grade F
        trade = _trade(entry="100", exit_="95", qty="100")
        grade = _svc().grade_closed_trade(trade)
        assert grade.grade == "F"

    def test_realized_pnl_winner(self):
        trade = _trade(entry="50", exit_="60", qty="200")
        grade = _svc().grade_closed_trade(trade)
        assert grade.is_winner is True
        assert grade.realized_pnl == Decimal("2000.00")

    def test_realized_pnl_loser(self):
        trade = _trade(entry="100", exit_="90", qty="10")
        grade = _svc().grade_closed_trade(trade)
        assert grade.is_winner is False
        assert grade.realized_pnl == Decimal("-100.00")

    def test_holding_days_propagated(self):
        trade = _trade(days_ago=7)
        grade = _svc().grade_closed_trade(trade)
        assert grade.holding_days == 7

    def test_exit_reason_propagated(self):
        trade = _trade(exit_reason="stop_loss")
        grade = _svc().grade_closed_trade(trade)
        assert grade.exit_reason == "stop_loss"

    def test_ticker_and_strategy_propagated(self):
        trade = _trade(ticker="MSFT", strategy="swing")
        grade = _svc().grade_closed_trade(trade)
        assert grade.ticker == "MSFT"
        assert grade.strategy_key == "swing"


# ═════════════════════ TestDrawdownMetrics ════════════════════════════════════

class TestDrawdownMetrics:
    """Tests for EvaluationEngineService.compute_drawdown_metrics."""

    def test_empty_curve_returns_zero(self):
        dd = _svc().compute_drawdown_metrics([])
        assert dd.max_drawdown == Decimal("0")
        assert dd.current_drawdown == Decimal("0")
        assert dd.high_water_mark == Decimal("0")

    def test_single_element_curve(self):
        dd = _svc().compute_drawdown_metrics([Decimal("10000")])
        assert dd.max_drawdown == Decimal("0")
        assert dd.current_drawdown == Decimal("0")
        assert dd.high_water_mark == Decimal("10000")

    def test_all_increasing_no_drawdown(self):
        curve = [Decimal(str(v)) for v in [100, 110, 120, 130]]
        dd = _svc().compute_drawdown_metrics(curve)
        assert dd.max_drawdown == Decimal("0")
        assert dd.current_drawdown == Decimal("0")
        assert dd.high_water_mark == Decimal("130")

    def test_drawdown_computed_correctly(self):
        # peak 120, then drops to 96 → 20 % drawdown
        curve = [Decimal(str(v)) for v in [100, 120, 96]]
        dd = _svc().compute_drawdown_metrics(curve)
        assert dd.max_drawdown == Decimal("0.2000")
        assert dd.high_water_mark == Decimal("120")

    def test_current_drawdown_when_below_hwm(self):
        curve = [Decimal(str(v)) for v in [100, 120, 108]]
        dd = _svc().compute_drawdown_metrics(curve)
        # 108 / 120 = 0.90 → 10 % drawdown
        assert dd.current_drawdown == Decimal("0.1000")

    def test_recovery_time_est_none_when_in_drawdown(self):
        curve = [Decimal(str(v)) for v in [100, 120, 108]]
        dd = _svc().compute_drawdown_metrics(curve)
        assert dd.recovery_time_est_days is None

    def test_recovery_time_est_zero_when_at_peak(self):
        curve = [Decimal(str(v)) for v in [100, 110, 120]]
        dd = _svc().compute_drawdown_metrics(curve)
        assert dd.recovery_time_est_days == 0

    def test_max_drawdown_is_worst_historical(self):
        # drops 20 %, recovers, drops only 10 %
        curve = [Decimal(str(v)) for v in [100, 80, 100, 90]]
        dd = _svc().compute_drawdown_metrics(curve)
        assert dd.max_drawdown == Decimal("0.2000")
        assert dd.current_drawdown == Decimal("0.1000")


# ═════════════════════ TestComputeAttribution ═════════════════════════════════

class TestComputeAttribution:
    """Tests for EvaluationEngineService.compute_attribution."""

    def test_attribution_by_ticker_groups_correctly(self):
        trades = [
            _trade("AAPL", entry="100", exit_="110"),
            _trade("AAPL", entry="110", exit_="105"),
            _trade("MSFT", entry="200", exit_="220"),
        ]
        attr = _svc().compute_attribution(trades)
        tickers = {r.key: r for r in attr.by_ticker}
        assert "AAPL" in tickers
        assert "MSFT" in tickers
        assert tickers["AAPL"].trade_count == 2
        assert tickers["MSFT"].trade_count == 1

    def test_hit_rate_calculation(self):
        trades = [
            _trade(exit_="110"),  # winner
            _trade(exit_="90"),   # loser
            _trade(exit_="110"),  # winner
            _trade(exit_="90"),   # loser
        ]
        attr = _svc().compute_attribution(trades)
        by_ticker = {r.key: r for r in attr.by_ticker}
        assert by_ticker["AAPL"].hit_rate == Decimal("0.5000")
        assert by_ticker["AAPL"].win_count == 2

    def test_attribution_by_strategy(self):
        trades = [
            _trade(strategy="momentum"),
            _trade(strategy="swing"),
            _trade(strategy="momentum"),
        ]
        attr = _svc().compute_attribution(trades)
        strategies = {r.key: r for r in attr.by_strategy}
        assert strategies["momentum"].trade_count == 2
        assert strategies["swing"].trade_count == 1

    def test_trades_without_theme_excluded_from_by_theme(self):
        trades = [
            _trade(theme=""),       # no theme
            _trade(theme="AI"),     # has theme
        ]
        attr = _svc().compute_attribution(trades)
        themes = {r.key for r in attr.by_theme}
        assert "AI" in themes
        assert "" not in themes

    def test_realized_pnl_sums_correctly(self):
        trades = [
            _trade("AAPL", entry="100", exit_="110", qty="100"),  # +1000
            _trade("AAPL", entry="100", exit_="95",  qty="100"),  # -500
        ]
        attr = _svc().compute_attribution(trades)
        by_ticker = {r.key: r for r in attr.by_ticker}
        assert by_ticker["AAPL"].realized_pnl == Decimal("500.00")

    def test_empty_trade_list_returns_empty_attribution(self):
        attr = _svc().compute_attribution([])
        assert attr.by_ticker == []
        assert attr.by_strategy == []
        assert attr.by_theme == []

    def test_unknown_strategy_key_grouped(self):
        trade = TradeRecord(
            ticker="TEST",
            strategy_key="",
            entry_price=Decimal("100"),
            exit_price=Decimal("110"),
            quantity=Decimal("10"),
            entry_time=_NOW - dt.timedelta(days=2),
            exit_time=_NOW,
        )
        attr = _svc().compute_attribution([trade])
        strategies = {r.key for r in attr.by_strategy}
        assert "unknown" in strategies


# ═════════════════════ TestGenerateDailyScorecard ════════════════════════════

class TestGenerateDailyScorecard:
    """Tests for EvaluationEngineService.generate_daily_scorecard."""

    def _equity_curve(self) -> list[Decimal]:
        return [Decimal(str(v)) for v in [95000, 97000, 98000, 100000]]

    def test_scorecard_basic_generation(self):
        snap = _snapshot()
        scorecard = _svc().generate_daily_scorecard(
            snapshot=snap,
            closed_today=[],
            benchmark_returns={"SPY": Decimal("0.005")},
            equity_curve=self._equity_curve(),
        )
        assert scorecard is not None
        assert scorecard.scorecard_date == _TODAY

    def test_scorecard_equity_and_cash_match_snapshot(self):
        snap = _snapshot(cash="90000", equity_snapshot="100000")
        scorecard = _svc().generate_daily_scorecard(
            snap, [], {"SPY": Decimal("0.005")}, self._equity_curve()
        )
        assert scorecard.equity == Decimal("100000")
        assert scorecard.cash == Decimal("90000")

    def test_scorecard_hit_rate_with_trades(self):
        trades = [
            _trade(exit_="110"),   # winner
            _trade(exit_="90"),    # loser
        ]
        snap = _snapshot()
        scorecard = _svc().generate_daily_scorecard(
            snap, trades, {"SPY": Decimal("0")}, self._equity_curve()
        )
        assert scorecard.closed_trade_count == 2
        assert scorecard.hit_rate == Decimal("0.5000")

    def test_scorecard_hit_rate_zero_with_no_trades(self):
        snap = _snapshot()
        scorecard = _svc().generate_daily_scorecard(
            snap, [], {"SPY": Decimal("0")}, self._equity_curve()
        )
        assert scorecard.closed_trade_count == 0
        assert scorecard.hit_rate == Decimal("0")

    def test_scorecard_avg_winner_pct(self):
        # Two winners: +10 %, +20 % → avg +15 %
        trades = [
            _trade(entry="100", exit_="110"),   # +10 %
            _trade(entry="100", exit_="120"),   # +20 %
        ]
        snap = _snapshot()
        scorecard = _svc().generate_daily_scorecard(
            snap, trades, {}, self._equity_curve()
        )
        assert scorecard.avg_winner_pct == Decimal("0.150000")

    def test_scorecard_avg_loser_pct(self):
        # Two losers: -5 %, -15 % → avg -10 %
        trades = [
            _trade(entry="100", exit_="95"),    # -5 %
            _trade(entry="100", exit_="85"),    # -15 %
        ]
        snap = _snapshot()
        scorecard = _svc().generate_daily_scorecard(
            snap, trades, {}, self._equity_curve()
        )
        assert scorecard.avg_loser_pct == Decimal("-0.100000")

    def test_benchmark_comparison_differential(self):
        # Portfolio daily return ~2.04 %, SPY = 0.5 %  → differential ~+1.54 %
        snap = _snapshot(cash="90000", equity_snapshot="100000", start_of_day="98000")
        benchmark_returns = {"SPY": Decimal("0.005"), "QQQ": Decimal("0.003")}
        scorecard = _svc().generate_daily_scorecard(
            snap, [], benchmark_returns, self._equity_curve()
        )
        bm = scorecard.benchmark_comparison
        # Check all benchmark keys are present
        assert "SPY" in bm.differentials
        assert "QQQ" in bm.differentials
        # Portfolio outperforms when positive
        assert bm.differentials["SPY"] == bm.portfolio_return - Decimal("0.005")

    def test_benchmark_comparison_portfolio_return_matches_snapshot(self):
        snap = _snapshot(equity_snapshot="100000", start_of_day="100000")
        scorecard = _svc().generate_daily_scorecard(
            snap, [], {"SPY": Decimal("0.01")}, self._equity_curve()
        )
        bm = scorecard.benchmark_comparison
        assert bm.portfolio_return == snap.daily_pnl_pct

    def test_drawdown_metrics_populated(self):
        # Known 20 % drawdown in curve
        curve = [Decimal(str(v)) for v in [100000, 120000, 96000]]
        snap = _snapshot()
        scorecard = _svc().generate_daily_scorecard(snap, [], {}, curve)
        assert scorecard.max_drawdown_pct == Decimal("0.2000")
        assert scorecard.current_drawdown_pct > Decimal("0")

    def test_attribution_by_ticker_populated(self):
        trades = [
            _trade("AAPL", exit_="110"),
            _trade("MSFT", exit_="220"),
        ]
        snap = _snapshot()
        scorecard = _svc().generate_daily_scorecard(
            snap, trades, {}, self._equity_curve()
        )
        tickers = {r.key for r in scorecard.attribution.by_ticker}
        assert "AAPL" in tickers
        assert "MSFT" in tickers

    def test_attribution_by_strategy_populated(self):
        trades = [_trade(strategy="momentum"), _trade(strategy="swing")]
        snap = _snapshot()
        scorecard = _svc().generate_daily_scorecard(
            snap, trades, {}, self._equity_curve()
        )
        strategies = {r.key for r in scorecard.attribution.by_strategy}
        assert "momentum" in strategies
        assert "swing" in strategies

    def test_attribution_by_theme_populated(self):
        trades = [_trade(theme="AI"), _trade(theme="defense")]
        snap = _snapshot()
        scorecard = _svc().generate_daily_scorecard(
            snap, trades, {}, self._equity_curve()
        )
        themes = {r.key for r in scorecard.attribution.by_theme}
        assert "AI" in themes
        assert "defense" in themes

    def test_mode_propagated_from_snapshot(self):
        snap = _snapshot()
        scorecard = _svc().generate_daily_scorecard(
            snap, [], {}, self._equity_curve()
        )
        assert scorecard.mode == "paper"

    def test_realized_pnl_sums_closed_trades(self):
        trades = [
            _trade(entry="100", exit_="110", qty="100"),   # +1000
            _trade(entry="100", exit_="95",  qty="100"),   # -500
        ]
        snap = _snapshot()
        scorecard = _svc().generate_daily_scorecard(
            snap, trades, {}, self._equity_curve()
        )
        assert scorecard.realized_pnl == Decimal("500.00")

    def test_unrealized_pnl_sums_open_positions(self):
        pos = PortfolioPosition(
            ticker="NVDA",
            quantity=Decimal("10"),
            avg_entry_price=Decimal("100"),
            current_price=Decimal("120"),
            opened_at=_NOW - dt.timedelta(days=3),
        )
        snap = _snapshot(positions=[pos])
        scorecard = _svc().generate_daily_scorecard(
            snap, [], {}, self._equity_curve()
        )
        # unrealized = (120 - 100) * 10 = 200
        assert scorecard.unrealized_pnl == Decimal("200.00")

    def test_net_pnl_is_realized_plus_unrealized(self):
        pos = PortfolioPosition(
            ticker="NVDA",
            quantity=Decimal("10"),
            avg_entry_price=Decimal("100"),
            current_price=Decimal("120"),
            opened_at=_NOW - dt.timedelta(days=3),
        )
        trades = [_trade(entry="100", exit_="110", qty="100")]  # +1000
        snap = _snapshot(positions=[pos])
        scorecard = _svc().generate_daily_scorecard(
            snap, trades, {}, self._equity_curve()
        )
        assert scorecard.net_pnl == scorecard.realized_pnl + scorecard.unrealized_pnl

    def test_scorecard_multiple_benchmarks(self):
        snap = _snapshot()
        bm = {"SPY": Decimal("0.005"), "QQQ": Decimal("0.003"), "IWM": Decimal("0.002")}
        scorecard = _svc().generate_daily_scorecard(
            snap, [], bm, self._equity_curve()
        )
        assert set(scorecard.benchmark_comparison.differentials.keys()) == {"SPY", "QQQ", "IWM"}
