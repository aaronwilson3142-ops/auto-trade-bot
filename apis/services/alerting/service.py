"""
Operator webhook alert service.

Sends structured JSON payloads to a configured webhook URL when key system
events occur (kill switch toggled, paper cycle errors, broker auth expiry,
daily evaluation complete).

Design rules
------------
- ``send_alert`` NEVER raises — all failures are logged at WARNING level and
  return False so callers can proceed regardless of delivery success.
- HTTP delivery uses ``httpx`` (already in project dependencies) with a
  configurable timeout.
- Optional HMAC-SHA256 request signing: when ``APIS_WEBHOOK_SECRET`` is set,
  every POST includes an ``X-APIS-Signature: sha256=<hex>`` header so the
  receiver can verify authenticity.
- Simple retry: up to ``max_retries`` attempts on failure (no backoff — these
  are fire-and-forget operator notifications, not transactional messages).
- ``is_enabled`` returns False when ``webhook_url`` is empty — callers may
  guard cheaply without inspecting settings.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Optional

from services.alerting.models import AlertEvent

logger = logging.getLogger(__name__)


class WebhookAlertService:
    """Deliver alert events to an operator webhook URL.

    Args:
        webhook_url:  Full HTTPS URL of the operator's webhook endpoint.
                      Empty string disables delivery without error.
        secret:       Optional HMAC-SHA256 signing secret.  When set, every
                      POST includes ``X-APIS-Signature: sha256=<hex>``.
        timeout:      HTTP request timeout in seconds (default 10).
        max_retries:  Number of delivery attempts before giving up (default 2).
    """

    def __init__(
        self,
        webhook_url: str = "",
        secret: str = "",
        timeout: int = 10,
        max_retries: int = 2,
    ) -> None:
        self._url = webhook_url.strip()
        self._secret = secret.strip()
        self._timeout = timeout
        self._max_retries = max(1, max_retries)

    @property
    def is_enabled(self) -> bool:
        """True when a webhook URL has been configured."""
        return bool(self._url)

    def send_alert(self, event: AlertEvent) -> bool:
        """Dispatch *event* to the configured webhook URL.

        Returns True on successful delivery (any 2xx response), False on all
        failure modes (disabled, network error, non-2xx response).  Never raises.
        """
        if not self.is_enabled:
            return False

        try:
            payload = self._build_payload(event)
            return self._post_with_retry(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "webhook_alert_unexpected_error",
                extra={"event_type": event.event_type, "error": str(exc)},
            )
            return False

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_payload(self, event: AlertEvent) -> dict:
        """Construct the JSON body for the webhook POST request."""
        return {
            "source": "apis",
            "event_type": event.event_type,
            "severity": event.severity,
            "title": event.title,
            "timestamp": event.timestamp.isoformat(),
            "payload": event.payload,
        }

    def _sign(self, body: str) -> str:
        """Compute HMAC-SHA256 hex signature over the serialized body string."""
        return hmac.new(
            self._secret.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _post_with_retry(self, payload: dict) -> bool:
        """POST *payload* JSON to the webhook URL with retry on failure.

        Returns True if any attempt receives a 2xx response, False otherwise.
        """
        import httpx

        body = json.dumps(payload)
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._secret:
            headers["X-APIS-Signature"] = f"sha256={self._sign(body)}"

        for attempt in range(1, self._max_retries + 1):
            try:
                resp = httpx.post(
                    self._url,
                    content=body,
                    headers=headers,
                    timeout=self._timeout,
                )
                if resp.is_success:
                    logger.info(
                        "webhook_alert_delivered",
                        extra={
                            "event_type": payload.get("event_type"),
                            "status_code": resp.status_code,
                            "attempt": attempt,
                        },
                    )
                    return True
                logger.warning(
                    "webhook_alert_non_2xx",
                    extra={
                        "event_type": payload.get("event_type"),
                        "status_code": resp.status_code,
                        "attempt": attempt,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "webhook_alert_delivery_failed",
                    extra={
                        "event_type": payload.get("event_type"),
                        "attempt": attempt,
                        "error": str(exc),
                    },
                )

        return False


def make_alert_service(webhook_url: str = "", secret: str = "") -> WebhookAlertService:
    """Factory — construct a ``WebhookAlertService`` from raw config strings.

    Intended to be called once at worker / API startup and stored in
    ``ApiAppState.alert_service``.
    """
    return WebhookAlertService(webhook_url=webhook_url, secret=secret)
