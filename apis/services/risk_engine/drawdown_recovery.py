"""Drawdown Recovery Mode — portfolio-level adaptive risk management."""

import enum
import datetime as dt
from dataclasses import dataclass
from typing import Optional

import structlog

log = structlog.get_logger(__name__)


class DrawdownState(str, enum.Enum):
    NORMAL = "NORMAL"      # drawdown < caution threshold
    CAUTION = "CAUTION"    # caution_pct <= drawdown < recovery_pct
    RECOVERY = "RECOVERY"  # drawdown >= recovery_pct


@dataclass(frozen=True)
class DrawdownStateResult:
    state: DrawdownState
    current_drawdown_pct: float   # 0.0 = no drawdown, 0.10 = 10% below HWM
    high_water_mark: float
    current_equity: float
    caution_threshold_pct: float
    recovery_threshold_pct: float
    size_multiplier: float         # 1.0 in NORMAL/CAUTION, recovery_mode_size_multiplier in RECOVERY


class DrawdownRecoveryService:
    """Stateless service: evaluates portfolio drawdown state and adjusts sizing."""

    @staticmethod
    def evaluate_state(
        current_equity: float,
        high_water_mark: float,
        caution_threshold_pct: float,
        recovery_threshold_pct: float,
        recovery_mode_size_multiplier: float,
    ) -> DrawdownStateResult:
        """
        Compute current DrawdownState from equity vs HWM.

        Args:
            current_equity: current portfolio equity
            high_water_mark: peak equity seen so far
            caution_threshold_pct: e.g. 0.05 = 5% drawdown -> CAUTION
            recovery_threshold_pct: e.g. 0.10 = 10% drawdown -> RECOVERY
            recovery_mode_size_multiplier: e.g. 0.50 = half size in RECOVERY

        Returns:
            DrawdownStateResult
        """
        if high_water_mark <= 0 or current_equity <= 0:
            return DrawdownStateResult(
                state=DrawdownState.NORMAL,
                current_drawdown_pct=0.0,
                high_water_mark=high_water_mark,
                current_equity=current_equity,
                caution_threshold_pct=caution_threshold_pct,
                recovery_threshold_pct=recovery_threshold_pct,
                size_multiplier=1.0,
            )

        drawdown_pct = max(0.0, (high_water_mark - current_equity) / high_water_mark)

        if drawdown_pct >= recovery_threshold_pct:
            state = DrawdownState.RECOVERY
            size_multiplier = recovery_mode_size_multiplier
        elif drawdown_pct >= caution_threshold_pct:
            state = DrawdownState.CAUTION
            size_multiplier = 1.0
        else:
            state = DrawdownState.NORMAL
            size_multiplier = 1.0

        log.debug(
            "drawdown_state_evaluated",
            state=state.value,
            drawdown_pct=round(drawdown_pct, 4),
            equity=current_equity,
            hwm=high_water_mark,
        )

        return DrawdownStateResult(
            state=state,
            current_drawdown_pct=drawdown_pct,
            high_water_mark=high_water_mark,
            current_equity=current_equity,
            caution_threshold_pct=caution_threshold_pct,
            recovery_threshold_pct=recovery_threshold_pct,
            size_multiplier=size_multiplier,
        )

    @staticmethod
    def apply_recovery_sizing(
        requested_quantity: int,
        state_result: DrawdownStateResult,
    ) -> int:
        """
        Apply size multiplier when in RECOVERY mode.
        Returns floored integer quantity (minimum 1 if original > 0).
        """
        if state_result.state != DrawdownState.RECOVERY:
            return requested_quantity
        if requested_quantity <= 0:
            return requested_quantity
        adjusted = int(requested_quantity * state_result.size_multiplier)
        return max(1, adjusted)

    @staticmethod
    def is_blocked(
        state_result: DrawdownStateResult,
        block_new_positions: bool,
    ) -> bool:
        """
        Returns True if new OPEN actions should be blocked entirely.
        Only applies in RECOVERY mode AND when block_new_positions=True.
        """
        return (
            state_result.state == DrawdownState.RECOVERY
            and block_new_positions
        )
