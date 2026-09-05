"""
Order Lifecycle Tracking Models.

Domain models and state containers specifically governing the multi-stage lifecycle of
trades: from signal through execution, protective SL, trailing, and exit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional

from trade_bot.domain.enums import OrderSide, OrderStatus, OrderType
from trade_bot.domain.models import Order, OrderRequest, Trade, utc_now


class TradeLifecycleState(str, Enum):
    """Lifecycle progression states for a managed trade from signal to termination."""
    PENDING_RISK = "PENDING_RISK"
    PENDING_SUBMIT = "PENDING_SUBMIT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    ACTIVE_PROTECTED = "ACTIVE_PROTECTED"
    ACTIVE_UNPROTECTED = "ACTIVE_UNPROTECTED"
    TRAILING = "TRAILING"
    EXIT_PENDING = "EXIT_PENDING"
    CLOSED = "CLOSED"
    EMERGENCY_EXITED = "EMERGENCY_EXITED"
    REJECTED = "REJECTED"


@dataclass
class ActiveTradeLifecycle:
    """
    Manages complete operational lifecycle for an active trade.
    Enforces 1:1 mapping between active entry, position, protective SL, and exits.
    """
    lifecycle_id: str
    symbol: str
    signal_id: str
    side: OrderSide
    target_quantity: int
    entry_order: Optional[Order] = None
    stop_loss_order: Optional[Order] = None
    exit_order: Optional[Order] = None
    lifecycle_state: TradeLifecycleState = TradeLifecycleState.PENDING_RISK
    current_stop_loss_price: Optional[float] = None
    trailing_watermark: Optional[float] = None
    filled_quantity: int = 0
    average_entry_price: float = 0.0
    is_emergency: bool = False
    emergency_reason: Optional[str] = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    trades: List[Trade] = field(default_factory=list)

    @property
    def is_terminal(self) -> bool:
        """Return True if the lifecycle has ended."""
        return self.lifecycle_state in (
            TradeLifecycleState.CLOSED,
            TradeLifecycleState.EMERGENCY_EXITED,
            TradeLifecycleState.REJECTED,
        )

    @property
    def is_active_in_market(self) -> bool:
        """Return True if an entry is in progress or position is open."""
        return self.lifecycle_state in (
            TradeLifecycleState.PENDING_SUBMIT,
            TradeLifecycleState.SUBMITTED,
            TradeLifecycleState.ACKNOWLEDGED,
            TradeLifecycleState.PARTIALLY_FILLED,
            TradeLifecycleState.ACTIVE_PROTECTED,
            TradeLifecycleState.ACTIVE_UNPROTECTED,
            TradeLifecycleState.TRAILING,
            TradeLifecycleState.EXIT_PENDING,
        )

    @property
    def has_active_protective_sl(self) -> bool:
        """Return True if a protective stop loss order is active."""
        if self.stop_loss_order is None:
            return False
        return self.stop_loss_order.is_active
