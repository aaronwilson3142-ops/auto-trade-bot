#!/usr/bin/env python3
"""
APIS Backtest Regime Sweep — accelerated learning via historical simulation.

Runs the BacktestComparisonService across multiple market regime windows
(bull, bear, sideways, volatile, recovery) to generate hundreds of simulated
trades and derive Sharpe-optimal strategy weights.

Results are persisted to the backtest_runs table (when DB is available) so
the weight optimizer job at 06:52 ET picks up the latest comparison
automatically on the next trading day.

Usage
-----
From the apis/ directory with the virtual environment active:

    python scripts/run_backtest_sweep.py

Or from Docker:

    docker exec -it docker-worker-1 python scripts/run_backtest_sweep.py

Options:
    --regimes       Comma-separated regime names to run (default: all)
    --tickers       Override ticker list (default: full universe)
    --initial-cash  Starting cash per simulation (default: 100000)
    --min-score     Minimum composite score threshold (default: 0.15 for learning)
    --dry-run       Print regime configs without running backtests

Examples:
    # Run all regimes with default settings
    python scripts/run_backtest_sweep.py

    # Run only bull and bear regimes
    python scripts/run_backtest_sweep.py --regimes bull,bear

    # Dry run to see what would be executed
    python scripts/run_backtest_sweep.py --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
import time
from decimal import Decimal
from pathlib import Path

# Ensure the project root is on sys.path so relative imports work
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from config.logging_config import configure_logging, get_logger
from config.universe import get_universe_tickers
from services.backtest.config import BacktestConfig
from services.backtest.comparison import BacktestComparisonService

configure_logging(log_level="INFO")
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Market Regime Windows
# ---------------------------------------------------------------------------
# Each regime is defined by a date range that represents a distinct market
# environment.  The backtest engine fetches history from yfinance, so these
# must be dates where data is available.
#
# The windows are chosen to cover the major regime types:
#   - BULL:      strong uptrend (2023 Q4 → 2024 Q1 AI rally)
#   - BEAR:      downtrend / correction (2022 H1 rate-hike sell-off)
#   - SIDEWAYS:  range-bound / low-vol consolidation (2023 Q2–Q3)
#   - VOLATILE:  high-vol whipsaw (2022 Q3–Q4 Fed pivot speculation)
#   - RECOVERY:  V-shaped rebound (late 2022 → early 2023)
#   - RECENT:    most recent 6-month window for current-regime validation

REGIME_WINDOWS: dict[str, dict] = {
    "bull_2024_q1": {
        "label": "AI Bull Rally (Oct 2023 → Mar 2024)",
        "start": dt.date(2023, 10, 1),
        "end": dt.date(2024, 3, 31),
        "description": "Strong tech-led rally driven by AI hype; momentum + theme strategies should shine",
    },
    "bear_2022_h1": {
        "label": "Rate Hike Sell-Off (Jan → Jun 2022)",
        "start": dt.date(2022, 1, 3),
        "end": dt.date(2022, 6, 30),
        "description": "Aggressive Fed tightening; growth stocks crushed; defensive strategies tested",
    },
    "sideways_2023_q2q3": {
        "label": "Consolidation (Apr → Sep 2023)",
        "start": dt.date(2023, 4, 1),
        "end": dt.date(2023, 9, 30),
        "description": "Range-bound market; tests strategy selectivity and signal quality",
    },
    "volatile_2022_q3q4": {
        "label": "Whipsaw (Jul → Dec 2022)",
        "start": dt.date(2022, 7, 1),
        "end": dt.date(2022, 12, 31),
        "description": "High-vol regime with bear rallies; tests risk management and drawdown controls",
    },
    "recovery_2023_q1": {
        "label": "V-Shaped Rebound (Jan → Mar 2023)",
        "start": dt.date(2023, 1, 3),
        "end": dt.date(2023, 3, 31),
        "description": "Post-sell-off recovery; macro tailwind + sentiment reversal",
    },
    "recent_6m": {
        "label": "Recent 6 Months (rolling)",
        "start": dt.date.today() - dt.timedelta(days=180),
        "end": dt.date.today() - dt.timedelta(days=1),
        "description": "Most recent market conditions for current-regime weight validation",
    },
}


def _get_session_factory():
    """Try to build a DB session factory; return None if unavailable."""
    try:
        from infra.db.session import SessionLocal
        return SessionLocal
    except Exception:
        logger.warning("db_unavailable_backtest_results_will_not_persist")
        return None


def run_sweep(
    regimes: list[str] | None = None,
    tickers: list[str] | None = None,
    initial_cash: Decimal = Decimal("100_000"),
    min_score: float = 0.15,
    dry_run: bool = False,
) -> dict[str, dict]:
    """Run backtest comparisons across the specified market regime windows.

    Args:
        regimes:      List of regime keys to run.  None = all regimes.
        tickers:      Ticker list.  None = full APIS universe.
        initial_cash: Starting capital per simulation.
        min_score:    Minimum composite score threshold for the backtest.
                      Lower than production default (0.30) to capture more
                      marginal trades for learning.
        dry_run:      If True, print configs and exit without running.

    Returns:
        Dict mapping regime_name → summary dict with returns, trades, etc.
    """
    selected_regimes = regimes or list(REGIME_WINDOWS.keys())
    universe = tickers or get_universe_tickers()
    session_factory = _get_session_factory()

    svc = BacktestComparisonService(session_factory=session_factory)

    # Patch BacktestConfig defaults for learning mode
    _original_min_score = BacktestConfig.min_score_threshold
    BacktestConfig.min_score_threshold = min_score

    results: dict[str, dict] = {}

    print("\n" + "=" * 72)
    print("  APIS BACKTEST REGIME SWEEP")
    print(f"  Regimes: {len(selected_regimes)} | Tickers: {len(universe)} | Cash: ${initial_cash:,.0f}")
    print(f"  Min score threshold: {min_score} (production default: 0.30)")
    print(f"  DB persistence: {'YES' if session_factory else 'NO (in-memory only)'}")
    print("=" * 72)

    for regime_name in selected_regimes:
        if regime_name not in REGIME_WINDOWS:
            logger.warning(f"Unknown regime '{regime_name}', skipping")
            continue

        window = REGIME_WINDOWS[regime_name]
        print(f"\n{'─' * 60}")
        print(f"  Regime: {window['label']}")
        print(f"  Period: {window['start']} → {window['end']}")
        print(f"  Note:   {window['description']}")
        print(f"{'─' * 60}")

        if dry_run:
            print("  [DRY RUN — skipping execution]")
            results[regime_name] = {"status": "dry_run"}
            continue

        start_time = time.time()
        try:
            comparison_id, run_results = svc.run_comparison(
                tickers=universe,
                start_date=window["start"],
                end_date=window["end"],
                initial_cash=initial_cash,
            )

            elapsed = time.time() - start_time

            # Summarize results
            print(f"\n  comparison_id: {comparison_id}")
            print(f"  Elapsed: {elapsed:.1f}s")
            print(f"  {'Strategy':<25} {'Return':>8} {'Sharpe':>7} {'MaxDD':>7} {'Trades':>7} {'WinRate':>8}")
            print(f"  {'─' * 25} {'─' * 8} {'─' * 7} {'─' * 7} {'─' * 7} {'─' * 8}")

            regime_summary = {
                "comparison_id": comparison_id,
                "elapsed_seconds": round(elapsed, 1),
                "start": str(window["start"]),
                "end": str(window["end"]),
                "strategies": {},
            }

            for rr in run_results:
                if rr.error:
                    print(f"  {rr.strategy_name:<25} ERROR: {rr.error}")
                    regime_summary["strategies"][rr.strategy_name] = {"error": rr.error}
                    continue

                r = rr.result
                wr_str = f"{r.win_rate * 100:.1f}%" if r.win_rate else "N/A"
                print(
                    f"  {rr.strategy_name:<25} "
                    f"{r.total_return_pct:>7.2f}% "
                    f"{r.sharpe_ratio:>7.2f} "
                    f"{r.max_drawdown_pct:>7.2f}% "
                    f"{r.total_trades:>7} "
                    f"{wr_str:>8}"
                )
                regime_summary["strategies"][rr.strategy_name] = {
                    "total_return_pct": r.total_return_pct,
                    "sharpe_ratio": r.sharpe_ratio,
                    "max_drawdown_pct": r.max_drawdown_pct,
                    "total_trades": r.total_trades,
                    "win_rate": r.win_rate,
                    "days_simulated": r.days_simulated,
                }

            results[regime_name] = regime_summary

        except Exception as exc:
            elapsed = time.time() - start_time
            logger.error(f"Regime '{regime_name}' failed after {elapsed:.1f}s: {exc}")
            results[regime_name] = {"status": "error", "error": str(exc)}

    # Restore original default
    BacktestConfig.min_score_threshold = _original_min_score

    # ── Summary ────────────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("  SWEEP COMPLETE")
    completed = sum(1 for v in results.values() if v.get("comparison_id"))
    errored = sum(1 for v in results.values() if v.get("status") == "error")
    total_trades = sum(
        sum(
            s.get("total_trades", 0)
            for s in v.get("strategies", {}).values()
            if isinstance(s, dict) and "total_trades" in s
        )
        for v in results.values()
    )
    print(f"  Regimes completed: {completed}")
    if errored:
        print(f"  Regimes errored: {errored}")
    print(f"  Total simulated trades across all regimes: {total_trades}")
    if session_factory:
        print("  Results persisted to DB — weight optimizer will use them at next 06:52 ET run")
    else:
        print("  WARNING: No DB — results are in-memory only, weight optimizer will not see them")
    print("=" * 72 + "\n")

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="APIS Backtest Regime Sweep — accelerate learning via historical simulation"
    )
    parser.add_argument(
        "--regimes",
        type=str,
        default=None,
        help="Comma-separated regime names (default: all). Options: "
             + ", ".join(REGIME_WINDOWS.keys()),
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="Comma-separated ticker list (default: full universe)",
    )
    parser.add_argument(
        "--initial-cash",
        type=float,
        default=100_000,
        help="Starting cash per simulation (default: 100000)",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.15,
        help="Minimum composite score threshold (default: 0.15 for learning mode)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print regime configs without running backtests",
    )

    args = parser.parse_args()

    regimes = args.regimes.split(",") if args.regimes else None
    tickers = args.tickers.split(",") if args.tickers else None

    run_sweep(
        regimes=regimes,
        tickers=tickers,
        initial_cash=Decimal(str(args.initial_cash)),
        min_score=args.min_score,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
