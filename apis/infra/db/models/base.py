"""
SQLAlchemy declarative base and shared timestamp mixin used by all ORM models.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base for all APIS ORM models."""
    pass


class TimestampMixin:
    """
    Adds ``created_at`` and ``updated_at`` columns to any ORM model.

    Both are set by the database on INSERT via ``server_default``.
    ``updated_at`` is also refreshed by SQLAlchemy on ORM-level UPDATE via
    ``onupdate``.  For raw-SQL updates, update the column explicitly.
    """

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime,
        server_default=sa.text("now()"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime,
        server_default=sa.text("now()"),
        onupdate=datetime.utcnow,
        nullable=False,
    )
