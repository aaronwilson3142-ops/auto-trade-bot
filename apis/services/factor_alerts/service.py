"""
Factor Tilt Alert Service — Phase 54.

Detects when the portfolio's dominant investment style factor changes
significantly cycle-over-cycle, and fires a webhook alert to operators.

Two triggers:
  1. Factor change — dominant_factor name shifts to a different factor.
  2. Weight shift  — same dominant_factor but its portfolio weight moved
     by >= min_weight_delta since the last recorded tilt event.

Design rules
------------
- Stateless: all methods are pure (no side-effects, no DB access).
- Never raises — all calls are wrapped in graceful-degradation try/except
  by the caller (paper_trading.py).
- Uses structlog only — no print() calls.

Spec references
---------------
- Phase 54 — Factor Tilt Alerts
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import structlog

from services.risk_engine.factor_exposure import FactorExposureResult

log = structlog.get_logger(__name__)


@dataclass
class FactorTiltEvent:
    """A single factor tilt detection event.

    Attributes:
        event_time:       UTC datetime when the tilt was detected.
        previous_factor:  Dominant factor name from the prior cycle (None if first cycle).
        new_factor:       Dominant factor name in the current cycle.
        previous_weight:  Portfolio weight of the relevant factor in the prior reference.
        new_weight:       Portfolio weight of the dominant factor in the current cycle.
        tilt_type:        "factor_change" | "weight_shift".
        delta_weight:     Absolute weight difference that triggered the event.
    """

    event_time: dt.datetime
    previous_factor: str | None
    new_factor: str
    previous_weight: float | None
    new_weight: float
    tilt_type: str  # "factor_change" | "weight_shift"
    delta_weight: float = 0.0


class FactorTiltAlertService:
    """Detect portfolio factor tilt events cycle-over-cycle.

    All methods are stateless — callers pass the full context required so
    the service remains fully testable without a running database or app state.
    """

    # Default threshold: 15 pp swing in dominant-factor weight triggers a weight-shift alert
    DEFAULT_MIN_WEIGHT_DELTA: float = 0.15

    @staticmethod
    def detect_tilt(
        current_result: FactorExposureResult,
        last_dominant_factor: str | None,
        factor_tilt_events: list | None = None,
        min_weight_delta: float = 0.15,
        event_time: dt.datetime | None = None,
    ) -> FactorTiltEvent | None:
        """Detect whether the current exposure represents a material factor tilt.

        Args:
            current_result:      Latest ``FactorExposureResult`` from the paper cycle.
            last_dominant_factor: The dominant factor recorded in the previous cycle
                                  (``None`` on the first cycle — no alert fired).
            factor_tilt_events:  In-memory list of prior ``FactorTiltEvent`` objects;
                                  used to derive the previous dominant-factor weight
                                  for weight-shift detection.
            min_weight_delta:    Minimum absolute weight change to trigger a weight-shift
                                  alert when the dominant factor name is unchanged.
            event_time:          Override for the event timestamp (defaults to UTC now).

        Returns:
            A ``FactorTiltEvent`` when a tilt is detected, otherwise ``None``.
        """
        if current_result is None:
            return None

        new_dominant = current_result.dominant_factor
        fw = current_result.portfolio_factor_weights
        new_weight = fw.get(new_dominant, 0.5)
        _time = event_time or dt.datetime.now(dt.UTC)

        # ── Trigger 1: dominant factor name changed ──────────────────────────
        if last_dominant_factor is not None and new_dominant != last_dominant_factor:
            prev_weight = fw.get(last_dominant_factor, 0.0)
            delta = abs(new_weight - prev_weight)
            log.info(
                "factor_tilt_detected_factor_change",
                previous_factor=last_dominant_factor,
                new_factor=new_dominant,
                delta_weight=round(delta, 4),
            )
            return FactorTiltEvent(
                event_time=_time,
                previous_factor=last_dominant_factor,
                new_factor=new_dominant,
                previous_weight=prev_weight,
                new_weight=new_weight,
                tilt_type="factor_change",
                delta_weight=round(delta, 4),
            )

        # ── Trigger 2: same dominant factor, weight shifted significantly ────
        # Use the most recent tilt event's new_weight as the prior reference point.
        if factor_tilt_events:
            last_event = factor_tilt_events[-1]
            last_weight = getattr(last_event, "new_weight", None)
            if last_weight is not None:
                weight_delta = abs(new_weight - last_weight)
                if weight_delta >= min_weight_delta:
                    log.info(
                        "factor_tilt_detected_weight_shift",
                        dominant_factor=new_dominant,
                        previous_weight=round(last_weight, 4),
                        new_weight=round(new_weight, 4),
                        delta=round(weight_delta, 4),
                    )
                    return FactorTiltEvent(
                        event_time=_time,
                        previous_factor=new_dominant,
                        new_factor=new_dominant,
                        previous_weight=last_weight,
                        new_weight=new_weight,
                        tilt_type="weight_shift",
                        delta_weight=round(weight_delta, 4),
                    )

        return None

    @staticmethod
    def build_alert_payload(event: FactorTiltEvent) -> dict:
        """Serialize a ``FactorTiltEvent`` to a webhook alert payload dict."""
        return {
            "tilt_type": event.tilt_type,
            "previous_factor": event.previous_factor,
            "new_factor": event.new_factor,
            "previous_weight": round(event.previous_weight, 4) if event.previous_weight is not None else None,
            "new_weight": round(event.new_weight, 4),
            "delta_weight": round(event.delta_weight, 4),
            "event_time": event.event_time.isoformat(),
        }
