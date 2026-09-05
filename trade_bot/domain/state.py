"""
Deterministic State Machines and State Trackers.

Guarantees explicit, auditable transitions for Orders and Positions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional, Set
from trade_bot.domain.enums import OrderSide, OrderStatus, PositionSide
from trade_bot.domain.exceptions import (
    InvalidOrderStateTransitionError,
    StateInconsistencyError,
)
from trade_bot.domain.models import Order, Position, Trade, utc_now


class OrderStateMachine:
    """
    Strict state machine governing Order lifecycle transitions.
    Disallows illegal state jumps to prevent financial and state corruption.
    """

    VALID_TRANSITIONS: Dict[OrderStatus, Set[OrderStatus]] = {
        OrderStatus.CREATED: {
            OrderStatus.PENDING_SUBMIT,
            OrderStatus.SUBMITTED,
            OrderStatus.REJECTED,
            OrderStatus.CANCELLED,
        },
        OrderStatus.PENDING_SUBMIT: {
            OrderStatus.SUBMITTED,
            OrderStatus.ACKNOWLEDGED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCEL_REQUESTED,
            OrderStatus.REJECTED,
            OrderStatus.CANCELLED,
        },
        OrderStatus.SUBMITTED: {
            OrderStatus.ACKNOWLEDGED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCEL_REQUESTED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        },
        OrderStatus.ACKNOWLEDGED: {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCEL_REQUESTED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        },
        OrderStatus.PARTIALLY_FILLED: {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCEL_REQUESTED,
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
        },
        OrderStatus.CANCEL_REQUESTED: {
            OrderStatus.CANCELLED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        },
        OrderStatus.FILLED: set(),
        OrderStatus.CANCELLED: set(),
        OrderStatus.REJECTED: set(),
        OrderStatus.EXPIRED: set(),
    }

    @classmethod
    def can_transition(cls, from_status: OrderStatus, to_status: OrderStatus) -> bool:
        """Check if transition from `from_status` to `to_status` is legal."""
        if from_status == to_status:
            return True
        return to_status in cls.VALID_TRANSITIONS.get(from_status, set())

    @classmethod
    def transition(
        cls,
        order: Order,
        to_status: OrderStatus,
        reason: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """
        Transition order to `to_status` or raise `InvalidOrderStateTransitionError`.
        """
        if order.status == to_status:
            return

        if not cls.can_transition(order.status, to_status):
            raise InvalidOrderStateTransitionError(
                f"Illegal order transition from {order.status.value} to {to_status.value} "
                f"for client_order_id='{order.client_order_id}'",
                context={
                    "client_order_id": order.client_order_id,
                    "from_status": order.status.value,
                    "to_status": to_status.value,
                    "reason": reason,
                },
            )

        order.status = to_status
        order.updated_at = timestamp or utc_now()
        if reason:
            order.rejection_reason = reason


class PositionTracker:
    """
    Manages deterministic position state, cost basis (average entry price),
    realized P&L, and position flipping upon execution fills.
    """

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.position = Position(symbol=symbol)

    def apply_trade(self, trade: Trade) -> Position:
        """
        Update position and compute realized P&L based on incoming Trade fill.
        """
        if trade.symbol != self.symbol:
            raise StateInconsistencyError(
                f"Trade symbol {trade.symbol} does not match tracker symbol {self.symbol}"
            )

        pos = self.position
        fill_qty = trade.quantity if trade.side == OrderSide.BUY else -trade.quantity
        current_qty = pos.quantity
        new_qty = current_qty + fill_qty

        # Case 1: Opening or increasing position in the same direction
        if current_qty == 0 or (current_qty > 0 and fill_qty > 0) or (current_qty < 0 and fill_qty < 0):
            total_cost = (pos.average_price * abs(current_qty)) + (trade.price * abs(fill_qty))
            pos.quantity = new_qty
            pos.average_price = round(total_cost / abs(new_qty), 4) if new_qty != 0 else 0.0

        # Case 2: Closing or reducing position
        elif (current_qty > 0 and fill_qty < 0) or (current_qty < 0 and fill_qty > 0):
            closing_qty = min(abs(current_qty), abs(fill_qty))
            if current_qty > 0:
                pnl = (trade.price - pos.average_price) * closing_qty
            else:
                pnl = (pos.average_price - trade.price) * closing_qty

            pos.realized_pnl = round(pos.realized_pnl + pnl - trade.brokerage - trade.stt_and_taxes, 2)

            if abs(fill_qty) < abs(current_qty):
                pos.quantity = new_qty
            elif abs(fill_qty) == abs(current_qty):
                pos.quantity = 0
                pos.average_price = 0.0
                pos.unrealized_pnl = 0.0
            else:
                flipped_qty = abs(fill_qty) - abs(current_qty)
                pos.quantity = -flipped_qty if current_qty > 0 else flipped_qty
                pos.average_price = trade.price

        pos.last_price = trade.price
        pos.updated_at = trade.timestamp
        return pos
