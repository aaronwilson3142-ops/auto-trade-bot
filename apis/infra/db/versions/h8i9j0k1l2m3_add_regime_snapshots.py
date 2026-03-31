"""add_regime_snapshots

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-03-20 00:00:00.000000

Phase 38 — Market Regime Detection + Regime-Adaptive Weight Profiles
Adds regime_snapshots table to persist market regime classification events
(both automated detections and manual operator overrides).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "h8i9j0k1l2m3"
down_revision = "g7h8i9j0k1l2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "regime_snapshots",
        sa.Column("id",     sa.String(36),  primary_key=True, nullable=False),
        sa.Column("regime", sa.String(32),  nullable=False),
        sa.Column("confidence", sa.Float,   nullable=False),
        sa.Column(
            "detection_basis_json",
            sa.Text, nullable=False, server_default="{}",
        ),
        sa.Column(
            "is_manual_override",
            sa.Boolean, nullable=False, server_default=sa.false(),
        ),
        sa.Column("override_reason", sa.Text, nullable=True),
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
    op.create_index("ix_regime_snapshot_regime",     "regime_snapshots", ["regime"])
    op.create_index("ix_regime_snapshot_created_at", "regime_snapshots", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_regime_snapshot_created_at", table_name="regime_snapshots")
    op.drop_index("ix_regime_snapshot_regime",     table_name="regime_snapshots")
    op.drop_table("regime_snapshots")
