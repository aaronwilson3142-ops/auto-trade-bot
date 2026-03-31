"""BacktestEngine — runs the APIS pipeline over historical data without a DB.

Architecture
------------
The backtest harness wires together the pure in-memory components of APIS
(feature pipeline → signal strategy → ranking → portfolio → risk) and
feeds them historical bar data sliced day-by-day to simulate realistic
sequential decision-making.

Key design decisions
--------------------
- No DB required: uses DataIngestionService / YFinanceAdapter to fetch all
  history up front into a dict[ticker, list[BarRecord]], then slices it
  each simulated day.
- Uses BaselineFeaturePipeline directly (bypasses FeatureStoreService)
  since no DB persistence is needed.
- Uses all 4 signal strategies (Momentum, ThemeAlignment, MacroTailwind,
  Sentiment) by default, producing a richer signal set for the ranking
  engine.  A custom ``strategies`` list can be injected for specific runs.
- Optional ``enrichment_service`` populates FeatureSet overlay fields
  (theme_scores, macro_bias, macro_regime, sentiment_score, etc.) before
  strategy scoring.  When omitted, strategies receive neutral defaults.
- Uses RankingEngineService in-memory (no DB).
- Uses PortfolioEngineService + RiskEngineService in-memory.
- Fills are synthetic: close price ± slippage, no real broker.
- Transaction costs deducted from cash on each trade.

Spec reference: APIS_MASTER_SPEC.md § 5.2 (Backtest Mode)
"""
from __future__ import annotations

import datetime as dt
import logging
import math
import uuid
from decimal import ROUND_DOWN, Decimal

import pandas as pd

from config.settings import get_settings
from services.backtest.config import BacktestConfig
from services.backtest.models import BacktestResult, DayResult
from services.data_ingestion.adapters.yfinance_adapter import YFinanceAdapter
from services.feature_store.enrichment import FeatureEnrichmentService
from services.feature_store.models import FeatureSet
from services.feature_store.pipeline import BaselineFeaturePipeline
from services.portfolio_engine.models import (
    ActionType,
    PortfolioPosition,
    PortfolioState,
)
from services.portfolio_engine.service import PortfolioEngineService
from services.ranking_engine.models import RankingConfig
from services.ranking_engine.service import RankingEngineService
from services.risk_engine.service import RiskEngineService
from services.signal_engine.models import SignalOutput
from services.signal_engine.strategies.macro_tailwind import MacroTailwindStrategy
from services.signal_engine.strategies.momentum import MomentumStrategy
from services.signal_engine.strategies.sentiment import SentimentStrategy
from services.signal_engine.strategies.theme_alignment import ThemeAlignmentStrategy

logger = logging.getLogger(__name__)

_BPS = Decimal("0.0001")  # 1 basis point as Decimal


class BacktestEngine:
    """Runs a day-by-day simulation of the APIS pipeline over historical data.

    Uses all four signal strategies (Momentum, ThemeAlignment, MacroTailwind,
    Sentiment) by default, producing a broader signal set than the original
    single-strategy implementation.

    Usage::

        config = BacktestConfig(
            start_date=date(2023, 1, 1),
            end_date=date(2023, 12, 31),
            tickers=["AAPL", "MSFT", "NVDA"],
            initial_cash=Decimal("100_000"),
        )
        engine = BacktestEngine()
        result = engine.run(config)

    Args:
        adapter:             Data source (default: YFinanceAdapter).
        pipeline:            Feature pipeline (default: BaselineFeaturePipeline).
        strategies:          List of strategy instances.  Defaults to all four:
                             [MomentumStrategy, ThemeAlignmentStrategy,
                              MacroTailwindStrategy, SentimentStrategy].
        ranking_config:      Ranking weights (default: RankingConfig).
        enrichment_service:  Optional FeatureEnrichmentService.  When provided,
                             each FeatureSet is enriched with intelligence
                             overlays before strategy scoring.  When omitted,
                             strategies receive neutral default overlays.
    """

    def __init__(
        self,
        adapter: YFinanceAdapter | None = None,
        pipeline: BaselineFeaturePipeline | None = None,
        strategies: list | None = None,
        ranking_config: RankingConfig | None = None,
        enrichment_service: FeatureEnrichmentService | None = None,
    ) -> None:
        self._adapter = adapter or YFinanceAdapter()
        self._pipeline = pipeline or BaselineFeaturePipeline()
        self._strategies: list = strategies if strategies is not None else [
            MomentumStrategy(),
            ThemeAlignmentStrategy(),
            MacroTailwindStrategy(),
            SentimentStrategy(),
        ]
        self._ranking_svc = RankingEngineService(config=ranking_config)
        self._enrichment_service = enrichment_service  # None = no enrichment

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        config: BacktestConfig,
        policy_signals: list | None = None,
        news_insights: list | None = None,
    ) -> BacktestResult:
        """Execute the backtest and return aggregated results.

        Args:
            config:          Backtest parameters (dates, tickers, cash, etc.).
            policy_signals:  Optional list of PolicySignal objects to apply as
                             macro/theme overlays during every simulated day.
                             Useful for scenario analysis ("what if the macro
                             was RISK_ON for the whole period?").
            news_insights:   Optional list of NewsInsight objects to apply as
                             sentiment overlays per-ticker each day.

        Raises:
            ValueError: if config validation fails.
        """
        config.validate()
        _policy_signals: list = policy_signals or []
        _news_insights: list = news_insights or []

        settings = get_settings()
        # Patch settings for this simulation
        settings.max_positions = config.max_positions
        settings.max_single_name_pct = config.max_single_name_pct

        portfolio_svc = PortfolioEngineService(settings)
        risk_svc = RiskEngineService(settings)

        # ── Fetch all history up front ──────────────────────────────────────
        logger.info(
            "BacktestEngine: fetching history for %d tickers (%s → %s)",
            len(config.tickers), config.start_date, config.end_date,
        )
        all_bars = self._adapter.fetch_bulk(
            config.tickers,
            start=config.start_date - dt.timedelta(days=120),  # extra window for features
            end=config.end_date,
        )

        # ── Build trading day sequence ──────────────────────────────────────
        trading_days = self._trading_days(config.start_date, config.end_date, all_bars)

        # ── Initialise portfolio state ──────────────────────────────────────
        portfolio_state = PortfolioState(cash=config.initial_cash)
        peak_value = config.initial_cash
        prev_portfolio_value = config.initial_cash
        total_transaction_costs = Decimal("0")
        trade_pnls: list[float] = []

        result = BacktestResult(
            start_date=config.start_date,
            end_date=config.end_date,
            initial_cash=config.initial_cash,
        )

        for sim_date in trading_days:
            day_result = self._simulate_day(
                sim_date=sim_date,
                portfolio_state=portfolio_state,
                portfolio_svc=portfolio_svc,
                risk_svc=risk_svc,
                all_bars=all_bars,
                config=config,
                trade_pnls=trade_pnls,
                policy_signals=_policy_signals,
                news_insights=_news_insights,
            )

            # Track transaction costs
            total_transaction_costs += day_result.transaction_costs

            # Drawdown
            pv = day_result.portfolio_value
            if pv > peak_value:
                peak_value = pv
            if peak_value > Decimal("0"):
                dd = float((pv - peak_value) / peak_value * Decimal("100"))
            else:
                dd = 0.0
            day_result.drawdown_pct = dd
            day_result.daily_pnl = pv - prev_portfolio_value
            day_result.cumulative_pnl = pv - config.initial_cash
            prev_portfolio_value = pv

            result.day_results.append(day_result)

        # ── Aggregate result ────────────────────────────────────────────────
        final_pv = result.day_results[-1].portfolio_value if result.day_results else config.initial_cash
        result.final_portfolio_value = final_pv
        result.total_transaction_costs = total_transaction_costs
        result.days_simulated = len(result.day_results)
        result.total_trades = sum(
            d.positions_opened + d.positions_closed for d in result.day_results
        )

        if config.initial_cash > Decimal("0"):
            result.total_return_pct = float(
                (final_pv - config.initial_cash) / config.initial_cash * Decimal("100")
            )

        if trade_pnls:
            wins = [p for p in trade_pnls if p > 0]
            result.winning_trades = len(wins)
            result.losing_trades = len(trade_pnls) - len(wins)
            result.win_rate = len(wins) / len(trade_pnls)

        max_dd = min((d.drawdown_pct for d in result.day_results), default=0.0)
        result.max_drawdown_pct = max_dd

        # Sharpe ratio (annualized, risk-free=0 for simplicity)
        daily_rets = [
            float(d.daily_pnl / prev_pv)
            for d, prev_pv in zip(
                result.day_results[1:],
                [config.initial_cash] + [d.portfolio_value for d in result.day_results[:-1]],
            )
            if prev_pv > Decimal("0")
        ]
        if len(daily_rets) > 1:
            mean_r = sum(daily_rets) / len(daily_rets)
            std_r = math.sqrt(
                sum((r - mean_r) ** 2 for r in daily_rets) / (len(daily_rets) - 1)
            )
            result.sharpe_ratio = (mean_r / std_r * math.sqrt(252)) if std_r > 0 else 0.0

        logger.info(
            "Backtest complete: %d days, %.2f%% return, %.2f%% max drawdown",
            result.days_simulated,
            result.total_return_pct,
            result.max_drawdown_pct,
        )
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _trading_days(
        self,
        start: dt.date,
        end: dt.date,
        all_bars: dict,
    ) -> list[dt.date]:
        """Return sorted list of trading dates in the simulation window.

        Uses the union of dates across all fetched tickers to identify
        trading days (skips weekends and market holidays automatically).
        """
        dates: set[dt.date] = set()
        for bars in all_bars.values():
            for b in bars:
                if start <= b.trade_date <= end:
                    dates.add(b.trade_date)
        return sorted(dates)

    def _simulate_day(
        self,
        sim_date: dt.date,
        portfolio_state: PortfolioState,
        portfolio_svc: PortfolioEngineService,
        risk_svc: RiskEngineService,
        all_bars: dict,
        config: BacktestConfig,
        trade_pnls: list[float],
        policy_signals: list,
        news_insights: list,
    ) -> DayResult:
        """Simulate one trading day and mutate portfolio_state in place."""
        day_result = DayResult(date=sim_date)

        # ── Build per-ticker DataFrames with history up to sim_date ────────
        ticker_dfs: dict[str, pd.DataFrame] = {}
        close_prices: dict[str, Decimal] = {}
        for ticker in config.tickers:
            bars = [
                b for b in all_bars.get(ticker, [])
                if b.trade_date <= sim_date
            ]
            if len(bars) < 20:
                continue
            df = pd.DataFrame([
                {
                    "trade_date": b.trade_date,
                    "open": float(b.open or 0),
                    "high": float(b.high or 0),
                    "low": float(b.low or 0),
                    "close": float(b.close or 0),
                    "adjusted_close": float(b.adjusted_close or b.close or 0),
                    "volume": int(b.volume or 0),
                }
                for b in bars
            ])
            ticker_dfs[ticker] = df
            last_bar = bars[-1]
            if last_bar.adjusted_close:
                close_prices[ticker] = last_bar.adjusted_close
            elif last_bar.close:
                close_prices[ticker] = last_bar.close

        if not ticker_dfs:
            day_result.cash = portfolio_state.cash
            day_result.portfolio_value = self._compute_portfolio_value(
                portfolio_state, close_prices
            )
            return day_result

        # ── Feature computation + optional enrichment ───────────────────────
        feature_sets: dict[str, FeatureSet] = {}
        for ticker, df in ticker_dfs.items():
            fs = self._pipeline.compute(
                security_id=uuid.uuid5(uuid.NAMESPACE_DNS, ticker),
                ticker=ticker,
                bars_df=df,
                as_of=dt.datetime.combine(sim_date, dt.time()),
            )
            # Enrich with intelligence overlays when an enrichment service is wired up
            if self._enrichment_service is not None:
                try:
                    fs = self._enrichment_service.enrich(
                        fs,
                        policy_signals=policy_signals,
                        news_insights=news_insights,
                    )
                except Exception:  # noqa: BLE001
                    pass  # continue with un-enriched feature set
            feature_sets[ticker] = fs

        # ── Signal generation (all strategies) ─────────────────────────────
        signals: list[SignalOutput] = []
        for ticker, fs in feature_sets.items():
            for strategy in self._strategies:
                try:
                    out = strategy.score(fs)
                    if out is not None:
                        signals.append(out)
                except Exception:  # noqa: BLE001
                    pass
        day_result.signals_generated = len(signals)

        # ── Ranking ─────────────────────────────────────────────────────────
        rankings = self._ranking_svc.rank_signals(
            signals, max_results=config.max_positions * 2
        )
        # Filter to min score threshold
        rankings = [r for r in rankings if float(r.composite_score or 0) >= config.min_score_threshold]
        day_result.rankings_produced = len(rankings)

        # ── Portfolio actions ───────────────────────────────────────────────
        proposed_actions = portfolio_svc.apply_ranked_opportunities(
            rankings, portfolio_state
        )

        # ── Apply risk checks and execute synthetic fills ───────────────────
        opens = 0
        closes = 0
        transaction_costs = Decimal("0")

        for action in proposed_actions:
            # Skip if ticker has no close price (can't fill)
            ticker_price = close_prices.get(action.ticker)
            if ticker_price is None:
                continue

            risk_result = risk_svc.validate_action(action, portfolio_state)
            if risk_result.is_hard_blocked:
                continue

            # Synthetic fill: close ± slippage
            cost_factor = Decimal(str(config.transaction_cost_bps)) * _BPS
            slip_factor = Decimal(str(config.slippage_bps)) * _BPS

            if action.action_type == ActionType.OPEN:
                fill_price = ticker_price * (Decimal("1") + slip_factor)
                quantity = (action.target_notional / fill_price).to_integral_value(
                    rounding=ROUND_DOWN
                )
                if quantity <= Decimal("0"):
                    continue
                gross_cost = quantity * fill_price
                tx_cost = gross_cost * cost_factor
                total_outlay = gross_cost + tx_cost
                if total_outlay > portfolio_state.cash:
                    continue
                # Synthesise fill by directly mutating portfolio state
                pos = PortfolioPosition(
                    ticker=action.ticker,
                    quantity=quantity,
                    avg_entry_price=fill_price,
                    current_price=fill_price,
                    opened_at=dt.datetime.combine(
                        sim_date, dt.time(), tzinfo=dt.UTC
                    ),
                    thesis_summary=action.thesis_summary or "",
                )
                portfolio_state.positions[action.ticker] = pos
                portfolio_state.cash -= total_outlay
                transaction_costs += tx_cost
                opens += 1

            elif action.action_type == ActionType.CLOSE:
                if action.ticker not in portfolio_state.positions:
                    continue
                fill_price = ticker_price * (Decimal("1") - slip_factor)
                pos = portfolio_state.positions.pop(action.ticker)
                proceeds = pos.quantity * fill_price
                tx_cost = proceeds * cost_factor
                pnl = float(proceeds - pos.cost_basis - tx_cost)
                trade_pnls.append(pnl)
                portfolio_state.cash += proceeds - tx_cost
                transaction_costs += tx_cost
                closes += 1

        day_result.positions_opened = opens
        day_result.positions_closed = closes
        day_result.transaction_costs = transaction_costs
        day_result.active_positions = len(portfolio_state.positions)
        day_result.cash = portfolio_state.cash
        day_result.portfolio_value = self._compute_portfolio_value(
            portfolio_state, close_prices
        )
        return day_result

    def _compute_portfolio_value(
        self,
        state: PortfolioState,
        close_prices: dict[str, Decimal],
    ) -> Decimal:
        """Mark portfolio positions to market using close prices."""
        equity = Decimal("0")
        for ticker, pos in state.positions.items():
            price = close_prices.get(ticker)
            if price:
                equity += pos.quantity * price
            else:
                equity += pos.cost_basis  # fallback to cost if no price
        return state.cash + equity
