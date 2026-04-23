"""add universe_overrides table (Phase 48 Dynamic Universe Management).

The ORM model ``infra.db.models.universe_override.UniverseOverride`` and the
``services.universe_management`` consumer have existed since Phase 48, but the
backing table was never added to Alembic — so ``UniverseManagementService``
silently skipped the DB load path and the universe API routes returned 500 on
any write attempt.  This migration creates the table to match the ORM exactly.

Revision ID: p6q7r8s9t0u1
Revises: o5p6q7r8s9t0
Create Date: 2026-04-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "p6q7r8s9t0u1"
down_revision: str | None = "o5p6q7r8s9t0"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "universe_overrides",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("operator_id", sa.String(128), nullable=True),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "action IN ('ADD', 'REMOVE')",
            name="ck_universe_override_action",
        ),
    )
    op.create_index(
        "ix_universe_override_ticker",
        "universe_overrides",
        ["ticker"],
        unique=False,
    )
    op.create_index(
        "ix_universe_override_active",
        "universe_overrides",
        ["active"],
        unique=False,
    )
    op.create_index(
        "ix_universe_override_action",
        "universe_overrides",
        ["action"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_universe_override_action", table_name="universe_overrides")
    op.drop_index("ix_universe_override_active", table_name="universe_overrides")
    op.drop_index("ix_universe_override_ticker", table_name="universe_overrides")
    op.drop_table("universe_overrides")
