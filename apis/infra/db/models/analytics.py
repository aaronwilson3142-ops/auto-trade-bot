"""Derived analytics models: features, security_feature_values."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class Feature(Base, TimestampMixin):
    """Catalog of available engineered features."""

    __tablename__ = "features"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    feature_key: Mapped[str] = mapped_column(sa.String, unique=True, nullable=False)
    feature_name: Mapped[str] = mapped_column(sa.String, nullable=False)
    feature_group: Mapped[str] = mapped_column(sa.String, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class SecurityFeatureValue(Base, TimestampMixin):
    """Computed feature values by security and point-in-time timestamp."""

    __tablename__ = "security_feature_values"
    __table_args__ = (
        sa.Index("ix_sfv_security_timestamp", "security_id", "as_of_timestamp"),
        sa.Index("ix_sfv_feature_timestamp", "feature_id", "as_of_timestamp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    security_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("securities.id"), nullable=False
    )
    feature_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("features.id"), nullable=False
    )
    as_of_timestamp: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False)
    feature_value_numeric: Mapped[Decimal | None] = mapped_column(sa.Numeric(20, 8), nullable=True)
    feature_value_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    source_version: Mapped[str | None] = mapped_column(sa.String, nullable=True)
