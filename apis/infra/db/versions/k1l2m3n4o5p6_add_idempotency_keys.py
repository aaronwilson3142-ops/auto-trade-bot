"""add_idempotency_keys

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-04-16 00:00:00.000000

Deep-Dive Plan Step 2 Rec 4 — Idempotency keys on fire-and-forget DB writers.

Adds ``idempotency_key VARCHAR(200) NULL`` with a unique constraint on three
tables whose writers are called once per cycle / run:

* portfolio_snapshots  — key = "{cycle_id}:portfolio_snapshot"
* position_history     — key = "{cycle_id}:position_history:{ticker}"
* evaluation_runs      — key = "{run_date}:{mode}:evaluation_run"

The column is nullable so historical rows (pre-Step-2) don't block migration.
New writes populate the key AND use ``ON CONFLICT DO NOTHING`` on the
unique index so a retry after a partially-failed cycle cannot insert a
duplicate row.

Rollback drops the unique constraint and column on each table — leaves
existing data intact.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "k1l2m3n4o5p6"
down_revision = "j0k1l2m3n4o5"
branch_labels = None
depends_on = None


_TABLES = [
    ("portfolio_snapshots", "uq_portfolio_snapshot_idempotency_key"),
    ("position_history", "uq_position_history_idempotency_key"),
    ("evaluation_runs", "uq_evaluation_run_idempotency_key"),
]


def upgrade() -> None:
    for table_name, constraint_name in _TABLES:
        op.add_column(
            table_name,
            sa.Column(
                "idempotency_key",
                sa.String(length=200),
                nullable=True,
            ),
        )
        op.create_unique_constraint(
            constraint_name,
            table_name,
            ["idempotency_key"],
        )


def downgrade() -> None:
    for table_name, constraint_name in reversed(_TABLES):
        op.drop_constraint(constraint_name, table_name, type_="unique")
        op.drop_column(table_name, "idempotency_key")
