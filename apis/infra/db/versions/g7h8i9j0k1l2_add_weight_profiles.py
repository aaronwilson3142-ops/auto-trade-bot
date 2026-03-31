"""add_weight_profiles

Revision ID: g7h8i9j0k1l2
Revises: f6a7b8c9d0e1
Create Date: 2026-03-20 00:00:00.000000

Phase 37 — Strategy Weight Auto-Tuning
Adds weight_profiles table to store per-strategy signal weights derived
from backtest comparison results or entered manually by the operator.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "g7h8i9j0k1l2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weight_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("profile_name", sa.String(128), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="optimized"),
        sa.Column("weights_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("sharpe_metrics_json", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("optimization_run_id", sa.String(36), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
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
    op.create_index("ix_weight_profile_is_active", "weight_profiles", ["is_active"])
    op.create_index("ix_weight_profile_created_at", "weight_profiles", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_weight_profile_created_at", table_name="weight_profiles")
    op.drop_index("ix_weight_profile_is_active", table_name="weight_profiles")
    op.drop_table("weight_profiles")
