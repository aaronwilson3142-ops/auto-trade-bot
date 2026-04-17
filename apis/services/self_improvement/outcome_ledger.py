"""Proposal Outcome Ledger — Deep-Dive Plan Step 6 Rec 10.

Records every terminal decision on an :class:`ImprovementProposal` (PROMOTED,
REJECTED, EXECUTED, REVERTED) together with the baseline metric snapshot at
the time of the decision.  A daily assessment job closes the window after
``PROPOSAL_OUTCOME_WINDOWS[proposal_type]`` days and fills in the realized
metric snapshot, verdict (improved/unchanged/regressed/inconclusive), and
confidence.  The ledger then drives a per-type batting-average feedback
signal that the proposal generator uses to prune under-performing types.

Everything here is **flag-gated** via
``settings.proposal_outcome_ledger_enabled`` (default False) so wiring a
call-site before flipping the flag is safe.

Per-type windows are per DEC-035 in the Deep-Dive Plan; unknown types use
``_DEFAULT`` (30 days).
"""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import structlog
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from infra.db.models.self_improvement import ImprovementProposal, ProposalOutcome

_log = structlog.get_logger(__name__)


# Per-type measurement windows in days (DEC-035, Deep-Dive Plan §6).
# Keys are the lowercase ``proposal_type`` values emitted by the self-improvement
# engine (matching ``services.self_improvement.models.ProposalType`` enum
# values).  ``window_days_for`` lowercases its input so callers can pass either
# case.  The ``_DEFAULT`` key wins when a type isn't mapped (plan §6).
PROPOSAL_OUTCOME_WINDOWS: dict[str, int] = {
    "source_weight": 45,
    "ranking_threshold": 30,
    "holding_period_rule": 14,
    "confidence_calibration": 60,
    "prompt_template": 30,
    "feature_transformation": 45,
    "sizing_formula": 30,
    "regime_classifier": 60,
    "_default": 30,
}


VALID_DECISIONS = ("PROMOTED", "REJECTED", "EXECUTED", "REVERTED")
VALID_VERDICTS = ("improved", "unchanged", "regressed", "inconclusive")


def window_days_for(proposal_type: str | None) -> int:
    """Return the measurement window (days) for ``proposal_type`` per DEC-035."""
    if not proposal_type:
        return PROPOSAL_OUTCOME_WINDOWS["_default"]
    return PROPOSAL_OUTCOME_WINDOWS.get(
        str(proposal_type).strip().lower(),
        PROPOSAL_OUTCOME_WINDOWS["_default"],
    )


@dataclass(frozen=True)
class BattingAverage:
    """Per-type outcome summary returned by :meth:`batting_average`."""

    proposal_type: str
    n_total: int
    n_improved: int
    n_regressed: int
    n_unchanged: int
    n_inconclusive: int

    @property
    def improved_rate(self) -> float:
        return self.n_improved / self.n_total if self.n_total else 0.0

    @property
    def regressed_rate(self) -> float:
        return self.n_regressed / self.n_total if self.n_total else 0.0


class ProposalOutcomeLedgerService:
    """Record and read proposal outcomes.

    All writes are flag-gated at the caller level — callers MUST check
    ``settings.proposal_outcome_ledger_enabled`` before invoking
    :meth:`write_decision`.  Reads (``batting_average``, ``get_due_for_assessment``)
    are always safe to call and simply return empty / no-op results when
    there are no rows in the ledger.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    # ------------------------------------------------------------------ writes
    def write_decision(
        self,
        *,
        proposal_id: uuid.UUID,
        decision: str,
        decision_at: dt.datetime,
        baseline_metric_snapshot: Mapping[str, Any],
        proposal_type: str | None = None,
        measurement_window_days: int | None = None,
    ) -> ProposalOutcome:
        """Insert a ledger row for a terminal proposal decision.

        ``measurement_window_days`` defaults to the per-type window.  Re-writing
        an existing (proposal_id, decision) is a no-op returning the prior row
        (the UNIQUE constraint enforces idempotency).
        """
        if decision not in VALID_DECISIONS:
            raise ValueError(
                f"invalid decision {decision!r} — expected one of {VALID_DECISIONS}"
            )

        existing = self._db.execute(
            select(ProposalOutcome).where(
                and_(
                    ProposalOutcome.proposal_id == proposal_id,
                    ProposalOutcome.decision == decision,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            _log.debug(
                "proposal_outcome.write_decision.exists",
                proposal_id=str(proposal_id),
                decision=decision,
            )
            return existing

        if measurement_window_days is None:
            measurement_window_days = window_days_for(proposal_type)

        row = ProposalOutcome(
            id=uuid.uuid4(),
            proposal_id=proposal_id,
            decision=decision,
            decision_at=decision_at,
            measurement_window_days=int(measurement_window_days),
            baseline_metric_snapshot=dict(baseline_metric_snapshot),
        )
        self._db.add(row)
        self._db.flush()
        _log.info(
            "proposal_outcome.write_decision",
            proposal_id=str(proposal_id),
            decision=decision,
            window_days=row.measurement_window_days,
        )
        return row

    def write_assessment(
        self,
        *,
        outcome_id: uuid.UUID,
        realized_metric_snapshot: Mapping[str, Any],
        outcome_verdict: str,
        outcome_confidence: float,
        measured_at: dt.datetime,
    ) -> ProposalOutcome:
        """Fill in the realized-snapshot columns once a window closes.

        Called by ``apps/worker/jobs/proposal_outcome_assessment.py``.
        """
        if outcome_verdict not in VALID_VERDICTS:
            raise ValueError(
                f"invalid verdict {outcome_verdict!r} — expected one of {VALID_VERDICTS}"
            )
        if not (0.0 <= outcome_confidence <= 1.0):
            raise ValueError(
                f"outcome_confidence must be in [0, 1], got {outcome_confidence!r}"
            )

        row = self._db.get(ProposalOutcome, outcome_id)
        if row is None:
            raise LookupError(f"ProposalOutcome {outcome_id} not found")
        row.realized_metric_snapshot = dict(realized_metric_snapshot)
        row.outcome_verdict = outcome_verdict
        row.outcome_confidence = float(outcome_confidence)
        row.measured_at = measured_at
        self._db.flush()
        _log.info(
            "proposal_outcome.write_assessment",
            outcome_id=str(outcome_id),
            verdict=outcome_verdict,
            confidence=outcome_confidence,
        )
        return row

    # ------------------------------------------------------------------ reads
    def get_due_for_assessment(
        self, *, now: dt.datetime | None = None
    ) -> list[ProposalOutcome]:
        """Return ledger rows whose measurement window has elapsed but
        whose ``realized_metric_snapshot`` is still NULL.
        """
        now = now or dt.datetime.now(dt.timezone.utc)
        rows = (
            self._db.execute(
                select(ProposalOutcome).where(
                    ProposalOutcome.realized_metric_snapshot.is_(None)
                )
            )
            .scalars()
            .all()
        )
        due: list[ProposalOutcome] = []
        for r in rows:
            closes_at = r.decision_at + dt.timedelta(days=int(r.measurement_window_days))
            if closes_at <= now:
                due.append(r)
        return due

    def batting_average(
        self,
        *,
        proposal_type: str | None = None,
        min_observations: int = 10,
    ) -> list[BattingAverage]:
        """Summarise outcome verdicts per proposal_type.

        If ``proposal_type`` is given, returns a list of length <=1 with just
        that type; otherwise one row per type seen in the ledger.  Types with
        fewer than ``min_observations`` closed outcomes are still returned so
        callers can decide how to treat thin samples (typically: fall back to
        default / ignore the feedback signal).
        """
        q = (
            select(
                ImprovementProposal.proposal_type,
                ProposalOutcome.outcome_verdict,
            )
            .join(
                ImprovementProposal,
                ImprovementProposal.id == ProposalOutcome.proposal_id,
            )
            .where(ProposalOutcome.outcome_verdict.isnot(None))
        )
        if proposal_type is not None:
            q = q.where(ImprovementProposal.proposal_type == proposal_type)

        tallies: dict[str, dict[str, int]] = {}
        for p_type, verdict in self._db.execute(q).all():
            bucket = tallies.setdefault(
                p_type,
                {"improved": 0, "regressed": 0, "unchanged": 0, "inconclusive": 0},
            )
            bucket[verdict] = bucket.get(verdict, 0) + 1

        out: list[BattingAverage] = []
        for p_type, counts in tallies.items():
            total = sum(counts.values())
            out.append(
                BattingAverage(
                    proposal_type=p_type,
                    n_total=total,
                    n_improved=counts["improved"],
                    n_regressed=counts["regressed"],
                    n_unchanged=counts["unchanged"],
                    n_inconclusive=counts["inconclusive"],
                )
            )
        # Stable ordering: by type name
        out.sort(key=lambda b: b.proposal_type)
        # Note: thin samples intentionally NOT filtered here — caller decides.
        _ = min_observations
        return out

    def types_to_suppress(
        self,
        *,
        min_observations: int,
        regressed_rate_threshold: float = 0.50,
    ) -> set[str]:
        """Return proposal_types whose regressed-rate exceeds the threshold
        with enough observations.  The generator feedback loop uses this.
        """
        bad: set[str] = set()
        for ba in self.batting_average(min_observations=min_observations):
            if ba.n_total >= min_observations and ba.regressed_rate >= regressed_rate_threshold:
                bad.add(ba.proposal_type)
        return bad
