"""
APIS FastAPI application.

Entry point for the API server. Routes are mounted in the routes/ directory.
"""
from __future__ import annotations

import datetime as _dt
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from apps.api.deps import AppStateDep, OperatorTokenDep, SettingsDep
from config.logging_config import configure_logging, get_logger
from config.settings import get_settings

settings = get_settings()
configure_logging(log_level=settings.log_level)
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Startup: load persisted kill switch + paper_cycle_count from DB
# ---------------------------------------------------------------------------

def _load_persisted_state() -> None:
    """Restore kill switch and paper_cycle_count from the system_state DB table.

    Runs once at process startup.  Failures are non-fatal — the process starts
    in a safe default state (kill_switch_active=False from env var check).

    Priority 19 — AppState Persistence
    """
    from apps.api.state import get_app_state

    app_state = get_app_state()
    cfg = get_settings()

    # Attach session factory to app_state so DB-backed API routes can use it
    try:
        from infra.db.session import SessionLocal
        app_state._session_factory = SessionLocal
        logger.info("session_factory_attached_to_app_state")
    except Exception as exc:  # noqa: BLE001
        logger.warning("session_factory_init_failed", error=str(exc))

    # env-var kill switch always takes precedence
    if cfg.kill_switch:
        app_state.kill_switch_active = True
        app_state.kill_switch_activated_by = "env"
        logger.info("kill_switch_active_from_env")

    try:
        from infra.db.models.system_state import (
            KEY_KILL_SWITCH_ACTIVATED_AT,
            KEY_KILL_SWITCH_ACTIVATED_BY,
            KEY_KILL_SWITCH_ACTIVE,
            KEY_PAPER_CYCLE_COUNT,
        )
        from infra.db.session import db_session as _db_session

        with _db_session() as db:
            from infra.db.models.system_state import SystemStateEntry

            def _get(key: str) -> str | None:
                entry = db.get(SystemStateEntry, key)
                return entry.value_text if entry else None

            # Kill switch — only apply if NOT already forced True by env var
            if not cfg.kill_switch:
                raw = _get(KEY_KILL_SWITCH_ACTIVE)
                if raw == "true":
                    app_state.kill_switch_active = True
                    at_raw = _get(KEY_KILL_SWITCH_ACTIVATED_AT)
                    if at_raw:
                        try:
                            app_state.kill_switch_activated_at = _dt.datetime.fromisoformat(at_raw)
                        except ValueError:
                            pass
                    app_state.kill_switch_activated_by = _get(KEY_KILL_SWITCH_ACTIVATED_BY) or None
                    logger.warning("kill_switch_restored_from_db")

            # Paper cycle count
            count_raw = _get(KEY_PAPER_CYCLE_COUNT)
            if count_raw is not None:
                try:
                    app_state.paper_cycle_count = int(count_raw)
                    logger.info("paper_cycle_count_restored", count=app_state.paper_cycle_count)
                except ValueError:
                    pass

    except Exception as exc:  # noqa: BLE001
        logger.warning("load_persisted_state_failed", error=str(exc))

    # Restore latest rankings from DB so paper cycles are not blocked after a restart
    try:
        import sqlalchemy as _sa

        from infra.db.models import Security
        from infra.db.models.signal import RankedOpportunity, RankingRun
        from infra.db.session import db_session as _db_session_rank
        from services.ranking_engine.models import RankedResult

        with _db_session_rank() as db:
            latest_run = db.execute(
                _sa.select(RankingRun).order_by(RankingRun.run_timestamp.desc()).limit(1)
            ).scalar_one_or_none()

            if latest_run is not None:
                rows = db.execute(
                    _sa.select(RankedOpportunity, Security.ticker)
                    .join(Security, Security.id == RankedOpportunity.security_id)
                    .where(RankedOpportunity.ranking_run_id == latest_run.id)
                    .order_by(RankedOpportunity.rank_position)
                ).all()

                restored: list[RankedResult] = []
                for opp, ticker in rows:
                    restored.append(RankedResult(
                        rank_position=opp.rank_position,
                        security_id=opp.security_id,
                        ticker=ticker,
                        composite_score=opp.composite_score,
                        portfolio_fit_score=opp.portfolio_fit_score,
                        recommended_action=opp.recommended_action,
                        target_horizon=opp.target_horizon or "medium",
                        thesis_summary=opp.thesis_summary or "",
                        disconfirming_factors=opp.disconfirming_factors or "",
                        sizing_hint_pct=opp.sizing_hint_pct,
                        source_reliability_tier="secondary_verified",
                        contains_rumor=False,
                        as_of=latest_run.run_timestamp,
                    ))

                if restored:
                    app_state.latest_rankings = restored
                    app_state.last_ranking_run_id = str(latest_run.id)
                    logger.info(
                        "latest_rankings_restored_from_db",
                        count=len(restored),
                        run_id=str(latest_run.id),
                    )
    except Exception as exc:  # noqa: BLE001
        logger.warning("latest_rankings_restore_failed", error=str(exc))

    # Restore latest portfolio snapshot equity baseline from DB (Priority 20)
    try:
        from infra.db.models.portfolio import PortfolioSnapshot as _DBSnap
        from infra.db.session import db_session as _db_session2

        with _db_session2() as db:
            latest_snap = (
                db.query(_DBSnap)
                .order_by(_DBSnap.snapshot_timestamp.desc())
                .first()
            )
            if latest_snap is not None:
                app_state.last_snapshot_at = latest_snap.snapshot_timestamp
                app_state.last_snapshot_equity = (
                    float(latest_snap.equity_value)
                    if latest_snap.equity_value is not None
                    else None
                )
                logger.info(
                    "portfolio_snapshot_restored",
                    equity=app_state.last_snapshot_equity,
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("load_portfolio_snapshot_failed", error=str(exc))

    # ── Phase 31: Initialize webhook alert service ──────────────────────────
    try:
        webhook_url = getattr(cfg, "webhook_url", "")
        webhook_secret = getattr(cfg, "webhook_secret", "")
        if webhook_url:
            from services.alerting.service import make_alert_service
            app_state.alert_service = make_alert_service(
                webhook_url=webhook_url,
                secret=webhook_secret,
            )
            logger.info("webhook_alert_service_initialized")
    except Exception as exc:  # noqa: BLE001
        logger.warning("webhook_alert_service_init_failed", error=str(exc))

    # ── Broker adapter initialization ────────────────────────────────────────
    try:
        from broker_adapters.alpaca.adapter import AlpacaBrokerAdapter
        from config.settings import get_alpaca_settings
        alpaca_cfg = get_alpaca_settings()
        if alpaca_cfg.is_configured:
            adapter = AlpacaBrokerAdapter(
                api_key=alpaca_cfg.alpaca_api_key,
                api_secret=alpaca_cfg.alpaca_api_secret,
                paper=True,
            )
            adapter.connect()
            app_state.broker_adapter = adapter
            logger.info("broker_adapter_initialized", adapter=adapter.adapter_name)
        else:
            logger.warning("broker_adapter_skipped_no_credentials")
    except Exception as exc:  # noqa: BLE001
        logger.warning("broker_adapter_init_failed", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    """FastAPI lifespan — runs _load_persisted_state() on startup, then
    starts the APScheduler worker in the same process so that the scheduler
    and the API share a single ApiAppState instance.  This eliminates the
    multi-process state-sharing gap where the worker updated its own isolated
    in-memory state and the API served stale data to the dashboard.
    """
    _load_persisted_state()

    # Start the APScheduler in a background thread inside this process.
    # Both the scheduler jobs and the API routes now call get_app_state()
    # and receive the *same* singleton object.
    scheduler = None
    try:
        from apps.worker.main import (
            _setup_alert_service,  # noqa: PLC0415
            build_scheduler,  # noqa: PLC0415
        )
        _setup_alert_service()
        scheduler = build_scheduler()
        scheduler.start()
        logger.info(
            "apis_scheduler_started_in_api_process",
            job_count=len(scheduler.get_jobs()),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("apis_scheduler_start_failed", error=str(exc))

    yield

    # Graceful shutdown
    if scheduler is not None:
        try:
            scheduler.shutdown(wait=False)
            logger.info("apis_scheduler_stopped")
        except Exception as exc:  # noqa: BLE001
            logger.warning("apis_scheduler_stop_failed", error=str(exc))


app = FastAPI(
    lifespan=lifespan,
    title="APIS — Autonomous Portfolio Intelligence System",
    version="0.1.0",
    description=(
        "A disciplined, modular, auditable portfolio operating system for U.S. equities. "
        "Research mode only in MVP."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

# Mount all v1 routers under /api/v1 prefix
from apps.api.routes import (  # noqa: E402
    actions_router,
    admin_router,
    backtest_router,
    config_router,
    correlation_router,
    earnings_router,
    evaluation_router,
    exit_levels_router,
    factor_router,
    factor_tilt_router,
    fill_quality_router,
    intelligence_router,
    liquidity_router,
    live_gate_router,
    metrics_router,
    portfolio_router,
    prices_router,
    rankings_router,
    readiness_router,
    rebalance_router,
    recommendations_router,
    regime_router,
    reports_router,
    sector_router,
    self_improvement_router,
    signal_quality_router,
    signals_router,
    stress_router,
    universe_router,
    var_router,
    weights_router,
)

_V1 = "/api/v1"
_AUTH = [OperatorTokenDep]  # applied to every /api/v1/* route

app.include_router(recommendations_router, prefix=_V1, dependencies=_AUTH)
app.include_router(portfolio_router,        prefix=_V1, dependencies=_AUTH)
app.include_router(actions_router,          prefix=_V1, dependencies=_AUTH)
app.include_router(evaluation_router,       prefix=_V1, dependencies=_AUTH)
app.include_router(reports_router,          prefix=_V1, dependencies=_AUTH)
app.include_router(config_router,           prefix=_V1, dependencies=_AUTH)
app.include_router(live_gate_router,        prefix=_V1, dependencies=_AUTH)
app.include_router(admin_router,            prefix=_V1, dependencies=_AUTH)
app.include_router(intelligence_router,     prefix=_V1, dependencies=_AUTH)
app.include_router(signals_router,          prefix=_V1, dependencies=_AUTH)
app.include_router(rankings_router,         prefix=_V1, dependencies=_AUTH)
app.include_router(backtest_router,         prefix=_V1, dependencies=_AUTH)
app.include_router(self_improvement_router, prefix=_V1, dependencies=_AUTH)
app.include_router(prices_router,           prefix=_V1, dependencies=_AUTH)
app.include_router(weights_router,          prefix=_V1, dependencies=_AUTH)
app.include_router(regime_router,           prefix=_V1, dependencies=_AUTH)
app.include_router(correlation_router,      prefix=_V1, dependencies=_AUTH)
app.include_router(sector_router,           prefix=_V1, dependencies=_AUTH)
app.include_router(liquidity_router,        prefix=_V1, dependencies=_AUTH)
app.include_router(var_router,              prefix=_V1, dependencies=_AUTH)
app.include_router(stress_router,           prefix=_V1, dependencies=_AUTH)
app.include_router(earnings_router,         prefix=_V1, dependencies=_AUTH)
app.include_router(signal_quality_router,   prefix=_V1, dependencies=_AUTH)
app.include_router(exit_levels_router,      prefix=_V1, dependencies=_AUTH)
app.include_router(universe_router,         prefix=_V1, dependencies=_AUTH)
app.include_router(rebalance_router,        prefix=_V1, dependencies=_AUTH)
app.include_router(factor_router,           prefix=_V1, dependencies=_AUTH)
app.include_router(fill_quality_router,     prefix=_V1, dependencies=_AUTH)
app.include_router(factor_tilt_router,      prefix=_V1, dependencies=_AUTH)

# Readiness probes — no auth (must respond even before token is configured)
app.include_router(readiness_router, prefix=_V1)

# Prometheus metrics endpoint (no auth — scraped by monitoring infrastructure)
app.include_router(metrics_router)

# Read-only operator dashboard
from apps.dashboard.router import dashboard_router  # noqa: E402

app.include_router(dashboard_router)


@app.get("/health", tags=["System"])
async def health(state: AppStateDep, cfg: SettingsDep) -> JSONResponse:
    """Health check returning process, DB, broker, and scheduler liveness.

    Returns HTTP 200 for "ok" / "degraded" states so docker healthcheck stays
    green as long as the API process itself is alive.  Returns HTTP 503 only
    when the database is unreachable (truly critical — nothing works without DB).
    """
    components: dict[str, str] = {}

    # ── Database ──────────────────────────────────────────────────────────────
    try:
        from infra.db.session import engine  # lazy import — avoids import-time crash
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        components["db"] = "ok"
    except Exception:
        components["db"] = "down"

    # ── Broker adapter ────────────────────────────────────────────────────────
    broker = state.broker_adapter
    if broker is None:
        components["broker"] = "not_connected"
    else:
        try:
            components["broker"] = "ok" if broker.ping() else "degraded"
        except Exception:
            components["broker"] = "error"

    # ── Scheduler (inferred from paper cycle timestamps) ──────────────────────
    last_cycle = state.last_paper_cycle_at
    if last_cycle is None:
        components["scheduler"] = "no_data"
    else:
        age_s = (_dt.datetime.now(tz=_dt.UTC) - last_cycle).total_seconds()
        components["scheduler"] = "stale" if age_s > 7200 else "ok"

    # ── Broker auth token ─────────────────────────────────────────────────────
    components["broker_auth"] = "expired" if state.broker_auth_expired else "ok"

    # ── Kill switch ───────────────────────────────────────────────────────────
    effective_kill = getattr(state, "kill_switch_active", False) or cfg.kill_switch
    components["kill_switch"] = "active" if effective_kill else "ok"

    # ── Overall status ────────────────────────────────────────────────────────
    if components["db"] == "down":
        overall = "down"
    elif any(v in ("down", "error", "stale", "expired", "active") for v in components.values()):
        overall = "degraded"
    else:
        overall = "ok"

    http_status = 503 if overall == "down" else 200
    return JSONResponse(
        status_code=http_status,
        content={
            "status": overall,
            "service": "api",
            "mode": cfg.operating_mode.value,
            "timestamp": _dt.datetime.now(tz=_dt.UTC).isoformat(),
            "components": components,
        },
    )


@app.get("/system/status", tags=["System"])
async def system_status(state: AppStateDep, cfg: SettingsDep) -> dict[str, object]:
    """Return current system mode and operating status."""
    effective_kill = getattr(state, "kill_switch_active", False) or cfg.kill_switch
    return {
        "env": cfg.env.value,
        "mode": cfg.operating_mode.value,
        "kill_switch": effective_kill,
        "max_positions": cfg.max_positions,
        "latest_ranking_run_id": getattr(state, "last_ranking_run_id", None),
        "latest_evaluation_run_id": getattr(state, "evaluation_run_id", None),
    }


logger.info("apis_api_initialized", mode=settings.operating_mode.value)
