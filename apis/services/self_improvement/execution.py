"""
AutoExecutionService — applies promoted improvement proposals to the running system.

Design
------
- Only proposals with status=PROMOTED may be executed.
- Protected components (risk_engine, execution_engine, …) are never executed,
  even if a PROMOTED proposal targets them.
- Execution applies candidate_params to app_state.runtime_overrides so downstream
  services can consume them; also updates app_state.promoted_versions.
- DB writes are fire-and-forget: exceptions are caught, logged, and never raised.
- Rollback restores baseline_params to app_state.runtime_overrides and marks the
  DB row as "rolled_back".

Public API
----------
execute_proposal(proposal, app_state, session_factory) → ExecutionRecord
rollback_execution(execution_id, app_state, session_factory) → bool
auto_execute_promoted(proposals, app_state, session_factory) → dict

Phase 35 — Self-Improvement Proposal Auto-Execution
"""
from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from config.logging_config import get_logger
from services.self_improvement.models import PROTECTED_COMPONENTS, ProposalStatus

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# In-memory result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ExecutionRecord:
    """In-memory snapshot of a single proposal execution.

    Mirrors the ProposalExecution ORM row, but lives as a plain dataclass
    so routes and tests don't need a DB session to read results.
    """
    id: str
    proposal_id: str
    proposal_type: str
    target_component: str
    config_delta: dict[str, Any]        # candidate_params that were applied
    baseline_params: dict[str, Any]     # baseline_params for rollback
    status: str                          # "applied" | "rolled_back"
    executed_at: dt.datetime
    rolled_back_at: dt.datetime | None = None
    notes: str = ""


# ---------------------------------------------------------------------------
# AutoExecutionService
# ---------------------------------------------------------------------------

class AutoExecutionService:
    """Executes and rolls back promoted improvement proposals.

    Injection points:
      session_factory — optional callable returning a SQLAlchemy Session context
                        manager.  When None the DB persist step is skipped
                        (safe for tests and environments without a DB).
    """

    def execute_proposal(
        self,
        proposal: Any,
        app_state: Any,
        session_factory: Callable | None = None,
    ) -> ExecutionRecord:
        """Apply a PROMOTED proposal to the runtime system.

        Args:
            proposal:        ImprovementProposal with status=PROMOTED.
            app_state:       ApiAppState — updated in-place.
            session_factory: Optional SQLAlchemy session factory.

        Returns:
            ExecutionRecord describing what was applied.

        Raises:
            ValueError: when proposal is not PROMOTED or targets a protected component.
        """
        # ── Guardrail checks ────────────────────────────────────────────────
        if proposal.status != ProposalStatus.PROMOTED:
            raise ValueError(
                f"Cannot execute proposal {proposal.id}: "
                f"status={proposal.status!r}, must be PROMOTED."
            )

        if proposal.target_component in PROTECTED_COMPONENTS:
            raise ValueError(
                f"Cannot execute proposal {proposal.id}: "
                f"target_component='{proposal.target_component}' is protected."
            )

        # ── Capture params ───────────────────────────────────────────────────
        config_delta: dict[str, Any] = dict(getattr(proposal, "candidate_params", {}))
        baseline_params: dict[str, Any] = dict(getattr(proposal, "baseline_params", {}))
        execution_id = str(uuid.uuid4())
        executed_at = dt.datetime.now(dt.UTC)

        # ── Apply to runtime overrides ───────────────────────────────────────
        if not hasattr(app_state, "runtime_overrides"):
            app_state.runtime_overrides = {}
        app_state.runtime_overrides.update(config_delta)

        # ── Update promoted_versions ─────────────────────────────────────────
        if hasattr(app_state, "promoted_versions"):
            app_state.promoted_versions[proposal.target_component] = (
                proposal.candidate_version
            )

        # ── Build in-memory record ───────────────────────────────────────────
        record = ExecutionRecord(
            id=execution_id,
            proposal_id=proposal.id,
            proposal_type=proposal.proposal_type.value if hasattr(proposal.proposal_type, "value") else str(proposal.proposal_type),
            target_component=proposal.target_component,
            config_delta=config_delta,
            baseline_params=baseline_params,
            status="applied",
            executed_at=executed_at,
            notes=f"Auto-executed: {proposal.proposal_summary[:200]}",
        )

        # ── Append to app_state.applied_executions ───────────────────────────
        if hasattr(app_state, "applied_executions"):
            app_state.applied_executions.append(record)

        # ── Fire-and-forget DB persist ───────────────────────────────────────
        self._persist_execution(record, session_factory)

        logger.info(
            "proposal_executed",
            execution_id=execution_id,
            proposal_id=proposal.id,
            target_component=proposal.target_component,
            config_delta_keys=list(config_delta.keys()),
        )
        return record

    def rollback_execution(
        self,
        execution_id: str,
        app_state: Any,
        session_factory: Callable | None = None,
    ) -> bool:
        """Roll back a previously applied execution.

        Restores baseline_params to runtime_overrides and marks the record
        as "rolled_back" both in-memory and in the DB.

        Args:
            execution_id:    ID of the ExecutionRecord to roll back.
            app_state:       ApiAppState — updated in-place.
            session_factory: Optional SQLAlchemy session factory.

        Returns:
            True if rollback succeeded, False if execution_id was not found
            or was already rolled back.
        """
        applied_executions: list[ExecutionRecord] = getattr(
            app_state, "applied_executions", []
        )
        record = next((r for r in applied_executions if r.id == execution_id), None)
        if record is None:
            logger.warning("rollback_execution_not_found", execution_id=execution_id)
            return False

        if record.status == "rolled_back":
            logger.warning(
                "rollback_already_rolled_back", execution_id=execution_id
            )
            return False

        # ── Restore baseline_params to runtime_overrides ─────────────────────
        if not hasattr(app_state, "runtime_overrides"):
            app_state.runtime_overrides = {}
        app_state.runtime_overrides.update(record.baseline_params)

        # ── Remove any keys that were added by the execution and not in baseline
        for key in record.config_delta:
            if key not in record.baseline_params:
                app_state.runtime_overrides.pop(key, None)

        # ── Update in-memory record ──────────────────────────────────────────
        record.status = "rolled_back"
        record.rolled_back_at = dt.datetime.now(dt.UTC)

        # ── Fire-and-forget DB update ────────────────────────────────────────
        self._persist_rollback(execution_id, record.rolled_back_at, session_factory)

        logger.info(
            "proposal_rolled_back",
            execution_id=execution_id,
            proposal_id=record.proposal_id,
        )
        return True

    def auto_execute_promoted(
        self,
        proposals: list[Any],
        app_state: Any,
        session_factory: Callable | None = None,
        min_confidence: float = 0.0,
    ) -> dict[str, Any]:
        """Auto-execute all PROMOTED proposals in a batch.

        Skips proposals that:
          - are not PROMOTED
          - target protected components
          - are already applied (by proposal_id)
          - have confidence_score below min_confidence (Phase 36)

        Args:
            proposals:       List of ImprovementProposal objects.
            app_state:       ApiAppState — updated in-place.
            session_factory: Optional SQLAlchemy session factory.
            min_confidence:  Minimum confidence_score for auto-execution (0.0 = no gate).

        Returns:
            dict with keys: executed_count, skipped_count, skipped_low_confidence,
                            error_count, errors.
        """
        executed_count = 0
        skipped_count = 0
        skipped_low_confidence = 0
        error_count = 0
        errors: list[str] = []

        already_applied_ids = {
            r.proposal_id
            for r in getattr(app_state, "applied_executions", [])
            if r.status == "applied"
        }

        for proposal in proposals:
            if proposal.status != ProposalStatus.PROMOTED:
                skipped_count += 1
                continue

            if proposal.target_component in PROTECTED_COMPONENTS:
                skipped_count += 1
                logger.info(
                    "auto_execute_skip_protected",
                    proposal_id=proposal.id,
                    component=proposal.target_component,
                )
                continue

            if proposal.id in already_applied_ids:
                skipped_count += 1
                logger.info(
                    "auto_execute_skip_already_applied",
                    proposal_id=proposal.id,
                )
                continue

            # Phase 36: confidence gate
            proposal_confidence = getattr(proposal, "confidence_score", 0.0)
            if min_confidence > 0.0 and proposal_confidence < min_confidence:
                skipped_low_confidence += 1
                skipped_count += 1
                logger.info(
                    "auto_execute_skip_low_confidence",
                    proposal_id=proposal.id,
                    confidence=proposal_confidence,
                    threshold=min_confidence,
                )
                continue

            try:
                self.execute_proposal(proposal, app_state, session_factory)
                executed_count += 1
            except Exception as exc:  # noqa: BLE001
                error_count += 1
                errors.append(f"{proposal.id}: {exc}")
                logger.error(
                    "auto_execute_proposal_failed",
                    proposal_id=proposal.id,
                    error=str(exc),
                )

        # Update last_auto_execute_at
        if hasattr(app_state, "last_auto_execute_at"):
            app_state.last_auto_execute_at = dt.datetime.now(dt.UTC)

        return {
            "executed_count": executed_count,
            "skipped_count": skipped_count,
            "skipped_low_confidence": skipped_low_confidence,
            "error_count": error_count,
            "errors": errors,
        }

    # ── DB helpers (fire-and-forget) ────────────────────────────────────────

    def _persist_execution(
        self,
        record: ExecutionRecord,
        session_factory: Callable | None,
    ) -> None:
        """Write a new ProposalExecution row to the DB.  Never raises."""
        if session_factory is None:
            return
        try:
            from infra.db.models.proposal_execution import ProposalExecution

            with session_factory() as db:
                row = ProposalExecution(
                    id=record.id,
                    proposal_id=record.proposal_id,
                    proposal_type=record.proposal_type,
                    target_component=record.target_component,
                    config_delta_json=json.dumps(record.config_delta),
                    baseline_params_json=json.dumps(record.baseline_params),
                    status=record.status,
                    executed_at=record.executed_at,
                    notes=record.notes,
                )
                db.add(row)
                db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("persist_execution_failed", error=str(exc))

    def _persist_rollback(
        self,
        execution_id: str,
        rolled_back_at: dt.datetime,
        session_factory: Callable | None,
    ) -> None:
        """Update an existing ProposalExecution row to rolled_back.  Never raises."""
        if session_factory is None:
            return
        try:
            from infra.db.models.proposal_execution import ProposalExecution

            with session_factory() as db:
                row = db.get(ProposalExecution, execution_id)
                if row is not None:
                    row.status = "rolled_back"
                    row.rolled_back_at = rolled_back_at
                    db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("persist_rollback_failed", error=str(exc))
