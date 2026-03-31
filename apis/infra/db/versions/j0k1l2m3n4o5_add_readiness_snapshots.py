"""add_readiness_snapshots

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-03-21 00:00:00.000000

Phase 56 — Readiness Report History
Adds readiness_snapshots table to persist live-mode readiness report snapshots
for trend tracking over time.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "j0k1l2m3n4o5"
down_revision = "i9j0k1l2m3n4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "readiness_snapshots",
        sa.Column("id",             sa.String(36),              primary_key=True, nullable=False),
        sa.Column("captured_at",    sa.DateTime(timezone=True), nullable=False),
        sa.Column("overall_status", sa.String(16),              nullable=False),
        sa.Column("current_mode",   sa.String(32),              nullable=False),
        sa.Column("target_mode",    sa.String(32),              nullable=False),
        sa.Column("pass_count",     sa.Integer,                 nullable=False, server_default="0"),
        sa.Column("warn_count",     sa.Integer,                 nullable=False, server_default="0"),
        sa.Column("fail_count",     sa.Integer,                 nullable=False, server_default="0"),
        sa.Column("gate_count",     sa.Integer,                 nullable=False, server_default="0"),
        sa.Column("gates_json",     sa.Text,                    nullable=False, server_default="[]"),
        sa.Column("recommendation", sa.Text,                    nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_readiness_snapshot_captured_at", "readiness_snapshots", ["captured_at"]
    )
    op.create_index(
        "ix_readiness_snapshot_overall_status", "readiness_snapshots", ["overall_status"]
    )


def downgrade() -> None:
    op.drop_index("ix_readiness_snapshot_overall_status", table_name="readiness_snapshots")
    op.drop_index("ix_readiness_snapshot_captured_at",    table_name="readiness_snapshots")
    op.drop_table("readiness_snapshots")
