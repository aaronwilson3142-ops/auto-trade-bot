"""
Admin route handlers for internal operations.

Endpoints
---------
  POST /api/v1/admin/invalidate-secrets
      Instructs APIS to clear the in-memory secrets cache so that the next
      call to ``SecretManager.get()`` re-fetches values from AWS Secrets
      Manager.  Intended to be called by the AWS Secrets Manager rotation
      Lambda immediately after secret rotation completes.

  GET /api/v1/admin/events
      Returns the most recent admin audit log entries from the database.
      Requires the same bearer token as the POST endpoint.

Security
--------
  Both endpoints require an ``Authorization: Bearer <token>`` header whose
  value must match the ``APIS_ADMIN_ROTATION_TOKEN`` environment variable.
  If the variable is empty or unset the endpoint returns 503 (disabled) so
  that accidental exposure of an unprotected admin surface is impossible.

  The token is compared using ``hmac.compare_digest`` to prevent
  timing-based side-channel attacks.

  This endpoint must NOT be exposed on a public-facing network path without
  an additional layer of access control (e.g. VPC-internal ALB, NGINX
  allow-list, or API Gateway resource policy).

AWS rotation Lambda integration
--------------------------------
  In your AWS Secrets Manager rotation function, after the rotation steps
  complete, POST to this endpoint:

      import requests
      requests.post(
          "https://your-apis-internal-host/api/v1/admin/invalidate-secrets",
          headers={"Authorization": f"Bearer {rotation_token}"},
          json={"secret_name": "apis/production/secrets"},
          timeout=10,
      )

  A ``secret_name`` body key is accepted but currently informational only —
  APIS holds a single global ``AWSSecretManager`` whose cache is cleared
  regardless of which secret name is sent.

Audit log
---------
  Every call to any admin endpoint is written to the ``admin_events`` DB
  table (Priority 17).  The write is fire-and-forget: if the DB is
  unavailable the primary HTTP response is still returned; the DB error is
  only logged at WARNING level.

Spec references
---------------
- APIS_MASTER_SPEC.md §3.4  — Auditability (rotation events logged)
- 04_APIS_BUILD_RUNBOOK.md §3 — Config and environment strategy
- Priority 16 — AWS Secrets rotation hook
- Priority 17 — Admin Audit Log
"""
from __future__ import annotations

import collections
import datetime as _dt
import hmac
import logging
import time
from threading import Lock
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel

from apps.api.deps import AppStateDep, SettingsDep
from config.settings import Environment

logger = logging.getLogger(__name__)

# ── In-process rate limiter ───────────────────────────────────────────────────
# Sliding-window: max 20 requests per 60 s per source IP.
# Uses a monotonic clock, so clock skew and DST changes have no effect.
_RATE_LIMIT_MAX: int = 20
_RATE_LIMIT_WINDOW_S: int = 60
_rate_limit_lock: Lock = Lock()
_rate_limit_store: dict[str, collections.deque] = {}


def _check_rate_limit(ip: Optional[str]) -> None:
    """Raise HTTP 429 when the IP has exceeded the admin rate limit.

    The ``Retry-After`` header tells the caller how many seconds to wait.
    """
    key = ip or "unknown"
    now = time.monotonic()
    with _rate_limit_lock:
        if key not in _rate_limit_store:
            _rate_limit_store[key] = collections.deque()
        dq = _rate_limit_store[key]
        cutoff = now - _RATE_LIMIT_WINDOW_S
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= _RATE_LIMIT_MAX:
            retry_after = int(_RATE_LIMIT_WINDOW_S - (now - dq[0])) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded on admin endpoint. Retry after {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )
        dq.append(now)

router = APIRouter(tags=["Admin"])


# ── Request / Response schemas ────────────────────────────────────────────────

class InvalidateSecretsRequest(BaseModel):
    """Optional request body for the invalidate-secrets endpoint.

    ``secret_name`` is informational — the caller may specify which secret
    was rotated, but APIS clears its entire in-memory cache regardless.
    """

    secret_name: str = ""


class InvalidateSecretsResponse(BaseModel):
    status: str          # "ok" | "skipped_env_backend"
    message: str
    secret_backend: str  # "aws" | "env"


class AdminEventResponse(BaseModel):
    """Single admin audit log entry returned by GET /admin/events."""

    id: str
    event_timestamp: str
    event_type: str
    result: str
    source_ip: Optional[str] = None
    secret_name: Optional[str] = None
    secret_backend: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _token_matches(expected: str, provided: str) -> bool:
    """Constant-time comparison to prevent timing side-channel attacks."""
    return hmac.compare_digest(
        expected.encode("utf-8"),
        provided.encode("utf-8"),
    )


def _extract_bearer(authorization: str | None) -> str:
    """Parse ``Authorization: Bearer <token>`` header value."""
    if not authorization:
        return ""
    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ""
    return parts[1].strip()


def _get_client_ip(request: Request) -> Optional[str]:
    """Extract client IP from X-Forwarded-For header or direct connection."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _log_admin_event(
    event_type: str,
    result: str,
    source_ip: Optional[str] = None,
    secret_name: Optional[str] = None,
    secret_backend: Optional[str] = None,
    details: Optional[dict] = None,
) -> None:
    """Write an admin audit event to the database.

    Fire-and-forget: DB write failures are logged at WARNING level but never
    re-raised so that a DB hiccup does not block the HTTP response.
    """
    try:
        from infra.db.models.audit import AdminEvent
        from infra.db.session import db_session as _db_session

        with _db_session() as db:
            event = AdminEvent(
                event_timestamp=_dt.datetime.now(_dt.timezone.utc),
                event_type=event_type,
                result=result,
                source_ip=source_ip,
                secret_name=secret_name or None,
                secret_backend=secret_backend or None,
                details_json=details or None,
            )
            db.add(event)
    except Exception as exc:  # noqa: BLE001
        logger.warning("admin_event_log_failed", exc_info=False, extra={"error": str(exc)})


def _require_auth(cfg: SettingsDep) -> str:
    """Return the configured token or raise 503/401 appropriately.

    Raises HTTPException(503) when the feature is disabled (empty token).
    Returns the expected token string for the caller to use.
    """
    token_expected = cfg.admin_rotation_token if cfg else ""
    if not token_expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Admin endpoints are disabled.  "
                "Set APIS_ADMIN_ROTATION_TOKEN to enable."
            ),
        )
    return token_expected


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post(
    "/admin/invalidate-secrets",
    response_model=InvalidateSecretsResponse,
    status_code=status.HTTP_200_OK,
    summary="Invalidate in-memory secrets cache",
    description=(
        "Clears the AWSSecretManager in-memory cache so the next "
        "get() call re-fetches from AWS Secrets Manager.  "
        "Requires Authorization: Bearer <APIS_ADMIN_ROTATION_TOKEN>."
    ),
)
def invalidate_secrets(
    request: Request,
    body: InvalidateSecretsRequest = InvalidateSecretsRequest(),
    authorization: str | None = Header(default=None),
    cfg: SettingsDep = None,  # type: ignore[assignment]
) -> InvalidateSecretsResponse:
    """AWS Secrets Manager rotation hook — clears in-memory secrets cache.

    Called by the rotation Lambda after secret rotation completes.
    Returns 503 when the feature is disabled (token not configured).
    Returns 401 when the bearer token does not match.
    Returns 200 with status="ok" when the cache is cleared.
    Returns 200 with status="skipped_env_backend" when running with
    EnvSecretManager (no cache to clear).
    """
    source_ip = _get_client_ip(request)
    _check_rate_limit(source_ip)

    # ── Feature guard ──────────────────────────────────────────────────────────
    token_expected = cfg.admin_rotation_token if cfg else ""
    if not token_expected:
        _log_admin_event("invalidate_secrets", "disabled", source_ip=source_ip)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Secrets invalidation endpoint is disabled.  "
                "Set APIS_ADMIN_ROTATION_TOKEN to enable."
            ),
        )

    # ── Authentication ─────────────────────────────────────────────────────────
    provided_token = _extract_bearer(authorization)
    if not provided_token or not _token_matches(token_expected, provided_token):
        logger.warning("invalidate_secrets: unauthorized attempt; bearer token mismatch")
        _log_admin_event("invalidate_secrets", "unauthorized", source_ip=source_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Authorization bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ── Invalidate cache ───────────────────────────────────────────────────────
    from config.secrets import AWSSecretManager, get_secret_manager

    secret_manager = get_secret_manager(env=cfg.env)
    backend_name = type(secret_manager).__name__

    if isinstance(secret_manager, AWSSecretManager):
        secret_manager.invalidate_cache()
        logger.info(
            "invalidate_secrets: cache cleared",
            extra={
                "secret_name": body.secret_name or secret_manager.secret_name,
                "backend": backend_name,
            },
        )
        _log_admin_event(
            "invalidate_secrets",
            "ok",
            source_ip=source_ip,
            secret_name=body.secret_name or secret_manager.secret_name,
            secret_backend="aws",
        )
        return InvalidateSecretsResponse(
            status="ok",
            message=(
                f"AWSSecretManager cache cleared.  "
                f"Next get() will re-fetch from AWS "
                f"(secret='{body.secret_name or secret_manager.secret_name}')."
            ),
            secret_backend="aws",
        )

    # EnvSecretManager — no cache; nothing to do
    logger.info(
        "invalidate_secrets: skipped (EnvSecretManager has no cache)",
        extra={"backend": backend_name},
    )
    _log_admin_event(
        "invalidate_secrets",
        "skipped_env_backend",
        source_ip=source_ip,
        secret_name=body.secret_name or None,
        secret_backend="env",
    )
    return InvalidateSecretsResponse(
        status="skipped_env_backend",
        message=(
            "Running with EnvSecretManager (environment variables).  "
            "No in-memory cache exists; no action taken.  "
            "Restart the process to pick up new environment values."
        ),
        secret_backend="env",
    )


@router.get(
    "/admin/events",
    response_model=list[AdminEventResponse],
    status_code=status.HTTP_200_OK,
    summary="List admin audit log events",
    description=(
        "Returns the most recent admin audit log entries from the database, "
        "newest first.  Requires Authorization: Bearer <APIS_ADMIN_ROTATION_TOKEN>."
    ),
)
def list_admin_events(
    request: Request,
    authorization: str | None = Header(default=None),
    cfg: SettingsDep = None,  # type: ignore[assignment]
    limit: int = 50,
) -> list[AdminEventResponse]:
    """Return the latest admin audit events from the database.

    Returns 503 when the feature is disabled (token not configured).
    Returns 401 when the bearer token does not match.
    Returns 503 when the database is unavailable.
    """
    source_ip = _get_client_ip(request)
    _check_rate_limit(source_ip)

    # ── Feature guard + auth ───────────────────────────────────────────────────
    token_expected = cfg.admin_rotation_token if cfg else ""
    if not token_expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin endpoints are disabled.  Set APIS_ADMIN_ROTATION_TOKEN to enable.",
        )
    provided_token = _extract_bearer(authorization)
    if not provided_token or not _token_matches(token_expected, provided_token):
        logger.warning("list_admin_events: unauthorized attempt")
        _log_admin_event("list_events", "unauthorized", source_ip=source_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Authorization bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ── Query ──────────────────────────────────────────────────────────────────
    try:
        from infra.db.models.audit import AdminEvent
        from infra.db.session import db_session as _db_session

        with _db_session() as db:
            rows = (
                db.query(AdminEvent)
                .order_by(AdminEvent.event_timestamp.desc())
                .limit(max(1, min(limit, 500)))
                .all()
            )
            _log_admin_event("list_events", "ok", source_ip=source_ip)
            return [
                AdminEventResponse(
                    id=str(row.id),
                    event_timestamp=row.event_timestamp.isoformat(),
                    event_type=row.event_type,
                    result=row.result,
                    source_ip=row.source_ip,
                    secret_name=row.secret_name,
                    secret_backend=row.secret_backend,
                )
                for row in rows
            ]
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("list_admin_events: database query failed", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database unavailable: {exc}",
        )


# ── Kill-switch endpoints (Priority 19) ───────────────────────────────────────


class KillSwitchRequest(BaseModel):
    """Body for POST /admin/kill-switch."""

    active: bool
    reason: str = ""


class KillSwitchStatusResponse(BaseModel):
    """Response for GET and POST /admin/kill-switch."""

    kill_switch_active: bool
    env_kill_switch: bool          # value of APIS_KILL_SWITCH env var
    effective: bool                # kill_switch_active OR env_kill_switch
    activated_at: Optional[str]    # ISO-8601 or None
    activated_by: Optional[str]    # source IP or "env" or None
    message: str


def _persist_kill_switch(active: bool, activated_by: Optional[str] = None) -> None:
    """Upsert kill switch state to system_state table.  Fire-and-forget."""
    import datetime as _now_dt
    try:
        from infra.db.models.system_state import (
            KEY_KILL_SWITCH_ACTIVATED_AT,
            KEY_KILL_SWITCH_ACTIVATED_BY,
            KEY_KILL_SWITCH_ACTIVE,
            SystemStateEntry,
        )
        from infra.db.session import db_session as _db_session

        now = _now_dt.datetime.now(_now_dt.timezone.utc)
        with _db_session() as db:
            for key, value in (
                (KEY_KILL_SWITCH_ACTIVE, "true" if active else "false"),
                (KEY_KILL_SWITCH_ACTIVATED_AT, now.isoformat() if active else ""),
                (KEY_KILL_SWITCH_ACTIVATED_BY, activated_by or ""),
            ):
                entry = db.get(SystemStateEntry, key)
                if entry is None:
                    entry = SystemStateEntry(key=key, value_text=value)
                    db.add(entry)
                else:
                    entry.value_text = value
    except Exception as exc:  # noqa: BLE001
        logger.warning("persist_kill_switch_failed", extra={"error": str(exc)})


@router.post(
    "/admin/kill-switch",
    response_model=KillSwitchStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Activate or deactivate the runtime kill switch",
    description=(
        "Immediately activates or deactivates the runtime kill switch.\n\n"
        "When active, the paper trading cycle returns ``status='killed'`` and no "
        "orders are submitted to the broker.\n\n"
        "**Deactivation is blocked** when ``APIS_KILL_SWITCH=true`` in the "
        "environment — the env var must be cleared and the process restarted.\n\n"
        "The kill switch state is persisted to the ``system_state`` DB table so "
        "it survives process restarts.\n\n"
        "Requires Authorization: Bearer <APIS_ADMIN_ROTATION_TOKEN>."
    ),
)
def set_kill_switch(
    request: Request,
    body: KillSwitchRequest,
    app_state: AppStateDep = None,  # type: ignore[assignment]
    authorization: str | None = Header(default=None),
    cfg: SettingsDep = None,  # type: ignore[assignment]
) -> KillSwitchStatusResponse:
    """Activate or deactivate the runtime kill switch.

    Returns 503 when the admin feature is disabled (token not configured).
    Returns 401 on wrong/missing bearer token.
    Returns 409 when deactivation is attempted while the env-var kill switch
    is still set to True (env var takes precedence; API cannot override it).
    """
    source_ip = _get_client_ip(request)
    _check_rate_limit(source_ip)

    # ── Feature guard + auth ───────────────────────────────────────────────────
    token_expected = cfg.admin_rotation_token if cfg else ""
    if not token_expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin endpoints are disabled.  Set APIS_ADMIN_ROTATION_TOKEN to enable.",
        )
    provided_token = _extract_bearer(authorization)
    if not provided_token or not _token_matches(token_expected, provided_token):
        logger.warning("set_kill_switch: unauthorized attempt")
        _log_admin_event("kill_switch", "unauthorized", source_ip=source_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Authorization bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    env_active = bool(cfg.kill_switch if cfg else False)

    # ── Deactivation blocked by env var ────────────────────────────────────────
    if not body.active and env_active:
        _log_admin_event(
            "kill_switch",
            "deactivate_blocked_env",
            source_ip=source_ip,
            details={"reason": body.reason},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Cannot deactivate kill switch: APIS_KILL_SWITCH=true is set in the "
                "environment.  Clear the env var and restart the process first."
            ),
        )

    # ── Apply change ───────────────────────────────────────────────────────────
    prev_active = app_state.kill_switch_active
    app_state.kill_switch_active = body.active
    if body.active:
        app_state.kill_switch_activated_at = _dt.datetime.now(_dt.timezone.utc)
        app_state.kill_switch_activated_by = source_ip
    else:
        app_state.kill_switch_activated_at = None
        app_state.kill_switch_activated_by = None

    _persist_kill_switch(body.active, activated_by=source_ip)

    action = "activated" if body.active else "deactivated"
    logger.warning(
        "kill_switch_changed: active=%s prev=%s source_ip=%s reason=%s",
        body.active, prev_active, source_ip, body.reason or None,
    )
    _log_admin_event(
        "kill_switch",
        action,
        source_ip=source_ip,
        details={"active": body.active, "reason": body.reason or None},
    )

    # ── Phase 31: Kill switch webhook alert ───────────────────────────────────
    _alert_svc = getattr(app_state, "alert_service", None)
    if _alert_svc and getattr(cfg, "alert_on_kill_switch", True):
        from services.alerting.models import AlertEvent, AlertEventType, AlertSeverity
        _event_type = (
            AlertEventType.KILL_SWITCH_ACTIVATED.value
            if body.active
            else AlertEventType.KILL_SWITCH_DEACTIVATED.value
        )
        _severity = AlertSeverity.CRITICAL.value if body.active else AlertSeverity.WARNING.value
        _title = (
            f"APIS Kill Switch {action.upper()} by {source_ip or 'unknown'}"
        )
        _alert_svc.send_alert(AlertEvent(
            event_type=_event_type,
            severity=_severity,
            title=_title,
            payload={"active": body.active, "reason": body.reason or None, "source_ip": source_ip},
        ))

    effective = app_state.kill_switch_active or env_active
    return KillSwitchStatusResponse(
        kill_switch_active=app_state.kill_switch_active,
        env_kill_switch=env_active,
        effective=effective,
        activated_at=app_state.kill_switch_activated_at.isoformat()
        if app_state.kill_switch_activated_at else None,
        activated_by=app_state.kill_switch_activated_by,
        message=f"Kill switch {action} successfully.",
    )


@router.post(
    "/admin/test-webhook",
    status_code=status.HTTP_200_OK,
    summary="Send a test webhook alert",
    description=(
        "Fires a test alert event to the configured webhook URL and returns "
        "the delivery result.  Useful for verifying webhook connectivity.\n\n"
        "Returns 503 when admin endpoints are disabled or no webhook URL is configured.\n\n"
        "Requires Authorization: Bearer <APIS_ADMIN_ROTATION_TOKEN>."
    ),
)
def test_webhook(
    request: Request,
    app_state: AppStateDep = None,  # type: ignore[assignment]
    authorization: str | None = Header(default=None),
    cfg: SettingsDep = None,  # type: ignore[assignment]
) -> dict:
    """Send a test alert to the configured webhook URL.

    Returns {"delivered": true/false, "webhook_enabled": true/false}.
    Returns 503 when admin is disabled or webhook URL is not configured.
    Returns 401 on wrong/missing bearer token.
    """
    source_ip = _get_client_ip(request)
    _check_rate_limit(source_ip)

    # ── Feature guard + auth ───────────────────────────────────────────────────
    token_expected = cfg.admin_rotation_token if cfg else ""
    if not token_expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin endpoints are disabled.  Set APIS_ADMIN_ROTATION_TOKEN to enable.",
        )
    provided_token = _extract_bearer(authorization)
    if not provided_token or not _token_matches(token_expected, provided_token):
        logger.warning("test_webhook: unauthorized attempt")
        _log_admin_event("test_webhook", "unauthorized", source_ip=source_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Authorization bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    alert_svc = getattr(app_state, "alert_service", None)
    if alert_svc is None or not alert_svc.is_enabled:
        _log_admin_event("test_webhook", "disabled", source_ip=source_ip)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook not configured.  Set APIS_WEBHOOK_URL to enable.",
        )

    from services.alerting.models import AlertEvent, AlertEventType, AlertSeverity
    test_event = AlertEvent(
        event_type=AlertEventType.TEST.value,
        severity=AlertSeverity.INFO.value,
        title="APIS test webhook — delivery verification",
        payload={"source_ip": source_ip, "initiated_by": "POST /admin/test-webhook"},
    )
    delivered = alert_svc.send_alert(test_event)
    _log_admin_event(
        "test_webhook",
        "delivered" if delivered else "failed",
        source_ip=source_ip,
    )
    return {"delivered": delivered, "webhook_enabled": True}


@router.get(
    "/admin/kill-switch",
    response_model=KillSwitchStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current kill switch state",
    description=(
        "Returns the current effective kill switch state, combining the runtime "
        "app-state flag and the APIS_KILL_SWITCH environment variable.\n\n"
        "Requires Authorization: Bearer <APIS_ADMIN_ROTATION_TOKEN>."
    ),
)
def get_kill_switch(
    request: Request,
    app_state: AppStateDep = None,  # type: ignore[assignment]
    authorization: str | None = Header(default=None),
    cfg: SettingsDep = None,  # type: ignore[assignment]
) -> KillSwitchStatusResponse:
    """Return the current kill switch state.

    Returns 503 when admin feature is disabled.
    Returns 401 on wrong/missing bearer token.
    """
    source_ip = _get_client_ip(request)
    _check_rate_limit(source_ip)

    token_expected = cfg.admin_rotation_token if cfg else ""
    if not token_expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin endpoints are disabled.  Set APIS_ADMIN_ROTATION_TOKEN to enable.",
        )
    provided_token = _extract_bearer(authorization)
    if not provided_token or not _token_matches(token_expected, provided_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Authorization bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    env_active = bool(cfg.kill_switch if cfg else False)
    effective = app_state.kill_switch_active or env_active

    return KillSwitchStatusResponse(
        kill_switch_active=app_state.kill_switch_active,
        env_kill_switch=env_active,
        effective=effective,
        activated_at=app_state.kill_switch_activated_at.isoformat()
        if app_state.kill_switch_activated_at else None,
        activated_by=app_state.kill_switch_activated_by,
        message="ok",
    )

