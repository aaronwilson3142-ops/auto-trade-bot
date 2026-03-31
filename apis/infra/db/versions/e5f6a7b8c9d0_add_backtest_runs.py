"""add_backtest_runs

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-03-20 00:00:00.000000

Adds the backtest_runs table for persisting strategy comparison results.
Each row is one strategy run within a comparison group (comparison_id).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

# revision identifiers, used by Alembic.
revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("comparison_id", sa.String(36), nullable=False),
        sa.Column("strategy_name", sa.String(64), nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.Column("ticker_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tickers_json", sa.Text, nullable=True),
        sa.Column("total_return_pct", sa.Float, nullable=True),
        sa.Column("sharpe_ratio", sa.Float, nullable=True),
        sa.Column("max_drawdown_pct", sa.Float, nullable=True),
        sa.Column("win_rate", sa.Float, nullable=True),
        sa.Column("total_trades", sa.Integer, nullable=False, server_default="0"),
        sa.Column("days_simulated", sa.Integer, nullable=False, server_default="0"),
        sa.Column("final_portfolio_value", sa.Float, nullable=True),
        sa.Column("initial_cash", sa.Float, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="completed"),
        sa.Column("run_note", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )
    op.create_index(
        "ix_backtest_runs_comparison_id",
        "backtest_runs",
        ["comparison_id"],
    )
    op.create_index(
        "ix_backtest_runs_created_at",
        "backtest_runs",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_backtest_runs_created_at", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_comparison_id", table_name="backtest_runs")
    op.drop_table("backtest_runs")
