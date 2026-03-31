"""Data models for Order Fill Quality Tracking (Phase 52).

FillQualityRecord  — one data point per filled order.
FillQualitySummary — aggregate statistics over a set of records.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class FillQualityRecord:
    """Captures the expected vs actual fill for one executed order.

    Slippage convention:
      - Positive slippage_usd means the fill was WORSE than expected
        (paid more on a BUY, received less on a SELL).
      - Negative slippage_usd means the fill was BETTER than expected.

    Direction:
      - "BUY"  for OPEN actions
      - "SELL" for CLOSE and TRIM actions
    """

    ticker: str
    direction: str                      # "BUY" | "SELL"
    action_type: str                    # "open" | "close" | "trim"
    expected_price: Decimal
    fill_price: Decimal
    quantity: Decimal
    slippage_usd: Decimal               # (fill - expected) * qty for BUY, flipped for SELL
    slippage_pct: Decimal               # slippage_usd / (expected_price * qty)
    filled_at: dt.datetime
    # Alpha-decay attribution (Phase 55) — populated by run_fill_quality_attribution
    alpha_captured_pct: float | None = None          # N-day return from fill price (positive = alpha gained)
    slippage_as_pct_of_move: float | None = None     # slippage / |price_move| (0 = no cost)


@dataclass
class FillQualitySummary:
    """Aggregate fill quality statistics over all captured records.

    All monetary values are in USD.  Percentages are expressed as
    decimal fractions (e.g. 0.001 = 0.1%).
    """

    total_fills: int = 0
    buy_fills: int = 0
    sell_fills: int = 0

    # Slippage in USD
    avg_slippage_usd: Decimal = Decimal("0")
    median_slippage_usd: Decimal = Decimal("0")
    worst_slippage_usd: Decimal = Decimal("0")   # most negative (best fill)
    best_slippage_usd: Decimal = Decimal("0")    # largest positive (worst fill)

    # Slippage as fraction of notional
    avg_slippage_pct: Decimal = Decimal("0")
    worst_slippage_pct: Decimal = Decimal("0")

    # Per-direction averages
    avg_buy_slippage_usd: Decimal | None = None
    avg_sell_slippage_usd: Decimal | None = None

    # Metadata
    computed_at: dt.datetime | None = None
    record_count: int = 0               # same as total_fills; explicit for clarity
    tickers_covered: list[str] = field(default_factory=list)


@dataclass
class AlphaDecaySummary:
    """Aggregate alpha-decay attribution statistics over enriched fill records.

    Attributes:
        records_with_alpha:          number of fill records that have alpha data.
        avg_alpha_captured_pct:      mean N-day return from fill price (all directions).
        avg_slippage_as_pct_of_move: mean fraction of price move eaten by slippage.
        positive_alpha_count:        fills where alpha_captured_pct > 0.
        negative_alpha_count:        fills where alpha_captured_pct <= 0.
        n_days:                      look-ahead window used for attribution.
        computed_at:                 UTC timestamp of the last attribution run.
    """

    records_with_alpha: int = 0
    avg_alpha_captured_pct: float | None = None
    avg_slippage_as_pct_of_move: float | None = None
    positive_alpha_count: int = 0
    negative_alpha_count: int = 0
    n_days: int = 5
    computed_at: dt.datetime | None = None
