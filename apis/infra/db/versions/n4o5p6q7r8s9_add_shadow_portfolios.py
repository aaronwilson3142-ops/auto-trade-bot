"""add shadow_portfolios / shadow_positions / shadow_trades (Deep-Dive Step 7, DEC-034).

Virtual paper portfolios that mirror live risk gates but take the ideas the
live portfolio rejected, watched, or stopped out on — plus three parallel
rebalance-weighting shadows (equal / score / score_invvol) per DEC-034.

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-04-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

# revision identifiers, used by Alembic.
revision: str = "n4o5p6q7r8s9"
down_revision: str | None = "m3n4o5p6q7r8"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # shadow_portfolios --------------------------------------------------
    op.create_table(
        "shadow_portfolios",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column(
            "starting_cash",
            sa.Numeric(14, 2),
            server_default=sa.text("100000"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint("name", name="uq_shadow_portfolios_name"),
    )

    # shadow_positions ---------------------------------------------------
    op.create_table(
        "shadow_positions",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "shadow_portfolio_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("shadow_portfolios.id"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("shares", sa.Numeric(14, 4), nullable=False),
        sa.Column("avg_cost", sa.Numeric(14, 4), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opened_source", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "shadow_portfolio_id",
            "ticker",
            name="uq_shadow_positions_portfolio_ticker",
        ),
    )
    op.create_index(
        "ix_shadow_positions_portfolio",
        "shadow_positions",
        ["shadow_portfolio_id"],
    )

    # shadow_trades ------------------------------------------------------
    op.create_table(
        "shadow_trades",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "shadow_portfolio_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("shadow_portfolios.id"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("shares", sa.Numeric(14, 4), nullable=False),
        sa.Column("price", sa.Numeric(14, 4), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(14, 2), nullable=True),
        sa.Column("rejection_reason", sa.String(64), nullable=True),
        sa.Column("weighting_mode", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_shadow_trades_portfolio_exec",
        "shadow_trades",
        ["shadow_portfolio_id", "executed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_shadow_trades_portfolio_exec", table_name="shadow_trades")
    op.drop_table("shadow_trades")
    op.drop_index("ix_shadow_positions_portfolio", table_name="shadow_positions")
    op.drop_table("shadow_positions")
    op.drop_table("shadow_portfolios")
