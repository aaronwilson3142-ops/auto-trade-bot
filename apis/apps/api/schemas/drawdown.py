from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class DrawdownStateResponse(BaseModel):
    state: str
    current_drawdown_pct: float
    high_water_mark: float
    current_equity: float
    caution_threshold_pct: float
    recovery_threshold_pct: float
    size_multiplier: float
    block_new_positions: bool
    state_changed_at: dt.datetime | None
