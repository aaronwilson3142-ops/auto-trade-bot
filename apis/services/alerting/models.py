"""
Alert event models for the APIS operator webhook pipeline.

AlertEvent is the canonical data object passed to WebhookAlertService.send_alert().
AlertEventType enumerates every system event that can trigger a webhook.
AlertSeverity controls how receivers triage the notification.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AlertSeverity(str, Enum):
    """Operator-visible severity level for a webhook alert."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertEventType(str, Enum):
    """Canonical event types that APIS can dispatch as webhook alerts."""

    KILL_SWITCH_ACTIVATED = "kill_switch_activated"
    KILL_SWITCH_DEACTIVATED = "kill_switch_deactivated"
    PAPER_CYCLE_ERROR = "paper_cycle_error"
    BROKER_AUTH_EXPIRED = "broker_auth_expired"
    DAILY_EVALUATION = "daily_evaluation"
    TEST = "test"


@dataclass
class AlertEvent:
    """A single alert event dispatched to the operator webhook.

    Attributes:
        event_type:  One of ``AlertEventType`` values (string).
        severity:    One of ``AlertSeverity`` values (string).
        title:       Short human-readable summary line for the notification.
        payload:     Arbitrary key/value detail dict (e.g. equity, return pct).
        timestamp:   UTC datetime of event occurrence (defaults to now).
    """

    event_type: str
    severity: str
    title: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: dt.datetime = field(
        default_factory=lambda: dt.datetime.now(dt.UTC)
    )
