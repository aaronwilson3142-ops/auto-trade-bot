"""add strategy_bandit_state (Deep-Dive Step 8, Rec 12).

One row per ``strategy_family`` holding the Beta(α, β) posterior that the
Thompson sampler draws from on each ranking cycle.  Cycle counters and the
last-sampled weight are persisted so the "resample every N cycles" cache
survives worker restarts.

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-04-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

# revision identifiers, used by Alembic.
revision: str = "o5p6q7r8s9t0"
down_revision: str | None = "n4o5p6q7r8s9"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "strategy_bandit_state",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("strategy_family", sa.String(64), nullable=False),
        sa.Column(
            "alpha",
            sa.Numeric(14, 4),
            nullable=False,
            server_default=sa.text("1.0"),
        ),
        sa.Column(
            "beta",
            sa.Numeric(14, 4),
            nullable=False,
            server_default=sa.text("1.0"),
        ),
        sa.Column(
            "n_wins",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "n_losses",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_sampled_weight", sa.Numeric(18, 16), nullable=True),
        sa.Column(
            "last_sampled_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "cycles_since_resample",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint(
        "uq_strategy_bandit_state_family",
        "strategy_bandit_state",
        ["strategy_family"],
    )
    op.create_index(
        "ix_strategy_bandit_state_family",
        "strategy_bandit_state",
        ["strategy_family"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_strategy_bandit_state_family",
        table_name="strategy_bandit_state",
    )
    op.drop_constraint(
        "uq_strategy_bandit_state_family",
        "strategy_bandit_state",
        type_="unique",
    )
    op.drop_table("strategy_bandit_state")
