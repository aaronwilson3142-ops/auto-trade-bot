"""Worker job: Fill Quality Alpha-Decay Attribution (Phase 55).

``run_fill_quality_attribution``
    Evening job (18:32 ET) that enriches in-memory FillQualityRecord objects
    with alpha-decay attribution by querying the N-day subsequent price for
    each fill from the SecurityBar DB table.

    For each FillQualityRecord in app_state.fill_quality_records:
      1. Compute the target date = filled_at + N trading days (approximate).
      2. Query SecurityBar for the closest bar at or after the target date.
      3. Call FillQualityService.compute_alpha_decay() to get
         (alpha_captured_pct, slippage_as_pct_of_move).
      4. Replace the record with an enriched copy (dataclasses.replace).
      5. Write the enriched list back to app_state.fill_quality_records.
      6. Compute AlphaDecaySummary and write to app_state.

    Graceful degradation: when DB is unavailable or no bar data exists
    the record is left unchanged (fields remain None).  Never raises.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import replace as _dc_replace
from decimal import Decimal
from typing import Any, Optional

from apps.api.state import ApiAppState
from config.logging_config import get_logger
from config.settings import Settings, get_settings

logger = get_logger(__name__)

# Default look-ahead window: 5 trading days
_DEFAULT_N_DAYS: int = 5


def _fetch_subsequent_price(
    ticker: str,
    filled_at: dt.datetime,
    n_days: int,
    session_factory: Any,
) -> Optional[Decimal]:
    """Query SecurityBar for the closing price approximately N trading days after filled_at.

    Returns None when session_factory is None or when no bar is found.
    Uses calendar-day approximation (n_days * 1.5) to account for weekends.
    """
    if session_factory is None:
        return None
    try:
        import sqlalchemy as _sa  # noqa: PLC0415
        from infra.db.models import Security as _Sec  # noqa: PLC0415
        from infra.db.models.market_data import SecurityBar as _Bar  # noqa: PLC0415

        # Approximate: N trading days ≈ N*1.5 calendar days
        target_date = filled_at.date() + dt.timedelta(days=int(n_days * 1.5))

        with session_factory() as db:
            row = db.execute(
                _sa.select(_Bar.close_price)
                .join(_Sec, _Sec.id == _Bar.security_id)
                .where(_Sec.ticker == ticker.upper())
                .where(_Bar.bar_date >= target_date)
                .order_by(_Bar.bar_date.asc())
                .limit(1)
            ).first()
            if row and row[0] is not None:
                return Decimal(str(row[0]))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "fill_quality_attribution_price_fetch_failed",
            ticker=ticker,
            error=str(exc),
        )
    return None


def run_fill_quality_attribution(
    app_state: ApiAppState,
    settings: Optional[Settings] = None,
    session_factory: Optional[Any] = None,
    n_days: int = _DEFAULT_N_DAYS,
) -> dict[str, Any]:
    """Enrich fill quality records with N-day alpha-decay attribution.

    Args:
        app_state:        Shared ApiAppState; reads/writes fill_quality_records,
                          writes fill_quality_attribution_summary +
                          fill_quality_attribution_updated_at.
        settings:         Settings instance; falls back to get_settings().
        session_factory:  SQLAlchemy session factory; None = no DB enrichment
                          (all records left with alpha fields as None).
        n_days:           Trading-day look-ahead window for price comparison.

    Returns:
        dict with keys: status, enriched_count, record_count, computed_at, errors.
    """
    cfg = settings or get_settings()  # noqa: F841
    run_at = dt.datetime.now(dt.timezone.utc)
    errors: list[str] = []

    try:
        from services.fill_quality.service import FillQualityService

        records = list(getattr(app_state, "fill_quality_records", []))
        enriched_count = 0
        enriched_records = []

        for record in records:
            subsequent_price = _fetch_subsequent_price(
                ticker=record.ticker,
                filled_at=record.filled_at,
                n_days=n_days,
                session_factory=session_factory,
            )
            if subsequent_price is not None:
                alpha_pct, slip_pct_of_move = FillQualityService.compute_alpha_decay(
                    record=record,
                    subsequent_price=subsequent_price,
                    n_days=n_days,
                )
                if alpha_pct is not None:
                    record = _dc_replace(
                        record,
                        alpha_captured_pct=alpha_pct,
                        slippage_as_pct_of_move=slip_pct_of_move,
                    )
                    enriched_count += 1
            enriched_records.append(record)

        app_state.fill_quality_records = enriched_records

        summary = FillQualityService.compute_attribution_summary(
            records=enriched_records,
            n_days=n_days,
            computed_at=run_at,
        )
        app_state.fill_quality_attribution_summary = summary
        app_state.fill_quality_attribution_updated_at = run_at

        logger.info(
            "fill_quality_attribution_complete",
            record_count=len(records),
            enriched_count=enriched_count,
            avg_alpha_captured_pct=summary.avg_alpha_captured_pct,
        )

        return {
            "status": "ok",
            "enriched_count": enriched_count,
            "record_count": len(records),
            "computed_at": run_at.isoformat(),
            "errors": errors,
        }

    except Exception as exc:  # noqa: BLE001
        logger.warning("fill_quality_attribution_failed", error=str(exc))
        errors.append(str(exc))
        return {
            "status": "error",
            "enriched_count": 0,
            "record_count": 0,
            "computed_at": run_at.isoformat(),
            "errors": errors,
        }
