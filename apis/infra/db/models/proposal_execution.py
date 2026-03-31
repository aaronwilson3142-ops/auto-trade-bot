"""ProposalExecution ORM — tracks auto-executed improvement proposals.

Each row represents one application of an ImprovementProposal's candidate_params
to the running system.  Rolled-back executions are marked in-place (rolled_back_at
set, status updated to "rolled_back") rather than deleted so the audit trail is
preserved.

Phase 35 — Self-Improvement Proposal Auto-Execution
"""
from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, Index, String, Text, func

from .base import Base


class ProposalExecution(Base):
    """Audit record for a single applied improvement proposal."""

    __tablename__ = "proposal_executions"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    proposal_id = Column(String(36), nullable=False, index=True)
    proposal_type = Column(String(64), nullable=True)
    target_component = Column(String(128), nullable=True)

    # Snapshot of what was applied and what can be used to roll back
    config_delta_json = Column(Text, nullable=True)     # JSON of candidate_params applied
    baseline_params_json = Column(Text, nullable=True)  # JSON of baseline_params (for rollback)

    # Lifecycle
    status = Column(String(32), nullable=False, default="applied")  # "applied" | "rolled_back"
    executed_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    rolled_back_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_proposal_exec_proposal_id", "proposal_id"),
        Index("ix_proposal_exec_executed_at", "executed_at"),
    )
