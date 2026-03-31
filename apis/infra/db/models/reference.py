"""Reference data models: securities, themes, security_themes."""
from __future__ import annotations

import uuid
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class Security(Base, TimestampMixin):
    """Master list of tradable instruments in scope."""

    __tablename__ = "securities"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticker: Mapped[str] = mapped_column(sa.String, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    asset_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    exchange: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    sector: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    industry: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    country: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    currency: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)


class Theme(Base, TimestampMixin):
    """Canonical theme registry (ai_infrastructure, semiconductors, etc.)."""

    __tablename__ = "themes"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    theme_key: Mapped[str] = mapped_column(sa.String, unique=True, nullable=False)
    theme_name: Mapped[str] = mapped_column(sa.String, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class SecurityTheme(Base, TimestampMixin):
    """Maps securities to themes with relationship type and confidence."""

    __tablename__ = "security_themes"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    security_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("securities.id"), nullable=False
    )
    theme_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("themes.id"), nullable=False
    )
    relationship_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    confidence_score: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(8, 4), nullable=True
    )
    source_method: Mapped[str | None] = mapped_column(sa.String, nullable=True)
