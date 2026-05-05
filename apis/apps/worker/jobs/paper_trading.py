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
import uuid
from decimal import Decimal
from typing import Any

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


def _persist_portfolio_snapshot(
    portfolio_state: Any,
    mode: str,
    cycle_id: str | None = None,
) -> None:
    """Fire-and-forget: insert a PortfolioSnapshot row into the DB.

    Never raises — DB failures are logged at WARNING level only.
    Called after every successful paper trading cycle.

    Deep-Dive Step 2 Rec 4: when ``cycle_id`` is provided, populates
    ``idempotency_key = f"{cycle_id}:portfolio_snapshot"`` and uses
    ``INSERT ... ON CONFLICT DO NOTHING`` on the unique index so retries
    are safe.  When ``cycle_id`` is None, falls back to plain insert
    (legacy behavior) to preserve backward compatibility with tests.
    """
    try:
        from decimal import Decimal as _Decimal

        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from infra.db.models.portfolio import PortfolioSnapshot as _DBSnap
        from infra.db.session import db_session as _db_session

        # Phase 70: never persist a negative-cash snapshot in paper mode.
        # A negative cash value means the broker's state was corrupted
        # (e.g. by a concurrent-cycle race).  Writing it to the DB would
        # poison the restore path (_load_persisted_state) and propagate
        # the corruption across container restarts.
        _snap_cash = _Decimal(str(portfolio_state.cash))
        if _snap_cash < _Decimal("0") and mode.lower() == "paper":
            logger.critical(
                "phase70_phantom_cash_snapshot_blocked",
                cash=str(_snap_cash),
                equity=str(portfolio_state.equity),
                gross_exposure=str(portfolio_state.gross_exposure),
                positions=len(portfolio_state.positions),
                note="Negative cash in paper mode — snapshot NOT written to DB",
            )
            return

        idem_key = f"{cycle_id}:portfolio_snapshot" if cycle_id else None
        values = dict(
            snapshot_timestamp=dt.datetime.now(dt.UTC),
            mode=mode,
            cash_balance=_snap_cash,
            gross_exposure=_Decimal(str(portfolio_state.gross_exposure)),
            net_exposure=(
                _Decimal(str(portfolio_state.equity))
                - _snap_cash
            ),
            equity_value=_Decimal(str(portfolio_state.equity)),
            drawdown_pct=_Decimal(str(portfolio_state.drawdown_pct)),
            notes=None,
            idempotency_key=idem_key,
        )
        with _db_session() as db:
            if idem_key is not None:
                stmt = pg_insert(_DBSnap).values(**values)
                stmt = stmt.on_conflict_do_nothing(
                    constraint="uq_portfolio_snapshot_idempotency_key"
                )
                db.execute(stmt)
            else:
                db.add(_DBSnap(**values))
    except Exception as exc:  # noqa: BLE001
        logger.warning("persist_portfolio_snapshot_failed %s", exc)


def _persist_positions(
    portfolio_state: Any,
    closed_trades_this_cycle: list | None,
    run_at: Any,
) -> None:
    """Phase 64: Authoritative Position table upsert.

    Writes one row per open position in ``portfolio_state`` with status='open',
    and closes any previously-open Position rows whose ticker is no longer in
    the portfolio state (status='closed', closed_at, exit_price, realized_pnl).

    This is the root fix for the Phantom Broker Positions bug: the restore path
    in ``_load_persisted_state`` reads from this table, so without authoritative
    writes here the only rehydrated state came from negative-cash snapshots
    with no matching positions.

    Fire-and-forget: never raises — DB failures are logged at WARNING level.
    """
    try:
        from decimal import Decimal as _Decimal

        from sqlalchemy import select as _select

        from infra.db.models import Security as _Security
        from infra.db.models.portfolio import Position as _DBPosition
        from infra.db.session import db_session as _db_session

        # Build ticker -> ClosedTrade map for realized_pnl / exit_price on closes
        ct_by_ticker: dict[str, Any] = {}
        for _ct in closed_trades_this_cycle or []:
            if getattr(_ct, "ticker", None):
                ct_by_ticker[_ct.ticker] = _ct

        with _db_session() as db:
            # Resolve ticker -> security_id for every open position
            open_tickers = list(portfolio_state.positions.keys())
            sec_by_ticker: dict[str, Any] = {}
            if open_tickers:
                sec_rows = db.execute(
                    _select(_Security).where(_Security.ticker.in_(open_tickers))
                ).scalars().all()
                sec_by_ticker = {s.ticker: s for s in sec_rows}

            # ── Upsert open positions ────────────────────────────────────────
            # Phase 75 (2026-05-04): track every (security_id) we touched in the
            # upsert so the close-loop below CANNOT re-close a row we just
            # opened/reopened in the same call.  This is defense-in-depth on
            # top of the (security_id, opened_at) idempotency below: even if
            # `held_tickers` is somehow missing an entry, the just-touched set
            # protects the row.  Without this, the row-inflation pattern
            # observed since 2026-04-20 (BK=22, UNP=20, ODFL=20, CSCO=7 etc.
            # rows per ownership episode) re-fires every cycle.
            _persist_touched_sec_ids: set = set()

            for ticker, pos in portfolio_state.positions.items():
                sec = sec_by_ticker.get(ticker)
                sec_id = getattr(pos, "security_id", None) or (sec.id if sec else None)
                if sec_id is None:
                    logger.warning(
                        "persist_positions_missing_security",
                        ticker=ticker,
                    )
                    continue

                # Phase 75 (2026-05-04): (security_id, opened_at) is the
                # natural unique key for one ownership episode.  The previous
                # query was `status='open'` only, so when an upstream bug
                # closed a row mid-episode the next cycle inserted a *new*
                # row with the same opened_at — producing the row-inflation
                # we saw on CSCO (7 rows / single broker fill, 2026-05-04)
                # and on BK/UNP/ODFL/HOLX/MRVL/etc. for weeks before.  Match
                # on (security_id, opened_at) and reopen if closed.
                _pos_opened_at = getattr(pos, "opened_at", None) or run_at
                same_episode = db.execute(
                    _select(_DBPosition)
                    .where(_DBPosition.security_id == sec_id)
                    .where(_DBPosition.opened_at == _pos_opened_at)
                    .order_by(_DBPosition.created_at.desc())
                    .limit(1)
                ).scalar_one_or_none()

                # Fall back to the legacy "any open row for this security"
                # match — this preserves prior behaviour when the in-memory
                # PortfolioPosition.opened_at was set later than the DB row's
                # opened_at (e.g. via broker-sync after a restart).
                existing = same_episode or db.execute(
                    _select(_DBPosition)
                    .where(_DBPosition.security_id == sec_id)
                    .where(_DBPosition.status == "open")
                    .order_by(_DBPosition.opened_at.desc())
                    .limit(1)
                ).scalar_one_or_none()

                qty = _Decimal(str(pos.quantity)) if pos.quantity else _Decimal("0")
                entry = _Decimal(str(pos.avg_entry_price)) if pos.avg_entry_price else _Decimal("0")
                cur = _Decimal(str(pos.current_price)) if pos.current_price else entry
                cost = (entry * qty).quantize(_Decimal("0.0001"))
                mv = (cur * qty).quantize(_Decimal("0.0001"))
                upl = (mv - cost).quantize(_Decimal("0.0001"))

                # Deep-Dive Step 5 Rec 7 deferred finisher (2026-04-18):
                # persist origin_strategy when the in-memory PortfolioPosition
                # carries one.  Empty string → NULL so resolve_family() still
                # lands on FAMILY_PARAMS["default"] for legacy rows.
                _os = getattr(pos, "origin_strategy", None) or None

                if existing is None:
                    db.add(_DBPosition(
                        security_id=sec_id,
                        opened_at=_pos_opened_at,
                        status="open",
                        entry_price=entry,
                        quantity=qty,
                        cost_basis=cost,
                        market_value=mv,
                        unrealized_pnl=upl,
                        origin_strategy=_os,
                    ))
                else:
                    # Phase 75 (2026-05-04): if the matching row is CLOSED,
                    # reopen it instead of inserting a duplicate.  This is
                    # the primary fix for the row-inflation bug.  The audit
                    # trail is preserved (created_at unchanged); only the
                    # status / closed_at / exit_price / realized_pnl are
                    # cleared because the position is now considered live
                    # again.
                    if existing.status != "open":
                        logger.info(
                            "phase75_position_row_reopened",
                            ticker=ticker,
                            opened_at=str(_pos_opened_at),
                            prior_closed_at=(
                                str(existing.closed_at)
                                if existing.closed_at is not None
                                else None
                            ),
                        )
                        existing.status = "open"
                        existing.closed_at = None
                        existing.exit_price = None
                        existing.realized_pnl = None
                    existing.quantity = qty
                    existing.entry_price = entry
                    existing.cost_basis = cost
                    existing.market_value = mv
                    existing.unrealized_pnl = upl
                    # Only backfill origin_strategy; never overwrite a value that
                    # was set at open-time with a fresh cycle's ranking (the
                    # ranking's dominant signal may have shifted).
                    if existing.origin_strategy in (None, "") and _os:
                        existing.origin_strategy = _os

                _persist_touched_sec_ids.add(sec_id)

            # ── Close DB positions that are no longer in portfolio_state ─────
            open_db_rows = db.execute(
                _select(_DBPosition, _Security.ticker)
                .join(_Security, _Security.id == _DBPosition.security_id)
                .where(_DBPosition.status == "open")
            ).all()
            held_tickers = set(portfolio_state.positions.keys())
            for row, ticker in open_db_rows:
                if ticker in held_tickers:
                    continue
                # Phase 75 (2026-05-04): never close a row whose security
                # was just upserted/reopened in this same _persist_positions
                # call.  Defense-in-depth — without this, an upstream bug
                # that drops the ticker from `portfolio_state.positions`
                # *between* the upsert loop above and this close loop would
                # immediately close the row we just inserted, perpetuating
                # the row-inflation pattern.
                if row.security_id in _persist_touched_sec_ids:
                    logger.warning(
                        "phase75_close_skipped_just_upserted",
                        ticker=ticker,
                        security_id=str(row.security_id),
                        note=(
                            "upstream dropped ticker from portfolio_state "
                            "between upsert and close — row preserved"
                        ),
                    )
                    continue
                ct = ct_by_ticker.get(ticker)
                row.status = "closed"
                row.closed_at = run_at
                if ct is not None:
                    if getattr(ct, "fill_price", None) is not None:
                        row.exit_price = _Decimal(str(ct.fill_price))
                    if getattr(ct, "realized_pnl", None) is not None:
                        row.realized_pnl = _Decimal(str(ct.realized_pnl))
    except Exception as exc:  # noqa: BLE001
        logger.warning("persist_positions_failed", error=str(exc))


def _persist_orders_and_fills(
    approved_requests: list,
    execution_results: list,
    run_at: Any,
    cycle_id: str | None = None,
) -> None:
    """Authoritative ``orders`` + ``fills`` ledger writer.

    Writes one ``Order`` row per ``ExecutionRequest`` (success or failure) and
    one ``Fill`` row per ``ExecutionResult`` with status == FILLED.  Was
    missing from the paper cycle entirely — the tables contained **zero rows**
    despite hundreds of executions, leaving the system with no queryable audit
    trail and no per-order P&L attribution basis.

    Idempotency: ``orders.idempotency_key = f"{cycle_id}:{ticker}:{side}"`` so
    a replayed cycle upserts rather than duplicating.  Matches the pattern used
    for ``portfolio_snapshots`` (``{cycle_id}:portfolio_snapshot``).

    Fire-and-forget: never raises — DB failures are logged at WARNING level,
    just like ``_persist_positions`` and ``_persist_portfolio_snapshot``.
    """
    try:
        from decimal import Decimal as _Decimal

        from sqlalchemy import select as _select

        from infra.db.models import Security as _Security
        from infra.db.models.portfolio import Fill as _DBFill
        from infra.db.models.portfolio import Order as _DBOrder
        from infra.db.models.portfolio import Position as _DBPosition
        from infra.db.session import db_session as _db_session
        from services.execution_engine.models import ExecutionStatus as _ExecStatus
        from services.portfolio_engine.models import ActionType as _ActionType

        if not approved_requests:
            return

        _cid = cycle_id or "unknown"

        with _db_session() as db:
            # Resolve ticker -> security_id once for every touched ticker
            tickers = sorted({req.action.ticker for req in approved_requests})
            sec_rows = db.execute(
                _select(_Security).where(_Security.ticker.in_(tickers))
            ).scalars().all()
            sec_by_ticker = {s.ticker: s.id for s in sec_rows}

            for req, res in zip(approved_requests, execution_results):
                ticker = req.action.ticker
                sec_id = sec_by_ticker.get(ticker)
                if sec_id is None:
                    logger.warning(
                        "persist_orders_missing_security",
                        ticker=ticker,
                    )
                    continue

                # BUY for OPEN; SELL for CLOSE and TRIM
                side = (
                    "buy" if req.action.action_type == _ActionType.OPEN else "sell"
                )
                order_status = res.status.value  # "filled" | "rejected" | ...
                qty = req.action.target_quantity or res.fill_quantity
                qty_d = _Decimal(str(qty)) if qty else None
                notional = req.action.target_notional
                notional_d = _Decimal(str(notional)) if notional else None

                idem = f"{_cid}:{ticker}:{side}"

                existing = db.execute(
                    _select(_DBOrder).where(_DBOrder.idempotency_key == idem).limit(1)
                ).scalar_one_or_none()

                # Look up the current open Position row so the Order can link
                # back to it (nullable — CLOSE on an already-closed position
                # rejects in execution engine, so position_id may be None for
                # REJECTED/BLOCKED rows).
                pos_row = db.execute(
                    _select(_DBPosition)
                    .where(_DBPosition.security_id == sec_id)
                    .where(_DBPosition.status == "open")
                    .order_by(_DBPosition.opened_at.desc())
                    .limit(1)
                ).scalar_one_or_none()
                pos_id = pos_row.id if pos_row is not None else None

                if existing is None:
                    order_row = _DBOrder(
                        broker_order_ref=res.broker_order_id,
                        security_id=sec_id,
                        position_id=pos_id,
                        order_timestamp=run_at,
                        order_type="market",
                        side=side,
                        quantity=qty_d,
                        notional_amount=notional_d,
                        limit_price=None,
                        stop_price=None,
                        status=order_status,
                        idempotency_key=idem,
                        decision_snapshot_json={
                            "action_type": req.action.action_type.value,
                            "reason": req.action.reason or "",
                            "expected_price": str(req.current_price),
                            "error_message": res.error_message,
                            "cycle_id": _cid,
                        },
                    )
                    db.add(order_row)
                    db.flush()
                    order_id = order_row.id
                else:
                    existing.status = order_status
                    existing.broker_order_ref = res.broker_order_id or existing.broker_order_ref
                    existing.quantity = qty_d or existing.quantity
                    existing.notional_amount = notional_d or existing.notional_amount
                    existing.position_id = pos_id or existing.position_id
                    order_id = existing.id

                # Emit a Fill row for any FILLED result
                if (
                    res.status == _ExecStatus.FILLED
                    and res.fill_price is not None
                    and res.fill_quantity is not None
                ):
                    fill_existing = db.execute(
                        _select(_DBFill).where(_DBFill.order_id == order_id).limit(1)
                    ).scalar_one_or_none()
                    if fill_existing is None:
                        db.add(_DBFill(
                            order_id=order_id,
                            fill_timestamp=res.filled_at or run_at,
                            fill_quantity=_Decimal(str(res.fill_quantity)),
                            fill_price=_Decimal(str(res.fill_price)),
                            fees=_Decimal(str(res.fees or 0)),
                            liquidity_flag=None,
                        ))
    except Exception as exc:  # noqa: BLE001
        logger.warning("persist_orders_fills_failed", error=str(exc))


def _shadow_enabled(cfg: Any) -> bool:
    """Deep-Dive Step 7: single place that resolves the shadow-portfolio flag.

    Every shadow call-site wraps its work in ``if _shadow_enabled(cfg):`` so a
    flag flip is byte-for-byte a no-op on live portfolio behaviour.
    """
    return bool(getattr(cfg, "shadow_portfolio_enabled", False))


def _shadow_service(db):
    """Lazy import + construct ShadowPortfolioService.  Returns ``None`` on
    any import/construction failure so the caller can soft-skip.
    """
    try:
        from services.shadow_portfolio import (  # noqa: PLC0415
            ShadowPortfolioService as _ShadowSvc,
        )

        return _ShadowSvc(db)
    except Exception as exc:  # noqa: BLE001
        logger.warning("shadow_portfolio.service_construct_failed", error=str(exc))
        return None


def _shadow_shares_for_notional(
    target_notional: Decimal | int | float | None,
    price: Decimal | int | float | None,
) -> Decimal:
    """Translate a (target_notional, price) pair into a whole-share quantity.

    Mirrors paper_trading's own BUY sizing (``to_integral_value`` + ROUND_DOWN)
    so a shadow and the live system agree on share count.  Returns Decimal("0")
    when either input is missing or non-positive.
    """
    try:
        if target_notional is None or price is None:
            return Decimal("0")
        tn = Decimal(str(target_notional))
        px = Decimal(str(price))
        if tn <= 0 or px <= 0:
            return Decimal("0")
        import decimal as _decimal  # noqa: PLC0415

        return (tn / px).to_integral_value(rounding=_decimal.ROUND_DOWN)
    except Exception:  # noqa: BLE001
        return Decimal("0")


def _fresh_rebalance_targets(app_state: Any, settings: Any) -> dict:
    """Return ``app_state.rebalance_targets`` iff the computed_at timestamp is
    within ``settings.rebalance_target_ttl_seconds`` of now.  Otherwise return
    an empty dict (stale targets are treated as absent).

    Step 1 (Deep-Dive Plan 2026-04-16): replaces the implicit "indefinite"
    freshness window previously used for rebalance-target CLOSE suppression
    and merge.  TTL default is 3600 s = 1 hr; set to 0 to disable the check.
    """
    targets = getattr(app_state, "rebalance_targets", {}) or {}
    if not targets:
        return {}
    ttl = int(getattr(settings, "rebalance_target_ttl_seconds", 3600))
    if ttl <= 0:
        # Freshness check disabled → legacy behavior (always honor targets)
        return targets
    computed_at = getattr(app_state, "rebalance_computed_at", None)
    if computed_at is None:
        # No timestamp → treat as stale (safer; avoids honoring ancient targets)
        return {}
    try:
        if computed_at.tzinfo is None:
            computed_at = computed_at.replace(tzinfo=dt.UTC)
        age = (dt.datetime.now(dt.UTC) - computed_at).total_seconds()
    except Exception:  # noqa: BLE001
        return {}
    if age > ttl:
        return {}
    return targets


def _apply_ranking_min_filter(
    rankings: list[Any],
    app_state: Any,
    settings: Any,
) -> list[Any]:
    """Filter a rankings list by composite-score floor.

    Legacy behavior (`conditional_ranking_min_enabled=False`, default):
    every ranking must satisfy ``composite_score >= ranking_min_composite_score``.

    Deep-Dive Plan Step 3 Rec 8 (flag ON): a ranking for a ticker that is
    **currently held** AND has ≥1 prior closed trade graded A or B in
    ``app_state.trade_grades`` gets a looser floor, ``ranking_min_held_positive``
    (default 0.20).  All other tickers still use the strict floor.  The flag
    default is OFF so this helper is bit-for-bit the legacy filter.
    """
    min_score = float(getattr(settings, "ranking_min_composite_score", 0.30))
    if not getattr(settings, "conditional_ranking_min_enabled", False):
        return [
            r for r in rankings
            if float(getattr(r, "composite_score", None) or 0) >= min_score
        ]

    loose_score = float(getattr(settings, "ranking_min_held_positive", 0.20))

    current_positions: set[str] = set()
    try:
        ps = getattr(app_state, "portfolio_state", None)
        if ps is not None:
            current_positions = set(getattr(ps, "positions", {}).keys())
    except Exception:  # noqa: BLE001
        current_positions = set()

    positive_counts: dict[str, int] = {}
    try:
        for g in getattr(app_state, "trade_grades", []) or []:
            t = getattr(g, "ticker", None)
            grade = getattr(g, "grade", None)
            if t and grade in ("A", "B"):
                positive_counts[t] = positive_counts.get(t, 0) + 1
    except Exception:  # noqa: BLE001
        positive_counts = {}

    out: list[Any] = []
    for r in rankings:
        t = getattr(r, "ticker", None) or getattr(r, "symbol", None)
        cs = float(getattr(r, "composite_score", None) or 0)
        if t in current_positions and positive_counts.get(t, 0) > 0:
            if cs >= loose_score:
                out.append(r)
        elif cs >= min_score:
            out.append(r)
    return out


def _persist_position_history(
    portfolio_state: Any,
    snapshot_at: Any,
    cycle_id: str | None = None,
) -> None:
    """Fire-and-forget: insert one PositionHistory row per open position.

    Never raises — DB failures are logged at WARNING level only.
    Called after broker sync so prices are current.

    Deep-Dive Step 2 Rec 4: when ``cycle_id`` is provided, each row gets
    ``idempotency_key = f"{cycle_id}:position_history:{ticker}"`` and the
    insert uses ``ON CONFLICT DO NOTHING`` so retries of the same cycle
    are no-ops.
    """
    try:
        from decimal import Decimal as _Decimal

        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from infra.db.models.portfolio import PositionHistory as _PosHist
        from infra.db.session import db_session as _db_session

        rows: list[dict] = []
        for pos in portfolio_state.positions.values():
            idem = (
                f"{cycle_id}:position_history:{pos.ticker}"
                if cycle_id else None
            )
            rows.append(
                dict(
                    ticker=pos.ticker,
                    snapshot_at=snapshot_at,
                    quantity=_Decimal(str(pos.quantity)),
                    avg_entry_price=_Decimal(str(pos.avg_entry_price)),
                    current_price=_Decimal(str(pos.current_price)),
                    market_value=_Decimal(str(pos.market_value)),
                    cost_basis=_Decimal(str(pos.cost_basis)),
                    unrealized_pnl=_Decimal(str(pos.unrealized_pnl)),
                    unrealized_pnl_pct=_Decimal(str(pos.unrealized_pnl_pct)),
                    idempotency_key=idem,
                )
            )
        if rows:
            with _db_session() as db:
                if cycle_id is not None:
                    for r in rows:
                        stmt = pg_insert(_PosHist).values(**r)
                        stmt = stmt.on_conflict_do_nothing(
                            constraint="uq_position_history_idempotency_key"
                        )
                        db.execute(stmt)
                else:
                    db.add_all([_PosHist(**r) for r in rows])
    except Exception as exc:  # noqa: BLE001
        logger.warning("persist_position_history_failed", error=str(exc))


def run_paper_trading_cycle(
    app_state: ApiAppState,
    settings: Settings | None = None,
    broker: Any | None = None,
    portfolio_svc: Any | None = None,
    risk_svc: Any | None = None,
    execution_svc: Any | None = None,
    market_data_svc: Any | None = None,
    reporting_svc: Any | None = None,
    eval_svc: Any | None = None,
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
    run_at = dt.datetime.now(dt.UTC)
    # Deep-Dive Step 2 Rec 4: stable cycle id used as the namespace for
    # idempotency keys written to portfolio_snapshots and position_history.
    # A retry of the same cycle uses the same id → unique constraint makes
    # duplicate rows impossible.
    cycle_id = uuid.uuid4().hex

    logger.info(
        "paper_trading_cycle_starting",
        mode=cfg.operating_mode.value,
        run_at=run_at.isoformat(),
        cycle_id=cycle_id,
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

    # ── Broker adapter lazy init (must precede health check) ─────────────────
    # On a fresh worker start app_state.broker_adapter is None.  The
    # broker-adapter health invariant below treats (adapter=None + DB has
    # open positions) as a catastrophic mid-cycle loss and fires the kill
    # switch.  That is the RIGHT behaviour mid-cycle but a FALSE POSITIVE
    # on a fresh worker start, where the adapter simply hasn't been
    # lazy-initialized yet.  Build it here so the invariant sees a present
    # adapter and falls through to the drift check (non-fatal) instead.
    # `broker` may be supplied by the test harness; `broker or existing`
    # preserves injection semantics.
    if getattr(app_state, "broker_adapter", None) is None and broker is None:
        try:
            from broker_adapters.paper.adapter import PaperBrokerAdapter
            app_state.broker_adapter = PaperBrokerAdapter(market_open=True)
            logger.info(
                "broker_adapter_lazy_initialized",
                cycle_id=cycle_id,
                reason="fresh_worker_start",
            )
        except Exception as _bi_exc:  # noqa: BLE001
            logger.warning(
                "broker_adapter_lazy_init_failed",
                error=str(_bi_exc),
                cycle_id=cycle_id,
            )

    # ── Deep-Dive Step 2 Rec 1: Broker-adapter health invariant ──────────────
    # Safety gate: if the broker adapter is absent while the DB says we have
    # live open positions, fire the kill switch and abort this cycle.  If the
    # adapter's reported positions drift from the DB, log a warning and let
    # the cycle proceed using the DB as the source of truth.  Healthy state
    # → no-op.  Feature-flagged via APIS_BROKER_HEALTH_INVARIANT_ENABLED
    # (default ON per DEC-034).
    if getattr(cfg, "broker_health_invariant_enabled", True):
        try:
            from services.broker_adapter.health import (
                BrokerAdapterHealthError as _BrokerHealthErr,
            )
            from services.broker_adapter.health import (
                check_broker_adapter_health as _check_broker_health,
            )

            def _fire_ks(reason: str) -> None:  # noqa: ARG001
                # health.check_broker_adapter_health calls this with a reason string
                try:
                    app_state.kill_switch_active = True
                except Exception:  # noqa: BLE001
                    pass

            _check_broker_health(
                app_state,
                cfg,
                fire_kill_switch_fn=_fire_ks,
            )
        except _BrokerHealthErr as _bhe:  # adapter absent with live positions
            logger.error(
                "broker_adapter_health_invariant_violated",
                error=str(_bhe),
                cycle_id=cycle_id,
            )
            _alert_svc = getattr(app_state, "alert_service", None)
            if _alert_svc is not None:
                try:
                    from services.alerting.models import (
                        AlertEvent,
                        AlertSeverity,
                    )
                    _alert_svc.send_alert(AlertEvent(
                        event_type="broker_adapter_health_violation",
                        severity=AlertSeverity.CRITICAL.value,
                        title=(
                            "APIS: Broker adapter missing while live positions "
                            "exist — kill switch fired, cycle aborted"
                        ),
                        payload={
                            "error": str(_bhe),
                            "cycle_id": cycle_id,
                            "run_at": run_at.isoformat(),
                        },
                    ))
                except Exception:  # noqa: BLE001
                    pass
            return {
                "status": "error_broker_health",
                "mode": cfg.operating_mode.value,
                "run_at": run_at.isoformat(),
                "proposed_count": 0,
                "approved_count": 0,
                "executed_count": 0,
                "reconciliation_clean": None,
                "errors": [f"broker_health: {_bhe}"],
            }
        except Exception as _bh_exc:  # noqa: BLE001
            # Never let the invariant crash the scheduler — log and proceed.
            logger.warning(
                "broker_adapter_health_check_failed",
                error=str(_bh_exc),
                cycle_id=cycle_id,
            )

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

    # ── Minimum composite score filter (learning acceleration) ────────────
    # Delegates to _apply_ranking_min_filter for unit testability.
    _min_score = getattr(cfg, "ranking_min_composite_score", 0.30)
    _pre_filter_count = len(rankings)
    rankings = _apply_ranking_min_filter(rankings, app_state, cfg)
    if _pre_filter_count != len(rankings):
        logger.info(
            "paper_cycle_min_score_filter",
            threshold=_min_score,
            before=_pre_filter_count,
            after=len(rankings),
            conditional_on=bool(
                getattr(cfg, "conditional_ranking_min_enabled", False)
            ),
        )

    # ── Deep-Dive Step 5 Rec 7 (deferred finisher 2026-04-18) ─────────────
    # Build ticker -> origin_strategy map from the ranking's contributing_signals
    # so new opens get the right strategy family key bound on their
    # PortfolioPosition + Position rows.  Empty when rankings carry no signals
    # (unit-test fixtures, cold starts) — PortfolioPosition.origin_strategy
    # then defaults to "" and resolve_family() returns FAMILY_PARAMS["default"].
    _origin_strategy_by_ticker: dict[str, str] = {}
    try:
        from services.risk_engine.family_params import derive_origin_strategy
        for _r in rankings:
            _origin = derive_origin_strategy(
                getattr(_r, "contributing_signals", None)
            )
            if _origin:
                _origin_strategy_by_ticker[_r.ticker] = _origin
    except Exception as _os_exc:  # noqa: BLE001
        logger.warning("derive_origin_strategy_failed", error=str(_os_exc))

    errors: list[str] = []

    try:
        # Lazy imports (keep startup fast; avoid circular imports at module level)
        from broker_adapters.paper.adapter import PaperBrokerAdapter
        from services.evaluation_engine.service import EvaluationEngineService
        from services.execution_engine.models import ExecutionRequest
        from services.execution_engine.service import ExecutionEngineService
        from services.market_data.service import MarketDataService
        from services.portfolio_engine.models import ActionType, PortfolioState
        from services.portfolio_engine.service import PortfolioEngineService
        from services.reporting.models import FillExpectation
        from services.reporting.service import ReportingService
        from services.risk_engine.service import RiskEngineService

        # ── Build services ────────────────────────────────────────────────────
        # Phase 65: persist the PaperBrokerAdapter in app_state so positions
        # survive across cycles.  Previously a new adapter was created every
        # cycle, losing all in-memory position state.
        _broker = broker or getattr(app_state, "broker_adapter", None)
        if _broker is None:
            _broker = PaperBrokerAdapter(market_open=True)
            app_state.broker_adapter = _broker
        # Runtime kill switch lambda — lets RiskEngine + ExecutionEngine check
        # app_state.kill_switch_active (toggled via API) without a process restart.
        _ks_fn = lambda: bool(getattr(app_state, "kill_switch_active", False))  # noqa: E731

        _portfolio_svc = portfolio_svc or PortfolioEngineService(settings=cfg)

        # Phase 76: snapshot inactive tickers once per cycle so the risk engine
        # can hard-block OPEN proposals on securities flagged is_active=false
        # (HOLX-class regression — strategy candidate selector still leaks
        # delisted/suspended names; risk engine is the defence-in-depth gate).
        _inactive_tickers: set[str] = set()
        try:
            import sqlalchemy as _sa_active  # noqa: PLC0415

            from infra.db.models import Security as _SecForActive  # noqa: PLC0415
            from infra.db.session import db_session as _db_session_active  # noqa: PLC0415
            with _db_session_active() as _db_active:
                _rows = _db_active.execute(
                    _sa_active.select(_SecForActive.ticker).where(
                        _SecForActive.is_active.is_(False)
                    )
                ).all()
                _inactive_tickers = {r[0] for r in _rows if r and r[0]}
        except Exception as _e:  # noqa: BLE001
            logger.warning(
                "paper_cycle_inactive_ticker_snapshot_failed",
                error=str(_e),
            )
            _inactive_tickers = set()
        _is_active_fn = (
            lambda t: t not in _inactive_tickers  # noqa: E731
        )

        _risk_svc = risk_svc or RiskEngineService(
            settings=cfg,
            kill_switch_fn=_ks_fn,
            is_active_fn=_is_active_fn,
        )
        _execution_svc = execution_svc or ExecutionEngineService(
            settings=cfg, broker=_broker, kill_switch_fn=_ks_fn
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
            # ── Phase 69: Reset daily position-open counter on day boundary ──
            portfolio_state.daily_opens_count = 0
            logger.info(
                "sod_equity_captured",
                date=str(_run_date),
                equity=str(portfolio_state.equity),
            )

        # ── Phase 69: Startup-aware daily position cap ─────────────────────
        # On first cycle after restart (or first cycle of the day), seed the
        # counter from DB so the risk engine's check_daily_position_cap sees
        # positions already opened today even if the worker was restarted.
        # Without this, daily_opens_count starts at 0 and the first burst
        # can exceed MAX_NEW_POSITIONS_PER_DAY (2026-04-28 incident: 7 vs 5).
        if portfolio_state.daily_opens_count == 0:
            try:
                from sqlalchemy import func as _func
                from sqlalchemy import select as _cap_select

                from infra.db.models.portfolio import Position as _CapPosition
                from infra.db.session import db_session as _cap_db_session

                with _cap_db_session() as _cap_db:
                    _today_opens = _cap_db.execute(
                        _cap_select(_func.count())
                        .select_from(_CapPosition)
                        .where(_CapPosition.status == "open")
                        .where(_func.date(_CapPosition.opened_at) == _run_date)
                    ).scalar() or 0
                    # Also count positions that were opened and already closed
                    # today — they still consumed a daily slot.
                    _today_closed = _cap_db.execute(
                        _cap_select(_func.count())
                        .select_from(_CapPosition)
                        .where(_CapPosition.status == "closed")
                        .where(_func.date(_CapPosition.opened_at) == _run_date)
                    ).scalar() or 0
                    _today_total = _today_opens + _today_closed
                    if _today_total > 0:
                        portfolio_state.daily_opens_count = _today_total
                        logger.info(
                            "phase69_daily_opens_restored_from_db",
                            date=str(_run_date),
                            today_opens=_today_opens,
                            today_closed=_today_closed,
                            daily_opens_count=_today_total,
                        )
            except Exception as _cap_exc:  # noqa: BLE001
                logger.warning(
                    "phase69_daily_opens_restore_failed",
                    error=str(_cap_exc),
                )

        # ────────────────────────────────────────────────────────────────────
        proposed_actions = _portfolio_svc.apply_ranked_opportunities(
            ranked_results=rankings,
            portfolio_state=portfolio_state,
        )

        # ── Deep-Dive Step 7: Shadow Portfolio — watch_tier hook ─────────────
        # For every ranked opportunity with composite_score in the configured
        # watch band [low, high] that the live portfolio did NOT act on (i.e.
        # not already in ``proposed_actions``), push a virtual BUY into the
        # ``watch_tier`` shadow.  Flag-gated — OFF is byte-for-byte legacy.
        if _shadow_enabled(cfg):
            try:
                _watch_low = float(getattr(cfg, "shadow_watch_composite_low", 0.55))
                _watch_high = float(getattr(cfg, "shadow_watch_composite_high", 0.65))
                _acted_tickers = {a.ticker for a in proposed_actions}
                from infra.db.session import db_session as _watch_db_session  # noqa: PLC0415

                with _watch_db_session() as _watch_db:
                    _wsvc = _shadow_service(_watch_db)
                    if _wsvc is not None:
                        for _ranked in (rankings or []):
                            _ticker = getattr(_ranked, "ticker", None) or getattr(
                                _ranked, "symbol", None
                            )
                            _cscore = float(
                                getattr(_ranked, "composite_score", None)
                                or getattr(_ranked, "score", 0.0)
                                or 0.0
                            )
                            if _ticker is None or _ticker in _acted_tickers:
                                continue
                            if not (_watch_low <= _cscore <= _watch_high):
                                continue
                            # Use per-position notional proxy = equity / 15 so
                            # watch-tier shadow sizing is roughly consistent
                            # with the live max_positions cap.
                            _watch_equity = (
                                float(portfolio_state.equity)
                                if portfolio_state.equity else 100000.0
                            )
                            _watch_notional = Decimal(str(_watch_equity / 15.0))
                            _watch_px = _fetch_price(
                                _ticker, _watch_notional, _market_data_svc, errors
                            )
                            _watch_shares = _shadow_shares_for_notional(
                                _watch_notional, _watch_px
                            )
                            if _watch_shares > Decimal("0") and _watch_px > Decimal("0"):
                                _wsvc.record_watch_tier(
                                    ticker=_ticker,
                                    shares=_watch_shares,
                                    price=_watch_px,
                                    composite_score=_cscore,
                                    executed_at=run_at,
                                )
            except Exception as _watch_exc:  # noqa: BLE001
                logger.warning(
                    "shadow_portfolio.watch_hook_failed",
                    error=str(_watch_exc),
                )

        # ── Phase 65: Suppress portfolio-engine CLOSEs for tickers that have
        # active rebalance targets.  The portfolio engine closes any position
        # whose ticker is NOT in ``buy_tickers`` (recommended_action == "buy"),
        # but the rebalancing engine independently wants to KEEP those positions
        # based on target-weight drift.  Without this filter the two systems
        # contradict each other: portfolio engine closes, rebalancer re-opens,
        # creating an alternating open/close churn every cycle.
        _reb_targets = _fresh_rebalance_targets(app_state, cfg)
        if _reb_targets:
            _before = len(proposed_actions)
            proposed_actions = [
                a for a in proposed_actions
                if not (
                    a.action_type == ActionType.CLOSE
                    and getattr(a, "reason", "") == "not_in_buy_set"
                    and a.ticker in _reb_targets
                )
            ]
            _suppressed = _before - len(proposed_actions)
            if _suppressed:
                logger.info(
                    "phase65_close_suppressed_rebalance_active",
                    suppressed_count=_suppressed,
                )

        # ── Deep-Dive Step 2 Rec 2: Action-conflict detector ─────────────────
        # Drop any opposing action pairs on the same ticker (OPEN vs CLOSE
        # today; extensible later) after portfolio + rebalancer merge.  The
        # higher-composite-score action wins; ties go to OPEN.  Flag-gated via
        # APIS_ACTION_CONFLICT_DETECTOR_ENABLED (default ON per DEC-034).
        if getattr(cfg, "action_conflict_detector_enabled", True):
            try:
                from services.action_orchestrator.invariants import (
                    resolve_action_conflicts as _resolve_conflicts,
                )

                def _conflict_alert(conflict: Any) -> None:
                    _alert_svc = getattr(app_state, "alert_service", None)
                    if _alert_svc is None:
                        return
                    try:
                        from services.alerting.models import (
                            AlertEvent,
                            AlertSeverity,
                        )
                        _alert_svc.send_alert(AlertEvent(
                            event_type="action_conflict_dropped",
                            severity=AlertSeverity.INFO.value,
                            title=(
                                f"APIS: Action conflict on {conflict.ticker} — "
                                f"kept {conflict.kept_action_type} (score "
                                f"{conflict.kept_score:.4f}), dropped "
                                f"{conflict.dropped_action_type} (score "
                                f"{conflict.dropped_score:.4f})"
                            ),
                            payload={
                                "ticker": conflict.ticker,
                                "kept_action_type": conflict.kept_action_type,
                                "kept_score": float(conflict.kept_score),
                                "dropped_action_type": conflict.dropped_action_type,
                                "dropped_score": float(conflict.dropped_score),
                                "resolution_reason": conflict.resolution_reason,
                                "cycle_id": cycle_id,
                            },
                        ))
                    except Exception:  # noqa: BLE001
                        pass

                _conflict_report = _resolve_conflicts(
                    proposed_actions,
                    settings=cfg,
                    alert_fn=_conflict_alert,
                )
                if _conflict_report.conflicts:
                    logger.warning(
                        "action_conflicts_resolved",
                        conflict_count=len(_conflict_report.conflicts),
                        cycle_id=cycle_id,
                    )
                proposed_actions = list(_conflict_report.resolved_actions)
            except Exception as _conflict_exc:  # noqa: BLE001
                logger.warning(
                    "action_conflict_detector_failed",
                    error=str(_conflict_exc),
                    cycle_id=cycle_id,
                )

        # ── Phase 39: Correlation-aware size adjustment ───────────────────────
        # Apply pairwise correlation penalty to OPEN actions before risk gating.
        # Highly correlated candidates receive reduced target_notional / quantity.
        try:
            from services.risk_engine.correlation import (
                CorrelationService as _CorrSvc,  # noqa: PLC0415
            )

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
            from services.risk_engine.sector_exposure import (
                SectorExposureService as _SectorSvc,  # noqa: PLC0415
            )

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

            # ── Sector rebalance trims: reduce overweight sectors back to limit ──
            # If a sector is ALREADY above max_sector_pct (from prior cycles),
            # generate TRIM actions for the largest positions in that sector.
            # These are pre-approved (risk_approved=True) like other trims.
            _closing_tickers = {
                a.ticker for a in proposed_actions if a.action_type == ActionType.CLOSE
            }
            _sector_trims = _SectorSvc.generate_sector_trim_actions(
                portfolio_state=portfolio_state,
                settings=cfg,
                already_closing=_closing_tickers,
            )
            if _sector_trims:
                for _st in _sector_trims:
                    proposed_actions.append(_st)
                    _closing_tickers.add(_st.ticker)
                logger.info("sector_rebalance_trims_added", count=len(_sector_trims))
        except Exception as _sect_exc:  # noqa: BLE001
            logger.error("sector_exposure_filter_failed", error=str(_sect_exc))
            # Fail-safe: drop all OPEN actions when filter crashes; CLOSE/TRIM pass through.
            proposed_actions = [a for a in proposed_actions if a.action_type != ActionType.OPEN]

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
            logger.error("liquidity_filter_failed", error=str(_liq_exc))
            # Fail-safe: drop all OPEN actions when filter crashes; CLOSE/TRIM pass through.
            proposed_actions = [a for a in proposed_actions if a.action_type != ActionType.OPEN]

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
            logger.error("var_gate_failed", error=str(_var_exc))
            # Fail-safe: drop all OPEN actions when VaR gate crashes; CLOSE/TRIM pass through.
            proposed_actions = [a for a in proposed_actions if a.action_type != ActionType.OPEN]

        # ── Phase 44: Portfolio stress test gate ─────────────────────────────
        # Block new OPEN actions when the worst-case historical-scenario stressed
        # loss exceeds max_stress_loss_pct.  CLOSE and TRIM always pass through.
        try:
            from services.risk_engine.stress_test import (
                StressTestService as _StressSvc,  # noqa: PLC0415
            )

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
            logger.error("stress_gate_failed", error=str(_stress_exc))
            # Fail-safe: drop all OPEN actions when stress gate crashes; CLOSE/TRIM pass through.
            proposed_actions = [a for a in proposed_actions if a.action_type != ActionType.OPEN]

        # ── Phase 45: Earnings proximity gate ─────────────────────────────────
        # Block new OPEN actions for tickers with earnings within the configured
        # proximity window (max_earnings_proximity_days).  Earnings are the
        # largest discontinuous risk events for equity positions; the system's
        # VaR and stop-loss models cannot protect against overnight earnings gaps.
        # CLOSE and TRIM actions always pass through.
        try:
            from services.risk_engine.earnings_calendar import (
                EarningsCalendarService as _EarnSvc,  # noqa: PLC0415
            )

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
        from services.risk_engine.drawdown_recovery import (  # noqa: PLC0415
            DrawdownRecoveryService as _DDSvc,
        )
        from services.risk_engine.drawdown_recovery import DrawdownState as _DDState

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
                app_state.drawdown_state_changed_at = dt.datetime.now(dt.UTC)
                _alert_svc_dd = getattr(app_state, "alert_service", None)
                if _alert_svc_dd:
                    try:
                        from services.alerting.models import (  # noqa: PLC0415
                            AlertEvent,
                            AlertSeverity,
                        )
                        _dd_severity = (
                            AlertSeverity.INFO.value
                            if new_state == "NORMAL"
                            else AlertSeverity.WARNING.value
                        )
                        _alert_svc_dd.send_alert(AlertEvent(
                            event_type="drawdown_state_change",
                            severity=_dd_severity,
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
            # (No state change — no update needed)

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
        # Refresh current prices for all held tickers so stop-loss calc is fresh.
        #
        # Phantom-equity writer fix (2026-04-22): previously we used
        # ``_fetch_price(ticker, Decimal("1000"), …)`` here, which on yfinance
        # failure would silently return the synthetic ``1000/100 = $10``
        # fallback and overwrite every held-ticker's real current_price.  That
        # collapsed gross_exposure and produced phantom portfolio snapshots
        # (equity ≈ cash + 0.25 × cost_basis) plus fake -90% stop-loss signals.
        # We now use the strict fetch and preserve the prior price on failure,
        # surfacing the staleness via ``mark_to_market_stale_price_preserved``.
        _mtm_stale: list[str] = []
        for ticker in list(portfolio_state.positions):
            fresh_price = _fetch_price_strict(ticker, _market_data_svc)
            if fresh_price is not None:
                portfolio_state.positions[ticker].current_price = fresh_price
            else:
                _prev = portfolio_state.positions[ticker].current_price
                _mtm_stale.append(ticker)
                logger.warning(
                    "mark_to_market_stale_price_preserved",
                    ticker=ticker,
                    preserved_price=str(_prev),
                )
        if _mtm_stale:
            logger.warning(
                "phantom_equity_guard_active",
                stale_tickers=_mtm_stale,
                stale_count=len(_mtm_stale),
                note="prior-close price preserved; investigate data provider",
            )
            errors.append(
                f"mtm_stale_prices: {len(_mtm_stale)} ticker(s) preserved prior-close"
            )

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
        # ── Phase 65b: Suppress non-critical exit CLOSEs for rebalance-protected
        # tickers.  Phase 65 already suppresses portfolio-engine "not_in_buy_set"
        # closes when a rebalance target exists, but exit-evaluation closes with
        # reasons like "score_decay_exit" or "max_position_age" bypassed that
        # filter.  The rebalance engine would then re-open the position next
        # cycle, creating every-other-cycle churn.  Critical risk exits
        # (stop_loss, trailing_stop, atr_stop) still fire unconditionally.
        _critical_exit_reasons = frozenset({
            "stop_loss", "trailing_stop", "atr_stop", "max_drawdown",
        })
        for exit_action in exit_actions:
            if exit_action.ticker in already_closing:
                continue
            _exit_reason = (getattr(exit_action, "reason", "") or "").lower()
            if (
                _reb_targets
                and exit_action.ticker in _reb_targets
                and not any(r in _exit_reason for r in _critical_exit_reasons)
            ):
                logger.info(
                    "phase65b_exit_suppressed_rebalance_protected",
                    ticker=exit_action.ticker,
                    reason=_exit_reason,
                )
                continue
            proposed_actions.append(exit_action)
            already_closing.add(exit_action.ticker)

        # ── Deep-Dive Step 7: Shadow Portfolio — stopped_out_continued hook
        # For every exit that fired on a stop reason (stop_loss, trailing_stop,
        # atr_stop, or max_position_age), virtually re-open the position at
        # the same price in the ``stopped_out_continued`` shadow.  Flag-gated.
        if _shadow_enabled(cfg):
            try:
                _stop_reasons = (
                    "stop_loss",
                    "trailing_stop",
                    "atr_stop",
                    "max_position_age",
                    "portfolio_fit_fail",
                )
                from infra.db.session import db_session as _so_db_session  # noqa: PLC0415

                with _so_db_session() as _so_db:
                    _sosvc = _shadow_service(_so_db)
                    if _sosvc is not None:
                        for _exit in exit_actions:
                            _reason = (getattr(_exit, "reason", "") or "").lower()
                            if not any(r in _reason for r in _stop_reasons):
                                continue
                            _pos = portfolio_state.positions.get(_exit.ticker)
                            if _pos is None:
                                continue
                            _px_so = getattr(_pos, "current_price", None) or getattr(
                                _pos, "avg_entry_price", None
                            )
                            _qty_so = getattr(_pos, "quantity", None)
                            if not (_px_so and _qty_so and _qty_so > 0):
                                continue
                            _sosvc.record_stopped_out_continued(
                                ticker=_exit.ticker,
                                shares=_qty_so,
                                price=_px_so,
                                stop_reason=_reason[:64] or "stop",
                                executed_at=run_at,
                            )
            except Exception as _so_exc:  # noqa: BLE001
                logger.warning(
                    "shadow_portfolio.stopped_out_hook_failed",
                    error=str(_so_exc),
                )

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
            from services.risk_engine.rebalancing import (
                RebalancingService as _RebSvc,  # noqa: PLC0415
            )

            _reb_targets = _fresh_rebalance_targets(app_state, cfg)
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

                # ── Anti-churn: cap OPEN target_notional to rebalance target ─────
                # When rebalance targets exist, portfolio-engine OPEN actions may be
                # sized at half-kelly (e.g. 14% of equity) while the rebalance target
                # is equal-weight (e.g. 6.67%).  The mismatch causes cycle-to-cycle
                # churn: OPEN at 14% → rebalance TRIM to 6.67% → OPEN again at 14%.
                # Fix: cap every OPEN's target_notional to the rebalance target weight
                # × equity, preventing oversizing relative to the rebalance plan.
                if _reb_targets:
                    _capped_count = 0
                    for _pa in proposed_actions:
                        if _pa.action_type != ActionType.OPEN:
                            continue
                        _tw = _reb_targets.get(_pa.ticker)
                        if _tw is None or _tw <= 0:
                            continue
                        _max_notional = Decimal(str(round(_tw * _reb_equity, 2)))
                        if _pa.target_notional > _max_notional:
                            logger.info(
                                "open_action_capped_to_rebalance_target",
                                ticker=_pa.ticker,
                                original_notional=str(_pa.target_notional),
                                capped_notional=str(_max_notional),
                                target_weight=round(_tw, 4),
                            )
                            _pa.target_notional = _max_notional
                            # Recalc target_quantity if price is available
                            if _pa.target_quantity is not None and _max_notional > 0:
                                _pos = portfolio_state.positions.get(_pa.ticker)
                                _px = getattr(_pos, "current_price", None) if _pos else None
                                if _px and float(_px) > 0:
                                    from decimal import ROUND_DOWN as _RD  # noqa: PLC0415
                                    _pa.target_quantity = (_max_notional / Decimal(str(_px))).quantize(
                                        Decimal("1"), rounding=_RD
                                    )
                            _capped_count += 1
                    if _capped_count:
                        logger.info("open_actions_capped_to_rebalance", count=_capped_count)

        except Exception as _reb_exc:  # noqa: BLE001
            logger.warning("rebalance_actions_failed", error=str(_reb_exc))

        # ── Deep-Dive Step 7 (DEC-034): Parallel rebalance-weighting shadows
        # Run the allocator three times in parallel (equal / score /
        # score_invvol) and push virtual BUYs into the matching
        # ``rebalance_*`` shadow.  Live portfolio still uses whatever
        # ``rebalance_weighting_method`` dictates; the shadows are purely A/B.
        if _shadow_enabled(cfg):
            try:
                from infra.db.session import db_session as _reb_shadow_db_session  # noqa: PLC0415
                from services.rebalancing_engine import (  # noqa: PLC0415
                    compute_weights as _compute_weights,
                )

                _modes = list(getattr(cfg, "shadow_rebalance_modes", []) or [])
                _reb_equity_s = (
                    float(portfolio_state.equity) if portfolio_state.equity else 0.0
                )
                _ranked_tickers = [
                    (getattr(r, "ticker", None) or getattr(r, "symbol", None))
                    for r in (rankings or [])
                ]
                _ranked_tickers = [t for t in _ranked_tickers if t]
                _n_pos = int(getattr(cfg, "max_positions", 15) or 15)
                _ranked_tickers = _ranked_tickers[: _n_pos]
                _scores_map = {
                    (getattr(r, "ticker", None) or getattr(r, "symbol", None)): float(
                        getattr(r, "composite_score", None)
                        or getattr(r, "score", 0.0)
                        or 0.0
                    )
                    for r in (rankings or [])
                }
                _vols_map = {
                    (getattr(r, "ticker", None) or getattr(r, "symbol", None)): float(
                        getattr(r, "realized_volatility", None)
                        or getattr(r, "volatility", 0.0)
                        or 0.0
                    )
                    for r in (rankings or [])
                }
                if _ranked_tickers and _reb_equity_s > 0:
                    with _reb_shadow_db_session() as _rdb:
                        _rsvc = _shadow_service(_rdb)
                        if _rsvc is not None:
                            for _mode in _modes:
                                _alloc = _compute_weights(
                                    ranked_tickers=_ranked_tickers,
                                    n_positions=len(_ranked_tickers),
                                    method=_mode,
                                    enabled=True,
                                    scores=_scores_map,
                                    volatilities=_vols_map,
                                    min_floor_fraction=float(
                                        getattr(cfg, "rebalance_min_floor_fraction", 0.10)
                                    ),
                                    max_single_weight=float(
                                        getattr(cfg, "rebalance_max_single_weight", 0.20)
                                    ),
                                )
                                for _t, _w in (_alloc.weights or {}).items():
                                    _notional = Decimal(str(_reb_equity_s * _w))
                                    _px_s = _fetch_price(
                                        _t, _notional, _market_data_svc, errors
                                    )
                                    _shares_s = _shadow_shares_for_notional(
                                        _notional, _px_s
                                    )
                                    if _shares_s > Decimal("0") and _px_s > Decimal("0"):
                                        _rsvc.record_rebalance_shadow(
                                            weighting_mode=_mode,
                                            ticker=_t,
                                            action="BUY",
                                            shares=_shares_s,
                                            price=_px_s,
                                            executed_at=run_at,
                                        )
            except Exception as _rshadow_exc:  # noqa: BLE001
                logger.warning(
                    "shadow_portfolio.rebalance_hook_failed",
                    error=str(_rshadow_exc),
                )

        # ── Phase 65b: Intra-cycle churn guard (safety net) ─────────────────
        # After ALL action sources (portfolio engine, exit evaluation,
        # rebalance, risk filters) have assembled proposed_actions, remove
        # any CLOSE for a ticker that also has an OPEN in the same batch.
        # The OPEN takes precedence — closing a position the system is
        # simultaneously opening is always waste.  This is the final
        # safety net; the upstream Phase 65 / Phase 65b exit-suppression
        # should prevent most cases, but edge-case interactions between
        # subsystems can still produce same-ticker OPEN+CLOSE pairs.
        _open_tickers_this_cycle = {
            a.ticker for a in proposed_actions if a.action_type == ActionType.OPEN
        }
        _close_tickers_this_cycle = {
            a.ticker
            for a in proposed_actions
            if a.action_type == ActionType.CLOSE
        }
        _churn_tickers = _open_tickers_this_cycle & _close_tickers_this_cycle
        if _churn_tickers:
            proposed_actions = [
                a for a in proposed_actions
                if not (
                    a.action_type == ActionType.CLOSE
                    and a.ticker in _churn_tickers
                )
            ]
            logger.warning(
                "phase65b_intra_cycle_churn_suppressed",
                suppressed_count=len(_churn_tickers),
                tickers=sorted(_churn_tickers),
            )

        # ── Validate each action + fetch price + build execution requests ──────
        approved_requests: list[ExecutionRequest] = []
        fill_expectations: list[FillExpectation] = []
        # Phase 70: track approved OPENs within THIS validation loop so the
        # risk engine's daily_position_cap check sees an up-to-date count.
        # Previously, daily_opens_count was only incremented AFTER execution
        # (Phase 69), so within a single cycle ALL OPENs passed the cap check
        # because the counter stayed at its pre-execution value.  This is why
        # 19 positions opened on 2026-04-29 despite a cap of 5.
        _pre_validation_opens = portfolio_state.daily_opens_count

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
                # ── Deep-Dive Step 7: Shadow Portfolio — rejected_actions hook
                # Push a virtual BUY into the ``rejected_actions`` shadow so
                # the weekly assessment can compare its P&L against the live
                # portfolio.  Flag-gated — OFF is byte-for-byte legacy.
                if _shadow_enabled(cfg) and action.action_type == ActionType.OPEN:
                    try:
                        from infra.db.session import (
                            db_session as _shadow_db_session,  # noqa: PLC0415
                        )

                        with _shadow_db_session() as _shadow_db:
                            _svc = _shadow_service(_shadow_db)
                            if _svc is not None:
                                _px = _fetch_price(
                                    action.ticker,
                                    action.target_notional,
                                    _market_data_svc,
                                    errors,
                                )
                                _shares = _shadow_shares_for_notional(
                                    action.target_notional, _px
                                )
                                if _shares > Decimal("0") and _px > Decimal("0"):
                                    _reason = ",".join(
                                        v.rule_name for v in risk_result.violations
                                    )[:64] or "risk_gate"
                                    _svc.record_rejected_action(
                                        ticker=action.ticker,
                                        shares=_shares,
                                        price=_px,
                                        rejection_reason=_reason,
                                        executed_at=run_at,
                                    )
                    except Exception as _shadow_exc:  # noqa: BLE001
                        logger.warning(
                            "shadow_portfolio.rejected_hook_failed",
                            ticker=action.ticker,
                            error=str(_shadow_exc),
                        )
                continue

            # Phase 70: increment daily_opens_count at approval time (not
            # after execution) so subsequent OPENs in the same batch see
            # an accurate counter and the daily cap works within a single cycle.
            if action.action_type == ActionType.OPEN:
                portfolio_state.daily_opens_count += 1

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

        # ── Phase 69 / Phase 70: Reconcile daily_opens_count after execution.
        # Phase 70 now increments daily_opens_count at APPROVAL time (inside
        # the risk-validation loop) so the cap works within a single cycle.
        # Here we reconcile: if some approved OPENs were rejected/blocked by
        # the broker, subtract them back so the counter reflects ACTUAL fills.
        _approved_opens = sum(
            1 for r in execution_results
            if r.action.action_type == ActionType.OPEN
        )
        _filled_opens = sum(
            1 for r in execution_results
            if r.status.value == "filled" and r.action.action_type == ActionType.OPEN
        )
        _rejected_opens = _approved_opens - _filled_opens
        if _rejected_opens > 0:
            portfolio_state.daily_opens_count -= _rejected_opens
            logger.info(
                "phase70_daily_opens_reconciled",
                rejected_opens=_rejected_opens,
                daily_opens_count=portfolio_state.daily_opens_count,
            )
        if _filled_opens > 0:
            logger.info(
                "phase69_daily_opens_incremented",
                filled_opens=_filled_opens,
                daily_opens_count=portfolio_state.daily_opens_count,
                limit=cfg.max_new_positions_per_day,
            )

        # ── Persist orders + fills ledger (2026-04-22 latent-bug fix) ─────────
        # Prior to this patch, the ``orders`` and ``fills`` tables contained
        # zero rows despite hundreds of executions — there was no production
        # code path writing them.  That left the system with no queryable
        # audit trail and no per-order basis for P&L attribution.  Mirrors the
        # Phase 64 ``_persist_positions`` contract: fire-and-forget, failures
        # logged at WARN, idempotency keyed on ``{cycle_id}:{ticker}:{side}``.
        _persist_orders_and_fills(
            approved_requests,
            execution_results,
            run_at,
            cycle_id=cycle_id,
        )

        # ── Phase 52: Capture fill quality records ────────────────────────────
        # Append one FillQualityRecord per filled order to app_state so the
        # evening run_fill_quality_update job can compute slippage aggregates.
        try:
            from services.execution_engine.models import ExecutionStatus as _FQExecStatus
            from services.fill_quality.service import FillQualityService as _FQSvc
            from services.portfolio_engine.models import ActionType as _FQActionType

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
                    _opened = _opened.replace(tzinfo=dt.UTC)
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
            errors.append(f"trade_grading: {_grade_exc}")

        # ── Deep-Dive Step 8 (Rec 12): Thompson bandit posterior update ─────
        # Per plan §8.6 this runs UNCONDITIONALLY — even when the flag is OFF
        # — so posteriors accumulate 2–4 weeks of live outcome data and the
        # operator gets a warm start when they eventually flip the flag ON.
        # Strategy-family is resolved via the security_id → strategy_key map
        # captured at OPEN time; if we can't resolve it we skip that trade.
        try:
            from services.strategy_bandit import StrategyBanditService  # type: ignore
            _newly_closed_for_bandit = getattr(app_state, "closed_trades", [])[_pre_record_count:]
            if _newly_closed_for_bandit:
                try:
                    from infra.db.session import SessionLocal as _SL_bandit
                except Exception:  # noqa: BLE001
                    _SL_bandit = None  # type: ignore
                if _SL_bandit is not None:
                    _strat_key_by_ticker = getattr(app_state, "strategy_key_by_ticker", {}) or {}
                    with _SL_bandit() as _db_bandit:
                        _bandit = StrategyBanditService(
                            _db_bandit,
                            smoothing_lambda=cfg.strategy_bandit_smoothing_lambda,
                            min_weight=cfg.strategy_bandit_min_weight,
                            max_weight=cfg.strategy_bandit_max_weight,
                            resample_every_n_cycles=cfg.strategy_bandit_resample_every_n_cycles,
                        )
                        for _ct in _newly_closed_for_bandit:
                            _family = (
                                getattr(_ct, "strategy_family", None)
                                or _strat_key_by_ticker.get(getattr(_ct, "ticker", ""))
                                or getattr(_ct, "strategy_key", None)
                            )
                            if not _family:
                                continue
                            try:
                                _bandit.update_from_trade(
                                    strategy_family=_family,
                                    realized_pnl=float(getattr(_ct, "realized_pnl", 0) or 0),
                                )
                            except Exception as _bu_exc:  # noqa: BLE001
                                logger.warning(
                                    "strategy_bandit_update_failed",
                                    family=_family,
                                    error=str(_bu_exc),
                                )
                        _db_bandit.commit()
        except Exception as _bandit_exc:  # noqa: BLE001
            # Never let the bandit break the paper cycle.
            logger.warning("strategy_bandit_hook_failed", error=str(_bandit_exc))

        # ── Sync portfolio state from broker ───────────────────────────────────
        try:
            acct = _broker.get_account_state()
            # Phase 70: log if broker cash is negative — should be impossible
            # after the lock + invariant fixes, but keep the diagnostic.
            if acct.cash_balance < Decimal("0"):
                logger.critical(
                    "phase70_broker_cash_negative_at_sync",
                    broker_cash=str(acct.cash_balance),
                    broker_equity=str(acct.equity_value),
                    broker_positions=len(acct.positions),
                    note="broker._cash went negative despite invariant guard",
                )
            portfolio_state.cash = acct.cash_balance
            broker_positions = _broker.list_positions()
            for bp in broker_positions:
                if bp.ticker in portfolio_state.positions:
                    portfolio_state.positions[bp.ticker].quantity = bp.quantity
                    portfolio_state.positions[bp.ticker].current_price = bp.current_price
                    # Phase 72: stamp origin_strategy on restored positions
                    # that were loaded from DB without one (Phase 59 restore
                    # previously omitted this field).  Same fallback chain as
                    # the new-position branch below.
                    _existing_os = getattr(
                        portfolio_state.positions[bp.ticker],
                        "origin_strategy", None,
                    ) or ""
                    if not _existing_os:
                        _os_fill = _origin_strategy_by_ticker.get(bp.ticker, "")
                        if not _os_fill:
                            _ranked_set = {
                                getattr(r, "ticker", None) for r in rankings
                            }
                            if _reb_targets and bp.ticker in _reb_targets:
                                _os_fill = "rebalance"
                            elif bp.ticker in _ranked_set:
                                _os_fill = "ranking_buy_signal"
                            else:
                                _os_fill = "unknown"
                        portfolio_state.positions[bp.ticker].origin_strategy = _os_fill
                else:
                    # Add new positions opened by the broker (e.g. via execution
                    # engine) that don't yet exist in portfolio_state.  Without
                    # this, cash is debited but gross_exposure stays 0, producing
                    # negative equity and blocking future OPEN actions.
                    from services.portfolio_engine.models import PortfolioPosition
                    # Phase 65b: robust origin_strategy fallback.
                    # Prefer the signal-derived key; fall back to "rebalance"
                    # for rebalance-opened positions, or "ranking_buy_signal"
                    # for tickers present in rankings, so the DB never gets NULL.
                    _os_value = _origin_strategy_by_ticker.get(bp.ticker, "")
                    if not _os_value:
                        _ranked_ticker_set = {
                            getattr(r, "ticker", None) for r in rankings
                        }
                        if _reb_targets and bp.ticker in _reb_targets:
                            _os_value = "rebalance"
                        elif bp.ticker in _ranked_ticker_set:
                            _os_value = "ranking_buy_signal"
                        else:
                            _os_value = "unknown"
                    portfolio_state.positions[bp.ticker] = PortfolioPosition(
                        ticker=bp.ticker,
                        quantity=bp.quantity,
                        avg_entry_price=getattr(bp, "average_entry_price", bp.current_price),
                        current_price=bp.current_price,
                        opened_at=run_at,
                        thesis_summary="",
                        strategy_key="",
                        security_id=None,
                        # Deep-Dive Step 5 Rec 7 deferred finisher (2026-04-18):
                        # bind the origin strategy family on first observation
                        # so the ATR exit evaluator and per-family max-age can
                        # key off it once APIS_ATR_STOPS_ENABLED flips ON.
                        origin_strategy=_os_value,
                    )
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
        reconciliation_clean: bool | None = None
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

        # Remove actions that were sent for execution (filled, rejected, blocked,
        # or errored) so they don't linger in proposed_actions forever.
        _executed_tickers = {
            req.action.ticker for req in approved_requests
        }
        app_state.proposed_actions = [
            a for a in proposed_actions if a.ticker not in _executed_tickers
        ]
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
        # Deep-Dive Step 2 Rec 4: pass cycle_id so the insert is idempotent on
        # retry of the same cycle.
        if app_state.portfolio_state is not None:
            _persist_portfolio_snapshot(
                app_state.portfolio_state,
                cfg.operating_mode.value,
                cycle_id=cycle_id,
            )

        # Persist per-position P&L snapshots to DB (fire-and-forget, Phase 32)
        # Deep-Dive Step 2 Rec 4: per-ticker idempotency key keyed on cycle_id.
        if app_state.portfolio_state is not None and app_state.portfolio_state.positions:
            _persist_position_history(
                app_state.portfolio_state,
                run_at,
                cycle_id=cycle_id,
            )

        # Persist authoritative Position rows (fire-and-forget, Phase 64)
        # Root fix for phantom-broker-positions bug: ensures the restore path
        # in _load_persisted_state() finds matching position rows instead of
        # phantom negative cash.
        if app_state.portfolio_state is not None:
            _newly_closed_this_cycle = getattr(app_state, "closed_trades", [])[_pre_record_count:]
            _persist_positions(
                app_state.portfolio_state,
                _newly_closed_this_cycle,
                run_at,
            )

        # ── Phase 50: Factor Exposure Monitoring ──────────────────────────────
        # Compute portfolio factor exposure (MOMENTUM / VALUE / GROWTH / QUALITY /
        # LOW_VOL) using data already in app_state — no new DB write.
        # Volatility data is queried read-only from the feature store; failure
        # degrades gracefully to 0.5 neutral LOW_VOL scores.
        try:
            from services.risk_engine.factor_exposure import (
                FactorExposureService as _FactorSvc,  # noqa: PLC0415
            )

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

                    from infra.db.models import Security as _Sec  # noqa: PLC0415
                    from infra.db.models.analytics import Feature as _Feat  # noqa: PLC0415
                    from infra.db.models.analytics import SecurityFeatureValue as _SFV
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
                from services.factor_alerts.service import (
                    FactorTiltAlertService as _FTASvc,  # noqa: PLC0415
                )
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
                            from services.alerting.models import (  # noqa: PLC0415
                                AlertEvent,
                                AlertSeverity,
                            )
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


def _fetch_price_strict(
    ticker: str,
    market_data_svc: Any,
) -> Decimal | None:
    """Fetch latest price for *ticker* — returns ``None`` on any failure.

    Strict variant for mark-to-market paths where ``_fetch_price``'s
    synthetic ``target_notional / 100`` fallback would corrupt
    ``gross_exposure`` and produce phantom portfolio snapshots.  Caller
    is expected to preserve the prior ``current_price`` when ``None`` is
    returned and log a WARN so the staleness is observable.

    Phantom-equity writer fix (2026-04-22):
    yfinance DNS failures on current holdings silently caused the
    mark-to-market loop to overwrite real prices with ``$10/share``
    (``target_notional=1000 → 1000/100 = 10``).  That produced
    ``equity ≈ cash + 0.25 × cost_basis`` snapshots, and with a
    simultaneously-weak daily_loss_limit gate could have executed fake
    stop-losses on all holdings.
    """
    try:
        snapshot = market_data_svc.get_snapshot(ticker)
        price = snapshot.latest_price
        if price and price > Decimal("0"):
            return Decimal(str(price))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "price_fetch_strict_failed",
            ticker=ticker,
            error=str(exc),
        )
    return None
