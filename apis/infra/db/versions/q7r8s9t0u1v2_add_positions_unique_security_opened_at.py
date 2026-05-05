"""add UNIQUE (security_id, opened_at) to positions (Phase 77).

Phase 75 (DEC-075) fixed the row-inflation bug at the persistence layer by
making ``_persist_positions`` perform an idempotent
``(security_id, opened_at)`` upsert with reopen-if-closed semantics.  The
2026-05-05 cleanup transaction (DEC-076 supporting work) collapsed the
historical 395 duplicate closed-position rows down to one canonical row per
``(security_id, opened_at)`` group, so the constraint is now safe to enforce.

This migration adds a database-level UNIQUE constraint on
``positions(security_id, opened_at)`` so any future regression of the Phase 75
Python-side guard is caught at the engine boundary instead of accumulating
silently in the audit trail.

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-05-05
"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "q7r8s9t0u1v2"
down_revision: str | None = "p6q7r8s9t0u1"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


_CONSTRAINT_NAME = "uq_positions_security_id_opened_at"
_TABLE_NAME = "positions"


def upgrade() -> None:
    """Add UNIQUE (security_id, opened_at) on positions.

    Pre-flight assumption (verified at apply time): zero duplicate
    ``(security_id, opened_at)`` groups exist.  The 2026-05-05 cleanup
    transaction collapsed the historical 395 dup rows; Phase 75's idempotent
    upsert prevents new ones.  If the constraint creation fails with a unique
    violation, the migration aborts cleanly inside its own transaction and the
    operator must investigate before retrying.
    """
    op.create_unique_constraint(
        _CONSTRAINT_NAME,
        _TABLE_NAME,
        ["security_id", "opened_at"],
    )


def downgrade() -> None:
    op.drop_constraint(
        _CONSTRAINT_NAME,
        _TABLE_NAME,
        type_="unique",
    )
