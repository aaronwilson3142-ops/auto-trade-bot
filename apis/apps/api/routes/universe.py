"""
Dynamic Universe Management API routes (Phase 48).

GET  /api/v1/universe/tickers
    Returns the full active universe with per-ticker status annotations.
    Populated by run_universe_refresh at 06:25 ET.

GET  /api/v1/universe/tickers/{ticker}
    Returns universe status detail for a single ticker.
    Returns data_available=False (200, not 404) when no refresh has run yet.

POST /api/v1/universe/tickers/{ticker}/override
    Creates an operator ADD or REMOVE override for a ticker.
    Writes a UniverseOverride row to the DB.

DELETE /api/v1/universe/tickers/{ticker}/override
    Deactivates all active overrides for a ticker (sets active=False).
"""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, HTTPException

from apps.api.deps import AppStateDep, SettingsDep
from apps.api.schemas.universe import (
    UniverseListResponse,
    UniverseOverrideDeleteResponse,
    UniverseOverrideRequest,
    UniverseOverrideResponse,
    UniverseTickerDetailResponse,
    UniverseTickerStatusSchema,
)

universe_router = APIRouter(prefix="/universe", tags=["Universe Management"])


@universe_router.get(
    "/tickers",
    response_model=UniverseListResponse,
    summary="Active trading universe with per-ticker status",
    description=(
        "Returns the full active universe list including operator override and "
        "signal quality annotations.  Populated by run_universe_refresh at 06:25 ET.  "
        "Returns no_data=True when no refresh has run yet (active universe is empty)."
    ),
)
def get_universe_tickers(
    state: AppStateDep,
    settings: SettingsDep,
) -> UniverseListResponse:
    """Return active universe from in-memory app_state."""
    from config.universe import UNIVERSE_TICKERS
    from services.universe_management.service import UniverseManagementService

    computed_at = getattr(state, "universe_computed_at", None)
    active = list(getattr(state, "active_universe", []))
    override_count = int(getattr(state, "universe_override_count", 0))
    min_quality = float(getattr(settings, "min_universe_signal_quality_score", 0.0))

    if not active:
        # No refresh has run yet — return base universe with no_data flag
        return UniverseListResponse(
            computed_at=computed_at,
            base_count=len(UNIVERSE_TICKERS),
            active_count=0,
            added_count=0,
            removed_count=0,
            override_count=override_count,
            min_quality_score=min_quality,
            active_tickers=[],
            added_tickers=[],
            removed_tickers=[],
            quality_removed_tickers=[],
            ticker_statuses=[],
            no_data=True,
        )

    # Build summary using the service
    quality_scores: dict[str, float] | None = None
    latest_quality = getattr(state, "latest_signal_quality", None)
    if latest_quality is not None and min_quality > 0.0:
        sq = getattr(latest_quality, "strategy_quality", {})
        per_ticker: dict[str, list[float]] = {}
        for _strat, stats in sq.items():
            wr = getattr(stats, "win_rate", None)
            if wr is not None:
                for t in UNIVERSE_TICKERS:
                    per_ticker.setdefault(t, []).append(float(wr))
        if per_ticker:
            quality_scores = {
                t: sum(v) / len(v) for t, v in per_ticker.items()
            }

    summary = UniverseManagementService.compute_universe_summary(
        base_tickers=list(UNIVERSE_TICKERS),
        active_tickers=active,
        overrides=[],            # we don't re-query DB here; override_count is in state
        signal_quality_scores=quality_scores,
        min_quality_score=min_quality,
        reference_dt=computed_at,
    )

    statuses = [
        UniverseTickerStatusSchema(
            ticker=s.ticker,
            in_base_universe=s.in_base_universe,
            in_active_universe=s.in_active_universe,
            override_action=s.override_action,
            override_reason=s.override_reason,
            quality_removed=s.quality_removed,
            signal_quality_score=s.signal_quality_score,
        )
        for s in summary.ticker_statuses
    ]

    return UniverseListResponse(
        computed_at=computed_at,
        base_count=summary.base_count,
        active_count=summary.active_count,
        added_count=len(summary.added_tickers),
        removed_count=len(summary.removed_tickers),
        override_count=override_count,
        min_quality_score=min_quality,
        active_tickers=active,
        added_tickers=summary.added_tickers,
        removed_tickers=summary.removed_tickers,
        quality_removed_tickers=summary.quality_removed_tickers,
        ticker_statuses=statuses,
        no_data=False,
    )


@universe_router.get(
    "/tickers/{ticker}",
    response_model=UniverseTickerDetailResponse,
    summary="Per-ticker universe status detail",
    description=(
        "Returns universe membership and override status for a single ticker.  "
        "Returns data_available=False (200, not 404) when no universe refresh "
        "has run yet."
    ),
)
def get_universe_ticker_detail(
    ticker: str,
    state: AppStateDep,
    settings: SettingsDep,
) -> UniverseTickerDetailResponse:
    """Return universe detail for a single ticker."""
    from config.universe import UNIVERSE_TICKERS

    ticker = ticker.upper()
    computed_at = getattr(state, "universe_computed_at", None)
    active = list(getattr(state, "active_universe", []))

    if not active:
        return UniverseTickerDetailResponse(
            ticker=ticker,
            data_available=False,
            in_base_universe=ticker in [t.upper() for t in UNIVERSE_TICKERS],
        )

    base_set = {t.upper() for t in UNIVERSE_TICKERS}

    return UniverseTickerDetailResponse(
        ticker=ticker,
        data_available=True,
        computed_at=computed_at,
        in_base_universe=ticker in base_set,
        in_active_universe=ticker in {t.upper() for t in active},
    )


@universe_router.post(
    "/tickers/{ticker}/override",
    response_model=UniverseOverrideResponse,
    summary="Add an operator override for a ticker",
    description=(
        "Creates an ADD or REMOVE override for the specified ticker.  "
        "The change takes effect at the next run_universe_refresh (06:25 ET) "
        "or can be triggered immediately via the scheduler.  "
        "Returns 503 if the database is unavailable."
    ),
)
def create_universe_override(
    ticker: str,
    body: UniverseOverrideRequest,
    state: AppStateDep,
    settings: SettingsDep,
) -> UniverseOverrideResponse:
    """Write a new UniverseOverride row to the database."""
    ticker = ticker.upper()
    action = body.action.upper()
    if action not in ("ADD", "REMOVE"):
        raise HTTPException(status_code=422, detail="action must be 'ADD' or 'REMOVE'")

    override_id = str(uuid.uuid4())
    try:
        from infra.db.models.universe_override import UniverseOverride
        from infra.db.session import db_session as _db_session

        with _db_session() as db:
            row = UniverseOverride(
                id=override_id,
                ticker=ticker,
                action=action,
                reason=body.reason,
                operator_id=body.operator_id,
                active=True,
                expires_at=body.expires_at,
            )
            db.add(row)
            db.flush()

    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"DB write failed: {exc}") from exc

    return UniverseOverrideResponse(
        status="created",
        ticker=ticker,
        action=action,
        override_id=override_id,
        reason=body.reason,
        expires_at=body.expires_at,
    )


@universe_router.delete(
    "/tickers/{ticker}/override",
    response_model=UniverseOverrideDeleteResponse,
    summary="Deactivate all active overrides for a ticker",
    description=(
        "Sets active=False on all active UniverseOverride rows for the ticker.  "
        "Returns deactivated_count=0 when there are no active overrides.  "
        "Returns 503 if the database is unavailable."
    ),
)
def delete_universe_override(
    ticker: str,
    state: AppStateDep,
    settings: SettingsDep,
) -> UniverseOverrideDeleteResponse:
    """Deactivate all active overrides for a ticker."""
    ticker = ticker.upper()

    try:
        from infra.db.models.universe_override import UniverseOverride
        from infra.db.session import db_session as _db_session

        with _db_session() as db:
            rows = (
                db.query(UniverseOverride)
                .filter(
                    UniverseOverride.ticker == ticker,
                    UniverseOverride.active == True,  # noqa: E712
                )
                .all()
            )
            for row in rows:
                row.active = False
            deactivated = len(rows)
            db.flush()

    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"DB update failed: {exc}") from exc

    return UniverseOverrideDeleteResponse(
        status="ok",
        ticker=ticker,
        deactivated_count=deactivated,
    )
