"""add_position_history

Revision ID: d4e5f6a7b8c9
Revises: c2d3e4f5a6b7
Create Date: 2026-03-20 00:00:00.000000

Adds the position_history table: one row per open position per paper trading
cycle, recording quantity, prices, and unrealized P&L over time.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "position_history",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("snapshot_at", sa.DateTime, nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=True),
        sa.Column("avg_entry_price", sa.Numeric(18, 6), nullable=True),
        sa.Column("current_price", sa.Numeric(18, 6), nullable=True),
        sa.Column("market_value", sa.Numeric(20, 4), nullable=True),
        sa.Column("cost_basis", sa.Numeric(20, 4), nullable=True),
        sa.Column("unrealized_pnl", sa.Numeric(20, 4), nullable=True),
        sa.Column("unrealized_pnl_pct", sa.Numeric(12, 6), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )
    op.create_index(
        "ix_pos_hist_ticker_snapshot",
        "position_history",
        ["ticker", "snapshot_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_pos_hist_ticker_snapshot", table_name="position_history")
    op.drop_table("position_history")
