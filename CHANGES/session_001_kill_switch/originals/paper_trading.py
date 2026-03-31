"""
Worker job: live paper trading cycle.

``run_paper_trading_cycle``
    Full end-to-end paper trading execution loop:

    1. Mode guard — no-op in RESEARCH or BACKTEST mode.
    2. Pull latest rankings from ApiAppState — skip if empty.
    3. Reuse or initialize PortfolioState from ApiAppState.
    4. Apply ranked opportunities → proposed PortfolioActions.
    5. Validate every action through RiskEngineService.
    6. Fetch current prices for approved actions via MarketDataService.
    7. Execute risk-approved actions via ExecutionEngineService + broker.
    8. Sync portfolio state from broker account + positions.
    9. Reconcile fills through ReportingService.
   10. Write results back to ApiAppState.

Design rules
------------
- Only runs in PAPER or HUMAN_APPROVED operating mode.
- Broker defaults to PaperBrokerAdapter if not injected.
- All exceptions caught — scheduler thread must not die.
- Returns a structured result dict for observability.

Spec references
---------------
- APIS_MASTER_SPEC.md § 3.1 (safety rollout: paper before live)
- API_AND_SERVICE_BOUNDARIES_SPEC.md § 2.4 (only execution_engine submits orders)
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Optional

from apps.api.state import ApiAppState
from broker_adapters.base.exceptions import BrokerAuthenticationError
from config.logging_config import get_logger
from config.settings import OperatingMode, Settings, get_settings

logger = get_logger(__name__)

# Operating modes that permit execution
_EXECUTION_MODES = {OperatingMode.PAPER, OperatingMode.HUMAN_APPROVED}

# System-state keys (must match infra/db/models/system_state.py constants)
_KEY_PAPER_CYCLE_COUNT = "paper_cycle_count"


def _persist_paper_cycle_count(count: int) -> None:
    """Fire-and-forget: upsert paper_cycle_count to system_state table.

    Never raises — DB write failures are logged at WARNING level only.
    """
    try:
        from infra.db.models.system_state import SystemStateEntry
        from infra.db.session import db_session as _db_session

        with _db_session() as db:
            entry = db.get(SystemStateEntry, _KEY_PAPER_CYCLE_COUNT)
            if entry is None:
                entry = SystemStateEntry(
                    key=_KEY_PAPER_CYCLE_COUNT,
                    value_text=str(count),
                )
                db.add(entry)
            else:
                entry.value_text = str(count)
    except Exception as exc:  # noqa: BLE001
        logger.warning("persist_paper_cycle_count_failed", error=str(exc))


def _persist_portfolio_snapshot(portfolio_state: Any, mode: str) -> None:
    """Fire-and-forget: insert a PortfolioSnapshot row into the DB.

    Never raises — DB failures are logged at WARNING level only.
    Called after every successful paper trading cycle.
    """
    try:
        from decimal import Decimal as _Decimal

        from infra.db.models.portfolio import PortfolioSnapshot as _DBSnap
        from infra.db.session import db_session as _db_session

        with _db_session() as db:
            snap = _DBSnap(
                snapshot_timestamp=dt.datetime.now(dt.timezone.utc),
                mode=mode,
                cash_balance=_Decimal(str(portfolio_state.cash)),
                gross_exposure=_Decimal(str(portfolio_state.gross_exposure)),
                net_exposure=(
                    _Decimal(str(portfolio_state.equity))
                    - _Decimal(str(portfolio_state.cash))
                ),
                equity_value=_Decimal(str(portfolio_state.equity)),
                drawdown_pct=_Decimal(str(portfolio_state.drawdown_pct)),
                notes=None,
            )
            db.add(snap)
    except Exception as exc:  # noqa: BLE001
        logger.warning("persist_portfolio_snapshot_failed %s", exc)


def _persist_position_history(portfolio_state: Any, snapshot_at: Any) -> None:
    """Fire-and-forget: insert one PositionHistory row per open position.

    Never raises — DB failures are logged at WARNING level only.
    Called after broker sync so prices are current.
    """
    try:
        from decimal import Decimal as _Decimal

        from infra.db.models.portfolio import PositionHistory as _PosHist
        from infra.db.session import db_session as _db_session

        rows = []
        for pos in portfolio_state.positions.values():
            rows.append(
                _PosHist(
                    ticker=pos.ticker,
                    snapshot_at=snapshot_at,
                    quantity=_Decimal(str(pos.quantity)),
                    avg_entry_price=_Decimal(str(pos.avg_entry_price)),
                    current_price=_Decimal(str(pos.current_price)),
                    market_value=_Decimal(str(pos.market_value)),
                    cost_basis=_Decimal(str(pos.cost_basis)),
                    unrealized_pnl=_Decimal(str(pos.unrealized_pnl)),
                    unrealized_pnl_pct=_Decimal(str(pos.unrealized_pnl_pct)),
                )
            )
        if rows:
            with _db_session() as db:
                db.add_all(rows)
    except Exception as exc:  # noqa: BLE001
        logger.warning("persist_position_history_failed", error=str(exc))


def run_paper_trading_cycle(
    app_state: ApiAppState,
    settings: Optional[Settings] = None,
    broker: Optional[Any] = None,
    portfolio_svc: Optional[Any] = None,
    risk_svc: Optional[Any] = None,
    execution_svc: Optional[Any] = None,
    market_data_svc: Optional[Any] = None,
    reporting_svc: Optional[Any] = None,
    eval_svc: Optional[Any] = None,
) -> dict[str, Any]:
    """Execute one full paper trading cycle.

    All services are lazily constructed when not injected so this function
    remains fully testable with mock injection.

    Args:
        app_state:       Shared ApiAppState read/written by this job.
        settings:        Settings instance; falls back to get_settings().
        broker:          BaseBrokerAdapter instance.  Falls back to
                         app_state.broker_adapter, then PaperBrokerAdapter().
        portfolio_svc:   PortfolioEngineService instance.
        risk_svc:        RiskEngineService instance.
        execution_svc:   ExecutionEngineService instance (uses *broker*).
        market_data_svc: MarketDataService instance for price fetching.
        reporting_svc:   ReportingService instance for fill reconciliation.

    Returns:
        dict with keys: status, mode, run_at, proposed_count, approved_count,
        executed_count, reconciliation_clean, errors.
    """
    cfg = settings or get_settings()
    run_at = dt.datetime.now(dt.timezone.utc)

    logger.info(
        "paper_trading_cycle_starting",
        mode=cfg.operating_mode.value,
        run_at=run_at.isoformat(),
    )

    # ── Kill switch guard (checked FIRST — overrides everything) ──────────────
    # Honours both the env-var kill_switch (settings) and the runtime flag
    # (app_state.kill_switch_active) set via POST /api/v1/admin/kill-switch.
    if cfg.kill_switch or getattr(app_state, "kill_switch_active", False):
        logger.warning("paper_trading_cycle_killed", mode=cfg.operating_mode.value)
        return {
            "status": "killed",
            "mode": cfg.operating_mode.value,
            "run_at": run_at.isoformat(),
            "proposed_count": 0,
            "approved_count": 0,
            "executed_count": 0,
            "reconciliation_clean": None,
            "errors": ["kill_switch_active"],
        }

    # ── Mode guard ────────────────────────────────────────────────────────────
    if cfg.operating_mode not in _EXECUTION_MODES:
        logger.info("paper_trading_cycle_skipped_mode", mode=cfg.operating_mode.value)
        return {
            "status": "skipped_mode",
            "mode": cfg.operating_mode.value,
            "run_at": run_at.isoformat(),
            "proposed_count": 0,
            "approved_count": 0,
            "executed_count": 0,
            "reconciliation_clean": None,
            "errors": [],
        }

    # ── Rankings check ────────────────────────────────────────────────────────
    rankings = list(app_state.latest_rankings)
    if not rankings:
        logger.warning("paper_trading_cycle_skipped_no_rankings")
        return {
            "status": "skipped_no_rankings",
            "mode": cfg.operating_mode.value,
            "run_at": run_at.isoformat(),
            "proposed_count": 0,
            "approved_count": 0,
            "executed_count": 0,
            "reconciliation_clean": None,
            "errors": [],
        }

    errors: list[str] = []

    try:
        # Lazy imports (keep startup fast; avoid circular imports at module level)
        from broker_adapters.paper.adapter import PaperBrokerAdapter
        from services.execution_engine.models import ExecutionRequest
        from services.execution_engine.service import ExecutionEngineService
        from services.market_data.service import MarketDataService
        from services.portfolio_engine.models import ActionType, PortfolioState
        from services.portfolio_engine.service import PortfolioEngineService
        from services.reporting.models import FillExpectation
        from services.reporting.service import ReportingService
        from services.evaluation_engine.service import EvaluationEngineService
        from services.risk_engine.service import RiskEngineService

        # ── Build services ────────────────────────────────────────────────────
        _broker = broker or getattr(app_state, "broker_adapter", None) or PaperBrokerAdapter(
            market_open=True
        )
        _portfolio_svc = portfolio_svc or PortfolioEngineService(settings=cfg)
        _risk_svc = risk_svc or RiskEngineService(settings=cfg)
        _execution_svc = execution_svc or ExecutionEngineService(
            settings=cfg, broker=_broker
        )
        _market_data_svc = market_data_svc or MarketDataService()
        _reporting_svc = reporting_svc or ReportingService()
        _eval_svc = eval_svc or EvaluationEngineService()

        # ── Initialize portfolio state ─────────────────────────────────────────
        portfolio_state: PortfolioState = app_state.portfolio_state or PortfolioState(
            cash=Decimal("100_000.00"),
            start_of_day_equity=Decimal("100_000.00"),
            high_water_mark=Decimal("100_000.00"),
        )

        # ── Connect broker ────────────────────────────────────────────────────
        try:
            if not _broker.ping():
                _broker.connect()
            # Clear any stale auth-expiry flag on successful connect
            if app_state.broker_auth_expired:
                app_state.broker_auth_expired = False
                app_state.broker_auth_expired_at = None
        except BrokerAuthenticationError as auth_exc:
            logger.error("broker_auth_expired", error=str(auth_exc))
            app_state.broker_auth_expired = True
            app_state.broker_auth_expired_at = run_at
            errors.append(f"broker_auth_expired: {auth_exc}")
            # ── Phase 31: Broker auth expiry alert ──────────────────────────
            _alert_svc = getattr(app_state, "alert_service", None)
            if _alert_svc and getattr(cfg, "alert_on_broker_auth_expiry", True):
                from services.alerting.models import AlertEvent, AlertEventType, AlertSeverity
                _alert_svc.send_alert(AlertEvent(
                    event_type=AlertEventType.BROKER_AUTH_EXPIRED.value,
                    severity=AlertSeverity.CRITICAL.value,
                    title="APIS: Broker authentication expired — no orders submitted",
                    payload={"mode": cfg.operating_mode.value, "error": str(auth_exc), "run_at": run_at.isoformat()},
                ))
            return {
                "status": "error_broker_auth",
                "mode": cfg.operating_mode.value,
                "run_at": run_at.isoformat(),
                "proposed_count": 0,
                "approved_count": 0,
                "executed_count": 0,
                "reconciliation_clean": False,
                "errors": errors,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("broker_connect_failed", error=str(exc))
            errors.append(f"broker_connect: {exc}")

        # ── Generate proposed actions (portfolio engine) ───────────────────────
        # ── Phase 27: Start-of-Day equity anchor ────────────────────────────
        # On the first cycle of each trading day, capture start-of-day equity
        # and update the high-water mark so daily P&L and drawdown metrics stay
        # accurate across day boundaries.
        _run_date = run_at.date()
        _last_sod = getattr(app_state, "last_sod_capture_date", None)
        if _last_sod is None or _run_date > _last_sod:
            portfolio_state.start_of_day_equity = portfolio_state.equity
            if (
                portfolio_state.high_water_mark is None
                or portfolio_state.equity > portfolio_state.high_water_mark
            ):
                portfolio_state.high_water_mark = portfolio_state.equity
            app_state.last_sod_capture_date = _run_date
            logger.info(
                "sod_equity_captured",
                date=str(_run_date),
                equity=str(portfolio_state.equity),
            )

        # ────────────────────────────────────────────────────────────────────
        proposed_actions = _portfolio_svc.apply_ranked_opportunities(
            ranked_results=rankings,
            portfolio_state=portfolio_state,
        )

        # ── Phase 39: Correlation-aware size adjustment ───────────────────────
        # Apply pairwise correlation penalty to OPEN actions before risk gating.
        # Highly correlated candidates receive reduced target_notional / quantity.
        try:
            from services.risk_engine.correlation import CorrelationService as _CorrSvc  # noqa: PLC0415

            _corr_matrix = getattr(app_state, "correlation_matrix", {})
            _existing_tickers = list(portfolio_state.positions.keys())
            adjusted: list = []
            for _act in proposed_actions:
                _act = _CorrSvc.adjust_action_for_correlation(
                    action=_act,
                    existing_tickers=_existing_tickers,
                    matrix=_corr_matrix,
                    settings=cfg,
                )
                adjusted.append(_act)
            proposed_actions = adjusted
        except Exception as _corr_exc:  # noqa: BLE001
            logger.warning("correlation_adjustment_failed", error=str(_corr_exc))

        # ── Phase 40: Sector exposure filter ─────────────────────────────────
        # Drop OPEN actions that would push any sector above max_sector_pct.
        # CLOSE and TRIM actions are never affected.
        # Updates app_state.sector_weights for the dashboard/endpoint.
        try:
            from services.risk_engine.sector_exposure import SectorExposureService as _SectorSvc  # noqa: PLC0415

            _before_sector = len([a for a in proposed_actions if a.action_type == ActionType.OPEN])
            proposed_actions = _SectorSvc.filter_for_sector_limits(
                actions=proposed_actions,
                portfolio_state=portfolio_state,
                settings=cfg,
            )
            _after_sector = len([a for a in proposed_actions if a.action_type == ActionType.OPEN])
            _sector_dropped = _before_sector - _after_sector
            if _sector_dropped:
                logger.info("sector_exposure_filter_applied", dropped_count=_sector_dropped)
            # Update in-memory sector weights for dashboard / endpoint
            app_state.sector_weights = _SectorSvc.compute_sector_weights(
                positions=portfolio_state.positions,
                equity=portfolio_state.equity,
            )
            app_state.sector_filtered_count = _sector_dropped
        except Exception as _sect_exc:  # noqa: BLE001
            logger.warning("sector_exposure_filter_failed", error=str(_sect_exc))

        # ── Phase 41: Liquidity filter ────────────────────────────────────────
        # Drop OPEN actions for illiquid tickers (dollar_volume_20d below
        # min_liquidity_dollar_volume) and cap notional to max_pct_of_adv × ADV.
        # CLOSE and TRIM actions are never affected.
        # Updates app_state.liquidity_filtered_count for the dashboard/endpoint.
        try:
            from services.risk_engine.liquidity import LiquidityService as _LiqSvc  # noqa: PLC0415

            _dv_map = getattr(app_state, "latest_dollar_volumes", {})
            _before_liq = len([a for a in proposed_actions if a.action_type == ActionType.OPEN])
            proposed_actions = _LiqSvc.filter_for_liquidity(
                actions=proposed_actions,
                dollar_volumes=_dv_map,
                settings=cfg,
            )
            _after_liq = len([a for a in proposed_actions if a.action_type == ActionType.OPEN])
            _liq_dropped = _before_liq - _after_liq
            if _liq_dropped:
                logger.info("liquidity_filter_applied", dropped_count=_liq_dropped)
            app_state.liquidity_filtered_count = _liq_dropped
        except Exception as _liq_exc:  # noqa: BLE001
            logger.warning("liquidity_filter_failed", error=str(_liq_exc))

        # ── Phase 43: Portfolio VaR gate ─────────────────────────────────────
        # Block new OPEN actions when 1-day 95% portfolio VaR exceeds the
        # max_portfolio_var_pct limit.  CLOSE and TRIM always pass through.
        try:
            from services.risk_engine.var_service import VaRService as _VaRSvc  # noqa: PLC0415

            _var_result = getattr(app_state, "latest_var_result", None)
            if _var_result is not None:
                _before_var = len([a for a in proposed_actions if a.action_type == ActionType.OPEN])
                proposed_actions, _var_blocked = _VaRSvc.filter_for_var_limit(
                    actions=proposed_actions,
                    var_result=_var_result,
                    settings=cfg,
                )
                if _var_blocked:
                    logger.info("var_gate_applied", blocked_count=_var_blocked)
                app_state.var_filtered_count = _var_blocked
        except Exception as _var_exc:  # noqa: BLE001
            logger.warning("var_gate_failed", error=str(_var_exc))

        # ── Phase 44: Portfolio stress test gate ─────────────────────────────
        # Block new OPEN actions when the worst-case historical-scenario stressed
        # loss exceeds max_stress_loss_pct.  CLOSE and TRIM always pass through.
        try:
            from services.risk_engine.stress_test import StressTestService as _StressSvc  # noqa: PLC0415

            _stress_result = getattr(app_state, "latest_stress_result", None)
            if _stress_result is not None:
                proposed_actions, _stress_blocked = _StressSvc.filter_for_stress_limit(
                    actions=proposed_actions,
                    stress_result=_stress_result,
                    settings=cfg,
                )
                if _stress_blocked:
                    logger.info("stress_gate_applied", blocked_count=_stress_blocked)
                app_state.stress_blocked_count = _stress_blocked
        except Exception as _stress_exc:  # noqa: BLE001
            logger.warning("stress_gate_failed", error=str(_stress_exc))

        # ── Phase 45: Earnings proximity gate ─────────────────────────────────
        # Block new OPEN actions for tickers with earnings within the configured
        # proximity window (max_earnings_proximity_days).  Earnings are the
        # largest discontinuous risk events for equity positions; the system's
        # VaR and stop-loss models cannot protect against overnight earnings gaps.
        # CLOSE and TRIM actions always pass through.
        try:
            from services.risk_engine.earnings_calendar import EarningsCalendarService as _EarnSvc  # noqa: PLC0415

            _earnings_cal = getattr(app_state, "latest_earnings_calendar", None)
            if _earnings_cal is not None:
                proposed_actions, _earn_blocked = _EarnSvc.filter_for_earnings_proximity(
                    actions=proposed_actions,
                    calendar_result=_earnings_cal,
                    settings=cfg,
                )
                if _earn_blocked:
                    logger.info("earnings_gate_applied", blocked_count=_earn_blocked)
                app_state.earnings_filtered_count = _earn_blocked
        except Exception as _earn_exc:  # noqa: BLE001
            logger.warning("earnings_gate_failed", error=str(_earn_exc))

        # ── Phase 47: Drawdown Recovery Mode ─────────────────────────────────────
        from services.risk_engine.drawdown_recovery import DrawdownRecoveryService as _DDSvc, DrawdownState as _DDState  # noqa: PLC0415

        try:
            _dd_equity = float(portfolio_state.equity)
            _dd_hwm = float(portfolio_state.high_water_mark) if portfolio_state.high_water_mark is not None else _dd_equity
            drawdown_result = _DDSvc.evaluate_state(
                current_equity=_dd_equity,
                high_water_mark=_dd_hwm,
                caution_threshold_pct=cfg.drawdown_caution_pct,
                recovery_threshold_pct=cfg.drawdown_recovery_pct,
                recovery_mode_size_multiplier=cfg.recovery_mode_size_multiplier,
            )
            # Detect state transition and fire alert
            prev_state = getattr(app_state, "drawdown_state", "NORMAL")
            new_state = drawdown_result.state.value
            if new_state != prev_state:
                app_state.drawdown_state = new_state
                app_state.drawdown_state_changed_at = dt.datetime.now(dt.timezone.utc)
                _alert_svc_dd = getattr(app_state, "alert_service", None)
                if _alert_svc_dd:
                    try:
                        from services.alerting.models import AlertEvent, AlertSeverity  # noqa: PLC0415
                        _alert_svc_dd.send_alert(AlertEvent(
                            event_type="drawdown_state_change",
                            severity=AlertSeverity.WARNING.value,
                            title=f"APIS: Drawdown state changed {prev_state} -> {new_state}",
                            payload={
                                "previous_state": prev_state,
                                "new_state": new_state,
                                "drawdown_pct": round(drawdown_result.current_drawdown_pct, 4),
                                "equity": _dd_equity,
                                "high_water_mark": _dd_hwm,
                            },
                        ))
                    except Exception as _dd_alert_exc:  # noqa: BLE001
                        logger.warning("drawdown_alert_failed", error=str(_dd_alert_exc))
                logger.warning(
                    "drawdown_state_transition",
                    prev=prev_state,
                    new=new_state,
                    drawdown_pct=round(drawdown_result.current_drawdown_pct, 4),
                )
            else:
                app_state.drawdown_state = new_state

            # Apply drawdown recovery adjustments to OPEN actions
            _dd_adjusted: list = []
            for _dd_action in proposed_actions:
                if _dd_action.action_type == ActionType.OPEN:
                    # Check hard block first
                    if _DDSvc.is_blocked(drawdown_result, cfg.recovery_mode_block_new_positions):
                        logger.info("drawdown_recovery_blocked_open", ticker=_dd_action.ticker)
                        continue
                    # Apply size multiplier in RECOVERY mode
                    if drawdown_result.state == _DDState.RECOVERY and getattr(_dd_action, "target_quantity", None):
                        from dataclasses import replace as _dc_replace  # noqa: PLC0415
                        _orig_qty = int(_dd_action.target_quantity)
                        _new_qty = _DDSvc.apply_recovery_sizing(_orig_qty, drawdown_result)
                        _dd_action = _dc_replace(_dd_action, target_quantity=Decimal(str(_new_qty)))
                _dd_adjusted.append(_dd_action)
            proposed_actions = _dd_adjusted
        except Exception as _dd_exc:  # noqa: BLE001
            logger.warning("drawdown_recovery_failed", error=str(_dd_exc))

        # ── Evaluate exit triggers for held positions ─────────────────────────
        # Refresh current prices for all held tickers so stop-loss calc is fresh
        for ticker in list(portfolio_state.positions):
            fresh_price = _fetch_price(ticker, Decimal("1000"), _market_data_svc, errors)
            if fresh_price > Decimal("0"):
                portfolio_state.positions[ticker].current_price = fresh_price

        ranked_scores = {
            r.ticker: (r.composite_score or Decimal("0")) for r in rankings
        }

        # ── Phase 42: Update peak prices for trailing stop tracking ──────────
        try:
            from services.risk_engine.service import update_position_peak_prices as _update_peaks
            _peaks = getattr(app_state, "position_peak_prices", {})
            _update_peaks(portfolio_state.positions, _peaks)
            app_state.position_peak_prices = _peaks
        except Exception as _peak_exc:  # noqa: BLE001
            logger.warning("peak_price_update_failed", error=str(_peak_exc))
            _peaks = {}

        exit_actions = _risk_svc.evaluate_exits(
            positions=portfolio_state.positions,
            ranked_scores=ranked_scores,
            peak_prices=_peaks,
        )
        # Merge exits — skip tickers already scheduled for close by rankings
        already_closing = {
            a.ticker for a in proposed_actions if a.action_type == ActionType.CLOSE
        }
        for exit_action in exit_actions:
            if exit_action.ticker not in already_closing:
                proposed_actions.append(exit_action)
                already_closing.add(exit_action.ticker)

        # ── Evaluate overconcentration trims ──────────────────────────────────
        # Fire TRIM if a position has grown above max_single_name_pct.
        # Skip tickers already receiving a CLOSE (full exit supersedes a trim).
        trim_actions = _risk_svc.evaluate_trims(portfolio_state=portfolio_state)
        for trim_action in trim_actions:
            if trim_action.ticker not in already_closing:
                proposed_actions.append(trim_action)
                already_closing.add(trim_action.ticker)

        # ── Phase 49: Portfolio Rebalancing ───────────────────────────────────
        # Merge rebalance TRIM/OPEN actions from the latest target weights.
        # TRIM actions are pre-approved (same as overconcentration trims).
        # OPEN suggestions enter the normal risk pipeline.
        # CLOSE actions always supersede rebalance TRIMs (dedup by already_closing).
        try:
            from services.risk_engine.rebalancing import RebalancingService as _RebSvc  # noqa: PLC0415

            _reb_targets = getattr(app_state, "rebalance_targets", {}) or {}
            if _reb_targets and getattr(cfg, "enable_rebalancing", True):
                _reb_equity = float(portfolio_state.equity) if portfolio_state.equity else 0.0
                _reb_actions = _RebSvc.generate_rebalance_actions(
                    positions=portfolio_state.positions,
                    target_weights=_reb_targets,
                    equity=_reb_equity,
                    settings=cfg,
                )
                for _reb_action in _reb_actions:
                    if _reb_action.ticker not in already_closing:
                        proposed_actions.append(_reb_action)
                        if _reb_action.action_type == ActionType.CLOSE:
                            already_closing.add(_reb_action.ticker)
                if _reb_actions:
                    logger.info(
                        "rebalance_actions_merged",
                        count=len(_reb_actions),
                    )
        except Exception as _reb_exc:  # noqa: BLE001
            logger.warning("rebalance_actions_failed", error=str(_reb_exc))

        # ── Validate each action + fetch price + build execution requests ──────
        approved_requests: list[ExecutionRequest] = []
        fill_expectations: list[FillExpectation] = []

        for action in proposed_actions:
            # Risk validation (gate-keeper)
            risk_result = _risk_svc.validate_action(
                action=action,
                portfolio_state=portfolio_state,
            )
            if risk_result.is_hard_blocked:
                logger.info(
                    "action_blocked_by_risk",
                    ticker=action.ticker,
                    violations=[v.rule_name for v in risk_result.violations],
                )
                continue

            # Price fetch
            current_price = _fetch_price(action.ticker, action.target_notional, _market_data_svc, errors)

            req = ExecutionRequest(action=action, current_price=current_price)
            approved_requests.append(req)

            # Build fill expectation for reconciliation
            if current_price > Decimal("0"):
                qty = (action.target_notional / current_price).to_integral_value(
                    rounding=__import__("decimal").ROUND_DOWN
                )
            else:
                qty = Decimal("0")
            fill_expectations.append(
                FillExpectation(
                    idempotency_key=f"{action.ticker}_{action.action_type.value}_{run_at.timestamp():.0f}",
                    ticker=action.ticker,
                    expected_quantity=qty,
                    expected_price=current_price,
                    submitted_at=run_at,
                )
            )

        # ── Execute approved actions ────────────────────────────────────────────
        execution_results = _execution_svc.execute_approved_actions(approved_requests)
        executed_count = sum(
            1 for r in execution_results if r.status.value == "filled"
        )

        # ── Phase 52: Capture fill quality records ────────────────────────────
        # Append one FillQualityRecord per filled order to app_state so the
        # evening run_fill_quality_update job can compute slippage aggregates.
        try:
            from services.execution_engine.models import ExecutionStatus as _FQExecStatus
            from services.portfolio_engine.models import ActionType as _FQActionType
            from services.fill_quality.service import FillQualityService as _FQSvc

            for _fq_req, _fq_res in zip(approved_requests, execution_results):
                if (
                    _fq_res.status == _FQExecStatus.FILLED
                    and _fq_res.fill_price is not None
                    and _fq_req.current_price > Decimal("0")
                ):
                    _fq_direction = (
                        "BUY" if _fq_req.action.action_type == _FQActionType.OPEN else "SELL"
                    )
                    _fq_qty = _fq_res.fill_quantity or Decimal("0")
                    if _fq_qty > Decimal("0"):
                        _fq_record = _FQSvc.build_record(
                            ticker=_fq_req.action.ticker,
                            direction=_fq_direction,
                            action_type=_fq_req.action.action_type.value,
                            expected_price=_fq_req.current_price,
                            fill_price=_fq_res.fill_price,
                            quantity=_fq_qty,
                            filled_at=_fq_res.filled_at or run_at,
                        )
                        app_state.fill_quality_records.append(_fq_record)
        except Exception as _fq_exc:  # noqa: BLE001
            logger.warning("fill_quality_capture_failed", error=str(_fq_exc))

        # Track current ledger size so Phase 28 can grade only the new entries.
        _pre_record_count = len(getattr(app_state, "closed_trades", []))
        # ── Phase 27: Record closed trades ─────────────────────────────────────
        # Capture P&L for each filled CLOSE/TRIM BEFORE broker sync removes
        # the position from portfolio_state.positions.
        try:
            from services.execution_engine.models import ExecutionStatus as _ExecStatus
            from services.portfolio_engine.models import ClosedTrade as _ClosedTrade

            for _req, _res in zip(approved_requests, execution_results):
                if (
                    _res.status == _ExecStatus.FILLED
                    and _req.action.action_type in (ActionType.CLOSE, ActionType.TRIM)
                    and _res.fill_price is not None
                ):
                    _ticker = _req.action.ticker
                    _pos = portfolio_state.positions.get(_ticker)
                    if _pos is None:
                        continue
                    _fill_qty = _res.fill_quantity or Decimal("0")
                    if _fill_qty <= Decimal("0"):
                        continue
                    _cost_sold = _pos.avg_entry_price * _fill_qty
                    _realized_pnl = (_res.fill_price - _pos.avg_entry_price) * _fill_qty
                    _realized_pnl_pct = (
                        (_realized_pnl / _cost_sold).quantize(Decimal("0.0001"))
                        if _cost_sold > Decimal("0") else Decimal("0")
                    )
                    _hold_days = max(0, (run_at - _pos.opened_at).days) if _pos.opened_at else 0
                    _ct = _ClosedTrade(
                        ticker=_ticker,
                        action_type=_req.action.action_type,
                        fill_price=_res.fill_price,
                        avg_entry_price=_pos.avg_entry_price,
                        quantity=_fill_qty,
                        realized_pnl=_realized_pnl.quantize(Decimal("0.01")),
                        realized_pnl_pct=_realized_pnl_pct,
                        reason=_req.action.reason or "",
                        opened_at=_pos.opened_at,
                        closed_at=run_at,
                        hold_duration_days=_hold_days,
                    )
                    app_state.closed_trades.append(_ct)
                    logger.info(
                        "closed_trade_recorded",
                        ticker=_ticker,
                        realized_pnl=str(_realized_pnl.quantize(Decimal("0.01"))),
                        reason=_req.action.reason or "",
                    )
        except Exception as _ct_exc:  # noqa: BLE001
            logger.warning("closed_trade_recording_failed", error=str(_ct_exc))
            errors.append(f"closed_trade_record: {_ct_exc}")        # ── Phase 28: Grade each newly recorded closed trade ─────────────────────
        # Convert each new ClosedTrade to a TradeRecord and assign a letter
        # grade (A/B/C/D/F) via EvaluationEngineService.grade_closed_trade().
        # Grades are appended to app_state.trade_grades for the /grades endpoint.
        try:
            from services.evaluation_engine.models import TradeRecord as _TradeRecord
            _newly_closed = getattr(app_state, "closed_trades", [])[_pre_record_count:]
            for _ct in _newly_closed:
                _opened = _ct.opened_at
                if _opened is not None and _opened.tzinfo is None:
                    _opened = _opened.replace(tzinfo=dt.timezone.utc)
                _tr = _TradeRecord(
                    ticker=_ct.ticker,
                    strategy_key="",
                    entry_price=_ct.avg_entry_price,
                    exit_price=_ct.fill_price,
                    quantity=_ct.quantity,
                    entry_time=_opened or run_at,
                    exit_time=_ct.closed_at,
                    exit_reason=_ct.reason,
                )
                _grade = _eval_svc.grade_closed_trade(_tr)
                app_state.trade_grades.append(_grade)
            if _newly_closed:
                logger.info("closed_trades_graded", count=len(_newly_closed))
        except Exception as _grade_exc:  # noqa: BLE001
            logger.warning("closed_trade_grading_failed", error=str(_grade_exc))
            errors.append(f"trade_grading: {_grade_exc}")        # ── Sync portfolio state from broker ───────────────────────────────────
        try:
            acct = _broker.get_account_state()
            portfolio_state.cash = acct.cash_balance
            broker_positions = _broker.list_positions()
            for bp in broker_positions:
                if bp.ticker in portfolio_state.positions:
                    portfolio_state.positions[bp.ticker].quantity = bp.quantity
                    portfolio_state.positions[bp.ticker].current_price = bp.current_price
            # Remove positions that broker no longer holds
            broker_tickers = {bp.ticker for bp in broker_positions}
            stale = [t for t in list(portfolio_state.positions) if t not in broker_tickers]
            for t in stale:
                del portfolio_state.positions[t]
        except Exception as exc:  # noqa: BLE001
            logger.warning("portfolio_state_sync_failed", error=str(exc))
            errors.append(f"state_sync: {exc}")

        # Clean up peak_prices for positions that are no longer held
        _peaks = getattr(app_state, "position_peak_prices", {})
        for _stale_ticker in list(_peaks.keys()):
            if _stale_ticker not in portfolio_state.positions:
                del _peaks[_stale_ticker]

        # ── Fill reconciliation ────────────────────────────────────────────────
        reconciliation_clean: Optional[bool] = None
        try:
            actual_fills = _broker.list_fills_since(run_at)
            reconciliation = _reporting_svc.reconcile_fills(
                expectations=fill_expectations,
                actual_fills=actual_fills,
            )
            reconciliation_clean = reconciliation.is_clean
        except Exception as exc:  # noqa: BLE001
            logger.warning("fill_reconciliation_failed", error=str(exc))
            errors.append(f"reconciliation: {exc}")

        # ── Persist results back to ApiAppState ───────────────────────────────
        app_state.portfolio_state = portfolio_state
        app_state.proposed_actions = proposed_actions
        if hasattr(app_state, "last_paper_cycle_at"):
            app_state.last_paper_cycle_at = run_at
        if hasattr(app_state, "paper_loop_active"):
            app_state.paper_loop_active = True

        result: dict[str, Any] = {
            "status": "ok",
            "mode": cfg.operating_mode.value,
            "run_at": run_at.isoformat(),
            "proposed_count": len(proposed_actions),
            "approved_count": len(approved_requests),
            "executed_count": executed_count,
            "reconciliation_clean": reconciliation_clean,
            "errors": errors,
        }

        # Append to in-memory cycle history (used by error-rate gate check)
        if hasattr(app_state, "paper_cycle_results"):
            app_state.paper_cycle_results.append(result)

        # Persist portfolio snapshot to DB (fire-and-forget, Priority 20)
        if app_state.portfolio_state is not None:
            _persist_portfolio_snapshot(app_state.portfolio_state, cfg.operating_mode.value)

        # Persist per-position P&L snapshots to DB (fire-and-forget, Phase 32)
        if app_state.portfolio_state is not None and app_state.portfolio_state.positions:
            _persist_position_history(app_state.portfolio_state, run_at)

        # ── Phase 50: Factor Exposure Monitoring ──────────────────────────────
        # Compute portfolio factor exposure (MOMENTUM / VALUE / GROWTH / QUALITY /
        # LOW_VOL) using data already in app_state — no new DB write.
        # Volatility data is queried read-only from the feature store; failure
        # degrades gracefully to 0.5 neutral LOW_VOL scores.
        try:
            from services.risk_engine.factor_exposure import FactorExposureService as _FactorSvc  # noqa: PLC0415

            _fe_positions = portfolio_state.positions if portfolio_state else {}
            if _fe_positions:
                # Ranking composite scores → MOMENTUM
                _fe_ranking_scores: dict[str, float] = {}
                for _r in app_state.latest_rankings:
                    if getattr(_r, "composite_score", None) is not None:
                        _fe_ranking_scores[_r.ticker] = float(_r.composite_score)

                _fe_fundamentals = getattr(app_state, "latest_fundamentals", {})
                _fe_dollar_vols = getattr(app_state, "latest_dollar_volumes", {})

                # Lightweight read-only DB query for volatility_20d
                _fe_vol_map: dict[str, float] = {}
                try:
                    import sqlalchemy as _sa  # noqa: PLC0415
                    from infra.db.models.analytics import Feature as _Feat, SecurityFeatureValue as _SFV  # noqa: PLC0415
                    from infra.db.models import Security as _Sec  # noqa: PLC0415
                    from infra.db.session import db_session as _fe_db_sess  # noqa: PLC0415

                    with _fe_db_sess() as _fe_db:
                        _vol_feat = _fe_db.execute(
                            _sa.select(_Feat).where(_Feat.feature_key == "volatility_20d")
                        ).scalar_one_or_none()

                        if _vol_feat is not None:
                            _fe_tickers = list(_fe_positions.keys())
                            _vol_subq = (
                                _sa.select(
                                    _SFV.security_id,
                                    _sa.func.max(_SFV.as_of_timestamp).label("max_ts"),
                                )
                                .where(_SFV.feature_id == _vol_feat.id)
                                .group_by(_SFV.security_id)
                                .subquery()
                            )
                            _vol_rows = _fe_db.execute(
                                _sa.select(_Sec.ticker, _SFV.feature_value_numeric)
                                .join(_SFV, _SFV.security_id == _Sec.id)
                                .join(
                                    _vol_subq,
                                    _sa.and_(
                                        _vol_subq.c.security_id == _SFV.security_id,
                                        _vol_subq.c.max_ts == _SFV.as_of_timestamp,
                                    ),
                                )
                                .where(_SFV.feature_id == _vol_feat.id)
                                .where(_Sec.ticker.in_(_fe_tickers))
                                .where(_SFV.feature_value_numeric.isnot(None))
                            ).all()
                            for _vt, _vv in _vol_rows:
                                if _vt and _vv is not None:
                                    _fe_vol_map[_vt] = float(_vv)
                except Exception as _vol_err:  # noqa: BLE001
                    logger.warning("factor_exposure_vol_fetch_failed", error=str(_vol_err))

                # Build per-ticker feature snapshots and compute scores
                _fe_ticker_features: dict[str, dict] = {}
                for _fe_tk in _fe_positions:
                    _fe_fund = _fe_fundamentals.get(_fe_tk)
                    _fe_ticker_features[_fe_tk] = {
                        "composite_score": _fe_ranking_scores.get(_fe_tk),
                        "pe_ratio": getattr(_fe_fund, "pe_ratio", None) if _fe_fund else None,
                        "eps_growth": getattr(_fe_fund, "eps_growth", None) if _fe_fund else None,
                        "dollar_volume_20d": _fe_dollar_vols.get(_fe_tk),
                        "volatility_20d": _fe_vol_map.get(_fe_tk),
                    }

                _fe_ticker_scores = {
                    _tk: _FactorSvc.compute_factor_scores(_fv)
                    for _tk, _fv in _fe_ticker_features.items()
                }

                _fe_equity = float(portfolio_state.equity) if portfolio_state else 0.0
                _fe_result = _FactorSvc.compute_portfolio_factor_exposure(
                    positions=_fe_positions,
                    ticker_scores=_fe_ticker_scores,
                    equity=_fe_equity,
                )
                app_state.latest_factor_exposure = _fe_result
                app_state.factor_exposure_computed_at = run_at
                logger.info(
                    "factor_exposure_updated",
                    dominant_factor=_fe_result.dominant_factor,
                    position_count=_fe_result.position_count,
                )
        except Exception as _factor_exc:  # noqa: BLE001
            logger.warning("factor_exposure_computation_failed", error=str(_factor_exc))

        # ── Phase 54: Factor Tilt Alert ──────────────────────────────────────
        # Detect dominant-factor changes cycle-over-cycle and fire webhook alert.
        # Runs only when factor exposure was successfully computed this cycle.
        try:
            _fe_new = getattr(app_state, "latest_factor_exposure", None)
            if _fe_new is not None:
                from services.factor_alerts.service import FactorTiltAlertService as _FTASvc  # noqa: PLC0415
                _last_dom = getattr(app_state, "last_dominant_factor", None)
                _tilt_events = getattr(app_state, "factor_tilt_events", [])
                _tilt_event = _FTASvc.detect_tilt(
                    current_result=_fe_new,
                    last_dominant_factor=_last_dom,
                    factor_tilt_events=_tilt_events,
                )
                if _tilt_event is not None:
                    _tilt_events_updated = list(_tilt_events) + [_tilt_event]
                    app_state.factor_tilt_events = _tilt_events_updated
                    # Fire webhook alert
                    _fta_alert_svc = getattr(app_state, "alert_service", None)
                    if _fta_alert_svc:
                        try:
                            from services.alerting.models import AlertEvent, AlertSeverity  # noqa: PLC0415
                            _fta_alert_svc.send_alert(AlertEvent(
                                event_type="factor_tilt_detected",
                                severity=AlertSeverity.INFO.value,
                                title=(
                                    f"APIS: Factor tilt detected — "
                                    f"{_tilt_event.previous_factor} → {_tilt_event.new_factor}"
                                    if _tilt_event.tilt_type == "factor_change"
                                    else f"APIS: Factor weight shift — {_tilt_event.new_factor} Δ{_tilt_event.delta_weight:.2f}"
                                ),
                                payload=_FTASvc.build_alert_payload(_tilt_event),
                            ))
                        except Exception as _fta_alert_exc:  # noqa: BLE001
                            logger.warning("factor_tilt_alert_send_failed", error=str(_fta_alert_exc))
                    logger.info(
                        "factor_tilt_event_recorded",
                        tilt_type=_tilt_event.tilt_type,
                        previous_factor=_tilt_event.previous_factor,
                        new_factor=_tilt_event.new_factor,
                        delta_weight=_tilt_event.delta_weight,
                    )
                # Always update last_dominant_factor to current cycle's result
                app_state.last_dominant_factor = _fe_new.dominant_factor
        except Exception as _fta_exc:  # noqa: BLE001
            logger.warning("factor_tilt_detection_failed", error=str(_fta_exc))

        # Increment durable cycle counter and persist to DB
        if hasattr(app_state, "paper_cycle_count"):
            app_state.paper_cycle_count += 1
            _persist_paper_cycle_count(app_state.paper_cycle_count)

        logger.info(
            "paper_trading_cycle_complete",
            proposed_count=result["proposed_count"],
            approved_count=result["approved_count"],
            executed_count=result["executed_count"],
            paper_cycle_count=getattr(app_state, "paper_cycle_count", None),
        )
        return result

    except Exception as exc:  # noqa: BLE001
        logger.exception("paper_trading_cycle_fatal_error", error=str(exc))
        # ── Phase 31: Paper cycle error alert ───────────────────────────────
        _alert_svc = getattr(app_state, "alert_service", None)
        if _alert_svc and getattr(cfg, "alert_on_paper_cycle_error", True):
            from services.alerting.models import AlertEvent, AlertEventType, AlertSeverity
            _alert_svc.send_alert(AlertEvent(
                event_type=AlertEventType.PAPER_CYCLE_ERROR.value,
                severity=AlertSeverity.WARNING.value,
                title="APIS: Paper trading cycle failed with an unexpected error",
                payload={"mode": cfg.operating_mode.value, "error": str(exc), "run_at": run_at.isoformat()},
            ))
        return {
            "status": "error",
            "mode": cfg.operating_mode.value,
            "run_at": run_at.isoformat(),
            "proposed_count": 0,
            "approved_count": 0,
            "executed_count": 0,
            "reconciliation_clean": None,
            "errors": [f"fatal: {exc}"],
        }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _fetch_price(
    ticker: str,
    target_notional: Decimal,
    market_data_svc: Any,
    errors: list[str],
) -> Decimal:
    """Fetch latest price for *ticker*.  Falls back to 1.00 on any error."""
    try:
        snapshot = market_data_svc.get_snapshot(ticker)
        price = snapshot.latest_price
        if price and price > Decimal("0"):
            return Decimal(str(price))
    except Exception as exc:  # noqa: BLE001
        logger.warning("price_fetch_failed", ticker=ticker, error=str(exc))
        errors.append(f"price_fetch_{ticker}: {exc}")

    # Fallback: derive rough price from notional / 100 shares assumption,
    # floor at $1.00 so quantity math stays plausible.
    fallback = (target_notional / Decimal("100")).quantize(Decimal("0.01"))
    return max(fallback, Decimal("1.00"))
