"""Weekly Shadow Performance Assessment job.

Deep-Dive Plan Step 7 Rec 11 + DEC-034.  Intended cadence: Sundays 19:00 ET.

Walks each named shadow portfolio, compares shadow total P&L against the
live portfolio over aligned matched windows, and emits improvement proposals
(``GATE_LOOSEN`` for rejection-reason shadows; ``ALLOCATOR_CHANGE`` for
rebalance-weighting shadows) when the paired-bootstrap delta is significant.

**This module is a STUB** — paired-bootstrap + proposal emission is deferred
to Step 7 Part B once the shadows have accumulated ≥4 weeks of data.  For
now the job:

    1. Reads ``settings.shadow_portfolio_enabled`` — early-exits if OFF.
    2. Summarises each shadow's trade count + total P&L + open-position count.
    3. Logs the summary so the operator can see the shadows are accumulating.
    4. Returns a dict keyed by shadow name with those counts.

Wiring this into APScheduler belongs in a later commit; landing the stub now
gives the weekly job a real module to import so we can test flag-gating
end-to-end without shipping a half-baked proposal emitter.
"""
from __future__ import annotations

import datetime as dt

import structlog

from config.settings import get_settings
from infra.db.session import SessionLocal
from services.shadow_portfolio import (
    REBALANCE_SHADOWS,
    REJECTION_SHADOWS,
    ShadowPortfolioService,
)

_log = structlog.get_logger(__name__)


def run_shadow_performance_assessment(now: dt.datetime | None = None) -> dict:
    """Entry point — safe to call regardless of flag state.

    Returns a summary dict of the form::

        {
            "flag_off": bool,
            "shadows": {
                "rejected_actions": {"n_trades": ..., "n_open": ...,
                                      "realized_pnl": ...},
                ...
            },
            "proposals_emitted": 0,   # stub: always 0 until Part B
        }
    """
    settings = get_settings()
    if not getattr(settings, "shadow_portfolio_enabled", False):
        _log.info("shadow_performance_assessment.skipped", reason="flag_off")
        return {"flag_off": True, "shadows": {}, "proposals_emitted": 0}

    now = now or dt.datetime.now(dt.timezone.utc)
    summary: dict[str, dict] = {}
    with SessionLocal() as db:
        svc = ShadowPortfolioService(db)
        # Make sure every canonical shadow exists so the dashboard can
        # display rows even when no trades have landed yet.
        svc.ensure_all_canonical()

        for shadow in svc.list_shadows():
            trades = svc.get_trades(shadow.name)
            realized = sum(
                (float(t.realized_pnl) for t in trades if t.realized_pnl is not None),
                0.0,
            )
            positions = svc.get_positions(shadow.name)
            bucket_kind = (
                "rejection"
                if shadow.name in REJECTION_SHADOWS
                else ("rebalance" if shadow.name in REBALANCE_SHADOWS else "other")
            )
            summary[shadow.name] = {
                "bucket_kind": bucket_kind,
                "n_trades": len(trades),
                "n_open_positions": len(positions),
                "realized_pnl": realized,
            }
            _log.info(
                "shadow_performance_assessment.shadow_summary",
                name=shadow.name,
                bucket_kind=bucket_kind,
                n_trades=len(trades),
                n_open=len(positions),
                realized_pnl=realized,
            )
        db.commit()

    return {
        "flag_off": False,
        "shadows": summary,
        "proposals_emitted": 0,  # stub: real emission in Step 7 Part B
        "measured_at": now.isoformat(),
    }
