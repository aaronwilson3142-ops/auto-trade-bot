"""add Position.origin_strategy for family-aware ATR exits

Deep-Dive Plan Step 5 Rec 7. Nullable ``VARCHAR(64)`` — positions opened
before this migration have ``origin_strategy = NULL`` and the
:pymod:`services.risk_engine.family_params` lookup treats ``NULL`` as the
``"default"`` family (wider/longer than the legacy 7%/20d/5% triple, so no
position is stopped-out earlier than it would have been under legacy rules).

Revises: k1l2m3n4o5p6_add_idempotency_keys (Step 2 cycle_id persistence).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "l2m3n4o5p6q7"
down_revision = "k1l2m3n4o5p6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "positions",
        sa.Column("origin_strategy", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("positions", "origin_strategy")
