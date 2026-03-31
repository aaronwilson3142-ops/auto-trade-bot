"""add_system_state

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-03-18 00:00:00.000000

Priority 19 — Kill Switch & AppState Persistence
Adds the system_state key-value table used to persist critical runtime flags
(kill_switch_active, paper_cycle_count, etc.) across process restarts.

The table is intentionally minimal — no UUID PK because the key IS the
primary key, and no TimestampMixin because updated_at is set explicitly.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'system_state',
        sa.Column('key', sa.String(100), primary_key=True, nullable=False,
                  comment='Logical name of the state entry.'),
        sa.Column('value_text', sa.Text(), nullable=False,
                  comment='JSON-encoded or plain-text value.'),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False,
                  comment='Last write timestamp.'),
        sa.PrimaryKeyConstraint('key'),
    )


def downgrade() -> None:
    op.drop_table('system_state')
