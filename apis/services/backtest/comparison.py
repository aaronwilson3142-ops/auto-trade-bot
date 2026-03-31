"""BacktestComparisonService — runs per-strategy + combined backtests and
persists results to the backtest_runs table.

Design
------
- Runs the BacktestEngine once per strategy (5 strategies) and once more
  with all strategies combined (6 runs per comparison request).
- Each run is persisted as a BacktestRun DB row linked by comparison_id.
- DB writes are optional: if no session_factory is supplied the service
  returns results in-memory without persisting.
- Never raises: DB failures are caught and logged; the comparison result
  is still returned.
- Respects the BacktestEngine's existing interface — just injects a single
  strategy at a time for the per-strategy runs.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from services.backtest.config import BacktestConfig
from services.backtest.engine import BacktestEngine
from services.backtest.models import BacktestResult
from services.signal_engine.strategies.macro_tailwind import MacroTailwindStrategy
from services.signal_engine.strategies.momentum import MomentumStrategy
from services.signal_engine.strategies.sentiment import SentimentStrategy
from services.signal_engine.strategies.theme_alignment import ThemeAlignmentStrategy
from services.signal_engine.strategies.valuation import ValuationStrategy

logger = logging.getLogger(__name__)


@dataclass
class StrategyRunResult:
    """Result of one strategy run within a comparison."""

    strategy_name: str
    result: BacktestResult
    run_id: str | None = None
    error: str | None = None


# Ordered list of (strategy_name, strategy_instance) for per-strategy runs
_SINGLE_STRATEGIES: list[tuple[str, Any]] = [
    ("momentum_v1", MomentumStrategy()),
    ("theme_alignment_v1", ThemeAlignmentStrategy()),
    ("macro_tailwind_v1", MacroTailwindStrategy()),
    ("sentiment_v1", SentimentStrategy()),
    ("valuation_v1", ValuationStrategy()),
]

_ALL_STRATEGY_NAME = "all_strategies"


class BacktestComparisonService:
    """Runs a multi-strategy backtest comparison and persists results.

    Args:
        engine_factory: Callable that returns a BacktestEngine given a
                        ``strategies`` list.  Defaults to constructing
                        ``BacktestEngine(strategies=strategies)``.
                        Inject a mock in tests.
        session_factory: SQLAlchemy ``sessionmaker`` for DB persistence.
                         When ``None``, results are returned in-memory only.
    """

    def __init__(
        self,
        engine_factory: Callable[[list], BacktestEngine] | None = None,
        session_factory: Any | None = None,
    ) -> None:
        self._engine_factory = engine_factory or (
            lambda strategies: BacktestEngine(strategies=strategies)
        )
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_comparison(
        self,
        tickers: list[str],
        start_date: dt.date,
        end_date: dt.date,
        initial_cash: Decimal = Decimal("100_000"),
    ) -> tuple[str, list[StrategyRunResult]]:
        """Run a full comparison across all 5 individual strategies + combined.

        Returns:
            (comparison_id, list[StrategyRunResult]) — comparison_id links
            all DB rows from this comparison.  Results list always has 6
            entries (5 individual + 1 combined) unless the engine raises,
            in which case the entry's ``error`` field is set.
        """
        comparison_id = str(uuid.uuid4())
        config = BacktestConfig(
            start_date=start_date,
            end_date=end_date,
            tickers=tickers,
            initial_cash=initial_cash,
        )

        run_results: list[StrategyRunResult] = []

        # ── Per-strategy runs ───────────────────────────────────────────────
        for strategy_name, strategy_instance in _SINGLE_STRATEGIES:
            run_result = self._run_one(
                strategy_name=strategy_name,
                strategies=[strategy_instance],
                config=config,
                comparison_id=comparison_id,
            )
            run_results.append(run_result)

        # ── Combined run (all strategies) ───────────────────────────────────
        all_strategies = [s for _, s in _SINGLE_STRATEGIES]
        combined_result = self._run_one(
            strategy_name=_ALL_STRATEGY_NAME,
            strategies=all_strategies,
            config=config,
            comparison_id=comparison_id,
        )
        run_results.append(combined_result)

        return comparison_id, run_results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _run_one(
        self,
        strategy_name: str,
        strategies: list,
        config: BacktestConfig,
        comparison_id: str,
    ) -> StrategyRunResult:
        """Run BacktestEngine for a single strategy config; persist to DB."""
        run_id = str(uuid.uuid4())
        try:
            engine = self._engine_factory(strategies)
            result = engine.run(config)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "backtest_comparison_run_failed strategy=%s error=%s",
                strategy_name,
                str(exc),
            )
            return StrategyRunResult(
                strategy_name=strategy_name,
                result=BacktestResult(
                    start_date=config.start_date,
                    end_date=config.end_date,
                    initial_cash=config.initial_cash,
                ),
                run_id=run_id,
                error=str(exc),
            )

        self._persist(
            run_id=run_id,
            comparison_id=comparison_id,
            strategy_name=strategy_name,
            config=config,
            result=result,
        )

        return StrategyRunResult(
            strategy_name=strategy_name,
            result=result,
            run_id=run_id,
        )

    def _persist(
        self,
        run_id: str,
        comparison_id: str,
        strategy_name: str,
        config: BacktestConfig,
        result: BacktestResult,
    ) -> None:
        """Write one BacktestRun row.  Never raises."""
        if self._session_factory is None:
            return
        try:
            from infra.db.models.backtest import BacktestRun

            row = BacktestRun(
                id=uuid.UUID(run_id),
                comparison_id=comparison_id,
                strategy_name=strategy_name,
                start_date=config.start_date,
                end_date=config.end_date,
                ticker_count=len(config.tickers),
                tickers_json=json.dumps(config.tickers),
                total_return_pct=result.total_return_pct,
                sharpe_ratio=result.sharpe_ratio,
                max_drawdown_pct=result.max_drawdown_pct,
                win_rate=result.win_rate,
                total_trades=result.total_trades,
                days_simulated=result.days_simulated,
                final_portfolio_value=float(result.final_portfolio_value),
                initial_cash=float(result.initial_cash),
                status="completed",
            )
            with self._session_factory() as session:
                session.add(row)
                session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("backtest_persist_failed strategy=%s error=%s", strategy_name, str(exc))
