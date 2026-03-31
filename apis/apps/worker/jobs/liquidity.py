"""
Worker job: liquidity data refresh (Phase 41).

``run_liquidity_refresh``
    Queries the feature store DB for the latest ``dollar_volume_20d`` value
    per universe ticker (from ``security_feature_values`` joined to
    ``features`` and ``securities``).  Stores the result in
    ``app_state.latest_dollar_volumes`` so the paper trading cycle can apply
    the liquidity filter without blocking on a DB query mid-cycle.

Design rules
------------
- Fire-and-forget: all exceptions caught; scheduler thread never dies.
- Graceful degradation: on DB failure app_state.latest_dollar_volumes is
  left unchanged (stale-but-safe rather than empty).
- Runs at 06:17 ET — after correlation_refresh (06:16),
  before fundamentals_refresh (06:18).
- No writes to DB — pure read job.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from apps.api.state import ApiAppState
from config.logging_config import get_logger
from config.settings import Settings, get_settings

logger = get_logger(__name__)


def run_liquidity_refresh(
    app_state: ApiAppState,
    settings: Optional[Settings] = None,
    session_factory: Optional[Any] = None,
) -> dict[str, Any]:
    """Load latest dollar_volume_20d per ticker from the feature store DB.

    Args:
        app_state:       Shared ApiAppState; liquidity fields are updated.
        settings:        Settings instance; falls back to get_settings().
        session_factory: SQLAlchemy session factory; skips DB step when None.

    Returns:
        dict with keys: status, ticker_count, computed_at, error.
    """
    cfg = settings or get_settings()  # noqa: F841 — kept for future use
    run_at = dt.datetime.now(dt.timezone.utc)

    logger.info("liquidity_refresh_starting")

    if session_factory is None:
        logger.warning("liquidity_refresh_skipped_no_db")
        return {
            "status": "skipped_no_db",
            "ticker_count": 0,
            "computed_at": run_at.isoformat(),
            "error": "no session_factory",
        }

    try:
        dollar_volumes: dict[str, float] = {}

        try:
            from infra.db.models.analytics import Feature, SecurityFeatureValue  # noqa: PLC0415
            from infra.db.models import Security  # noqa: PLC0415
            import sqlalchemy as sa  # noqa: PLC0415

            with session_factory() as session:
                # Find the Feature row for dollar_volume_20d
                feat_row = session.execute(
                    sa.select(Feature).where(Feature.feature_key == "dollar_volume_20d")
                ).scalar_one_or_none()

                if feat_row is None:
                    logger.warning("liquidity_refresh_feature_key_not_found")
                    return {
                        "status": "no_feature",
                        "ticker_count": 0,
                        "computed_at": run_at.isoformat(),
                        "error": "dollar_volume_20d feature not in catalog",
                    }

                feature_id = feat_row.id

                # For each security, get the most recent dollar_volume_20d value.
                # Subquery: max as_of_timestamp per security for this feature.
                subq = (
                    sa.select(
                        SecurityFeatureValue.security_id,
                        sa.func.max(SecurityFeatureValue.as_of_timestamp).label("max_ts"),
                    )
                    .where(SecurityFeatureValue.feature_id == feature_id)
                    .group_by(SecurityFeatureValue.security_id)
                    .subquery()
                )

                rows = session.execute(
                    sa.select(Security.ticker, SecurityFeatureValue.feature_value_numeric)
                    .join(SecurityFeatureValue, SecurityFeatureValue.security_id == Security.id)
                    .join(
                        subq,
                        sa.and_(
                            subq.c.security_id == SecurityFeatureValue.security_id,
                            subq.c.max_ts == SecurityFeatureValue.as_of_timestamp,
                        ),
                    )
                    .where(SecurityFeatureValue.feature_id == feature_id)
                    .where(SecurityFeatureValue.feature_value_numeric.isnot(None))
                ).all()

            for ticker, value_numeric in rows:
                if ticker and value_numeric is not None:
                    dollar_volumes[ticker] = float(value_numeric)

        except Exception as db_exc:  # noqa: BLE001
            logger.warning("liquidity_refresh_db_load_failed", error=str(db_exc))
            return {
                "status": "error_db",
                "ticker_count": 0,
                "computed_at": run_at.isoformat(),
                "error": str(db_exc),
            }

        if not dollar_volumes:
            logger.warning("liquidity_refresh_no_data")
            return {
                "status": "no_data",
                "ticker_count": 0,
                "computed_at": run_at.isoformat(),
                "error": "no dollar_volume_20d values found",
            }

        # Update app_state in-memory
        app_state.latest_dollar_volumes = dollar_volumes
        app_state.liquidity_computed_at = run_at

        logger.info(
            "liquidity_refresh_complete",
            ticker_count=len(dollar_volumes),
        )

        return {
            "status": "ok",
            "ticker_count": len(dollar_volumes),
            "computed_at": run_at.isoformat(),
            "error": None,
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("liquidity_refresh_failed", error=str(exc))
        return {
            "status": "error",
            "ticker_count": 0,
            "computed_at": run_at.isoformat(),
            "error": str(exc),
        }
