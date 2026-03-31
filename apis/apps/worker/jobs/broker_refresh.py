"""
Worker job: broker OAuth token auto-refresh.

``run_broker_token_refresh``
    Attempts to silently refresh the broker's access token.  Called once
    daily at 05:30 ET before market-data ingestion starts (06:00 ET).

    Flow
    ----
    1. Obtain the broker adapter from ``app_state.broker_adapter``.
       If no adapter is configured, skip silently.
    2. If the adapter is not a ``SchwabBrokerAdapter``, skip.
       Other adapters (IBKR, Paper, Alpaca) manage their own auth lifecycle.
    3. Call ``broker.refresh_auth()``.
       - ``BrokerAuthenticationError`` ← refresh token expired or token file
         missing.  Sets ``app_state.broker_auth_expired = True`` so /health
         and /metrics surface the degraded state before the market opens.
       - Any other exception        ← transient network hiccup.  Logged at
         WARNING, no state change.  The next daily refresh attempt will retry.
    4. On success, clears ``app_state.broker_auth_expired`` if it was set.

Design rules
------------
- The job NEVER raises: all exceptions are caught so the scheduler thread
  cannot die due to an auth failure.
- ``app_state.broker_auth_expired = True`` is the sole handshake with the
  API layer — the paper trading cycle already respects this flag and returns
  ``status="error_broker_auth"`` rather than trying (and silently failing)
  to place orders.

Spec references
---------------
- APIS_MASTER_SPEC.md § 3.1 (safety rollout: paper before live)
- Priority 17 — Broker Auth Expiry Detection (flag introduced)
- Priority 18 — Token Auto-Refresh (this file)
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from apps.api.state import ApiAppState
from config.logging_config import get_logger
from config.settings import Settings

logger = get_logger(__name__)


def run_broker_token_refresh(
    app_state: ApiAppState,
    settings: Settings | None = None,  # reserved for future use
    broker: Any | None = None,         # injected in tests; else from app_state
) -> dict[str, Any]:
    """Attempt to refresh the Schwab OAuth token.

    Returns a result dict with one of the following ``status`` values:

    * ``"ok"``           — Token refreshed successfully.
    * ``"skipped"``      — No broker configured or not a Schwab adapter.
    * ``"error_auth"``   — OAuth refresh token expired; manual re-auth needed.
    * ``"error_other"``  — Unexpected error; will retry on next cycle.
    """
    _broker = broker if broker is not None else app_state.broker_adapter

    if _broker is None:
        logger.info("broker_token_refresh: no broker configured; skipped")
        return {"status": "skipped", "reason": "no_broker"}

    # Lazy import to avoid hard dependency on schwab-py everywhere
    try:
        from broker_adapters.schwab.adapter import SchwabBrokerAdapter
        is_schwab = isinstance(_broker, SchwabBrokerAdapter)
    except ImportError:
        is_schwab = False

    if not is_schwab:
        adapter_name = getattr(_broker, "adapter_name", type(_broker).__name__)
        logger.info(
            "broker_token_refresh: skipped (adapter does not need OAuth refresh)",
            extra={"adapter": adapter_name},
        )
        return {"status": "skipped", "reason": "not_schwab", "adapter": adapter_name}

    # ── Attempt refresh ───────────────────────────────────────────────────────
    try:
        _broker.refresh_auth()

        # Clear any stale expiry flag left from a previous failed refresh
        if app_state.broker_auth_expired:
            logger.info(
                "broker_token_refresh: cleared stale broker_auth_expired flag "
                "after successful refresh"
            )
            app_state.broker_auth_expired = False
            app_state.broker_auth_expired_at = None

        logger.info("broker_token_refresh: ok")
        return {"status": "ok"}

    except Exception as exc:  # noqa: BLE001
        # Import here to avoid circular-import risk at job-load time
        from broker_adapters.base.exceptions import BrokerAuthenticationError

        if isinstance(exc, BrokerAuthenticationError):
            logger.critical(
                "broker_token_refresh: refresh token expired — "
                "manual browser re-auth required before next market open",
                extra={"error": str(exc)},
            )
            app_state.broker_auth_expired = True
            app_state.broker_auth_expired_at = dt.datetime.now(dt.UTC)
            return {"status": "error_auth", "error": str(exc)}

        logger.warning(
            "broker_token_refresh: unexpected error; will retry next cycle",
            extra={"error": str(exc)},
        )
        return {"status": "error_other", "error": str(exc)}
