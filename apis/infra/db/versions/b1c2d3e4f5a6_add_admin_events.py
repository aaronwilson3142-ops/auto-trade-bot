"""add_admin_events

Revision ID: b1c2d3e4f5a6
Revises: 9ed5639351bb
Create Date: 2026-03-18 00:00:00.000000

Priority 17 — Admin Audit Log
Adds the admin_events table to persist every admin HTTP API call for
operator traceability (rotation events, list-events queries, etc.).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: str | None = '9ed5639351bb'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'admin_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('event_timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('result', sa.String(50), nullable=False),
        sa.Column('source_ip', sa.String(50), nullable=True),
        sa.Column('secret_name', sa.String(255), nullable=True),
        sa.Column('secret_backend', sa.String(50), nullable=True),
        sa.Column('details_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_admin_events_event_timestamp', 'admin_events', ['event_timestamp'])
    op.create_index('ix_admin_events_event_type', 'admin_events', ['event_type'])


def downgrade() -> None:
    op.drop_index('ix_admin_events_event_type', table_name='admin_events')
    op.drop_index('ix_admin_events_event_timestamp', table_name='admin_events')
    op.drop_table('admin_events')
