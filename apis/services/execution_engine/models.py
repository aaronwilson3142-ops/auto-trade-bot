"""
Execution engine domain models (plain dataclasses, no ORM dependency).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional

from services.portfolio_engine.models import PortfolioAction


class ExecutionStatus(str, Enum):
    FILLED = "filled"
    REJECTED = "rejected"       # broker rejected the order
    BLOCKED = "blocked"         # kill switch or pre-execution guard
    ERROR = "error"             # unexpected exception during execution


@dataclass
class ExecutionRequest:
    """Wraps a risk-approved PortfolioAction with the price needed for sizing.

    For OPEN actions: current_price is required to convert target_notional →
    integer share quantity (floor division, no fractional shares in MVP).

    For CLOSE actions: current_price is informational; the execution engine
    reads the held quantity from the broker adapter's position list.
    """

    action: PortfolioAction
    current_price: Decimal          # market price at submission time


@dataclass
class ExecutionResult:
    """Outcome of a single ExecutionRequest."""

    status: ExecutionStatus
    action: PortfolioAction
    broker_order_id: Optional[str] = None
    fill_price: Optional[Decimal] = None
    fill_quantity: Optional[Decimal] = None
    fees: Decimal = Decimal("0")
    filled_at: Optional[dt.datetime] = None
    error_message: Optional[str] = None

