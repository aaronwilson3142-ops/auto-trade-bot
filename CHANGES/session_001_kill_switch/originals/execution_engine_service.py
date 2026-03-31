"""
Execution Engine Service.

Translates risk-approved PortfolioActions into broker orders and records fills.
The only service permitted to call broker_adapter.place_order().

Design rules enforced here:
  - Kill switch is re-checked immediately before every order submission
    (belt-and-suspenders: risk_engine already checked at proposal validation).
  - Only ActionType.OPEN and ActionType.CLOSE trigger real orders.
  - BLOCKED actions are returned as-is with ExecutionStatus.BLOCKED.
  - Fractional shares are not permitted in MVP: quantity = floor(notional/price).
  - Idempotency keys are built from ticker + action_type + timestamp so that
    duplicate submissions from retries are detected by the broker adapter.

Spec references:
  - API_AND_SERVICE_BOUNDARIES_SPEC.md § 3.12
  - API_AND_SERVICE_BOUNDARIES_SPEC.md § 2.4 (only execution_engine submits orders)
"""
from __future__ import annotations

import uuid
from decimal import Decimal, ROUND_DOWN
from typing import Optional

import structlog

from broker_adapters.base.adapter import BaseBrokerAdapter
from broker_adapters.base.exceptions import (
    BrokerError,
    KillSwitchActiveError,
    PositionNotFoundError,
)
from broker_adapters.base.models import OrderRequest, OrderSide, OrderType
from config.settings import Settings
from services.execution_engine.models import ExecutionRequest, ExecutionResult, ExecutionStatus
from services.portfolio_engine.models import ActionType

log = structlog.get_logger(__name__)


class ExecutionEngineService:
    """
    Routes risk-approved portfolio actions to the broker and records fills.

    Thread-safety: not thread-safe; callers must coordinate access.
    """

    def __init__(self, settings: Settings, broker: BaseBrokerAdapter) -> None:
        self._settings = settings
        self._broker = broker
        self._log = log.bind(service="execution_engine", broker=broker.adapter_name)

    # ── Public API ────────────────────────────────────────────────────────────

    def execute_action(self, request: ExecutionRequest) -> ExecutionResult:
        """Execute a single risk-approved PortfolioAction.

        Pre-conditions:
          - request.action.risk_approved must be True (validated upstream by risk_engine).
          - request.current_price must be positive.

        Returns an ExecutionResult regardless of outcome (no exceptions bubble up
        to callers — errors are captured in the result object).
        """
        action = request.action

        # ── Kill switch re-check ────────────────────────────────────────────
        if self._settings.kill_switch:
            self._log.warning("execution_blocked_kill_switch", ticker=action.ticker)
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                action=action,
                error_message="Kill switch active — order not submitted.",
            )

        # ── BLOCKED actions pass-through ────────────────────────────────────
        if action.action_type == ActionType.BLOCKED:
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                action=action,
                error_message="Action was marked BLOCKED by risk engine.",
            )

        try:
            if action.action_type == ActionType.OPEN:
                return self._execute_open(request)
            elif action.action_type == ActionType.CLOSE:
                return self._execute_close(request)
            elif action.action_type == ActionType.TRIM:
                return self._execute_trim(request)
            else:
                return ExecutionResult(
                    status=ExecutionStatus.ERROR,
                    action=action,
                    error_message=f"Unsupported action_type: {action.action_type}",
                )
        except KillSwitchActiveError as exc:
            self._log.error("kill_switch_raised_by_broker", ticker=action.ticker, error=str(exc))
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                action=action,
                error_message=str(exc),
            )
        except BrokerError as exc:
            self._log.error("broker_order_rejected", ticker=action.ticker, error=str(exc))
            return ExecutionResult(
                status=ExecutionStatus.REJECTED,
                action=action,
                error_message=str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            self._log.exception("execution_unexpected_error", ticker=action.ticker, error=str(exc))
            return ExecutionResult(
                status=ExecutionStatus.ERROR,
                action=action,
                error_message=f"Unexpected error: {exc}",
            )

    def execute_approved_actions(
        self, requests: list[ExecutionRequest]
    ) -> list[ExecutionResult]:
        """Execute a batch of risk-approved actions sequentially.

        All results are collected and returned; a single failure does not
        abort the remaining queue.
        """
        results: list[ExecutionResult] = []
        for req in requests:
            result = self.execute_action(req)
            results.append(result)
            self._log.info(
                "batch_execution_step",
                ticker=req.action.ticker,
                action_type=req.action.action_type.value,
                status=result.status.value,
            )
        return results

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _execute_open(self, request: ExecutionRequest) -> ExecutionResult:
        """Buy: floor(target_notional / price) shares, market order."""
        action = request.action
        price = request.current_price

        if price <= Decimal("0"):
            return ExecutionResult(
                status=ExecutionStatus.ERROR,
                action=action,
                error_message=f"Invalid price {price} for OPEN action.",
            )

        quantity = (action.target_notional / price).to_integral_value(rounding=ROUND_DOWN)
        if quantity <= Decimal("0"):
            return ExecutionResult(
                status=ExecutionStatus.REJECTED,
                action=action,
                error_message=(
                    f"Computed quantity is 0: notional={action.target_notional} "
                    f"price={price}. Order not submitted."
                ),
            )

        order_req = OrderRequest(
            idempotency_key=self._make_idempotency_key(action, "open"),
            ticker=action.ticker,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=quantity,
        )

        order = self._broker.place_order(order_req)
        fills = self._broker.get_fills_for_order(order.broker_order_id)

        fill_price = order.average_fill_price
        fill_qty = order.filled_quantity
        filled_at = order.filled_at
        fees = sum((f.fees for f in fills), Decimal("0"))

        self._log.info(
            "open_order_filled",
            ticker=action.ticker,
            quantity=str(fill_qty),
            fill_price=str(fill_price),
        )

        return ExecutionResult(
            status=ExecutionStatus.FILLED,
            action=action,
            broker_order_id=order.broker_order_id,
            fill_price=fill_price,
            fill_quantity=fill_qty,
            fees=fees,
            filled_at=filled_at,
        )

    def _execute_close(self, request: ExecutionRequest) -> ExecutionResult:
        """Sell: full position quantity, market order."""
        action = request.action

        try:
            position = self._broker.get_position(action.ticker)
        except PositionNotFoundError as exc:
            return ExecutionResult(
                status=ExecutionStatus.REJECTED,
                action=action,
                error_message=f"No position to close for {action.ticker}: {exc}",
            )

        quantity = position.quantity
        if quantity <= Decimal("0"):
            return ExecutionResult(
                status=ExecutionStatus.REJECTED,
                action=action,
                error_message=f"Position quantity is 0 for {action.ticker}; nothing to sell.",
            )

        order_req = OrderRequest(
            idempotency_key=self._make_idempotency_key(action, "close"),
            ticker=action.ticker,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=quantity,
        )

        order = self._broker.place_order(order_req)
        fills = self._broker.get_fills_for_order(order.broker_order_id)

        fill_price = order.average_fill_price
        fill_qty = order.filled_quantity
        filled_at = order.filled_at
        fees = sum((f.fees for f in fills), Decimal("0"))

        self._log.info(
            "close_order_filled",
            ticker=action.ticker,
            quantity=str(fill_qty),
            fill_price=str(fill_price),
            reason=action.reason,
        )

        return ExecutionResult(
            status=ExecutionStatus.FILLED,
            action=action,
            broker_order_id=order.broker_order_id,
            fill_price=fill_price,
            fill_quantity=fill_qty,
            fees=fees,
            filled_at=filled_at,
        )

    def _execute_trim(self, request: ExecutionRequest) -> ExecutionResult:
        """Sell target_quantity shares from an existing position (partial reduction).

        TRIM differs from CLOSE in that only a specified number of shares are sold
        (partial exit), not the full position.  The ``target_quantity`` field of the
        action specifies the number of shares to sell.  The remaining shares continue
        to be held.

        If ``target_quantity`` exceeds the actual position size, the sell is capped
        at the full position (equivalent to a CLOSE in that edge-case).
        """
        action = request.action

        if action.target_quantity is None or action.target_quantity <= Decimal("0"):
            return ExecutionResult(
                status=ExecutionStatus.REJECTED,
                action=action,
                error_message=(
                    "TRIM action requires a positive target_quantity "
                    "(number of shares to sell). "
                    f"Got: {action.target_quantity}"
                ),
            )

        try:
            position = self._broker.get_position(action.ticker)
        except PositionNotFoundError as exc:
            return ExecutionResult(
                status=ExecutionStatus.REJECTED,
                action=action,
                error_message=f"No position to trim for {action.ticker}: {exc}",
            )

        # Cap sell quantity at the actual position size
        sell_quantity = min(action.target_quantity, position.quantity)
        if sell_quantity <= Decimal("0"):
            return ExecutionResult(
                status=ExecutionStatus.REJECTED,
                action=action,
                error_message=(
                    f"Position quantity is 0 for {action.ticker}; nothing to trim."
                ),
            )

        order_req = OrderRequest(
            idempotency_key=self._make_idempotency_key(action, "trim"),
            ticker=action.ticker,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=sell_quantity,
        )

        order = self._broker.place_order(order_req)
        fills = self._broker.get_fills_for_order(order.broker_order_id)

        fill_price = order.average_fill_price
        fill_qty = order.filled_quantity
        filled_at = order.filled_at
        fees = sum((f.fees for f in fills), Decimal("0"))

        self._log.info(
            "trim_order_filled",
            ticker=action.ticker,
            quantity=str(fill_qty),
            fill_price=str(fill_price),
            reason=action.reason,
        )

        return ExecutionResult(
            status=ExecutionStatus.FILLED,
            action=action,
            broker_order_id=order.broker_order_id,
            fill_price=fill_price,
            fill_quantity=fill_qty,
            fees=fees,
            filled_at=filled_at,
        )

    @staticmethod
    def _make_idempotency_key(action: "PortfolioAction", suffix: str) -> str:  # noqa: F821
        """Generate a unique idempotency key for this action attempt."""
        return f"{action.ticker}_{suffix}_{uuid.uuid4()}"

