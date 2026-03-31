"""Source ingestion models: sources, source_events, security_event_links."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class Source(Base, TimestampMixin):
    """Registry of data/news/policy/chatter sources."""

    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_key: Mapped[str] = mapped_column(sa.String, unique=True, nullable=False)
    source_name: Mapped[str] = mapped_column(sa.String, nullable=False)
    source_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    reliability_tier: Mapped[str] = mapped_column(sa.String, nullable=False)
    default_weight: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(8, 4), nullable=True)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)


class SourceEvent(Base, TimestampMixin):
    """Normalized ingested source item (article, filing, transcript, rumor, etc.)."""

    __tablename__ = "source_events"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("sources.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    headline: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    body_text: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    event_timestamp: Mapped[Optional[datetime]] = mapped_column(sa.DateTime, nullable=True, index=True)
    ingested_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False)
    url: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    raw_payload_ref: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    credibility_score: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(8, 4), nullable=True)
    decay_score: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(8, 4), nullable=True)
    is_verified: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    metadata_json: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)


class SecurityEventLink(Base, TimestampMixin):
    """Links a source event to one or more impacted securities."""

    __tablename__ = "security_event_links"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_event_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("source_events.id"), nullable=False
    )
    security_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("securities.id"), nullable=False
    )
    link_reason: Mapped[Optional[str]] = mapped_column(sa.String, nullable=True)
    impact_direction: Mapped[Optional[str]] = mapped_column(sa.String, nullable=True)
    impact_confidence: Mapped[Optional[Decimal]] = mapped_column(sa.Numeric(8, 4), nullable=True)
