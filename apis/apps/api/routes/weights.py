"""Route handlers for /api/v1/signals/weights/*.

Phase 37 — Strategy Weight Auto-Tuning.

Endpoints
---------
POST /api/v1/signals/weights/optimize
    Derive Sharpe-proportional weights from the latest backtest comparison
    in the DB and persist as an active WeightProfile.
    Returns: OptimizeWeightsResponse

GET /api/v1/signals/weights/current
    Return the currently active WeightProfile.
    Returns: WeightProfileSchema (404 if none active)

GET /api/v1/signals/weights/history?limit=20
    Return all weight profiles newest first.
    Returns: WeightProfileListResponse

PUT /api/v1/signals/weights/active/{profile_id}
    Manually set a specific profile as active.
    Returns: SetActiveWeightResponse

POST /api/v1/signals/weights/manual
    Create a manual weight profile with operator-specified weights.
    Returns: OptimizeWeightsResponse

Design
------
- All list/detail endpoints return gracefully when DB is unavailable.
- POST /optimize reads the most recent backtest comparison from DB.
- Ranking engine picks up the new active weights on its next run via
  app_state.active_weight_profile.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from apps.api.deps import AppStateDep
from apps.api.schemas.weights import (
    CreateManualWeightRequest,
    OptimizeWeightsResponse,
    SetActiveWeightResponse,
    WeightProfileListResponse,
    WeightProfileSchema,
)

weights_router = APIRouter(prefix="/signals/weights", tags=["Strategy Weights"])


def _profile_to_schema(p: object) -> WeightProfileSchema:
    """Convert a WeightProfileRecord to the Pydantic schema."""
    return WeightProfileSchema(
        id=p.id,
        profile_name=p.profile_name,
        source=p.source,
        weights=p.weights,
        sharpe_metrics=p.sharpe_metrics,
        is_active=p.is_active,
        optimization_run_id=p.optimization_run_id,
        notes=getattr(p, "notes", None),
        created_at=getattr(p, "created_at", None),
    )


# ---------------------------------------------------------------------------
# POST /optimize — derive weights from latest backtest
# ---------------------------------------------------------------------------

@weights_router.post("/optimize", response_model=OptimizeWeightsResponse)
async def optimize_weights(
    state: AppStateDep,
) -> OptimizeWeightsResponse:
    """Derive Sharpe-proportional weights from the latest backtest comparison.

    Reads the most recent individual-strategy BacktestRun rows from the DB,
    computes normalised weights proportional to each strategy's Sharpe ratio,
    persists a new WeightProfile (active=True), and updates app_state so the
    next ranking cycle picks up the new weights immediately.

    Returns HTTP 503 when the DB is unavailable.
    Returns HTTP 404 when no backtest data exists yet.
    """
    session_factory = getattr(state, "_session_factory", None)
    if session_factory is None:
        raise HTTPException(status_code=503, detail="DB unavailable")

    try:
        import sqlalchemy as sa

        from infra.db.models.backtest import BacktestRun
        from services.signal_engine.weight_optimizer import WeightOptimizerService

        # Fetch the most recent comparison's individual-strategy rows
        with session_factory() as session:
            # Find the newest comparison_id
            newest = session.execute(
                sa.select(BacktestRun.comparison_id)
                .order_by(BacktestRun.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()

            if newest is None:
                raise HTTPException(
                    status_code=404,
                    detail="No backtest data found. Run POST /backtest/compare first.",
                )

            runs = session.execute(
                sa.select(BacktestRun).where(
                    BacktestRun.comparison_id == newest
                )
            ).scalars().all()

        svc = WeightOptimizerService(session_factory=session_factory)
        profile = svc.optimize_from_backtest(
            backtest_runs=runs,
            comparison_id=newest,
            set_active=True,
        )

        # Propagate to in-memory state immediately
        state.active_weight_profile = profile

        return OptimizeWeightsResponse(
            profile=_profile_to_schema(profile),
            message="Weight profile optimized from latest backtest and activated.",
        )

    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Optimization failed: {exc}") from exc


# ---------------------------------------------------------------------------
# GET /current — active profile
# ---------------------------------------------------------------------------

@weights_router.get("/current", response_model=WeightProfileSchema)
async def get_current_weights(
    state: AppStateDep,
) -> WeightProfileSchema:
    """Return the currently active weight profile.

    Returns HTTP 404 when no active profile exists.
    """
    # Prefer in-memory cache; fall back to DB query
    profile = getattr(state, "active_weight_profile", None)
    if profile is None:
        session_factory = getattr(state, "_session_factory", None)
        if session_factory:
            from services.signal_engine.weight_optimizer import WeightOptimizerService

            svc = WeightOptimizerService(session_factory=session_factory)
            profile = svc.get_active_profile()
            if profile:
                state.active_weight_profile = profile

    if profile is None:
        raise HTTPException(status_code=404, detail="No active weight profile found.")

    return _profile_to_schema(profile)


# ---------------------------------------------------------------------------
# GET /history — all profiles
# ---------------------------------------------------------------------------

@weights_router.get("/history", response_model=WeightProfileListResponse)
async def list_weight_profiles(
    state: AppStateDep,
    limit: int = Query(default=20, ge=1, le=100),
) -> WeightProfileListResponse:
    """Return all weight profiles, newest first.

    Returns empty list when DB is unavailable.
    """
    session_factory = getattr(state, "_session_factory", None)
    if session_factory is None:
        return WeightProfileListResponse(profiles=[], count=0)

    try:
        from services.signal_engine.weight_optimizer import WeightOptimizerService

        svc = WeightOptimizerService(session_factory=session_factory)
        profiles = svc.list_profiles(limit=limit)
        schemas = [_profile_to_schema(p) for p in profiles]
        return WeightProfileListResponse(profiles=schemas, count=len(schemas))
    except Exception:  # noqa: BLE001
        return WeightProfileListResponse(profiles=[], count=0)


# ---------------------------------------------------------------------------
# PUT /active/{profile_id} — set active profile
# ---------------------------------------------------------------------------

@weights_router.put("/active/{profile_id}", response_model=SetActiveWeightResponse)
async def set_active_weight_profile(
    profile_id: str,
    state: AppStateDep,
) -> SetActiveWeightResponse:
    """Set a specific weight profile as the active one.

    Deactivates all other profiles.  Returns HTTP 404 when the profile_id
    is not found.  Returns HTTP 503 when DB is unavailable.
    """
    session_factory = getattr(state, "_session_factory", None)
    if session_factory is None:
        raise HTTPException(status_code=503, detail="DB unavailable")

    try:
        from services.signal_engine.weight_optimizer import WeightOptimizerService

        svc = WeightOptimizerService(session_factory=session_factory)
        profile = svc.set_active_profile(profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="Weight profile not found.")

        # Update in-memory state
        state.active_weight_profile = profile

        return SetActiveWeightResponse(
            profile_id=profile_id,
            message=f"Weight profile '{profile.profile_name}' set as active.",
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"DB error: {exc}") from exc


# ---------------------------------------------------------------------------
# POST /manual — create manual weight profile
# ---------------------------------------------------------------------------

@weights_router.post("/manual", response_model=OptimizeWeightsResponse)
async def create_manual_weight_profile(
    body: CreateManualWeightRequest,
    state: AppStateDep,
) -> OptimizeWeightsResponse:
    """Create a manually specified weight profile.

    Weights are normalised to sum to 1.0 before persisting.  Pass
    ``set_active=true`` to immediately activate the new profile.
    """
    session_factory = getattr(state, "_session_factory", None)

    try:
        from services.signal_engine.weight_optimizer import WeightOptimizerService

        svc = WeightOptimizerService(session_factory=session_factory)
        profile = svc.create_manual_profile(
            weights=body.weights,
            profile_name=body.profile_name,
            set_active=body.set_active,
            notes=body.notes,
        )

        if body.set_active:
            state.active_weight_profile = profile

        return OptimizeWeightsResponse(
            profile=_profile_to_schema(profile),
            message="Manual weight profile created.",
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to create profile: {exc}") from exc
