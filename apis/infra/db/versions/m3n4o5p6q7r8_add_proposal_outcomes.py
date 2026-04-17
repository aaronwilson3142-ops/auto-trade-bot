"""add proposal_outcomes (Deep-Dive Plan Step 6 Rec 10).

Ledger of terminal decisions on ImprovementProposals + realized metric
snapshots after per-type measurement windows close.  See
``apis/services/self_improvement/outcome_ledger.py`` for the window table
(PROPOSAL_OUTCOME_WINDOWS, DEC-035) and the write/read service.

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-04-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

# revision identifiers, used by Alembic.
revision: str = "m3n4o5p6q7r8"
down_revision: str | None = "l2m3n4o5p6q7"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "proposal_outcomes",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "proposal_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("improvement_proposals.id"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("measurement_window_days", sa.Integer, nullable=False),
        sa.Column("baseline_metric_snapshot", pg.JSONB, nullable=False),
        sa.Column("realized_metric_snapshot", pg.JSONB, nullable=True),
        sa.Column("outcome_verdict", sa.String(20), nullable=True),
        sa.Column("outcome_confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "proposal_id",
            "decision",
            name="uq_proposal_outcome_proposal_decision",
        ),
    )
    op.create_index(
        "ix_proposal_outcome_decision_at",
        "proposal_outcomes",
        ["decision_at"],
    )
    op.create_index(
        "ix_proposal_outcome_verdict",
        "proposal_outcomes",
        ["outcome_verdict"],
    )


def downgrade() -> None:
    op.drop_index("ix_proposal_outcome_verdict", table_name="proposal_outcomes")
    op.drop_index("ix_proposal_outcome_decision_at", table_name="proposal_outcomes")
    op.drop_table("proposal_outcomes")
