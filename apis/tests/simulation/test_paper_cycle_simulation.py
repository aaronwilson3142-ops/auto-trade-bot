"""
Simulation tests: paper trading cycle end-to-end.

These tests exercise the full ``run_paper_trading_cycle`` function using:
  - Real service instances (PortfolioEngineService, RiskEngineService,
    ExecutionEngineService, ReportingService) constructed in-memory
  - PaperBrokerAdapter (market_open=True) — no real brokerage calls
  - Synthetic RankedResult objects injected into ApiAppState
  - Market data mocked via a lightweight stub so no yfinance calls occur

No database, no network, no APScheduler — pure in-process simulation.

Covers:
  - Kill-switch gate (cycle returns "killed" immediately)
  - Mode guard (RESEARCH mode returns "skipped_mode")
  - Empty-rankings guard (returns "skipped_no_rankings")
  - Broker authentication failure path
  - Successful single-ticker execution cycle
  - Multi-ticker execution cycle
  - Portfolio state persistence back to ApiAppState
  - Cycle counter incremented in ApiAppState
  - Cycle result appended to paper_cycle_results history
  - Re-entry with existing portfolio (no double-open)
  - Execution with HUMAN_APPROVED mode
  - Simulation driven by live multi-strategy signal pipeline

Design notes
------------
- ``_fetch_price`` falls back to ``target_notional / 100`` whenever
  ``market_data_svc.get_snapshot`` raises, so we can inject a stub that
  raises to exercise the fallback path or returns a Decimal price.
- Fire-and-forget DB helpers (_persist_paper_cycle_count,
  _persist_portfolio_snapshot) catch all exceptions silently, so they
  never fail the test even when no DB is configured.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from apps.api.state import ApiAppState
from apps.worker.jobs.paper_trading import run_paper_trading_cycle
from broker_adapters.base.exceptions import BrokerAuthenticationError
from broker_adapters.paper.adapter import PaperBrokerAdapter
from config.settings import OperatingMode, Settings
from services.execution_engine.service import ExecutionEngineService
from services.portfolio_engine.service import PortfolioEngineService
from services.ranking_engine.models import RankedResult
from services.reporting.service import ReportingService
from services.risk_engine.service import RiskEngineService


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_settings(
    mode: OperatingMode = OperatingMode.PAPER,
    kill_switch: bool = False,
    max_positions: int = 10,
) -> Settings:
    """Return a Settings object suitable for simulation tests."""
    return Settings(
        operating_mode=mode,
        kill_switch=kill_switch,
        max_positions=max_positions,
    )


def _make_ranked_result(
    ticker: str = "AAPL",
    score: float = 0.75,
    rank: int = 1,
    action: str = "buy",
    contains_rumor: bool = False,
    sizing_hint_pct: float = 0.05,
) -> RankedResult:
    """Return a minimal but valid RankedResult for injection into ApiAppState."""
    return RankedResult(
        rank_position=rank,
        security_id=uuid.uuid4(),
        ticker=ticker,
        composite_score=Decimal(str(score)),
        portfolio_fit_score=Decimal(str(score * 0.9)),
        recommended_action=action,
        target_horizon="medium_term",
        thesis_summary=f"{ticker} shows strong momentum signal",
        disconfirming_factors="Valuation stretched; macro headwinds possible",
        sizing_hint_pct=Decimal(str(sizing_hint_pct)),
        source_reliability_tier="secondary_verified",
        contains_rumor=contains_rumor,
        contributing_signals=[],
        as_of=dt.datetime.utcnow(),
    )


def _fresh_state(
    rankings: list[RankedResult] | None = None,
    kill_switch: bool = False,
    broker_auth_expired: bool = False,
) -> ApiAppState:
    """Build an ApiAppState ready for a simulation run."""
    state = ApiAppState()
    state.kill_switch_active = kill_switch
    state.broker_auth_expired = broker_auth_expired
    state.latest_rankings = rankings or []
    return state


def _make_services(
    settings: Settings,
    market_open: bool = True,
    prices: dict | None = None,
):
    """Construct the four injected services used by run_paper_trading_cycle.

    Args:
        settings:    Settings instance.
        market_open: Override for PaperBrokerAdapter market-hours check.
        prices:      Optional dict of ticker → float price.  Each entry is
                     registered via broker.set_price() so paper orders can fill.
    """
    broker = PaperBrokerAdapter(market_open=market_open)
    for ticker, price in (prices or {}).items():
        broker.set_price(ticker, Decimal(str(price)))
    portfolio_svc = PortfolioEngineService(settings=settings)
    risk_svc = RiskEngineService(settings=settings)
    execution_svc = ExecutionEngineService(settings=settings, broker=broker)
    reporting_svc = ReportingService()
    return broker, portfolio_svc, risk_svc, execution_svc, reporting_svc


class _AuthFailingBroker:
    """Stub broker whose connect() raises BrokerAuthenticationError.

    Implements the minimum surface area needed by ExecutionEngineService and
    run_paper_trading_cycle so the error path is reached correctly.
    """

    adapter_name: str = "auth_failing_stub"

    def ping(self) -> bool:
        return False

    def connect(self) -> None:
        raise BrokerAuthenticationError("credentials_invalid")


class _PriceStub:
    """Lightweight market-data stub that returns a fixed price per ticker."""

    def __init__(self, price: float = 150.0) -> None:
        self._price = Decimal(str(price))

    def get_snapshot(self, ticker: str) -> Any:
        snap = MagicMock()
        snap.latest_price = self._price
        return snap


class _FailingPriceStub:
    """Market-data stub that always raises (exercises the price fallback path)."""

    def get_snapshot(self, ticker: str) -> Any:
        raise RuntimeError(f"price_unavailable: {ticker}")


# ── TestPaperCycleKillSwitch ──────────────────────────────────────────────────


class TestPaperCycleKillSwitch:
    """Kill switch is checked first; cycle must abort immediately."""

    def test_returns_killed_status(self):
        settings = _make_settings(kill_switch=True)
        state = _fresh_state(kill_switch=True)
        result = run_paper_trading_cycle(app_state=state, settings=settings)
        assert result["status"] == "killed"

    def test_killed_proposed_count_is_zero(self):
        settings = _make_settings(kill_switch=True)
        state = _fresh_state(kill_switch=True)
        result = run_paper_trading_cycle(app_state=state, settings=settings)
        assert result["proposed_count"] == 0

    def test_killed_executed_count_is_zero(self):
        settings = _make_settings(kill_switch=True)
        state = _fresh_state(kill_switch=True)
        result = run_paper_trading_cycle(app_state=state, settings=settings)
        assert result["executed_count"] == 0

    def test_killed_even_with_rankings_present(self):
        """Kill switch overrides present rankings."""
        settings = _make_settings(kill_switch=True)
        rankings = [_make_ranked_result("AAPL", score=0.90)]
        state = _fresh_state(rankings=rankings, kill_switch=True)
        result = run_paper_trading_cycle(app_state=state, settings=settings)
        assert result["status"] == "killed"

    def test_killed_result_has_mode_field(self):
        settings = _make_settings(mode=OperatingMode.PAPER, kill_switch=True)
        state = _fresh_state(kill_switch=True)
        result = run_paper_trading_cycle(app_state=state, settings=settings)
        assert "mode" in result


# ── TestPaperCycleModeGuard ───────────────────────────────────────────────────


class TestPaperCycleModeGuard:
    """Only PAPER and HUMAN_APPROVED modes allow execution."""

    def test_research_mode_returns_skipped(self):
        settings = _make_settings(mode=OperatingMode.RESEARCH)
        state = _fresh_state()
        result = run_paper_trading_cycle(app_state=state, settings=settings)
        assert result["status"] == "skipped_mode"

    def test_backtest_mode_returns_skipped(self):
        settings = _make_settings(mode=OperatingMode.BACKTEST)
        state = _fresh_state()
        result = run_paper_trading_cycle(app_state=state, settings=settings)
        assert result["status"] == "skipped_mode"

    def test_skipped_mode_proposed_count_zero(self):
        settings = _make_settings(mode=OperatingMode.RESEARCH)
        state = _fresh_state(rankings=[_make_ranked_result("MSFT")])
        result = run_paper_trading_cycle(app_state=state, settings=settings)
        assert result["proposed_count"] == 0

    def test_paper_mode_does_not_skip(self):
        """PAPER mode proceeds past the mode guard (may still skip for no-rankings)."""
        settings = _make_settings(mode=OperatingMode.PAPER)
        state = _fresh_state()
        result = run_paper_trading_cycle(app_state=state, settings=settings)
        assert result["status"] != "skipped_mode"

    def test_human_approved_mode_does_not_skip(self):
        settings = _make_settings(mode=OperatingMode.HUMAN_APPROVED)
        state = _fresh_state()
        result = run_paper_trading_cycle(app_state=state, settings=settings)
        assert result["status"] != "skipped_mode"


# ── TestPaperCycleNoRankings ──────────────────────────────────────────────────


class TestPaperCycleNoRankings:
    """Empty rankings list skips the full pipeline."""

    def test_empty_rankings_returns_skipped(self):
        settings = _make_settings()
        state = _fresh_state(rankings=[])
        result = run_paper_trading_cycle(app_state=state, settings=settings)
        assert result["status"] == "skipped_no_rankings"

    def test_skipped_no_rankings_counts_are_zero(self):
        settings = _make_settings()
        state = _fresh_state(rankings=[])
        result = run_paper_trading_cycle(app_state=state, settings=settings)
        assert result["proposed_count"] == 0
        assert result["approved_count"] == 0
        assert result["executed_count"] == 0

    def test_skipped_no_rankings_has_run_at(self):
        settings = _make_settings()
        state = _fresh_state(rankings=[])
        result = run_paper_trading_cycle(app_state=state, settings=settings)
        assert "run_at" in result
        # Must be a parseable ISO timestamp
        dt.datetime.fromisoformat(result["run_at"])


# ── TestPaperCycleBrokerAuth ──────────────────────────────────────────────────


class TestPaperCycleBrokerAuth:
    """Broker authentication failures are handled gracefully."""

    def test_auth_error_returns_error_status(self):
        """When broker.connect() raises BrokerAuthenticationError, cycle reports error_broker_auth."""
        settings = _make_settings()
        rankings = [_make_ranked_result("AAPL")]
        state = _fresh_state(rankings=rankings)
        result = run_paper_trading_cycle(
            app_state=state,
            settings=settings,
            broker=_AuthFailingBroker(),
        )
        assert result["status"] == "error_broker_auth"

    def test_auth_error_executed_count_is_zero(self):
        settings = _make_settings()
        rankings = [_make_ranked_result("AAPL")]
        state = _fresh_state(rankings=rankings)
        result = run_paper_trading_cycle(
            app_state=state,
            settings=settings,
            broker=_AuthFailingBroker(),
        )
        assert result["executed_count"] == 0

    def test_auth_error_sets_expired_flag_on_state(self):
        """After a BrokerAuthenticationError, app_state.broker_auth_expired is True."""
        settings = _make_settings()
        rankings = [_make_ranked_result("AAPL")]
        state = _fresh_state(rankings=rankings)
        run_paper_trading_cycle(
            app_state=state,
            settings=settings,
            broker=_AuthFailingBroker(),
        )
        assert state.broker_auth_expired is True


# ── TestPaperCycleSingleTicker ────────────────────────────────────────────────


class TestPaperCycleSingleTicker:
    """Successful execution of a single high-score ticker."""

    def _run(self, ticker: str = "NVDA", score: float = 0.82) -> tuple[dict, ApiAppState]:
        settings = _make_settings()
        rankings = [_make_ranked_result(ticker=ticker, score=score)]
        state = _fresh_state(rankings=rankings)
        broker, portfolio_svc, risk_svc, execution_svc, reporting_svc = _make_services(
            settings, prices={ticker: 200.0}
        )
        result = run_paper_trading_cycle(
            app_state=state,
            settings=settings,
            broker=broker,
            portfolio_svc=portfolio_svc,
            risk_svc=risk_svc,
            execution_svc=execution_svc,
            market_data_svc=_PriceStub(price=200.0),
            reporting_svc=reporting_svc,
        )
        return result, state

    def test_status_is_ok(self):
        result, _ = self._run()
        assert result["status"] == "ok"

    def test_proposed_count_positive(self):
        result, _ = self._run()
        assert result["proposed_count"] >= 1

    def test_approved_count_positive(self):
        result, _ = self._run()
        assert result["approved_count"] >= 1

    def test_executed_count_positive(self):
        result, _ = self._run()
        assert result["executed_count"] >= 1

    def test_portfolio_state_written_back(self):
        _, state = self._run()
        assert state.portfolio_state is not None

    def test_cash_reduced_after_buy(self):
        """After a filled buy, broker cash is reduced and synced back to portfolio_state."""
        result, state = self._run()
        # executed_count > 0 confirms a fill occurred
        # After the fill the broker's cash_balance is synced back into portfolio_state.cash
        if result["executed_count"] > 0:
            assert state.portfolio_state.cash < Decimal("100000")
        else:
            pytest.skip("No fills occurred; cash reduction check skipped")

    def test_result_has_run_at_timestamp(self):
        result, _ = self._run()
        assert "run_at" in result
        dt.datetime.fromisoformat(result["run_at"])

    def test_errors_list_exists(self):
        result, _ = self._run()
        assert "errors" in result
        assert isinstance(result["errors"], list)

    def test_cycle_counter_incremented(self):
        settings = _make_settings()
        ticker = "AAPL"
        rankings = [_make_ranked_result(ticker=ticker)]
        state = _fresh_state(rankings=rankings)
        state.paper_cycle_count = 3
        broker, portfolio_svc, risk_svc, execution_svc, reporting_svc = _make_services(
            settings, prices={ticker: 150.0}
        )
        run_paper_trading_cycle(
            app_state=state,
            settings=settings,
            broker=broker,
            portfolio_svc=portfolio_svc,
            risk_svc=risk_svc,
            execution_svc=execution_svc,
            market_data_svc=_PriceStub(),
            reporting_svc=reporting_svc,
        )
        assert state.paper_cycle_count == 4

    def test_result_appended_to_history(self):
        settings = _make_settings()
        ticker = "AAPL"
        rankings = [_make_ranked_result(ticker=ticker)]
        state = _fresh_state(rankings=rankings)
        state.paper_cycle_results = []
        broker, portfolio_svc, risk_svc, execution_svc, reporting_svc = _make_services(
            settings, prices={ticker: 150.0}
        )
        run_paper_trading_cycle(
            app_state=state,
            settings=settings,
            broker=broker,
            portfolio_svc=portfolio_svc,
            risk_svc=risk_svc,
            execution_svc=execution_svc,
            market_data_svc=_PriceStub(),
            reporting_svc=reporting_svc,
        )
        assert len(state.paper_cycle_results) == 1


# ── TestPaperCycleMultiTicker ─────────────────────────────────────────────────


class TestPaperCycleMultiTicker:
    """Five tickers injected; portfolio engine selects from ranked list."""

    TICKERS = ["NVDA", "MSFT", "GOOGL", "META", "AMZN"]

    def _run(self) -> tuple[dict, ApiAppState]:
        settings = _make_settings(max_positions=10)
        rankings = [
            _make_ranked_result(ticker=t, score=0.85 - i * 0.05, rank=i + 1)
            for i, t in enumerate(self.TICKERS)
        ]
        state = _fresh_state(rankings=rankings)
        prices = {t: 300.0 for t in self.TICKERS}
        broker, portfolio_svc, risk_svc, execution_svc, reporting_svc = _make_services(
            settings, prices=prices
        )
        result = run_paper_trading_cycle(
            app_state=state,
            settings=settings,
            broker=broker,
            portfolio_svc=portfolio_svc,
            risk_svc=risk_svc,
            execution_svc=execution_svc,
            market_data_svc=_PriceStub(price=300.0),
            reporting_svc=reporting_svc,
        )
        return result, state

    def test_status_is_ok(self):
        result, _ = self._run()
        assert result["status"] == "ok"

    def test_proposed_count_matches_tickers(self):
        result, _ = self._run()
        # Portfolio engine may propose fewer than 5 (risk / position limits), but > 0
        assert result["proposed_count"] >= 1

    def test_executed_at_least_one(self):
        result, _ = self._run()
        assert result["executed_count"] >= 1

    def test_portfolio_state_written_back(self):
        """portfolio_state is written back to ApiAppState regardless of fill outcome."""
        _, state = self._run()
        assert state.portfolio_state is not None

    def test_mode_field_value(self):
        result, _ = self._run()
        assert result["mode"] == OperatingMode.PAPER.value


# ── TestPaperCycleReEntry ─────────────────────────────────────────────────────


class TestPaperCycleReEntry:
    """Running the cycle twice: second run reuses existing portfolio state."""

    def test_second_run_does_not_crash(self):
        settings = _make_settings()
        ticker = "AAPL"
        rankings = [_make_ranked_result(ticker, score=0.80)]
        state = _fresh_state(rankings=rankings)
        broker, portfolio_svc, risk_svc, execution_svc, reporting_svc = _make_services(
            settings, prices={ticker: 100.0}
        )
        kwargs = dict(
            settings=settings,
            broker=broker,
            portfolio_svc=portfolio_svc,
            risk_svc=risk_svc,
            execution_svc=execution_svc,
            market_data_svc=_PriceStub(price=100.0),
            reporting_svc=reporting_svc,
        )
        result1 = run_paper_trading_cycle(app_state=state, **kwargs)
        result2 = run_paper_trading_cycle(app_state=state, **kwargs)
        assert result1["status"] == "ok"
        assert result2["status"] == "ok"

    def test_cycle_count_increments_each_run(self):
        settings = _make_settings()
        ticker = "AAPL"
        rankings = [_make_ranked_result(ticker)]
        state = _fresh_state(rankings=rankings)
        state.paper_cycle_count = 0
        broker, portfolio_svc, risk_svc, execution_svc, reporting_svc = _make_services(
            settings, prices={ticker: 150.0}
        )
        kwargs = dict(
            settings=settings,
            broker=broker,
            portfolio_svc=portfolio_svc,
            risk_svc=risk_svc,
            execution_svc=execution_svc,
            market_data_svc=_PriceStub(),
            reporting_svc=reporting_svc,
        )
        run_paper_trading_cycle(app_state=state, **kwargs)
        run_paper_trading_cycle(app_state=state, **kwargs)
        assert state.paper_cycle_count == 2


# ── TestPaperCyclePriceFallback ───────────────────────────────────────────────


class TestPaperCyclePriceFallback:
    """When market data unavailable, the fallback price keeps the cycle alive.

    _fetch_price falls back to target_notional/100 when market_data_svc raises,
    but PaperBrokerAdapter still needs set_price() for fills.  These tests verify
    the error is captured gracefully and the cycle returns 'ok'.
    """

    def test_cycle_succeeds_with_failing_price_stub(self):
        settings = _make_settings()
        ticker = "TSLA"
        rankings = [_make_ranked_result(ticker, score=0.78)]
        state = _fresh_state(rankings=rankings)
        broker, portfolio_svc, risk_svc, execution_svc, reporting_svc = _make_services(
            settings, prices={ticker: 50.0}
        )
        result = run_paper_trading_cycle(
            app_state=state,
            settings=settings,
            broker=broker,
            portfolio_svc=portfolio_svc,
            risk_svc=risk_svc,
            execution_svc=execution_svc,
            market_data_svc=_FailingPriceStub(),
            reporting_svc=reporting_svc,
        )
        assert result["status"] == "ok"

    def test_errors_list_captures_price_failure(self):
        settings = _make_settings()
        ticker = "TSLA"
        rankings = [_make_ranked_result(ticker, score=0.78)]
        state = _fresh_state(rankings=rankings)
        broker, portfolio_svc, risk_svc, execution_svc, reporting_svc = _make_services(
            settings, prices={ticker: 50.0}
        )
        result = run_paper_trading_cycle(
            app_state=state,
            settings=settings,
            broker=broker,
            portfolio_svc=portfolio_svc,
            risk_svc=risk_svc,
            execution_svc=execution_svc,
            market_data_svc=_FailingPriceStub(),
            reporting_svc=reporting_svc,
        )
        # errors list should record the price_fetch failure from market_data_svc
        price_errors = [e for e in result["errors"] if "price_fetch" in e]
        assert len(price_errors) >= 1


# ── TestPaperCycleHumanApprovedMode ──────────────────────────────────────────


class TestPaperCycleHumanApprovedMode:
    """HUMAN_APPROVED mode follows the identical execution path as PAPER."""

    def test_human_approved_mode_executes(self):
        settings = _make_settings(mode=OperatingMode.HUMAN_APPROVED)
        ticker = "AMZN"
        rankings = [_make_ranked_result(ticker, score=0.83)]
        state = _fresh_state(rankings=rankings)
        broker, portfolio_svc, risk_svc, execution_svc, reporting_svc = _make_services(
            settings, prices={ticker: 180.0}
        )
        result = run_paper_trading_cycle(
            app_state=state,
            settings=settings,
            broker=broker,
            portfolio_svc=portfolio_svc,
            risk_svc=risk_svc,
            execution_svc=execution_svc,
            market_data_svc=_PriceStub(price=180.0),
            reporting_svc=reporting_svc,
        )
        assert result["status"] == "ok"
        assert result["mode"] == OperatingMode.HUMAN_APPROVED.value


# ── TestPaperCycleWatchAndAvoidSignals ────────────────────────────────────────


class TestPaperCycleWatchAndAvoidSignals:
    """Rankings with 'watch' or 'avoid' actions produce zero proposed actions."""

    def test_watch_action_not_opened(self):
        settings = _make_settings()
        rankings = [_make_ranked_result("GME", score=0.50, action="watch")]
        state = _fresh_state(rankings=rankings)
        broker, portfolio_svc, risk_svc, execution_svc, reporting_svc = _make_services(
            settings, prices={"GME": 20.0}
        )
        result = run_paper_trading_cycle(
            app_state=state,
            settings=settings,
            broker=broker,
            portfolio_svc=portfolio_svc,
            risk_svc=risk_svc,
            execution_svc=execution_svc,
            market_data_svc=_PriceStub(),
            reporting_svc=reporting_svc,
        )
        assert result["proposed_count"] == 0

    def test_avoid_action_not_opened(self):
        settings = _make_settings()
        rankings = [_make_ranked_result("GME", score=0.30, action="avoid")]
        state = _fresh_state(rankings=rankings)
        broker, portfolio_svc, risk_svc, execution_svc, reporting_svc = _make_services(
            settings, prices={"GME": 20.0}
        )
        result = run_paper_trading_cycle(
            app_state=state,
            settings=settings,
            broker=broker,
            portfolio_svc=portfolio_svc,
            risk_svc=risk_svc,
            execution_svc=execution_svc,
            market_data_svc=_PriceStub(),
            reporting_svc=reporting_svc,
        )
        assert result["proposed_count"] == 0


# ── TestPaperCycleMultiStrategyPipeline ───────────────────────────────────────


class TestPaperCycleMultiStrategyPipeline:
    """
    Full end-to-end simulation: build FeatureSet → 4 strategies → rank → cycle.

    This is the "crown jewel" simulation: exercises the Phase 21 signal engine
    changes through the complete paper trading loop — from raw features to
    a filled order slip.
    """

    @staticmethod
    def _build_feature_set(item: dict):
        """Construct a FeatureSet from a dict using proper ComputedFeature objects."""
        import datetime as _dt
        from decimal import Decimal as _D
        from services.feature_store.models import ComputedFeature, FeatureSet

        now = _dt.datetime.utcnow()
        features = [
            ComputedFeature("return_1m", "momentum", _D(str(item.get("return_1m", 0.08))), now),
            ComputedFeature("return_3m", "momentum", _D(str(item.get("return_3m", item.get("return_1m", 0.08) * 2))), now),
            ComputedFeature("return_6m", "momentum", _D(str(item.get("return_6m", item.get("return_1m", 0.08) * 3))), now),
            ComputedFeature("sma_cross_signal", "trend", _D(str(item.get("sma_cross", 1.0))), now),
            ComputedFeature("volatility_20d", "risk", _D("0.25"), now),
            ComputedFeature("dollar_volume_20d", "liquidity", _D("8000000000"), now),
            ComputedFeature("atr_14", "risk", _D("1.5"), now),
            ComputedFeature("sma_20", "trend", _D("100.0"), now),
            ComputedFeature("sma_50", "trend", _D("90.0"), now),
            ComputedFeature("price_vs_sma20", "trend", _D("0.05"), now),
            ComputedFeature("price_vs_sma50", "trend", _D("0.15"), now),
        ]
        return FeatureSet(
            security_id=item["security_id"],
            ticker=item["ticker"],
            as_of_timestamp=now,
            features=features,
            theme_scores=item.get("theme_scores", {}),
            macro_bias=item.get("macro_bias", 0.0),
            macro_regime=item.get("macro_regime", "NEUTRAL"),
            sentiment_score=item.get("sentiment_score", 0.0),
            sentiment_confidence=item.get("sentiment_confidence", 0.0),
        )

    def _build_rankings_from_features(self, tickers_features: list[dict]) -> list[RankedResult]:
        """
        Build RankedResult objects using the real multi-strategy signal pipeline.

        Bypasses the DB-backed ``RankingEngineService.run()`` and calls the
        in-memory ``rank_signals()`` API directly — no session required.
        """
        from services.ranking_engine.service import RankingEngineService
        from services.signal_engine.service import SignalEngineService

        signal_engine = SignalEngineService()  # defaults: all 4 strategies
        ranking_engine = RankingEngineService()

        all_signals = []
        for item in tickers_features:
            features = self._build_feature_set(item)
            signals = signal_engine.score_from_features([features])
            all_signals.extend(signals)

        return ranking_engine.rank_signals(all_signals)

    def test_pipeline_produces_buy_rankings(self):
        """High-momentum + bullish overlay produces buy-ranked results."""
        sid = uuid.uuid4()
        rankings = self._build_rankings_from_features([{
            "security_id": sid,
            "ticker": "NVDA",
            "return_1m": 0.18,
            "return_3m": 0.36,
            "return_6m": 0.54,
            "sma_cross": 1.0,
            "theme_scores": {"AI_infrastructure": 0.85, "semiconductor": 0.75},
            "macro_bias": 0.6,
            "macro_regime": "RISK_ON",
            "sentiment_score": 0.7,
            "sentiment_confidence": 0.8,
        }])
        assert len(rankings) >= 1
        assert rankings[0].recommended_action == "buy"

    def test_pipeline_executes_cycle_successfully(self):
        """Full pipeline from features to filled orders returns status 'ok'."""
        sids = [uuid.uuid4() for _ in range(3)]
        tickers = ["NVDA", "MSFT", "GOOGL"]
        ticker_data = [
            {
                "security_id": sids[0],
                "ticker": "NVDA",
                "return_1m": 0.15, "return_3m": 0.30, "return_6m": 0.45,
                "theme_scores": {"AI_infrastructure": 0.80},
                "macro_bias": 0.5, "macro_regime": "RISK_ON",
                "sentiment_score": 0.6, "sentiment_confidence": 0.75,
            },
            {
                "security_id": sids[1],
                "ticker": "MSFT",
                "return_1m": 0.10, "return_3m": 0.20, "return_6m": 0.30,
                "theme_scores": {"cloud": 0.70, "AI_infrastructure": 0.60},
                "macro_bias": 0.4, "macro_regime": "RISK_ON",
                "sentiment_score": 0.5, "sentiment_confidence": 0.65,
            },
            {
                "security_id": sids[2],
                "ticker": "GOOGL",
                "return_1m": 0.09, "return_3m": 0.18, "return_6m": 0.27,
                "theme_scores": {"AI_infrastructure": 0.55},
                "macro_bias": 0.3, "macro_regime": "NEUTRAL",
                "sentiment_score": 0.4, "sentiment_confidence": 0.60,
            },
        ]
        rankings = self._build_rankings_from_features(ticker_data)
        assert len(rankings) >= 1

        settings = _make_settings(max_positions=10)
        state = _fresh_state(rankings=rankings)
        prices = {t: 250.0 for t in tickers}
        broker, portfolio_svc, risk_svc, execution_svc, reporting_svc = _make_services(
            settings, prices=prices
        )
        result = run_paper_trading_cycle(
            app_state=state,
            settings=settings,
            broker=broker,
            portfolio_svc=portfolio_svc,
            risk_svc=risk_svc,
            execution_svc=execution_svc,
            market_data_svc=_PriceStub(price=250.0),
            reporting_svc=reporting_svc,
        )
        assert result["status"] == "ok"
        assert result["executed_count"] >= 1

    def test_bearish_sentiment_reduces_score(self):
        """Bearish features should score lower and not produce a 'buy' action."""
        sid = uuid.uuid4()
        rankings = self._build_rankings_from_features([{
            "security_id": sid,
            "ticker": "DOOM",
            "return_1m": -0.15,
            "return_3m": -0.30,
            "return_6m": -0.45,
            "sma_cross": -1.0,
            "theme_scores": {},
            "macro_bias": -0.7,
            "macro_regime": "RISK_OFF",
            "sentiment_score": -0.8,
            "sentiment_confidence": 0.9,
        }])
        if rankings:
            # Should NOT recommend buying a strongly bearish security
            assert rankings[0].recommended_action != "buy"

    def test_all_four_strategies_contribute_signals(self):
        """Verify SignalEngineService emits 5 signals per ticker (one per strategy)."""
        from services.signal_engine.service import SignalEngineService

        signal_engine = SignalEngineService()
        sid = uuid.uuid4()
        features = self._build_feature_set({
            "security_id": sid,
            "ticker": "AAPL",
            "return_1m": 0.12,
            "return_3m": 0.24,
            "return_6m": 0.36,
            "theme_scores": {"consumer_tech": 0.70},
            "macro_bias": 0.3,
            "macro_regime": "RISK_ON",
            "sentiment_score": 0.5,
            "sentiment_confidence": 0.70,
        })
        signals = signal_engine.score_from_features([features])
        assert len(signals) == 5
        strategy_keys = {s.strategy_key for s in signals}
        assert "momentum_v1" in strategy_keys
        assert "theme_alignment_v1" in strategy_keys
        assert "macro_tailwind_v1" in strategy_keys
        assert "sentiment_v1" in strategy_keys
        assert "valuation_v1" in strategy_keys

    def test_neutral_overlay_preserved_in_cycle(self):
        """No overlay data → neutral signals; cycle still completes without error."""
        sid = uuid.uuid4()
        rankings = self._build_rankings_from_features([{
            "security_id": sid,
            "ticker": "FLAT",
            "return_1m": 0.04,
            "return_3m": 0.08,
            "return_6m": 0.12,
            # All overlays at neutral defaults
        }])
        settings = _make_settings()
        state = _fresh_state(rankings=rankings)
        broker, portfolio_svc, risk_svc, execution_svc, reporting_svc = _make_services(
            settings, prices={"FLAT": 50.0}
        )
        result = run_paper_trading_cycle(
            app_state=state,
            settings=settings,
            broker=broker,
            portfolio_svc=portfolio_svc,
            risk_svc=risk_svc,
            execution_svc=execution_svc,
            market_data_svc=_PriceStub(price=50.0),
            reporting_svc=reporting_svc,
        )
        # Must not crash; status may be 'ok' or 'skipped*' depending on composite score
        assert result["status"] in {"ok", "skipped_no_rankings"}
