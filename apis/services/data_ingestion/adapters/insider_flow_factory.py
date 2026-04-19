"""
Factory for selecting the active ``InsiderFlowAdapter`` from settings.

Phase 57 Part 2 (DEC-024 / 2026-04-18) introduced two concrete providers:
``QuiverQuantAdapter`` and ``SECEdgarFormFourAdapter``.  This factory is the
ONE place worker / enrichment code asks for an adapter instance — it reads
``settings.insider_flow_provider`` and the associated credential fields, and
falls back to ``NullInsiderFlowAdapter`` with a WARNING on any config gap.

Fallback matrix:

    provider            | credentials present? | returns
    --------------------+----------------------+-----------------------------
    null                | n/a                  | NullInsiderFlowAdapter
    quiverquant         | api_key ✓            | QuiverQuantAdapter
    quiverquant         | api_key ✗            | NullInsiderFlowAdapter (warn)
    sec_edgar           | user_agent ✓         | SECEdgarFormFourAdapter
    sec_edgar           | user_agent ✗         | NullInsiderFlowAdapter (warn)
    composite           | both ✓               | _CompositeInsiderFlowAdapter
    composite           | partial / neither    | whichever concrete one has
                                                  creds; else Null (warn)

The factory NEVER raises — a bad config always degrades to Null, because
a missing signal is preferable to a crashed paper cycle.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from services.data_ingestion.adapters.insider_flow_adapter import (
    InsiderFlowAdapter,
    InsiderFlowEvent,
    NullInsiderFlowAdapter,
)

logger = logging.getLogger(__name__)


class _CompositeInsiderFlowAdapter(InsiderFlowAdapter):
    """Merge events from multiple underlying adapters."""

    SOURCE_KEY: str = "insider_flow_composite"

    def __init__(self, adapters: list[InsiderFlowAdapter]) -> None:
        if not adapters:
            raise ValueError(
                "_CompositeInsiderFlowAdapter requires at least one adapter"
            )
        self._adapters = adapters

    def fetch_events(
        self,
        tickers: list[str],
        lookback_days: int = 90,
        as_of: dt.date | None = None,
    ) -> list[InsiderFlowEvent]:
        out: list[InsiderFlowEvent] = []
        for a in self._adapters:
            try:
                out.extend(a.fetch_events(tickers, lookback_days=lookback_days, as_of=as_of))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "composite_adapter_subcall_failed adapter=%s error=%s",
                    type(a).__name__, exc,
                )
        return out


def build_insider_flow_adapter(
    *,
    settings: Any | None = None,
    ticker_to_cik: dict[str, str] | None = None,
) -> InsiderFlowAdapter:
    """Return the active ``InsiderFlowAdapter`` per settings.

    Args:
        settings: a ``Settings`` instance (from ``config.settings``).  If
            omitted, the singleton is looked up lazily so call sites in hot
            paths don't have to thread it through.
        ticker_to_cik: optional ticker→CIK map for the EDGAR adapter.  Can
            be None; tickers with no CIK are silently skipped at fetch time.

    Returns:
        A concrete adapter, or ``NullInsiderFlowAdapter`` on any gap.
    """
    if settings is None:
        from config.settings import get_settings
        settings = get_settings()

    provider = (getattr(settings, "insider_flow_provider", "null") or "null").strip().lower()
    quiver_key = getattr(settings, "quiverquant_api_key", "") or ""
    ua = getattr(settings, "sec_edgar_user_agent", "") or ""

    if provider in ("", "null", "none", "off", "disabled"):
        return NullInsiderFlowAdapter()

    active: list[InsiderFlowAdapter] = []

    want_quiver = provider in ("quiverquant", "composite")
    want_edgar = provider in ("sec_edgar", "composite")

    if want_quiver:
        if quiver_key:
            try:
                from services.data_ingestion.adapters.quiverquant_adapter import (
                    QuiverQuantAdapter,
                )
                active.append(QuiverQuantAdapter(api_key=quiver_key))
                logger.info("insider_flow_factory wired=quiverquant")
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "insider_flow_factory quiverquant_init_failed error=%s", exc,
                )
        else:
            logger.warning(
                "insider_flow_factory provider=%s but quiverquant_api_key is empty — "
                "skipping QuiverQuant",
                provider,
            )

    if want_edgar:
        if ua:
            try:
                from services.data_ingestion.adapters.sec_edgar_form4_adapter import (
                    SECEdgarFormFourAdapter,
                )
                active.append(
                    SECEdgarFormFourAdapter(
                        user_agent=ua, ticker_to_cik=ticker_to_cik,
                    )
                )
                logger.info("insider_flow_factory wired=sec_edgar")
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "insider_flow_factory sec_edgar_init_failed error=%s", exc,
                )
        else:
            logger.warning(
                "insider_flow_factory provider=%s but sec_edgar_user_agent is empty — "
                "skipping EDGAR",
                provider,
            )

    if not active:
        logger.warning(
            "insider_flow_factory falling back to NullInsiderFlowAdapter "
            "(provider=%s had no usable credentials)",
            provider,
        )
        return NullInsiderFlowAdapter()

    if len(active) == 1:
        return active[0]
    return _CompositeInsiderFlowAdapter(active)
