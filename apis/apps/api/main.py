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

from config.logging_config import configure_logging, get_logger
from config.settings import get_settings
from apps.api.deps import AppStateDep, SettingsDep

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
        from config.settings import get_alpaca_settings
        from broker_adapters.alpaca.adapter import AlpacaBrokerAdapter
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
    """FastAPI lifespan — runs _load_persisted_state() on startup."""
    _load_persisted_state()
    yield


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
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Mount all v1 routers under /api/v1 prefix
from apps.api.routes import (  # noqa: E402
    actions_router,
    admin_router,
    backtest_router,
    config_router,
    correlation_router,
    evaluation_router,
    exit_levels_router,
    intelligence_router,
    live_gate_router,
    liquidity_router,
    metrics_router,
    portfolio_router,
    prices_router,
    rankings_router,
    recommendations_router,
    reports_router,
    self_improvement_router,
    signals_router,
    weights_router,
    regime_router,
    sector_router,
    var_router,
    stress_router,
    earnings_router,
    signal_quality_router,
    universe_router,
    rebalance_router,
    factor_router,
    fill_quality_router,
    readiness_router,
    factor_tilt_router,
)

_V1 = "/api/v1"
app.include_router(recommendations_router, prefix=_V1)
app.include_router(portfolio_router,        prefix=_V1)
app.include_router(actions_router,          prefix=_V1)
app.include_router(evaluation_router,       prefix=_V1)
app.include_router(reports_router,          prefix=_V1)
app.include_router(config_router,           prefix=_V1)
app.include_router(live_gate_router,        prefix=_V1)
app.include_router(admin_router,            prefix=_V1)
app.include_router(intelligence_router,     prefix=_V1)
app.include_router(signals_router,          prefix=_V1)
app.include_router(rankings_router,         prefix=_V1)
app.include_router(backtest_router,         prefix=_V1)
app.include_router(self_improvement_router, prefix=_V1)
app.include_router(prices_router,           prefix=_V1)
app.include_router(weights_router,          prefix=_V1)
app.include_router(regime_router,           prefix=_V1)
app.include_router(correlation_router,      prefix=_V1)
app.include_router(sector_router,           prefix=_V1)
app.include_router(liquidity_router,        prefix=_V1)
app.include_router(var_router,              prefix=_V1)
app.include_router(stress_router,           prefix=_V1)
app.include_router(earnings_router,         prefix=_V1)
app.include_router(signal_quality_router,   prefix=_V1)
app.include_router(exit_levels_router,      prefix=_V1)
app.include_router(universe_router,         prefix=_V1)
app.include_router(rebalance_router,        prefix=_V1)
app.include_router(factor_router,           prefix=_V1)
app.include_router(fill_quality_router,     prefix=_V1)
app.include_router(readiness_router,        prefix=_V1)
app.include_router(factor_tilt_router,      prefix=_V1)

# Prometheus metrics endpoint (no prefix — standard /metrics path)
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
        age_s = (_dt.datetime.now(tz=_dt.timezone.utc) - last_cycle).total_seconds()
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
            "timestamp": _dt.datetime.now(tz=_dt.timezone.utc).isoformat(),
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
        "latest_ranking_run_id": None,  # populated once ranking engine is live
        "latest_evaluation_run_id": None,
    }


logger.info("apis_api_initialized", mode=settings.operating_mode.value)
