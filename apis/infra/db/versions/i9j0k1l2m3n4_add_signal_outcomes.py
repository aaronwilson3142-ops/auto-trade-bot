"""add_signal_outcomes

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-03-20 00:00:00.000000

Phase 46 — Signal Quality Tracking + Per-Strategy Attribution
Adds signal_outcomes table to persist per-trade signal prediction outcomes
for each strategy, enabling win-rate, average-return, and Sharpe-estimate
statistics per strategy.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "i9j0k1l2m3n4"
down_revision = "h8i9j0k1l2m3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signal_outcomes",
        sa.Column("id",           sa.String(36),  primary_key=True, nullable=False),
        sa.Column("ticker",       sa.String(16),  nullable=False),
        sa.Column("strategy_name", sa.String(64), nullable=False),
        sa.Column("signal_score", sa.Numeric(12, 6), nullable=True),
        sa.Column(
            "trade_opened_at",
            sa.DateTime(timezone=True), nullable=False,
        ),
        sa.Column(
            "trade_closed_at",
            sa.DateTime(timezone=True), nullable=False,
        ),
        sa.Column("outcome_return_pct", sa.Numeric(12, 6), nullable=False),
        sa.Column("hold_days",    sa.Integer,     nullable=False),
        sa.Column("was_profitable", sa.Boolean,  nullable=False),
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
        sa.UniqueConstraint(
            "ticker", "strategy_name", "trade_opened_at",
            name="uq_signal_outcome_trade",
        ),
    )
    op.create_index("ix_signal_outcome_strategy",  "signal_outcomes", ["strategy_name"])
    op.create_index("ix_signal_outcome_ticker",    "signal_outcomes", ["ticker"])
    op.create_index("ix_signal_outcome_opened_at", "signal_outcomes", ["trade_opened_at"])


def downgrade() -> None:
    op.drop_index("ix_signal_outcome_opened_at", table_name="signal_outcomes")
    op.drop_index("ix_signal_outcome_ticker",    table_name="signal_outcomes")
    op.drop_index("ix_signal_outcome_strategy",  table_name="signal_outcomes")
    op.drop_table("signal_outcomes")
