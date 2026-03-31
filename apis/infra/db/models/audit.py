"""Continuity and audit models: decision_audit, session_checkpoints, admin_events."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class DecisionAudit(Base, TimestampMixin):
    """Structured audit log for major project and system decisions."""

    __tablename__ = "decision_audit"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    decision_timestamp: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False)
    decision_type: Mapped[str] = mapped_column(sa.String, nullable=False)
    summary: Mapped[str] = mapped_column(sa.Text, nullable=False)
    details_json: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    source_ref: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class SessionCheckpoint(Base, TimestampMixin):
    """Structured mirror of session handoff log entries for DB-side continuity."""

    __tablename__ = "session_checkpoints"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    checkpoint_timestamp: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False)
    capacity_trigger: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    objective: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    current_stage: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    current_status: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    files_changed_json: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    qa_status: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    open_items_json: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    risks_json: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    continuity_notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class AdminEvent(Base, TimestampMixin):
    """Audit log for admin HTTP API calls (e.g. invalidate-secrets, list-events).

    Every call to an admin endpoint is recorded here regardless of outcome so
    that operators can trace who triggered what and when.  The table is small
    (low-volume admin calls only) and never purged automatically.

    Priority 17 — Admin Audit Log
    """

    __tablename__ = "admin_events"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_timestamp: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, index=True
    )
    # e.g. "invalidate_secrets", "list_events"
    event_type: Mapped[str] = mapped_column(sa.String(100), nullable=False, index=True)
    # "ok", "skipped_env_backend", "unauthorized", "disabled", "error"
    result: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    # Remote IP from X-Forwarded-For or request.client.host
    source_ip: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)
    # Informational — which secret was named in the request body
    secret_name: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    # "aws" | "env" | None
    secret_backend: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)
    # Catch-all structured payload for future fields
    details_json: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
