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
                    activated_by = _get(KEY_KILL_SWITCH_ACTIVATED_BY) or ""
                    # Guard: test-pollution rows (activated_by "testclient" or
                    # empty/None) are NOT legitimate kill-switch activations.
                    # Auto-clear them instead of loading stale state into runtime.
                    _is_test_pollution = activated_by.lower() in (
                        "testclient", "test", "pytest", "",
                    )
                    if _is_test_pollution:
                        logger.warning(
                            "kill_switch_stale_test_pollution_detected",
                            activated_by=activated_by or "empty",
                            action="auto_clearing_db_rows",
                        )
                        for _stale_key in (
                            KEY_KILL_SWITCH_ACTIVE,
                            KEY_KILL_SWITCH_ACTIVATED_AT,
                            KEY_KILL_SWITCH_ACTIVATED_BY,
                        ):
                            _stale_entry = db.get(SystemStateEntry, _stale_key)
                            if _stale_entry:
                                db.delete(_stale_entry)
                        db.commit()
                        logger.info("kill_switch_test_pollution_cleared")
                    else:
                        app_state.kill_switch_active = True
                        at_raw = _get(KEY_KILL_SWITCH_ACTIVATED_AT)
                        if at_raw:
                            try:
                                app_state.kill_switch_activated_at = (
                                    _dt.datetime.fromisoformat(at_raw)
                                )
                            except ValueError:
                                pass
                        app_state.kill_switch_activated_by = activated_by or None
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
                # Restore last_paper_cycle_at so the health check doesn't
                # report "no_data" after every restart.  The snapshot timestamp
                # is the best available proxy for the last successful cycle.
                # Ensure timezone-aware (health check uses UTC-aware datetime).
                _snap_ts = latest_snap.snapshot_timestamp
                if _snap_ts is not None and _snap_ts.tzinfo is None:
                    _snap_ts = _snap_ts.replace(tzinfo=_dt.UTC)
                app_state.last_paper_cycle_at = _snap_ts
                logger.info(
                    "portfolio_snapshot_restored",
                    equity=app_state.last_snapshot_equity,
                    last_cycle_at=str(latest_snap.snapshot_timestamp),
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("load_portfolio_snapshot_failed", error=str(exc))

    # ── Phase 59: Restore portfolio_state from open Position rows ───────────
    try:
        from decimal import Decimal as _Dec

        import sqlalchemy as _sa_port

        from infra.db.models import Security
        from infra.db.models.portfolio import PortfolioSnapshot as _DBSnap2
        from infra.db.models.portfolio import Position as _DBPosition
        from infra.db.session import db_session as _db_sess_port
        from services.portfolio_engine.models import PortfolioPosition, PortfolioState

        with _db_sess_port() as db:
            # Get latest snapshot for cash / HWM / SOD
            snap = db.execute(
                _sa_port.select(_DBSnap2)
                .order_by(_DBSnap2.snapshot_timestamp.desc())
                .limit(1)
            ).scalar_one_or_none()

            # Get open positions
            open_rows = db.execute(
                _sa_port.select(_DBPosition, Security.ticker)
                .join(Security, Security.id == _DBPosition.security_id)
                .where(_DBPosition.status == "open")
                .order_by(_DBPosition.opened_at)
            ).all()

            if snap is not None or open_rows:
                positions: dict[str, PortfolioPosition] = {}
                for pos, ticker in open_rows:
                    qty = _Dec(str(pos.quantity)) if pos.quantity else _Dec("0")
                    entry = _Dec(str(pos.entry_price)) if pos.entry_price else _Dec("0")
                    # Use market_value / quantity as current price proxy; fall back to entry
                    if pos.market_value and qty > 0:
                        cur_price = (_Dec(str(pos.market_value)) / qty).quantize(_Dec("0.000001"))
                    else:
                        cur_price = entry
                    # Phase 72: restore origin_strategy from DB so
                    # broker-sync + _persist_positions don't lose it.
                    # Phase 73 (2026-05-04): re-indented INTO the loop —
                    # the previous dedent meant only the last-iteration
                    # position was added to the dict, restoring 1 of N
                    # positions on every API boot.  See HEALTH_LOG and
                    # project_phase73_position_restore_indentation.md.
                    _db_os = getattr(pos, "origin_strategy", None) or ""
                    positions[ticker] = PortfolioPosition(
                        ticker=ticker,
                        quantity=qty,
                        avg_entry_price=entry,
                        current_price=cur_price,
                        opened_at=pos.opened_at,
                        thesis_summary=(pos.thesis_snapshot_json or {}).get("summary", "") if isinstance(pos.thesis_snapshot_json, dict) else "",
                        strategy_key="",
                        security_id=pos.security_id,
                        origin_strategy=_db_os,
                    )

                cash = _Dec(str(snap.cash_balance)) if snap and snap.cash_balance else _Dec("100000")
                equity_val = _Dec(str(snap.equity_value)) if snap and snap.equity_value else None

                # Phase 63 guard (2026-04-14), strengthened Phase 70
                # (2026-04-29): refuse to restore ANY snapshot with
                # negative cash in paper mode.  The paper broker enforces
                # InsufficientFundsError, so negative cash is always a
                # bug (originally from concurrent-cycle race conditions).
                # The previous guard required zero positions to trigger,
                # but the race can produce negative cash WITH positions.
                if cash < _Dec("0"):
                    logger.warning(
                        "portfolio_state_restore_phantom_cash_reset",
                        snapshot_cash=str(cash),
                        snapshot_equity=str(equity_val),
                        position_count=len(positions),
                        reason="negative cash in paper mode — resetting to $100k",
                    )
                    cash = _Dec("100000")
                    equity_val = _Dec("100000")
                    # Also clear restored positions — they were sized
                    # against a corrupt cash baseline and the broker
                    # starts fresh on restart anyway.
                    positions = {}

                app_state.portfolio_state = PortfolioState(
                    cash=cash,
                    positions=positions,
                    start_of_day_equity=equity_val,
                    start_of_month_equity=equity_val,
                    high_water_mark=equity_val,
                    daily_opens_count=0,
                )
                logger.info(
                    "portfolio_state_restored_from_db",
                    positions=len(positions),
                    cash=str(cash),
                    equity=str(equity_val),
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("portfolio_state_restore_failed", error=str(exc))

    # ── Phase 59: Restore closed_trades + trade_grades from closed Positions ─
    try:
        from decimal import Decimal as _Dec2

        import sqlalchemy as _sa_ct

        from infra.db.models import Security as _Sec2
        from infra.db.models.portfolio import Position as _DBPos2
        from infra.db.session import db_session as _db_sess_ct
        from services.evaluation_engine.models import PositionGrade
        from services.portfolio_engine.models import ActionType, ClosedTrade

        with _db_sess_ct() as db:
            closed_rows = db.execute(
                _sa_ct.select(_DBPos2, _Sec2.ticker)
                .join(_Sec2, _Sec2.id == _DBPos2.security_id)
                .where(_DBPos2.status == "closed")
                .where(_DBPos2.closed_at.isnot(None))
                .order_by(_DBPos2.closed_at.desc())
                .limit(200)
            ).all()

            restored_trades: list = []
            restored_grades: list = []
            for pos, ticker in closed_rows:
                entry_p = _Dec2(str(pos.entry_price)) if pos.entry_price else _Dec2("0")
                exit_p = _Dec2(str(pos.exit_price)) if pos.exit_price else entry_p
                qty = _Dec2(str(pos.quantity)) if pos.quantity else _Dec2("0")
                r_pnl = _Dec2(str(pos.realized_pnl)) if pos.realized_pnl else (exit_p - entry_p) * qty
                cost = entry_p * qty if qty else _Dec2("1")
                r_pnl_pct = (r_pnl / cost) if cost else _Dec2("0")
                opened = pos.opened_at or _dt.datetime.now(_dt.UTC)
                closed = pos.closed_at or _dt.datetime.now(_dt.UTC)
                hold_days = (closed.date() - opened.date()).days if closed and opened else 0

                ct = ClosedTrade(
                    ticker=ticker,
                    action_type=ActionType.CLOSE,
                    fill_price=exit_p,
                    avg_entry_price=entry_p,
                    quantity=qty,
                    realized_pnl=r_pnl,
                    realized_pnl_pct=r_pnl_pct,
                    reason="restored_from_db",
                    opened_at=opened,
                    closed_at=closed,
                    hold_duration_days=hold_days,
                )
                restored_trades.append(ct)

                # Re-derive the trade grade from P&L percentage
                if r_pnl_pct >= _Dec2("0.05"):
                    grade = "A"
                elif r_pnl_pct >= _Dec2("0.02"):
                    grade = "B"
                elif r_pnl_pct >= _Dec2("0"):
                    grade = "C"
                elif r_pnl_pct >= _Dec2("-0.03"):
                    grade = "D"
                else:
                    grade = "F"
                restored_grades.append(PositionGrade(
                    ticker=ticker,
                    strategy_key="",
                    realized_pnl=r_pnl,
                    realized_pnl_pct=r_pnl_pct,
                    holding_days=hold_days,
                    is_winner=r_pnl > 0,
                    exit_reason="restored_from_db",
                    grade=grade,
                ))

            if restored_trades:
                # Reverse so oldest-first matches the in-memory append order
                app_state.closed_trades = list(reversed(restored_trades))
                app_state.trade_grades = list(reversed(restored_grades))
                logger.info(
                    "closed_trades_restored_from_db",
                    count=len(restored_trades),
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("closed_trades_restore_failed", error=str(exc))

    # ── Phase 59: Restore active_weight_profile from WeightProfile table ─────
    try:
        import json as _json_wp

        import sqlalchemy as _sa_wp

        from infra.db.models.weight_profile import WeightProfile as _DBWeight
        from infra.db.session import db_session as _db_sess_wp
        from services.signal_engine.weight_optimizer import WeightProfileRecord

        with _db_sess_wp() as db:
            row = db.execute(
                _sa_wp.select(_DBWeight)
                .where(_DBWeight.is_active.is_(True))
                .order_by(_DBWeight.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()

            if row is not None:
                app_state.active_weight_profile = WeightProfileRecord(
                    id=str(row.id),
                    profile_name=row.profile_name,
                    source=row.source,
                    weights=_json_wp.loads(row.weights_json) if row.weights_json else {},
                    sharpe_metrics=_json_wp.loads(row.sharpe_metrics_json) if row.sharpe_metrics_json else {},
                    is_active=True,
                    optimization_run_id=row.optimization_run_id,
                    notes=row.notes,
                    created_at=row.created_at,
                )
                logger.info("weight_profile_restored_from_db", profile=row.profile_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("weight_profile_restore_failed", error=str(exc))

    # ── Phase 59: Restore current_regime_result from RegimeSnapshot table ────
    try:
        import json as _json_rg

        import sqlalchemy as _sa_rg

        from infra.db.models.regime_detection import RegimeSnapshot as _DBRegime
        from infra.db.session import db_session as _db_sess_rg
        from services.signal_engine.regime_detection import MarketRegime, RegimeResult

        with _db_sess_rg() as db:
            rows = db.execute(
                _sa_rg.select(_DBRegime)
                .order_by(_DBRegime.created_at.desc())
                .limit(30)
            ).all()

            regime_history: list = []
            for row in rows:
                basis = _json_rg.loads(row.detection_basis_json) if row.detection_basis_json else {}
                rr = RegimeResult(
                    regime=MarketRegime(row.regime),
                    confidence=row.confidence,
                    detection_basis=basis,
                    is_manual_override=row.is_manual_override,
                    override_reason=row.override_reason,
                    detected_at=row.created_at,
                )
                regime_history.append(rr)

            if regime_history:
                app_state.current_regime_result = regime_history[0]
                # Reverse so newest-last matches the append order
                app_state.regime_history = list(reversed(regime_history))
                logger.info(
                    "regime_result_restored_from_db",
                    regime=regime_history[0].regime.value,
                    confidence=regime_history[0].confidence,
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("regime_result_restore_failed", error=str(exc))

    # ── Phase 59: Restore latest_readiness_report from ReadinessSnapshot ─────
    try:
        import json as _json_rr

        import sqlalchemy as _sa_rr

        from infra.db.models.readiness import ReadinessSnapshot as _DBReady
        from infra.db.session import db_session as _db_sess_rr
        from services.readiness.models import ReadinessGateRow, ReadinessReport

        with _db_sess_rr() as db:
            row = db.execute(
                _sa_rr.select(_DBReady)
                .order_by(_DBReady.captured_at.desc())
                .limit(1)
            ).scalar_one_or_none()

            if row is not None:
                gates_raw = _json_rr.loads(row.gates_json) if row.gates_json else []
                gate_rows = [ReadinessGateRow(**g) for g in gates_raw]
                app_state.latest_readiness_report = ReadinessReport(
                    generated_at=row.captured_at,
                    current_mode=row.current_mode,
                    target_mode=row.target_mode,
                    overall_status=row.overall_status,
                    gate_rows=gate_rows,
                    pass_count=row.pass_count,
                    warn_count=row.warn_count,
                    fail_count=row.fail_count,
                    recommendation=row.recommendation or "",
                )
                logger.info(
                    "readiness_report_restored_from_db",
                    status=row.overall_status,
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("readiness_report_restore_failed", error=str(exc))

    # ── Phase 59: Restore promoted_versions from PromotedVersion table ───────
    try:
        import sqlalchemy as _sa_pv

        from infra.db.models.self_improvement import PromotedVersion as _DBPromoted
        from infra.db.session import db_session as _db_sess_pv

        with _db_sess_pv() as db:
            rows = db.execute(
                _sa_pv.select(_DBPromoted)
                .order_by(_DBPromoted.promotion_timestamp.desc())
            ).scalars().all()

            if rows:
                promoted: dict[str, str] = {}
                for row in rows:
                    key = f"{row.component_type}:{row.component_key}"
                    if key not in promoted:  # latest per component
                        promoted[key] = row.version_label
                app_state.promoted_versions = promoted
                logger.info("promoted_versions_restored_from_db", count=len(promoted))
    except Exception as exc:  # noqa: BLE001
        logger.warning("promoted_versions_restore_failed", error=str(exc))

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


def _run_startup_catchup() -> None:
    """Re-run morning pipeline jobs that were missed due to a process restart.

    Phase 59 — Dashboard State Persistence & Worker Resilience.

    On startup, checks the current time (ET) and the day of week.  If it is
    a weekday and past the scheduled time for a morning-pipeline job, AND the
    corresponding app_state field is still empty/None (meaning neither the DB
    restore nor a previous run populated it), the job is fired synchronously
    in dependency order.

    This ensures the dashboard is fully populated within a few minutes of any
    mid-day restart, rather than staying blank until the next scheduled slot.

    All jobs are fire-and-forget with their own try/except, so a single
    failure does not block the rest.
    """
    import zoneinfo

    from apps.api.state import get_app_state

    app_state = get_app_state()
    cfg = get_settings()

    et = zoneinfo.ZoneInfo("US/Eastern")
    now = _dt.datetime.now(et)

    # Only catch up on weekdays
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        logger.info("startup_catchup_skipped_weekend")
        return

    current_hour_min = now.hour * 60 + now.minute
    logger.info(
        "startup_catchup_starting",
        current_time_et=now.strftime("%H:%M"),
        weekday=now.strftime("%A"),
    )

    # Define the catch-up jobs in dependency order.
    # Each tuple: (scheduled_minute_of_day, field_to_check, job_function_name, job_args_builder)
    # We only run a job if its scheduled time has passed AND the corresponding
    # app_state field is still at its default (empty/None).

    def _session_factory():
        try:
            from infra.db.session import SessionLocal
            return SessionLocal
        except Exception:
            return None

    catchup_ran = 0

    # 06:16 — Correlation refresh
    if current_hour_min >= 376 and not app_state.correlation_matrix:
        try:
            from apps.worker.jobs import run_correlation_refresh
            logger.info("startup_catchup_running", job="correlation_refresh")
            run_correlation_refresh(app_state=app_state, settings=cfg, session_factory=_session_factory())
            catchup_ran += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("startup_catchup_failed", job="correlation_refresh", error=str(exc))

    # 06:17 — Liquidity refresh
    if current_hour_min >= 377 and not app_state.latest_dollar_volumes:
        try:
            from apps.worker.jobs import run_liquidity_refresh
            logger.info("startup_catchup_running", job="liquidity_refresh")
            run_liquidity_refresh(app_state=app_state, settings=cfg, session_factory=_session_factory())
            catchup_ran += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("startup_catchup_failed", job="liquidity_refresh", error=str(exc))

    # 06:19 — VaR refresh
    if current_hour_min >= 379 and app_state.latest_var_result is None:
        try:
            from apps.worker.jobs import run_var_refresh
            logger.info("startup_catchup_running", job="var_refresh")
            run_var_refresh(app_state=app_state, settings=cfg, session_factory=_session_factory())
            catchup_ran += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("startup_catchup_failed", job="var_refresh", error=str(exc))

    # 06:20 — Regime detection (only if not already restored from DB)
    if current_hour_min >= 380 and app_state.current_regime_result is None:
        try:
            from apps.worker.jobs import run_regime_detection
            logger.info("startup_catchup_running", job="regime_detection")
            run_regime_detection(app_state=app_state, settings=cfg, session_factory=_session_factory())
            catchup_ran += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("startup_catchup_failed", job="regime_detection", error=str(exc))

    # 06:21 — Stress test
    if current_hour_min >= 381 and app_state.latest_stress_result is None:
        try:
            from apps.worker.jobs import run_stress_test
            logger.info("startup_catchup_running", job="stress_test")
            run_stress_test(app_state=app_state, settings=cfg)
            catchup_ran += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("startup_catchup_failed", job="stress_test", error=str(exc))

    # 06:23 — Earnings calendar
    if current_hour_min >= 383 and app_state.latest_earnings_calendar is None:
        try:
            from apps.worker.jobs import run_earnings_refresh
            logger.info("startup_catchup_running", job="earnings_refresh")
            run_earnings_refresh(app_state=app_state, settings=cfg)
            catchup_ran += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("startup_catchup_failed", job="earnings_refresh", error=str(exc))

    # 06:25 — Universe refresh
    if current_hour_min >= 385 and not app_state.active_universe:
        try:
            from apps.worker.jobs import run_universe_refresh
            logger.info("startup_catchup_running", job="universe_refresh")
            run_universe_refresh(app_state=app_state, settings=cfg, session_factory=_session_factory())
            catchup_ran += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("startup_catchup_failed", job="universe_refresh", error=str(exc))

    # 06:26 — Rebalance check
    if current_hour_min >= 386 and not app_state.rebalance_targets:
        try:
            from apps.worker.jobs import run_rebalance_check
            logger.info("startup_catchup_running", job="rebalance_check")
            run_rebalance_check(app_state=app_state, settings=cfg)
            catchup_ran += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("startup_catchup_failed", job="rebalance_check", error=str(exc))

    # 06:30 — Signal generation (only if rankings are empty — rankings depend on signals)
    if current_hour_min >= 390 and not app_state.latest_rankings:
        try:
            from apps.worker.jobs import run_signal_generation
            logger.info("startup_catchup_running", job="signal_generation")
            run_signal_generation(app_state=app_state, settings=cfg, session_factory=_session_factory())
            catchup_ran += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("startup_catchup_failed", job="signal_generation", error=str(exc))

        # 06:45 — Ranking generation (only if signals were just re-run)
        if current_hour_min >= 405:
            try:
                from apps.worker.jobs import run_ranking_generation
                logger.info("startup_catchup_running", job="ranking_generation")
                run_ranking_generation(app_state=app_state, settings=cfg, session_factory=_session_factory())
                catchup_ran += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("startup_catchup_failed", job="ranking_generation", error=str(exc))

    # 06:52 — Weight optimization (only if not already restored from DB)
    if current_hour_min >= 412 and app_state.active_weight_profile is None:
        try:
            from apps.worker.jobs import run_weight_optimization
            logger.info("startup_catchup_running", job="weight_optimization")
            run_weight_optimization(app_state=app_state, settings=cfg, session_factory=_session_factory())
            catchup_ran += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("startup_catchup_failed", job="weight_optimization", error=str(exc))

    logger.info("startup_catchup_complete", jobs_ran=catchup_ran)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    """FastAPI lifespan — runs _load_persisted_state() on startup, then
    starts the APScheduler worker in the same process so that the scheduler
    and the API share a single ApiAppState instance.  This eliminates the
    multi-process state-sharing gap where the worker updated its own isolated
    in-memory state and the API served stale data to the dashboard.
    """
    _load_persisted_state()
    _run_startup_catchup()

    # Start the APScheduler in a background thread inside this process.
    # Both the scheduler jobs and the API routes now call get_app_state()
    # and receive the *same* singleton object.
    scheduler = None
    try:
        from apps.worker.main import (
            _restore_evaluation_history_from_db,  # noqa: PLC0415
            _setup_alert_service,  # noqa: PLC0415
            build_scheduler,  # noqa: PLC0415
        )
        _restore_evaluation_history_from_db()
        _setup_alert_service()
        scheduler = build_scheduler()
        scheduler.start()
        logger.info(
            "apis_scheduler_started_in_api_process",
            job_count=len(scheduler.get_jobs()),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("apis_scheduler_start_failed", error=str(exc))

    # Expose the scheduler instance to the health endpoint (module-level
    # reference so /health can directly inspect `scheduler.running` rather
    # than inferring liveness from paper-cycle timestamps, which are only
    # refreshed during US market hours and produce false `stale` results
    # every morning and on weekends).
    global _APSCHEDULER_INSTANCE
    _APSCHEDULER_INSTANCE = scheduler

    yield

    # Graceful shutdown
    if scheduler is not None:
        try:
            scheduler.shutdown(wait=False)
            logger.info("apis_scheduler_stopped")
        except Exception as exc:  # noqa: BLE001
            logger.warning("apis_scheduler_stop_failed", error=str(exc))
    _APSCHEDULER_INSTANCE = None


# Module-level handle to the in-process APScheduler instance. Populated by
# the FastAPI lifespan above so /health can inspect it directly.
_APSCHEDULER_INSTANCE: object | None = None


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

    # ── Scheduler liveness (APScheduler heartbeat via Redis) ────────────────
    # `scheduler.running` only checks that the APScheduler object hasn't been
    # shutdown — it does NOT prove the dispatch thread is executing jobs.
    # On 2026-04-30, `running` was True for 27h while zero jobs fired.
    #
    # The worker now writes an epoch timestamp to `worker:scheduler_heartbeat`
    # every 5 min via an APScheduler-managed job.  If this key is stale
    # (>10 min) or missing, the dispatch thread has stalled.
    try:
        import redis as _redis_health
        _r = _redis_health.Redis.from_url(
            cfg.redis_url, socket_connect_timeout=2, socket_timeout=2,
        )
        _hb_val = _r.get("worker:scheduler_heartbeat")
        if _hb_val is None:
            # Key missing — worker may not have started or Redis was flushed.
            # Fall back to the old in-process check for backward compat.
            sched = _APSCHEDULER_INSTANCE
            if sched is not None and getattr(sched, "running", False):
                components["scheduler"] = "ok"
            else:
                components["scheduler"] = "no_heartbeat"
        else:
            _age = _dt.datetime.now(tz=_dt.UTC).timestamp() - float(_hb_val)
            if _age < 600:  # 10 min
                components["scheduler"] = "ok"
            else:
                components["scheduler"] = "stale"
                components["scheduler_heartbeat_age_s"] = str(int(_age))
    except Exception:
        # Redis unavailable — fall back to in-process check
        sched = _APSCHEDULER_INSTANCE
        if sched is not None and getattr(sched, "running", False):
            components["scheduler"] = "ok"
        else:
            components["scheduler"] = "unknown"

    # ── Paper cycle freshness (informational — only stale during market hours)
    last_cycle = state.last_paper_cycle_at
    if last_cycle is None:
        components["paper_cycle"] = "no_data"
    else:
        age_s = (_dt.datetime.now(tz=_dt.UTC) - last_cycle).total_seconds()
        # Only flag stale if we're currently *inside* the paper-cycle window
        # (09:35–15:30 ET, Mon–Fri). Outside that window, stale is expected.
        now_et = _dt.datetime.now(tz=_dt.UTC) - _dt.timedelta(hours=4)  # EDT offset
        in_cycle_window = (
            now_et.weekday() < 5
            and (now_et.hour, now_et.minute) >= (9, 35)
            and (now_et.hour, now_et.minute) <= (15, 30)
        )
        if in_cycle_window and age_s > 7200:
            components["paper_cycle"] = "stale"
        else:
            components["paper_cycle"] = "ok"

    # ── Broker auth token ─────────────────────────────────────────────────────
    components["broker_auth"] = "expired" if state.broker_auth_expired else "ok"

    # ── system_state test-pollution scan ─────────────────────────────────────
    # Detect stale rows written by test runners (testclient, pytest, etc.)
    # that could poison runtime on the next restart.
    try:
        from infra.db.models.system_state import (
            KEY_KILL_SWITCH_ACTIVATED_BY as _KS_BY,
        )
        from infra.db.models.system_state import (
            KEY_KILL_SWITCH_ACTIVE as _KS_ACTIVE,
        )
        from infra.db.models.system_state import (
            SystemStateEntry as _SSE,
        )
        from infra.db.session import db_session as _db_health

        with _db_health() as _hdb:
            _ks_active = _hdb.get(_SSE, _KS_ACTIVE)
            _ks_by = _hdb.get(_SSE, _KS_BY)
            _by_val = (_ks_by.value_text if _ks_by else "").lower()
            if (
                _ks_active
                and _ks_active.value_text == "true"
                and _by_val in ("testclient", "test", "pytest", "")
            ):
                components["system_state_pollution"] = "detected"
            else:
                components["system_state_pollution"] = "ok"
    except Exception:
        components["system_state_pollution"] = "unknown"

    # ── Kill switch ───────────────────────────────────────────────────────────
    effective_kill = getattr(state, "kill_switch_active", False) or cfg.kill_switch
    components["kill_switch"] = "active" if effective_kill else "ok"

    # ── Overall status ────────────────────────────────────────────────────────
    if components["db"] == "down":
        overall = "down"
    elif any(v in ("down", "error", "stale", "stopped", "expired", "active", "detected", "no_heartbeat") for v in components.values()):
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
