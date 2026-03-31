"""
Evaluation engine configuration.

All thresholds and benchmark tickers are defined here so they can be adjusted
without touching service logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


# ── Default benchmarks ─────────────────────────────────────────────────────────

DEFAULT_BENCHMARK_TICKERS: list[str] = ["SPY", "QQQ", "IWM"]


# ── Grade thresholds (by realized_pnl_pct) ────────────────────────────────────

GRADE_THRESHOLDS: dict[str, Decimal] = {
    "A": Decimal("0.05"),    # >= +5 %
    "B": Decimal("0.02"),    # >= +2 %
    "C": Decimal("0.00"),    # >=  0 %
    "D": Decimal("-0.03"),   # >= -3 %
    # "F" is the fallback for anything below -3 %
}


# ── Evaluation config object ───────────────────────────────────────────────────

@dataclass
class EvaluationConfig:
    """Runtime configuration for EvaluationEngineService."""

    benchmark_tickers: list[str] = field(
        default_factory=lambda: list(DEFAULT_BENCHMARK_TICKERS)
    )
    grade_thresholds: dict[str, Decimal] = field(
        default_factory=lambda: dict(GRADE_THRESHOLDS)
    )
