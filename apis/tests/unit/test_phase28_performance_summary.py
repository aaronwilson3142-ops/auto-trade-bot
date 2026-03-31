"""
Phase 28 — Live Performance Summary + Closed Trade Grading + P&L Metrics
=========================================================================

Tests covering:
  - PerformanceSummaryResponse schema
  - GET /api/v1/portfolio/performance endpoint (no state, with state, edge cases)
  - GET /api/v1/portfolio/grades endpoint (list, filter, distribution)
  - Trade grading integration in paper_trading.py cycle
  - Prometheus metrics: apis_realized_pnl_usd, apis_unrealized_pnl_usd,
    apis_daily_return_pct

All tests are pure unit tests — no DB, no network, no broker credentials.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

# ── Shared helpers ─────────────────────────────────────────────────────────────

def _make_state(**kwargs):
    """Return a fresh ApiAppState, optionally with overrides."""
    from apps.api.state import ApiAppState
    state = ApiAppState()
    for k, v in kwargs.items():
        setattr(state, k, v)
    return state


def _make_portfolio_state(cash=Decimal("50000"), equity_extra=Decimal("0")):
    """Return a minimal PortfolioState."""
    from services.portfolio_engine.models import PortfolioState
    sod = cash + equity_extra
    return PortfolioState(
        cash=cash,
        start_of_day_equity=sod,
        high_water_mark=sod,
    )


def _make_closed_trade(ticker="AAPL", pnl=Decimal("500")):
    """Return a ClosedTrade with the given realized_pnl (positive = winner)."""
    from services.portfolio_engine.models import ActionType, ClosedTrade
    qty = Decimal("10")
    entry = Decimal("200")
    fill = entry + (pnl / qty)
    return ClosedTrade(
        ticker=ticker,
        action_type=ActionType.CLOSE,
        fill_price=fill,
        avg_entry_price=entry,
        quantity=qty,
        realized_pnl=pnl,
        realized_pnl_pct=(pnl / (entry * qty)).quantize(Decimal("0.0001")),
        reason="not_in_buy_set",
        opened_at=dt.datetime(2026, 3, 1, 10, 0, tzinfo=dt.UTC),
        closed_at=dt.datetime(2026, 3, 19, 15, 30, tzinfo=dt.UTC),
        hold_duration_days=18,
    )


def _make_position(ticker="AAPL", qty=10, entry=200.0, current=210.0):
    """Return a PortfolioPosition."""
    from services.portfolio_engine.models import PortfolioPosition
    return PortfolioPosition(
        ticker=ticker,
        quantity=Decimal(str(qty)),
        avg_entry_price=Decimal(str(entry)),
        current_price=Decimal(str(current)),
        opened_at=dt.datetime(2026, 3, 10, 9, 30, tzinfo=dt.UTC),
    )


# ── 1. PerformanceSummaryResponse Schema ──────────────────────────────────────

class TestPerformanceSummarySchema:
    def test_schema_fields_present(self):
        from apps.api.schemas.portfolio import PerformanceSummaryResponse
        r = PerformanceSummaryResponse(
            equity=100_000.0,
            start_of_day_equity=99_000.0,
            high_water_mark=105_000.0,
            daily_return_pct=1.0101,
            drawdown_from_hwm_pct=4.7619,
            total_realized_pnl=350.0,
            realized_trade_count=3,
            win_count=2,
            loss_count=1,
            win_rate=0.6667,
            total_unrealized_pnl=200.0,
            open_position_count=2,
            cash=50_000.0,
            as_of=dt.datetime.now(tz=dt.UTC),
        )
        assert r.equity == 100_000.0
        assert r.win_rate == pytest.approx(0.6667)

    def test_schema_win_rate_none(self):
        from apps.api.schemas.portfolio import PerformanceSummaryResponse
        r = PerformanceSummaryResponse(
            equity=100_000.0, start_of_day_equity=100_000.0,
            high_water_mark=None, daily_return_pct=0.0,
            drawdown_from_hwm_pct=0.0, total_realized_pnl=0.0,
            realized_trade_count=0, win_count=0, loss_count=0,
            win_rate=None, total_unrealized_pnl=0.0,
            open_position_count=0, cash=100_000.0,
            as_of=dt.datetime.now(tz=dt.UTC),
        )
        assert r.win_rate is None

    def test_schema_high_water_mark_optional(self):
        from apps.api.schemas.portfolio import PerformanceSummaryResponse
        r = PerformanceSummaryResponse(
            equity=50_000.0, start_of_day_equity=50_000.0,
            high_water_mark=None, daily_return_pct=0.0,
            drawdown_from_hwm_pct=0.0, total_realized_pnl=0.0,
            realized_trade_count=0, win_count=0, loss_count=0,
            win_rate=None, total_unrealized_pnl=0.0,
            open_position_count=0, cash=50_000.0,
            as_of=dt.datetime.now(tz=dt.UTC),
        )
        assert r.high_water_mark is None


# ── 2. TradeGradeRecord / TradeGradeHistoryResponse Schema ────────────────────

class TestTradeGradeSchemas:
    def test_trade_grade_record_fields(self):
        from apps.api.schemas.portfolio import TradeGradeRecord
        r = TradeGradeRecord(
            ticker="NVDA", strategy_key="momentum_v1",
            realized_pnl=250.0, realized_pnl_pct=0.125,
            holding_days=5, is_winner=True, exit_reason="thesis", grade="A",
        )
        assert r.grade == "A"
        assert r.is_winner is True

    def test_trade_grade_history_distribution(self):
        from apps.api.schemas.portfolio import TradeGradeHistoryResponse, TradeGradeRecord
        now = dt.datetime.now(tz=dt.UTC)
        items = [
            TradeGradeRecord(ticker="A", strategy_key="", realized_pnl=100.0,
                             realized_pnl_pct=0.05, holding_days=3,
                             is_winner=True, exit_reason="", grade="B"),
        ]
        r = TradeGradeHistoryResponse(
            count=1,
            grade_distribution={"A": 0, "B": 1, "C": 0, "D": 0, "F": 0},
            items=items,
        )
        assert r.grade_distribution["B"] == 1
        assert r.count == 1


# ── 3. GET /portfolio/performance — no portfolio state ───────────────────────

class TestPerformanceEndpointNoState:
    def test_returns_zeroes_when_no_portfolio(self):
        import asyncio

        from apps.api.routes.portfolio import get_performance_summary
        state = _make_state()
        result = asyncio.run(get_performance_summary(state))
        assert result.equity == 0.0
        assert result.daily_return_pct == 0.0
        assert result.win_rate is None
        assert result.high_water_mark is None

    def test_no_portfolio_win_count_zero(self):
        import asyncio

        from apps.api.routes.portfolio import get_performance_summary
        state = _make_state()
        result = asyncio.run(get_performance_summary(state))
        assert result.win_count == 0
        assert result.loss_count == 0
        assert result.realized_trade_count == 0


# ── 4. GET /portfolio/performance — equity metrics ───────────────────────────

class TestPerformanceSummaryEquityMetrics:
    def test_daily_return_pct_positive(self):
        import asyncio

        from apps.api.routes.portfolio import get_performance_summary
        ps = _make_portfolio_state(cash=Decimal("50000"))
        ps.start_of_day_equity = Decimal("50000")
        ps.cash = Decimal("51000")   # equity grows
        state = _make_state(portfolio_state=ps)
        result = asyncio.run(get_performance_summary(state))
        # equity == cash (no positions) = 51000; sod = 50000 → +2.0%
        assert result.daily_return_pct == pytest.approx(2.0, rel=1e-3)

    def test_daily_return_pct_negative(self):
        import asyncio

        from apps.api.routes.portfolio import get_performance_summary
        ps = _make_portfolio_state(cash=Decimal("50000"))
        ps.start_of_day_equity = Decimal("50000")
        ps.cash = Decimal("49000")
        state = _make_state(portfolio_state=ps)
        result = asyncio.run(get_performance_summary(state))
        assert result.daily_return_pct == pytest.approx(-2.0, rel=1e-3)

    def test_drawdown_from_hwm_positive(self):
        import asyncio

        from apps.api.routes.portfolio import get_performance_summary
        ps = _make_portfolio_state(cash=Decimal("45000"))
        ps.high_water_mark = Decimal("50000")
        ps.start_of_day_equity = Decimal("48000")
        state = _make_state(portfolio_state=ps)
        result = asyncio.run(get_performance_summary(state))
        # equity=45000, hwm=50000 → (50000-45000)/50000*100 = 10%
        assert result.drawdown_from_hwm_pct == pytest.approx(10.0, rel=1e-3)

    def test_drawdown_clamped_to_zero_when_above_hwm(self):
        import asyncio

        from apps.api.routes.portfolio import get_performance_summary
        ps = _make_portfolio_state(cash=Decimal("55000"))
        ps.high_water_mark = Decimal("50000")
        ps.start_of_day_equity = Decimal("50000")
        state = _make_state(portfolio_state=ps)
        result = asyncio.run(get_performance_summary(state))
        assert result.drawdown_from_hwm_pct == 0.0

    def test_sod_zero_safe(self):
        """start_of_day_equity=0 should not cause ZeroDivisionError."""
        import asyncio

        from apps.api.routes.portfolio import get_performance_summary
        ps = _make_portfolio_state(cash=Decimal("100"))
        ps.start_of_day_equity = Decimal("0")
        state = _make_state(portfolio_state=ps)
        result = asyncio.run(get_performance_summary(state))
        assert result.daily_return_pct == 0.0


# ── 5. GET /portfolio/performance — realized P&L ─────────────────────────────

class TestPerformanceSummaryRealizedPnl:
    def test_total_realized_pnl_sum(self):
        import asyncio

        from apps.api.routes.portfolio import get_performance_summary
        ps = _make_portfolio_state()
        ct1 = _make_closed_trade("AAPL", pnl=Decimal("300"))
        ct2 = _make_closed_trade("NVDA", pnl=Decimal("200"))
        state = _make_state(portfolio_state=ps, closed_trades=[ct1, ct2])
        result = asyncio.run(get_performance_summary(state))
        assert result.total_realized_pnl == pytest.approx(500.0, rel=1e-3)

    def test_win_loss_counts(self):
        import asyncio

        from apps.api.routes.portfolio import get_performance_summary
        ps = _make_portfolio_state()
        ct1 = _make_closed_trade("AAPL", pnl=Decimal("300"))   # winner
        ct2 = _make_closed_trade("NVDA", pnl=Decimal("-100"))  # loser
        ct3 = _make_closed_trade("MSFT", pnl=Decimal("50"))    # winner
        state = _make_state(portfolio_state=ps, closed_trades=[ct1, ct2, ct3])
        result = asyncio.run(get_performance_summary(state))
        assert result.win_count == 2
        assert result.loss_count == 1

    def test_win_rate_calculation(self):
        import asyncio

        from apps.api.routes.portfolio import get_performance_summary
        ps = _make_portfolio_state()
        trades = [
            _make_closed_trade("A", pnl=Decimal("100")),
            _make_closed_trade("B", pnl=Decimal("100")),
            _make_closed_trade("C", pnl=Decimal("-50")),
            _make_closed_trade("D", pnl=Decimal("-50")),
        ]
        state = _make_state(portfolio_state=ps, closed_trades=trades)
        result = asyncio.run(get_performance_summary(state))
        assert result.win_rate == pytest.approx(0.5, rel=1e-3)

    def test_win_rate_none_when_no_trades(self):
        import asyncio

        from apps.api.routes.portfolio import get_performance_summary
        ps = _make_portfolio_state()
        state = _make_state(portfolio_state=ps)
        result = asyncio.run(get_performance_summary(state))
        assert result.win_rate is None


# ── 6. GET /portfolio/performance — unrealized P&L ────────────────────────────

class TestPerformanceSummaryUnrealized:
    def test_unrealized_pnl_from_positions(self):
        import asyncio

        from apps.api.routes.portfolio import get_performance_summary
        ps = _make_portfolio_state()
        # AAPL: 10 shares, entry=200, current=210 → unrealized = 100
        # NVDA: 5 shares, entry=500, current=490 → unrealized = -50
        ps.positions["AAPL"] = _make_position("AAPL", qty=10, entry=200, current=210)
        ps.positions["NVDA"] = _make_position("NVDA", qty=5, entry=500, current=490)
        state = _make_state(portfolio_state=ps)
        result = asyncio.run(get_performance_summary(state))
        assert result.total_unrealized_pnl == pytest.approx(50.0, rel=1e-2)

    def test_open_position_count(self):
        import asyncio

        from apps.api.routes.portfolio import get_performance_summary
        ps = _make_portfolio_state()
        ps.positions["AAPL"] = _make_position("AAPL")
        ps.positions["NVDA"] = _make_position("NVDA")
        state = _make_state(portfolio_state=ps)
        result = asyncio.run(get_performance_summary(state))
        assert result.open_position_count == 2

    def test_no_positions_unrealized_zero(self):
        import asyncio

        from apps.api.routes.portfolio import get_performance_summary
        ps = _make_portfolio_state()
        state = _make_state(portfolio_state=ps)
        result = asyncio.run(get_performance_summary(state))
        assert result.total_unrealized_pnl == 0.0
        assert result.open_position_count == 0


# ── 7. GET /portfolio/grades endpoint ────────────────────────────────────────

class TestTradeGradeEndpoint:
    def _make_grade(self, ticker="AAPL", grade="B", pnl=100.0, pnl_pct=0.05):
        from services.evaluation_engine.models import PositionGrade
        return PositionGrade(
            ticker=ticker,
            strategy_key="",
            realized_pnl=Decimal(str(pnl)),
            realized_pnl_pct=Decimal(str(pnl_pct)),
            holding_days=5,
            is_winner=pnl > 0,
            exit_reason="test",
            grade=grade,
        )

    def test_empty_grades_returns_empty(self):
        import asyncio

        from apps.api.routes.portfolio import get_trade_grades
        state = _make_state()
        result = asyncio.run(get_trade_grades(limit=50, ticker=None, state=state))
        assert result.count == 0
        assert result.items == []

    def test_grades_returned_most_recent_first(self):
        import asyncio

        from apps.api.routes.portfolio import get_trade_grades
        grades = [
            self._make_grade("AAPL", "A"),
            self._make_grade("NVDA", "B"),
            self._make_grade("MSFT", "C"),
        ]
        state = _make_state(trade_grades=grades)
        result = asyncio.run(get_trade_grades(limit=50, ticker=None, state=state))
        # reversed → MSFT, NVDA, AAPL
        assert result.items[0].ticker == "MSFT"
        assert result.items[-1].ticker == "AAPL"

    def test_ticker_filter_case_insensitive(self):
        import asyncio

        from apps.api.routes.portfolio import get_trade_grades
        grades = [
            self._make_grade("AAPL", "A"),
            self._make_grade("NVDA", "B"),
        ]
        state = _make_state(trade_grades=grades)
        result = asyncio.run(get_trade_grades(limit=50, ticker="aapl", state=state))
        assert result.count == 1
        assert result.items[0].ticker == "AAPL"

    def test_limit_respected(self):
        import asyncio

        from apps.api.routes.portfolio import get_trade_grades
        grades = [self._make_grade(f"T{i}", "C") for i in range(20)]
        state = _make_state(trade_grades=grades)
        result = asyncio.run(get_trade_grades(limit=5, ticker=None, state=state))
        assert result.count == 5

    def test_grade_distribution_counts(self):
        import asyncio

        from apps.api.routes.portfolio import get_trade_grades
        grades = [
            self._make_grade("A1", "A"), self._make_grade("A2", "A"),
            self._make_grade("B1", "B"),
            self._make_grade("F1", "F"), self._make_grade("F2", "F"),
        ]
        state = _make_state(trade_grades=grades)
        result = asyncio.run(get_trade_grades(limit=50, ticker=None, state=state))
        assert result.grade_distribution["A"] == 2
        assert result.grade_distribution["B"] == 1
        assert result.grade_distribution["F"] == 2
        assert result.grade_distribution["C"] == 0


# ── 8. Paper cycle integration — grading wired ──────────────────────────────

class TestPaperCycleGradeIntegration:
    def _make_ranked(self, ticker, score="0.80"):
        from decimal import Decimal

        from services.ranking_engine.models import RankedResult
        return RankedResult(
            rank_position=1,
            security_id=uuid.uuid4(),
            ticker=ticker,
            composite_score=Decimal(score),
            portfolio_fit_score=Decimal("0.70"),
            recommended_action="buy",
            target_horizon="medium_term",
            thesis_summary="test",
            disconfirming_factors="",
            sizing_hint_pct=Decimal("0.08"),
            source_reliability_tier="secondary_verified",
            contains_rumor=False,
            contributing_signals=[],
            as_of=dt.datetime.utcnow(),
        )

    def _make_app_state_with_position(self):
        from apps.api.state import ApiAppState
        from broker_adapters.base.models import OrderRequest, OrderSide, OrderType
        from broker_adapters.paper.adapter import PaperBrokerAdapter
        from services.portfolio_engine.models import PortfolioPosition, PortfolioState

        broker = PaperBrokerAdapter(starting_cash=Decimal("50000"), market_open=True)
        broker.connect()
        broker.set_price("AAPL", Decimal("200.00"))
        broker.place_order(OrderRequest(
            idempotency_key="buy_aapl_phase28",
            ticker="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("50"),
        ))

        app_state = ApiAppState()
        ps = PortfolioState(
            cash=broker.get_account_state().cash_balance,
            start_of_day_equity=Decimal("50000"),
            high_water_mark=Decimal("50000"),
        )
        for bp in broker.list_positions():
            ps.positions[bp.ticker] = PortfolioPosition(
                ticker=bp.ticker,
                quantity=bp.quantity,
                avg_entry_price=bp.average_entry_price,
                current_price=bp.current_price,
                opened_at=dt.datetime(2026, 3, 1, 9, 35, tzinfo=dt.UTC),
            )
        app_state.portfolio_state = ps
        app_state.broker_adapter = broker
        # No AAPL in rankings → engine will CLOSE it
        app_state.latest_rankings = [self._make_ranked("NVDA")]
        return app_state, broker

    def test_cycle_appends_trade_grade(self):
        """A CLOSE fill should generate a PositionGrade in trade_grades."""
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from config.settings import OperatingMode, Settings

        cfg = Settings(operating_mode=OperatingMode.PAPER)
        app_state, broker = self._make_app_state_with_position()
        broker.set_price("NVDA", Decimal("500.00"))

        result = run_paper_trading_cycle(app_state=app_state, settings=cfg, broker=broker)
        assert result["status"] == "ok"
        # At least one grade should be recorded
        assert len(app_state.trade_grades) >= 1

    def test_cycle_grade_ticker_matches_closed_trade(self):
        """Trade grade ticker should match the closed trade ticker."""
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from config.settings import OperatingMode, Settings

        cfg = Settings(operating_mode=OperatingMode.PAPER)
        app_state, broker = self._make_app_state_with_position()
        broker.set_price("NVDA", Decimal("500.00"))

        run_paper_trading_cycle(app_state=app_state, settings=cfg, broker=broker)
        closed_tickers = {t.ticker for t in app_state.closed_trades}
        graded_tickers = {g.ticker for g in app_state.trade_grades}
        # Every graded ticker must correspond to a closed trade
        assert graded_tickers <= closed_tickers

    def test_cycle_grade_has_letter_grade(self):
        """Each PositionGrade must have a valid letter grade A-F."""
        from apps.worker.jobs.paper_trading import run_paper_trading_cycle
        from config.settings import OperatingMode, Settings

        cfg = Settings(operating_mode=OperatingMode.PAPER)
        app_state, broker = self._make_app_state_with_position()
        broker.set_price("NVDA", Decimal("500.00"))

        run_paper_trading_cycle(app_state=app_state, settings=cfg, broker=broker)
        for grade in app_state.trade_grades:
            assert grade.grade in ("A", "B", "C", "D", "F")


# ── 9. Prometheus metrics phase 28 ───────────────────────────────────────────

class TestPrometheusMetricsPhase28:
    def _scrape(self, state, settings=None):
        import asyncio

        from apps.api.routes.metrics import prometheus_metrics
        from config.settings import Settings
        cfg = settings or Settings()
        return asyncio.run(
            prometheus_metrics(state=state, settings=cfg)
        )

    def test_realized_pnl_gauge_present(self):
        state = _make_state()
        scrape = self._scrape(state)
        assert "apis_realized_pnl_usd" in scrape

    def test_unrealized_pnl_gauge_present(self):
        state = _make_state()
        scrape = self._scrape(state)
        assert "apis_unrealized_pnl_usd" in scrape

    def test_daily_return_pct_gauge_present(self):
        state = _make_state()
        scrape = self._scrape(state)
        assert "apis_daily_return_pct" in scrape

    def test_realized_pnl_reflects_closed_trades(self):
        ct1 = _make_closed_trade("AAPL", pnl=Decimal("300"))
        ct2 = _make_closed_trade("NVDA", pnl=Decimal("200"))
        state = _make_state(closed_trades=[ct1, ct2])
        scrape = self._scrape(state)
        assert "500.0" in scrape or "500" in scrape

    def test_no_closed_trades_realized_pnl_zero(self):
        state = _make_state()
        scrape = self._scrape(state)
        # apis_realized_pnl_usd 0.0 should appear
        lines = [l for l in scrape.splitlines() if "apis_realized_pnl_usd" in l and not l.startswith("#")]
        assert len(lines) == 1
        value = float(lines[0].split()[-2])
        assert value == 0.0

    def test_daily_return_pct_nonzero_when_equity_grew(self):
        ps = _make_portfolio_state(cash=Decimal("51000"))
        ps.start_of_day_equity = Decimal("50000")
        state = _make_state(portfolio_state=ps)
        scrape = self._scrape(state)
        lines = [l for l in scrape.splitlines() if "apis_daily_return_pct" in l and not l.startswith("#")]
        assert len(lines) == 1
        value = float(lines[0].split()[-2])
        assert value == pytest.approx(2.0, rel=1e-3)
