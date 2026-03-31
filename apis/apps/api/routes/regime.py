"""
Regime Detection REST API — /api/v1/signals/regime

Routes
------
GET    /api/v1/signals/regime          — current regime (from app_state)
POST   /api/v1/signals/regime/override — set manual operator override
DELETE /api/v1/signals/regime/override — clear manual override; automated
                                         detection takes over next cycle
GET    /api/v1/signals/regime/history  — last N regime snapshots from DB

Design
------
- GET /regime returns the in-memory RegimeResult from app_state.current_regime_result;
  falls back to a SIDEWAYS / 0.0 stub when no detection has run yet.
- POST /override writes a manual RegimeResult to app_state and fire-and-forgets
  a DB snapshot.  The next ranking cycle will pick up the override via
  run_regime_detection respecting the is_manual_override flag.
- DELETE /override clears app_state.current_regime_result; the next automated
  detection cycle produces a fresh classification.
- GET /history reads regime_snapshots from DB; degrades gracefully to the
  in-memory regime_history list when the DB is unavailable.

Phase 38 — Market Regime Detection + Regime-Adaptive Weight Profiles
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from apps.api.deps import AppStateDep, SettingsDep
from apps.api.schemas.regime import (
    RegimeCurrentResponse,
    RegimeHistoryResponse,
    RegimeOverrideRequest,
    RegimeOverrideResponse,
    RegimeSnapshotSchema,
)

regime_router = APIRouter(prefix="/signals/regime", tags=["Regime Detection"])

_VALID_REGIMES = {"BULL_TREND", "BEAR_TREND", "SIDEWAYS", "HIGH_VOL"}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _regime_str(result: Any) -> str:
    """Extract regime string from a RegimeResult (handles both enum and str)."""
    regime = getattr(result, "regime", "SIDEWAYS")
    return regime.value if hasattr(regime, "value") else str(regime)


def _build_current_response(state: Any) -> RegimeCurrentResponse:
    """Build RegimeCurrentResponse from app_state.current_regime_result."""
    from services.signal_engine.regime_detection import (
        REGIME_DEFAULT_WEIGHTS,
        MarketRegime,
    )

    result: Optional[Any] = getattr(state, "current_regime_result", None)

    if result is None:
        return RegimeCurrentResponse(
            regime="SIDEWAYS",
            confidence=0.0,
            detection_basis={"reason": "no regime detection has run yet"},
            is_manual_override=False,
            override_reason=None,
            detected_at=None,
            regime_weights=dict(REGIME_DEFAULT_WEIGHTS[MarketRegime.SIDEWAYS]),
        )

    r_str = _regime_str(result)
    try:
        regime_enum = MarketRegime(r_str)
        weights = dict(REGIME_DEFAULT_WEIGHTS[regime_enum])
    except (KeyError, ValueError):
        weights = {}

    return RegimeCurrentResponse(
        regime=r_str,
        confidence=float(getattr(result, "confidence", 0.0)),
        detection_basis=dict(getattr(result, "detection_basis", {})),
        is_manual_override=bool(getattr(result, "is_manual_override", False)),
        override_reason=getattr(result, "override_reason", None),
        detected_at=getattr(result, "detected_at", None),
        regime_weights=weights,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@regime_router.get(
    "",
    response_model=RegimeCurrentResponse,
    summary="Get current market regime",
)
def get_current_regime(state: AppStateDep, cfg: SettingsDep) -> RegimeCurrentResponse:
    """Return the most recently detected market regime.

    Returns SIDEWAYS with 0.0 confidence when no detection has run yet.
    """
    return _build_current_response(state)


@regime_router.post(
    "/override",
    response_model=RegimeOverrideResponse,
    summary="Set manual regime override",
)
def set_regime_override(
    request: RegimeOverrideRequest,
    state: AppStateDep,
    cfg: SettingsDep,
) -> RegimeOverrideResponse:
    """Override the detected regime with an operator-supplied value.

    The override is held in-memory in app_state and will be respected by
    the next run_regime_detection cycle (which checks is_manual_override).
    A RegimeSnapshot is persisted to the DB as a fire-and-forget side-effect.
    """
    if request.regime not in _VALID_REGIMES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid regime '{request.regime}'. "
                f"Must be one of {sorted(_VALID_REGIMES)}."
            ),
        )

    from services.signal_engine.regime_detection import (
        REGIME_DEFAULT_WEIGHTS,
        MarketRegime,
        RegimeDetectionService,
    )

    regime_enum = MarketRegime(request.regime)
    svc = RegimeDetectionService()
    result = svc.set_manual_override(regime=regime_enum, reason=request.reason)

    # Write override to app_state
    state.current_regime_result = result

    # Append to in-memory history (cap at 30)
    history: list = getattr(state, "regime_history", [])
    history.append(result)
    if len(history) > 30:
        history = history[-30:]
    state.regime_history = history

    # Fire-and-forget DB persist
    try:
        from infra.db.session import SessionLocal
        svc.persist_snapshot(result, session_factory=SessionLocal)
    except Exception:  # noqa: BLE001
        pass

    return RegimeOverrideResponse(
        status="override_set",
        regime=request.regime,
        is_manual_override=True,
        regime_weights=dict(REGIME_DEFAULT_WEIGHTS[regime_enum]),
    )


@regime_router.delete(
    "/override",
    response_model=RegimeOverrideResponse,
    summary="Clear manual regime override",
)
def clear_regime_override(state: AppStateDep, cfg: SettingsDep) -> RegimeOverrideResponse:
    """Remove the active manual override.

    Automated regime detection will produce a fresh classification on the
    next run_regime_detection job cycle.
    """
    from services.signal_engine.regime_detection import (
        REGIME_DEFAULT_WEIGHTS,
        MarketRegime,
    )

    state.current_regime_result = None

    return RegimeOverrideResponse(
        status="override_cleared",
        regime=None,
        is_manual_override=False,
        regime_weights=dict(REGIME_DEFAULT_WEIGHTS[MarketRegime.SIDEWAYS]),
    )


@regime_router.get(
    "/history",
    response_model=RegimeHistoryResponse,
    summary="Regime detection history",
)
def get_regime_history(
    state: AppStateDep,
    cfg: SettingsDep,
    limit: int = Query(default=20, ge=1, le=100),
) -> RegimeHistoryResponse:
    """Return up to *limit* recent regime snapshots.

    Reads from the ``regime_snapshots`` DB table; degrades gracefully to the
    in-memory ``app_state.regime_history`` list when the DB is unavailable.
    """
    try:
        import sqlalchemy as sa
        from infra.db.models.regime_detection import RegimeSnapshot
        from infra.db.session import SessionLocal

        with SessionLocal() as session:
            rows = (
                session.execute(
                    sa.select(RegimeSnapshot)
                    .order_by(RegimeSnapshot.created_at.desc())
                    .limit(limit)
                )
                .scalars()
                .all()
            )

        snapshots = [
            RegimeSnapshotSchema(
                id=row.id,
                regime=row.regime,
                confidence=row.confidence,
                is_manual_override=row.is_manual_override,
                override_reason=row.override_reason,
                detected_at=getattr(row, "created_at", None),
            )
            for row in rows
        ]
        return RegimeHistoryResponse(snapshots=snapshots, count=len(snapshots))

    except Exception:  # noqa: BLE001
        # Graceful degradation: serve from in-memory history
        in_mem: list = getattr(state, "regime_history", [])
        snapshots = [
            RegimeSnapshotSchema(
                id=f"mem-{i}",
                regime=_regime_str(r),
                confidence=float(getattr(r, "confidence", 0.0)),
                is_manual_override=bool(getattr(r, "is_manual_override", False)),
                override_reason=getattr(r, "override_reason", None),
                detected_at=getattr(r, "detected_at", None),
            )
            for i, r in enumerate(reversed(in_mem[-limit:]))
        ]
        return RegimeHistoryResponse(snapshots=snapshots, count=len(snapshots))
