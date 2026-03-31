"""Phase 54 — Factor Tilt Alert routes.

Endpoints
---------
GET /portfolio/factor-tilt-history
    Returns the in-memory list of factor tilt events (newest last).
    Returns HTTP 200 + empty list when no tilt events have been recorded yet.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from apps.api.deps import AppStateDep
from apps.api.schemas.factor_alerts import FactorTiltEventSchema, FactorTiltHistoryResponse

factor_tilt_router = APIRouter(tags=["Portfolio"])


@factor_tilt_router.get(
    "/portfolio/factor-tilt-history",
    response_model=FactorTiltHistoryResponse,
    summary="Factor tilt event history",
)
async def get_factor_tilt_history(
    state: AppStateDep,
    limit: int = Query(default=50, ge=1, le=500, description="Maximum number of events to return"),
) -> FactorTiltHistoryResponse:
    """Return the most recent factor tilt events recorded during paper trading cycles.

    A tilt event is recorded when:
    - The portfolio's dominant investment style factor changes (e.g. MOMENTUM → VALUE).
    - The dominant factor's portfolio weight shifts by >= 15 percentage points
      since the last recorded tilt event.

    Returns HTTP 200 + empty list when no tilt events have been recorded yet.
    """
    events_raw: list = list(getattr(state, "factor_tilt_events", []))
    # Newest-first in response; slice to limit
    events_sliced = events_raw[-limit:] if len(events_raw) > limit else events_raw
    events_sliced_reversed = list(reversed(events_sliced))

    last_dominant = getattr(state, "last_dominant_factor", None)
    fe_computed_at = getattr(state, "factor_exposure_computed_at", None)

    event_schemas = [
        FactorTiltEventSchema(
            event_time=ev.event_time,
            previous_factor=ev.previous_factor,
            new_factor=ev.new_factor,
            previous_weight=ev.previous_weight,
            new_weight=ev.new_weight,
            tilt_type=ev.tilt_type,
            delta_weight=ev.delta_weight,
        )
        for ev in events_sliced_reversed
    ]

    return FactorTiltHistoryResponse(
        events=event_schemas,
        total_events=len(events_raw),
        last_dominant_factor=last_dominant,
        as_of=fe_computed_at,
    )
