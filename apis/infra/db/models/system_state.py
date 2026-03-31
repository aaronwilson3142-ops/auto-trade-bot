"""System state persistence model.

Stores a small number of critical runtime values that must survive process
restarts.  Uses a key-value layout with a text column (`value_text`) that
holds JSON-encoded values so arbitrary types can be stored without schema
changes.

Keys used by APIS (by convention — not enforced by the model):
  ``kill_switch_active``     "true" | "false"
  ``kill_switch_activated_at``  ISO-8601 datetime string | ""
  ``kill_switch_activated_by``  source IP or "env" | ""
  ``paper_cycle_count``     integer string, e.g. "17"

Priority 19 — Kill Switch & AppState Persistence
"""
from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

# Well-known key constants used throughout the codebase
KEY_KILL_SWITCH_ACTIVE = "kill_switch_active"
KEY_KILL_SWITCH_ACTIVATED_AT = "kill_switch_activated_at"
KEY_KILL_SWITCH_ACTIVATED_BY = "kill_switch_activated_by"
KEY_PAPER_CYCLE_COUNT = "paper_cycle_count"


class SystemStateEntry(Base):
    """Single key-value row in the ``system_state`` table.

    The table has no TimestampMixin so that ``updated_at`` is always written
    explicitly by application code (we must control when the timestamp
    changes, not let SQLAlchemy set it indirectly on non-ORM updates).
    """

    __tablename__ = "system_state"

    key: Mapped[str] = mapped_column(
        sa.String(100),
        primary_key=True,
        comment="Logical name of the state entry, e.g. 'kill_switch_active'.",
    )
    value_text: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
        comment="JSON-encoded or plain-text value for the state entry.",
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        onupdate=dt.datetime.utcnow,
        nullable=False,
        comment="Last time this row was written.",
    )
