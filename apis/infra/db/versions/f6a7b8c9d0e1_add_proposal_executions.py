"""add_proposal_executions

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-03-20 00:00:00.000000

Phase 35 — Self-Improvement Proposal Auto-Execution
Adds proposal_executions table to track applied improvement proposals.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proposal_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("proposal_id", sa.String(36), nullable=False),
        sa.Column("proposal_type", sa.String(64), nullable=True),
        sa.Column("target_component", sa.String(128), nullable=True),
        sa.Column("config_delta_json", sa.Text, nullable=True),
        sa.Column("baseline_params_json", sa.Text, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="applied"),
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_proposal_exec_proposal_id",
        "proposal_executions",
        ["proposal_id"],
    )
    op.create_index(
        "ix_proposal_exec_executed_at",
        "proposal_executions",
        ["executed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_proposal_exec_executed_at", table_name="proposal_executions")
    op.drop_index("ix_proposal_exec_proposal_id", table_name="proposal_executions")
    op.drop_table("proposal_executions")
