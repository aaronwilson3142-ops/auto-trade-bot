"""Broker-adapter health invariant (Deep-Dive Plan Step 2, Rec 2).

Runs at the top of every paper-trading cycle to catch silent adapter loss.

Failure mode history
--------------------
Phase 64/65 uncovered that a crash mid-cycle could zero-out
``ApiAppState.broker_adapter`` while DB-persisted positions still carried
dollar value.  Without a pre-flight check the next cycle would build a
fresh ``PaperBrokerAdapter`` (cash-only, zero positions), immediately read
a *negative* cash figure from the phantom-position restore path, and then
submit a flurry of new orders to "rebuild" the book -- a textbook
catastrophic-reset scenario.

Invariant
---------
1. **Adapter present when positions exist.**
   If the DB reports any ``Position.status='open'`` rows and
   ``app_state.broker_adapter is None``, fire the kill switch and raise
   ``BrokerAdapterHealthError``.  No orders can be submitted in this
   cycle.  Operator must investigate before re-enabling.

2. **Position-count drift between broker and DB.**
   If both are present but disagree on a ticker's quantity beyond
   ``broker_health_position_drift_tolerance`` shares, emit a WARNING alert
   and proceed with the DB as source of truth.  This is non-fatal --
   tolerating drift is the lesser evil than blocking trading on every
   transient reconciliation window.

Feature flag
------------
``APIS_BROKER_HEALTH_INVARIANT_ENABLED`` (default ON).  If False, the
entry-point becomes a no-op.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from config.logging_config import get_logger

logger = get_logger(__name__)


class BrokerAdapterHealthError(RuntimeError):
    """Raised when the broker adapter is missing while live positions exist.

    The paper-trading cycle catches this, flips the kill switch, and
    returns an error status dict instead of submitting any orders.
    """


@dataclass
class HealthResult:
    """Outcome of a broker-adapter health check.

    Attributes
    ----------
    ok:
        True if no fatal invariant was violated.  Non-fatal drift still
        produces ``ok=True`` but populates ``drift_tickers``.
    adapter_present:
        Whether ``app_state.broker_adapter`` was non-None.
    db_position_count:
        Number of open Position rows the DB reported.
    drift_tickers:
        Tickers whose broker and DB quantities disagreed by more than
        the configured tolerance.  Non-fatal; DB wins.
    reason:
        Short machine-readable reason code; None when ok.
    """

    ok: bool
    adapter_present: bool
    db_position_count: int
    drift_tickers: list[str] = field(default_factory=list)
    reason: str | None = None


def _count_db_open_positions(db_session_factory: Any) -> int:
    """Return count of ``Position.status='open'`` rows.

    Never raises -- returns 0 on any DB error and logs a warning.  A DB
    error during health-check should NOT block trading; the whole point
    of the invariant is to guard against adapter loss, not DB outages.
    """
    try:
        from sqlalchemy import func, select

        from infra.db.models.portfolio import Position

        with db_session_factory() as db:
            count = db.execute(
                select(func.count()).select_from(Position).where(
                    Position.status == "open"
                )
            ).scalar_one_or_none()
            return int(count or 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("broker_health_db_query_failed", error=str(exc))
        return 0


def _db_positions_by_ticker(db_session_factory: Any) -> dict[str, Decimal]:
    """Return {ticker: quantity} for open DB positions.

    Never raises -- returns {} on any DB error.
    """
    try:
        from sqlalchemy import select

        from infra.db.models.portfolio import Position
        from infra.db.models.reference import Security

        out: dict[str, Decimal] = {}
        with db_session_factory() as db:
            rows = db.execute(
                select(Security.ticker, Position.quantity)
                .join(Security, Security.id == Position.security_id)
                .where(Position.status == "open")
            ).all()
            for ticker, qty in rows:
                if ticker and qty is not None:
                    out[ticker] = Decimal(str(qty))
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("broker_health_db_ticker_query_failed", error=str(exc))
        return {}


def check_broker_adapter_health(
    app_state: Any,
    settings: Any,
    db_session_factory: Any | None = None,
    fire_kill_switch_fn: Any | None = None,
) -> HealthResult:
    """Run the broker-adapter health invariant.

    Called at the top of ``run_paper_trading_cycle``.  Short-circuits
    immediately if ``settings.broker_health_invariant_enabled`` is False.

    Parameters
    ----------
    app_state:
        The ApiAppState.  Read ``broker_adapter`` from it.
    settings:
        Settings instance.  Reads ``broker_health_invariant_enabled`` and
        ``broker_health_position_drift_tolerance``.
    db_session_factory:
        Callable returning a context-managed SQLAlchemy session.
        Defaults to ``infra.db.session.db_session``.
    fire_kill_switch_fn:
        Callable invoked with a reason string when the adapter-missing
        invariant fires.  Defaults to setting
        ``app_state.kill_switch_active = True``.

    Returns
    -------
    HealthResult
        Structured outcome.  Callers should check ``.ok`` before proceeding.
        On fatal violation the function *also* raises BrokerAdapterHealthError
        so mis-handling of the result still results in a hard stop.
    """
    if not getattr(settings, "broker_health_invariant_enabled", True):
        return HealthResult(
            ok=True,
            adapter_present=getattr(app_state, "broker_adapter", None) is not None,
            db_position_count=0,
            reason="disabled",
        )

    if db_session_factory is None:
        from infra.db.session import db_session as _db_session
        db_session_factory = _db_session

    adapter = getattr(app_state, "broker_adapter", None)
    adapter_present = adapter is not None

    # ── Invariant 1: adapter missing with live positions ────────────────
    db_count = _count_db_open_positions(db_session_factory)
    if not adapter_present and db_count > 0:
        reason = "broker_adapter_missing_with_live_positions"
        logger.critical(
            "broker_health_invariant_fired",
            reason=reason,
            db_position_count=db_count,
        )
        if fire_kill_switch_fn is None:
            # Default: flip runtime kill-switch on app_state.
            try:
                app_state.kill_switch_active = True
            except Exception:  # noqa: BLE001
                pass
        else:
            try:
                fire_kill_switch_fn(reason)
            except Exception as exc:  # noqa: BLE001
                logger.error("broker_health_kill_switch_fn_failed", error=str(exc))
        raise BrokerAdapterHealthError(reason)

    # ── Invariant 2: position-count drift (non-fatal) ───────────────────
    drift_tickers: list[str] = []
    if adapter_present and db_count > 0:
        tolerance = Decimal(str(
            getattr(settings, "broker_health_position_drift_tolerance", 0.01)
        ))
        db_positions = _db_positions_by_ticker(db_session_factory)
        try:
            broker_positions = getattr(adapter, "positions_by_ticker", {}) or {}
            if callable(broker_positions):
                broker_positions = broker_positions()
        except Exception as exc:  # noqa: BLE001
            logger.warning("broker_health_broker_position_read_failed", error=str(exc))
            broker_positions = {}

        all_tickers = set(db_positions) | set(broker_positions)
        for ticker in all_tickers:
            db_qty = db_positions.get(ticker, Decimal("0"))
            raw_broker = broker_positions.get(ticker, 0) or 0
            # broker may return Position objects or raw qty; attempt both
            try:
                broker_qty = Decimal(str(
                    getattr(raw_broker, "quantity", raw_broker)
                ))
            except Exception:  # noqa: BLE001
                broker_qty = Decimal("0")
            if abs(db_qty - broker_qty) > tolerance:
                drift_tickers.append(ticker)

        if drift_tickers:
            logger.warning(
                "broker_health_position_drift",
                tickers=drift_tickers,
                tolerance=str(tolerance),
            )

    return HealthResult(
        ok=True,
        adapter_present=adapter_present,
        db_position_count=db_count,
        drift_tickers=drift_tickers,
        reason=None,
    )
