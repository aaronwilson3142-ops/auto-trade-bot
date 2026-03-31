"""Price streaming routes.

Endpoints
---------
GET  /prices/snapshot      — REST snapshot of current portfolio prices (no WebSocket)
WS   /prices/ws            — WebSocket feed; pushes price ticks every 2 seconds

Phase 36 — Real-time Price Streaming / WebSocket Feed
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from apps.api.deps import AppStateDep
from apps.api.schemas.prices import PriceSnapshotResponse, PriceTickSchema

router = APIRouter(prefix="/prices", tags=["Prices"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_ticks(state: object) -> list[PriceTickSchema]:
    """Build price ticks from app_state.portfolio_state.positions."""
    portfolio_state = getattr(state, "portfolio_state", None)
    if portfolio_state is None:
        return []

    positions = getattr(portfolio_state, "positions", {})
    ticks: list[PriceTickSchema] = []

    for ticker, pos in positions.items():
        qty = float(getattr(pos, "quantity", 0))
        entry = float(getattr(pos, "avg_entry_price", 0.0))
        price = float(getattr(pos, "current_price", entry))
        market_value = float(getattr(pos, "market_value", price * qty))

        pnl_pct = 0.0
        if entry > 0:
            pnl_pct = round((price - entry) / entry, 6)

        ticks.append(
            PriceTickSchema(
                ticker=ticker,
                current_price=round(price, 4),
                avg_entry_price=round(entry, 4),
                unrealized_pnl_pct=pnl_pct,
                market_value=round(market_value, 2),
                quantity=qty,
            )
        )

    return ticks


# ---------------------------------------------------------------------------
# REST snapshot
# ---------------------------------------------------------------------------

@router.get("/snapshot", response_model=PriceSnapshotResponse)
async def price_snapshot(state: AppStateDep) -> PriceSnapshotResponse:
    """Return the latest portfolio price snapshot as a REST response.

    This is the non-WebSocket fallback for operators that cannot maintain a
    persistent connection.  Returns an empty ticks list when no positions exist.
    """
    ticks = _build_ticks(state)
    note = None if ticks else "No open positions in portfolio."
    return PriceSnapshotResponse(
        ticks=ticks,
        position_count=len(ticks),
        as_of=dt.datetime.now(dt.timezone.utc),
        note=note,
    )


# ---------------------------------------------------------------------------
# WebSocket feed
# ---------------------------------------------------------------------------

@router.websocket("/ws")
async def prices_websocket(websocket: WebSocket, state: AppStateDep) -> None:  # type: ignore[return]
    """Stream portfolio price ticks every 2 seconds over WebSocket.

    Message format (JSON):
      {
        "ticks": [ { ticker, current_price, avg_entry_price,
                     unrealized_pnl_pct, market_value, quantity }, ... ],
        "position_count": N,
        "as_of": "<ISO-8601 UTC>"
      }

    The connection is kept alive until the client disconnects.
    Empty ticks list is sent when no positions are open.
    """
    await websocket.accept()
    try:
        while True:
            ticks = _build_ticks(state)
            payload = {
                "ticks": [t.model_dump() for t in ticks],
                "position_count": len(ticks),
                "as_of": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        # Connection closed unexpectedly — no re-raise so the handler exits cleanly
        pass
