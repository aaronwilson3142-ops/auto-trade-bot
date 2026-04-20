"""Daily assessment job for the Proposal Outcome Ledger.

Deep-Dive Plan Step 6 Rec 10 / DEC-035.  Runs at 18:30 ET each day (after
US market close + daily P&L), walks every ``ProposalOutcome`` whose
``measurement_window_days`` has elapsed, computes the realized metric
snapshot, and writes the verdict back to the ledger.

**This module is a STUB** — the actual metric computation is deferred to
Step 6 Part B once we've decided on the canonical per-type metric family
(e.g. SOURCE_WEIGHT → Δ batting-avg of signals from that source; SIZING_FORMULA
→ Δ realized Sharpe of positions sized by that formula).  For now it only:

    1. Reads ``settings.proposal_outcome_ledger_enabled`` — exits early if off.
    2. Fetches due rows via :class:`ProposalOutcomeLedgerService`.
    3. Logs them (so the operator can see the job is running).
    4. Writes ``inconclusive`` verdicts with confidence=0 — a harmless default
       until the real metric family is wired.

Wiring this into APScheduler belongs in a later commit; landing the stub now
keeps the ledger table from silently growing an unbounded backlog of
unassessed rows once the feature flag is flipped.
"""
from __future__ import annotations

import datetime as dt

import structlog

from config.settings import get_settings
from infra.db.session import SessionLocal
from services.self_improvement.outcome_ledger import (
    ProposalOutcomeLedgerService,
)

_log = structlog.get_logger(__name__)


def run_proposal_outcome_assessment(now: dt.datetime | None = None) -> dict:
    """Entry point — safe to call regardless of flag state.

    Returns a summary dict ``{"considered": N, "assessed": K, "skipped": S}``
    so callers / dashboards can see what happened.
    """
    settings = get_settings()
    if not getattr(settings, "proposal_outcome_ledger_enabled", False):
        _log.info("proposal_outcome_assessment.skipped", reason="flag_off")
        return {"considered": 0, "assessed": 0, "skipped": 0, "flag_off": True}

    now = now or dt.datetime.now(dt.UTC)
    with SessionLocal() as db:
        svc = ProposalOutcomeLedgerService(db)
        due = svc.get_due_for_assessment(now=now)
        _log.info(
            "proposal_outcome_assessment.due",
            count=len(due),
        )
        assessed = 0
        skipped = 0
        for row in due:
            # Stub: write inconclusive so the row leaves the "due" queue.
            # Real metric computation lands in Step 6 Part B.
            try:
                svc.write_assessment(
                    outcome_id=row.id,
                    realized_metric_snapshot={"stub": True, "reason": "metric_family_not_wired"},
                    outcome_verdict="inconclusive",
                    outcome_confidence=0.0,
                    measured_at=now,
                )
                assessed += 1
            except Exception as exc:  # pragma: no cover — defensive
                _log.warning(
                    "proposal_outcome_assessment.assess_failed",
                    outcome_id=str(row.id),
                    error=str(exc),
                )
                skipped += 1
        db.commit()
    return {
        "considered": len(due),
        "assessed": assessed,
        "skipped": skipped,
        "flag_off": False,
    }
