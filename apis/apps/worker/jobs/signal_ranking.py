"""
Worker job: signal generation, ranking, weight optimization, and regime detection.

Functions
---------
run_signal_generation   — generate signals for universe tickers (DB path)
run_ranking_generation  — rank signals and write results to ApiAppState
run_weight_optimization — derive Sharpe-proportional strategy weights from
                          the latest backtest comparison and update
                          app_state.active_weight_profile
run_regime_detection    — classify market regime from latest ranking signals;
                          writes RegimeResult to app_state.current_regime_result
                          and regime-adaptive weights to app_state.active_weight_profile

Design rules
------------
- run_signal_generation needs a DB session; skips gracefully when
  session_factory is None.
- run_ranking_generation uses the pure in-memory RankingEngineService path
  and writes directly to app_state.latest_rankings.
- run_weight_optimization reads BacktestRun rows from DB; skips gracefully
  when session_factory is None or no backtest data exists.
- run_regime_detection uses app_state.latest_rankings as input signals;
  no session_factory required for detection (DB persist is fire-and-forget).
- All functions catch all exceptions so the scheduler thread never dies.
"""
from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from typing import Any

from apps.api.state import ApiAppState
from config.logging_config import get_logger
from config.settings import Settings, get_settings
from config.universe import get_universe_tickers

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# run_signal_generation
# ---------------------------------------------------------------------------

def run_signal_generation(
    app_state: ApiAppState,
    settings: Settings | None = None,
    session_factory: Callable | None = None,
    signal_service: Any | None = None,
) -> dict[str, Any]:
    """Generate and persist signals for the universe using the DB path.

    Args:
        app_state:       Shared ApiAppState — not written by this job directly
                         (signals are consumed by run_ranking_generation).
        settings:        Settings instance.
        session_factory: Callable returning a SQLAlchemy Session.  Skips when
                         None.
        signal_service:  SignalEngineService instance for injection/testing.

    Returns:
        dict with keys: status, signal_run_id, tickers, errors, run_at.
    """
    cfg = settings or get_settings()
    run_at = dt.datetime.now(dt.UTC)

    logger.info("signal_generation_job_starting", run_at=run_at.isoformat())

    if session_factory is None:
        logger.warning("signal_generation_job_skipped_no_session_factory")
        return {
            "status": "skipped_no_session",
            "signal_run_id": None,
            "tickers": [],
            "errors": [],
            "run_at": run_at.isoformat(),
        }

    try:
        from services.signal_engine.service import SignalEngineService

        svc = signal_service or SignalEngineService()
        # Phase 48: use active_universe if populated; fall back to static universe
        active_universe = getattr(app_state, "active_universe", [])
        tickers = list(active_universe) if active_universe else get_universe_tickers()
        signal_run_id = uuid.uuid4()

        # Pull intelligence overlays from app_state (populated by run_feature_enrichment)
        policy_signals = getattr(app_state, "latest_policy_signals", [])
        news_insights = getattr(app_state, "latest_news_insights", [])
        fundamentals_store = getattr(app_state, "latest_fundamentals", {})

        with session_factory() as session:
            outputs = svc.run(
                session=session,
                signal_run_id=signal_run_id,
                tickers=tickers,
                policy_signals=policy_signals,
                news_insights=news_insights,
                fundamentals_store=fundamentals_store,
            )
            session.commit()

        # Propagate signal_run_id so run_ranking_generation can link RankingRun → SignalRun
        app_state.last_signal_run_id = str(signal_run_id)

        logger.info(
            "signal_generation_job_complete",
            signal_run_id=str(signal_run_id),
            tickers=len(tickers),
            signals=len(outputs),
        )
        return {
            "status": "ok",
            "signal_run_id": str(signal_run_id),
            "tickers": tickers,
            "errors": [],
            "run_at": run_at.isoformat(),
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("signal_generation_job_failed", error=str(exc))
        return {
            "status": "error",
            "signal_run_id": None,
            "tickers": [],
            "errors": [str(exc)],
            "run_at": run_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# run_ranking_generation
# ---------------------------------------------------------------------------

def run_ranking_generation(
    app_state: ApiAppState,
    settings: Settings | None = None,
    signals: list[Any] | None = None,
    ranking_service: Any | None = None,
    session_factory: Any | None = None,
) -> dict[str, Any]:
    """Rank signals and write the result list to app_state.latest_rankings.

    When a ``session_factory`` is provided AND ``app_state.last_signal_run_id``
    is set, the DB path is used: a ``RankingRun`` row and per-ticker
    ``RankedOpportunity`` rows are persisted and
    ``app_state.last_ranking_run_id`` is set for the history API.

    Falls back to the pure in-memory path when either is absent.

    Args:
        app_state:       Shared ApiAppState — latest_rankings is written here.
        settings:        Settings instance.
        signals:         Pre-built list of SignalOutput objects.  When None an
                         empty list is used (produces empty rankings).
        ranking_service: RankingEngineService instance for injection/testing.
        session_factory: Callable returning a SQLAlchemy Session.  When
                         provided together with a valid last_signal_run_id the
                         DB-persistence path is taken.

    Returns:
        dict with keys: status, ranking_run_id, ranked_count, run_at.
    """
    from services.ranking_engine.service import RankingEngineService

    cfg = settings or get_settings()
    run_at = dt.datetime.now(dt.UTC)
    ranking_run_id = str(uuid.uuid4())

    logger.info("ranking_generation_job_starting", run_at=run_at.isoformat())

    try:
        svc = ranking_service or RankingEngineService()

        # Preserve None so svc.run() can trigger its own DB load when no
        # signals are explicitly injected.  Only fall back to [] on the
        # in-memory path where there is no DB to load from.
        signal_run_id_str = getattr(app_state, "last_signal_run_id", None)

        if session_factory is not None and signal_run_id_str is not None:
            # --- DB path: persist RankingRun + RankedOpportunity rows.
            # Pass signals=None (unless caller injected them) so svc.run()
            # loads the full SignalOutput list from the DB via signal_run_id.
            import uuid as _uuid
            signal_run_uuid = _uuid.UUID(signal_run_id_str)
            with session_factory() as session:
                db_run_id, ranked = svc.run(
                    session=session,
                    signal_run_id=signal_run_uuid,
                    signals=signals,  # None → DB load; list → use as-is
                )
                session.commit()
            ranking_run_id = str(db_run_id)
            logger.info(
                "ranking_generation_job_complete_db",
                ranking_run_id=ranking_run_id,
                ranked_count=len(ranked),
            )
        else:
            # --- In-memory fallback (no DB available)
            ranked = svc.rank_signals(signals or [], max_results=cfg.max_positions)
            logger.info(
                "ranking_generation_job_complete_memory",
                ranking_run_id=ranking_run_id,
                ranked_count=len(ranked),
            )

        # Write to shared state
        app_state.latest_rankings = ranked
        app_state.ranking_run_id = ranking_run_id
        app_state.ranking_as_of = run_at
        app_state.last_ranking_run_id = ranking_run_id

        return {
            "status": "ok",
            "ranking_run_id": ranking_run_id,
            "ranked_count": len(ranked),
            "run_at": run_at.isoformat(),
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("ranking_generation_job_failed", error=str(exc))
        return {
            "status": "error",
            "ranking_run_id": ranking_run_id,
            "ranked_count": 0,
            "run_at": run_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# run_weight_optimization
# ---------------------------------------------------------------------------

def run_weight_optimization(
    app_state: ApiAppState,
    settings: Settings | None = None,
    session_factory: Callable | None = None,
) -> dict[str, Any]:
    """Derive Sharpe-proportional strategy weights from the latest backtest.

    Reads BacktestRun rows for the most recent comparison_id from the DB,
    computes normalised per-strategy weights via WeightOptimizerService,
    persists the result as an active WeightProfile, and writes the profile
    to ``app_state.active_weight_profile`` so the next ranking cycle picks
    it up without needing an API call.

    Skips gracefully when session_factory is None or no backtest data exists.
    Never raises — all exceptions are caught and logged.

    Args:
        app_state:       Shared ApiAppState — active_weight_profile written here.
        settings:        Settings instance (unused; kept for signature symmetry).
        session_factory: Callable returning a SQLAlchemy Session.

    Returns:
        dict with keys: status, profile_id, profile_name, weights, run_at.
    """
    run_at = dt.datetime.now(dt.UTC)
    logger.info("weight_optimization_job_starting", run_at=run_at.isoformat())

    if session_factory is None:
        logger.warning("weight_optimization_job_skipped_no_session_factory")
        return {
            "status": "skipped_no_session",
            "profile_id": None,
            "profile_name": None,
            "weights": {},
            "run_at": run_at.isoformat(),
        }

    try:
        import sqlalchemy as sa

        from infra.db.models.backtest import BacktestRun
        from services.signal_engine.weight_optimizer import WeightOptimizerService

        with session_factory() as session:
            newest_comparison_id = session.execute(
                sa.select(BacktestRun.comparison_id)
                .order_by(BacktestRun.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()

            if newest_comparison_id is None:
                logger.info("weight_optimization_job_skipped_no_backtest_data")
                return {
                    "status": "skipped_no_backtest_data",
                    "profile_id": None,
                    "profile_name": None,
                    "weights": {},
                    "run_at": run_at.isoformat(),
                }

            runs = session.execute(
                sa.select(BacktestRun).where(
                    BacktestRun.comparison_id == newest_comparison_id
                )
            ).scalars().all()

        svc = WeightOptimizerService(session_factory=session_factory)
        profile = svc.optimize_from_backtest(
            backtest_runs=runs,
            comparison_id=newest_comparison_id,
            set_active=True,
        )

        # Propagate to in-memory state immediately
        app_state.active_weight_profile = profile

        logger.info(
            "weight_optimization_job_complete",
            profile_id=profile.id,
            profile_name=profile.profile_name,
            weights=profile.weights,
        )
        return {
            "status": "ok",
            "profile_id": profile.id,
            "profile_name": profile.profile_name,
            "weights": profile.weights,
            "run_at": run_at.isoformat(),
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("weight_optimization_job_failed", error=str(exc))
        return {
            "status": "error",
            "profile_id": None,
            "profile_name": None,
            "weights": {},
            "run_at": run_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# run_regime_detection
# ---------------------------------------------------------------------------

def run_regime_detection(
    app_state: ApiAppState,
    settings: Settings | None = None,
    session_factory: Callable | None = None,
) -> dict[str, Any]:
    """Classify market regime from latest ranking signals.

    Reads ``app_state.latest_rankings`` as universe signals.  If an active
    manual override is stored in ``app_state.current_regime_result`` it is
    respected without re-computing.

    When the detected regime differs from the previous one (or no profile
    exists yet), a regime-adaptive ``WeightProfileRecord`` is written to
    ``app_state.active_weight_profile`` so the next 06:45 ranking cycle
    picks up the updated weights.  The 06:52 weight optimisation job may
    further refine the profile from backtest data.

    DB persistence of the RegimeSnapshot is fire-and-forget; ``session_factory``
    is optional (None = skip DB write).  Never raises — all exceptions caught.

    Args:
        app_state:       Shared ApiAppState.
        settings:        Settings instance (unused; kept for signature symmetry).
        session_factory: Callable returning a SQLAlchemy Session (optional).

    Returns:
        dict with keys: status, regime, confidence, regime_changed, run_at.
    """
    run_at = dt.datetime.now(dt.UTC)
    logger.info("regime_detection_job_starting", run_at=run_at.isoformat())

    try:
        from services.signal_engine.regime_detection import (
            MarketRegime,
            RegimeDetectionService,
        )
        from services.signal_engine.weight_optimizer import WeightProfileRecord

        signals = getattr(app_state, "latest_rankings", [])
        previous = getattr(app_state, "current_regime_result", None)

        svc = RegimeDetectionService(session_factory=session_factory)

        # Respect an active manual override — do not overwrite it
        if previous is not None and getattr(previous, "is_manual_override", False):
            result = previous
            logger.info(
                "regime_detection_job_manual_override_active",
                regime=result.regime.value
                if hasattr(result.regime, "value")
                else str(result.regime),
            )
        else:
            result = svc.detect_from_signals(signals)

        # ---- Update app_state ------------------------------------------------
        app_state.current_regime_result = result

        history: list[Any] = getattr(app_state, "regime_history", [])
        history.append(result)
        if len(history) > 30:
            history = history[-30:]
        app_state.regime_history = history

        # ---- Regime-adaptive weight profile ---------------------------------
        prev_regime = getattr(previous, "regime", None) if previous else None
        current_regime: MarketRegime = result.regime
        regime_changed = prev_regime is None or prev_regime != current_regime

        if regime_changed:
            weights = svc.get_regime_weights(current_regime)
            profile = WeightProfileRecord(
                id=str(uuid.uuid4()),
                profile_name=f"regime_{current_regime.value.lower()}",
                source="regime",
                weights=weights,
                sharpe_metrics={},
                is_active=True,
                notes=f"Auto-derived from regime detection: {current_regime.value}",
            )
            app_state.active_weight_profile = profile
            logger.info(
                "regime_detection_job_weights_updated",
                regime=current_regime.value,
                weights=weights,
            )

        # ---- Fire-and-forget DB persist -------------------------------------
        svc.persist_snapshot(result, session_factory=session_factory)

        regime_str = (
            result.regime.value if hasattr(result.regime, "value") else str(result.regime)
        )
        logger.info(
            "regime_detection_job_complete",
            regime=regime_str,
            confidence=result.confidence,
            regime_changed=regime_changed,
        )
        return {
            "status": "ok",
            "regime": regime_str,
            "confidence": result.confidence,
            "regime_changed": regime_changed,
            "run_at": run_at.isoformat(),
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("regime_detection_job_failed", error=str(exc))
        return {
            "status": "error",
            "regime": None,
            "confidence": 0.0,
            "regime_changed": False,
            "run_at": run_at.isoformat(),
        }
