"""Phase 42: GET /portfolio/exit-levels endpoint."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter

from apps.api.deps import AppStateDep, SettingsDep
from apps.api.schemas.exit_levels import ExitLevelsResponse, PositionExitLevelSchema

exit_levels_router = APIRouter()


@exit_levels_router.get("/portfolio/exit-levels", response_model=ExitLevelsResponse)
def get_exit_levels(app_state: AppStateDep, settings: SettingsDep) -> ExitLevelsResponse:
    """Return current stop-loss, trailing stop, and take-profit levels for all open positions."""
    portfolio_state = app_state.portfolio_state
    peak_prices: dict = getattr(app_state, "position_peak_prices", {})
    positions_data: list[PositionExitLevelSchema] = []

    trailing_stop_pct = getattr(settings, "trailing_stop_pct", 0.0)
    trailing_stop_activation_pct = getattr(settings, "trailing_stop_activation_pct", 0.03)
    take_profit_pct = getattr(settings, "take_profit_pct", 0.0)
    stop_loss_pct = getattr(settings, "stop_loss_pct", 0.07)

    if portfolio_state and portfolio_state.positions:
        for ticker, pos in portfolio_state.positions.items():
            current = float(pos.current_price)
            entry = float(pos.avg_entry_price)
            pnl_pct = float(pos.unrealized_pnl_pct) if entry > 0 else 0.0
            peak = peak_prices.get(ticker)
            if peak is None:
                peak = max(current, entry)

            # Stop-loss level
            stop_level = entry * (1 - stop_loss_pct) if stop_loss_pct > 0 else None

            # Trailing stop level
            trailing_activated = pnl_pct >= trailing_stop_activation_pct
            trailing_level = (
                peak * (1 - trailing_stop_pct)
                if trailing_stop_pct > 0
                else None
            )

            # Take-profit level
            tp_level = entry * (1 + take_profit_pct) if take_profit_pct > 0 else None

            positions_data.append(PositionExitLevelSchema(
                ticker=ticker,
                current_price=current,
                avg_entry_price=entry,
                unrealized_pnl_pct=pnl_pct,
                peak_price=peak,
                stop_loss_level=stop_level,
                trailing_stop_level=trailing_level,
                take_profit_level=tp_level,
                trailing_stop_activated=trailing_activated,
                stop_loss_pct=stop_loss_pct,
                trailing_stop_pct=trailing_stop_pct,
                take_profit_pct=take_profit_pct,
            ))

    return ExitLevelsResponse(
        positions=positions_data,
        trailing_stop_pct=trailing_stop_pct,
        trailing_stop_activation_pct=trailing_stop_activation_pct,
        take_profit_pct=take_profit_pct,
        computed_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    )
