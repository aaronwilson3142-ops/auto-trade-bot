"""Fill Quality Service (Phase 52).

Stateless service that computes slippage metrics from filled orders.

Slippage is defined as the difference between the price at which the
execution engine was instructed to trade (the *expected* price) and the
actual *fill* price reported by the broker.

  BUY  slippage_usd = (fill_price - expected_price) * quantity
  SELL slippage_usd = (expected_price - fill_price) * quantity

A positive value means the fill was worse than expected (cost more or
received less).  Negative means the fill was unexpectedly favourable.
"""
from __future__ import annotations

import datetime as dt
import statistics
from decimal import Decimal

import structlog

from services.fill_quality.models import AlphaDecaySummary, FillQualityRecord, FillQualitySummary

log = structlog.get_logger(__name__)


class FillQualityService:
    """Stateless helper — all methods are class-level."""

    # ── Slippage calculation ──────────────────────────────────────────────────

    @staticmethod
    def compute_slippage(
        direction: str,
        expected_price: Decimal,
        fill_price: Decimal,
        quantity: Decimal,
    ) -> tuple[Decimal, Decimal]:
        """Return (slippage_usd, slippage_pct) for one fill.

        Args:
            direction:      "BUY" or "SELL"
            expected_price: price at signal / risk evaluation time
            fill_price:     actual average fill price from broker
            quantity:       number of shares filled (positive)

        Returns:
            Tuple of (slippage_usd, slippage_pct).  Both are zero when
            expected_price or quantity is zero.
        """
        if expected_price <= Decimal("0") or quantity <= Decimal("0"):
            return Decimal("0"), Decimal("0")

        if direction == "BUY":
            slippage_usd = (fill_price - expected_price) * quantity
        else:  # SELL
            slippage_usd = (expected_price - fill_price) * quantity

        notional = expected_price * quantity
        slippage_pct = (slippage_usd / notional).quantize(Decimal("0.000001"))

        return slippage_usd.quantize(Decimal("0.01")), slippage_pct

    @classmethod
    def build_record(
        cls,
        ticker: str,
        direction: str,
        action_type: str,
        expected_price: Decimal,
        fill_price: Decimal,
        quantity: Decimal,
        filled_at: dt.datetime,
    ) -> FillQualityRecord:
        """Construct a FillQualityRecord from raw fill data."""
        slippage_usd, slippage_pct = cls.compute_slippage(
            direction=direction,
            expected_price=expected_price,
            fill_price=fill_price,
            quantity=quantity,
        )
        return FillQualityRecord(
            ticker=ticker,
            direction=direction,
            action_type=action_type,
            expected_price=expected_price,
            fill_price=fill_price,
            quantity=quantity,
            slippage_usd=slippage_usd,
            slippage_pct=slippage_pct,
            filled_at=filled_at,
        )

    # ── Aggregation ───────────────────────────────────────────────────────────

    @staticmethod
    def compute_fill_summary(
        records: list[FillQualityRecord],
        computed_at: dt.datetime | None = None,
    ) -> FillQualitySummary:
        """Compute aggregate statistics over a list of FillQualityRecord objects.

        Returns an empty summary (all zeros) when records is empty.
        """
        if not records:
            return FillQualitySummary(
                computed_at=computed_at or dt.datetime.now(dt.UTC),
            )

        slippages_usd = [float(r.slippage_usd) for r in records]
        slippages_pct = [float(r.slippage_pct) for r in records]

        buy_records = [r for r in records if r.direction == "BUY"]
        sell_records = [r for r in records if r.direction == "SELL"]

        avg_buy = (
            Decimal(str(statistics.mean(float(r.slippage_usd) for r in buy_records))).quantize(Decimal("0.01"))
            if buy_records else None
        )
        avg_sell = (
            Decimal(str(statistics.mean(float(r.slippage_usd) for r in sell_records))).quantize(Decimal("0.01"))
            if sell_records else None
        )

        tickers = sorted({r.ticker for r in records})

        return FillQualitySummary(
            total_fills=len(records),
            buy_fills=len(buy_records),
            sell_fills=len(sell_records),
            avg_slippage_usd=Decimal(str(statistics.mean(slippages_usd))).quantize(Decimal("0.01")),
            median_slippage_usd=Decimal(str(statistics.median(slippages_usd))).quantize(Decimal("0.01")),
            worst_slippage_usd=Decimal(str(max(slippages_usd))).quantize(Decimal("0.01")),
            best_slippage_usd=Decimal(str(min(slippages_usd))).quantize(Decimal("0.01")),
            avg_slippage_pct=Decimal(str(statistics.mean(slippages_pct))).quantize(Decimal("0.000001")),
            worst_slippage_pct=Decimal(str(max(slippages_pct))).quantize(Decimal("0.000001")),
            avg_buy_slippage_usd=avg_buy,
            avg_sell_slippage_usd=avg_sell,
            computed_at=computed_at or dt.datetime.now(dt.UTC),
            record_count=len(records),
            tickers_covered=tickers,
        )

    # ── Filtering helpers ─────────────────────────────────────────────────────

    @staticmethod
    def filter_by_ticker(
        records: list[FillQualityRecord],
        ticker: str,
    ) -> list[FillQualityRecord]:
        """Return records for a specific ticker (case-insensitive)."""
        upper = ticker.upper()
        return [r for r in records if r.ticker.upper() == upper]

    @staticmethod
    def filter_by_direction(
        records: list[FillQualityRecord],
        direction: str,
    ) -> list[FillQualityRecord]:
        """Return records matching direction ('BUY' or 'SELL')."""
        upper = direction.upper()
        return [r for r in records if r.direction.upper() == upper]

    # ── Alpha-decay attribution (Phase 55) ────────────────────────────────────

    @staticmethod
    def compute_alpha_decay(
        record: FillQualityRecord,
        subsequent_price: Decimal,
        n_days: int,
    ) -> tuple:
        """Compute alpha-decay attribution for one fill record.

        Compares the actual fill price to the price N trading days later to
        estimate how much slippage cost relative to the realised price move.

        Args:
            record:           FillQualityRecord (must have fill_price > 0).
            subsequent_price: Price of the security N trading days after fill.
            n_days:           Number of trading days in the look-ahead window.

        Returns:
            Tuple of (alpha_captured_pct, slippage_as_pct_of_move).
            Both are None when prices are invalid or quantity is zero.

            alpha_captured_pct:       For BUY: (subsequent - fill) / fill.
                                      For SELL: (fill - subsequent) / fill.
                                      Positive = price moved in the right direction.
            slippage_as_pct_of_move:  slippage_usd / abs(price_move_usd) where
                                      price_move_usd = abs(subsequent - fill) * quantity.
                                      None when price_move_usd is zero (flat price).
        """
        if subsequent_price <= Decimal("0") or record.fill_price <= Decimal("0"):
            return None, None

        fill = record.fill_price
        qty = record.quantity
        direction = record.direction.upper()

        if direction == "BUY":
            price_move = subsequent_price - fill
        else:  # SELL
            price_move = fill - subsequent_price

        alpha_captured_pct = float(price_move / fill)

        price_move_usd = abs(subsequent_price - fill) * qty
        if price_move_usd <= Decimal("0"):
            slippage_as_pct_of_move = None
        else:
            ratio = record.slippage_usd / price_move_usd
            slippage_as_pct_of_move = float(ratio.quantize(Decimal("0.0001")))

        return alpha_captured_pct, slippage_as_pct_of_move

    @classmethod
    def compute_attribution_summary(
        cls,
        records: list,
        n_days: int = 5,
        computed_at: dt.datetime | None = None,
    ) -> AlphaDecaySummary:
        """Compute aggregate alpha-decay statistics from enriched fill records.

        Only records with non-None alpha_captured_pct are included in averages.

        Args:
            records:     list of FillQualityRecord (may have alpha fields or None).
            n_days:      look-ahead window; stored on the summary for reference.
            computed_at: override timestamp (defaults to UTC now).

        Returns:
            AlphaDecaySummary with aggregate statistics.
        """
        enriched = [r for r in records if getattr(r, "alpha_captured_pct", None) is not None]
        if not enriched:
            return AlphaDecaySummary(
                n_days=n_days,
                computed_at=computed_at or dt.datetime.now(dt.UTC),
            )

        alpha_vals = [r.alpha_captured_pct for r in enriched]
        slippage_pct_vals = [
            r.slippage_as_pct_of_move
            for r in enriched
            if r.slippage_as_pct_of_move is not None
        ]

        avg_alpha = statistics.mean(alpha_vals)
        avg_slip_pct = statistics.mean(slippage_pct_vals) if slippage_pct_vals else None

        return AlphaDecaySummary(
            records_with_alpha=len(enriched),
            avg_alpha_captured_pct=round(avg_alpha, 6),
            avg_slippage_as_pct_of_move=round(avg_slip_pct, 4) if avg_slip_pct is not None else None,
            positive_alpha_count=sum(1 for v in alpha_vals if v > 0),
            negative_alpha_count=sum(1 for v in alpha_vals if v <= 0),
            n_days=n_days,
            computed_at=computed_at or dt.datetime.now(dt.UTC),
        )
