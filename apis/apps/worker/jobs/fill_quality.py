"""Worker job: Order Fill Quality Update (Phase 52).

``run_fill_quality_update``
    Evening job that computes fill quality aggregate statistics from the
    in-memory FillQualityRecord list accumulated during paper trading cycles.

    Runs at 18:05 ET (after market close and evaluation pipeline).
    Never raises — errors are logged at WARNING level only.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from apps.api.state import ApiAppState
from config.logging_config import get_logger
from config.settings import Settings, get_settings

logger = get_logger(__name__)


def run_fill_quality_update(
    app_state: ApiAppState,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Compute fill quality summary from accumulated fill records.

    Args:
        app_state: Shared ApiAppState; reads fill_quality_records,
                   writes fill_quality_summary + fill_quality_updated_at.
        settings:  Settings instance; falls back to get_settings().

    Returns:
        dict with keys: status, record_count, computed_at, errors.
    """
    cfg = settings or get_settings()  # noqa: F841 — available for future config use
    run_at = dt.datetime.now(dt.UTC)
    errors: list[str] = []

    try:
        from services.fill_quality.service import FillQualityService

        records = list(getattr(app_state, "fill_quality_records", []))
        summary = FillQualityService.compute_fill_summary(
            records=records,
            computed_at=run_at,
        )
        app_state.fill_quality_summary = summary
        app_state.fill_quality_updated_at = run_at

        logger.info(
            "fill_quality_update_complete",
            record_count=summary.record_count,
            avg_slippage_usd=str(summary.avg_slippage_usd),
            total_fills=summary.total_fills,
        )

        return {
            "status": "ok",
            "record_count": summary.record_count,
            "computed_at": run_at.isoformat(),
            "errors": errors,
        }

    except Exception as exc:  # noqa: BLE001
        logger.warning("fill_quality_update_failed", error=str(exc))
        errors.append(str(exc))
        return {
            "status": "error",
            "record_count": 0,
            "computed_at": run_at.isoformat(),
            "errors": errors,
        }
