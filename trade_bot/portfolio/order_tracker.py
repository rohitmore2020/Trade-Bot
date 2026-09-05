"""
Order Lifecycle Tracker.

Enforces:
1. Strict order state machine transitions (CREATED -> SUBMITTED -> ACKNOWLEDGED -> PARTIALLY_FILLED -> FILLED, etc.)
2. Safe idempotent handling of duplicate order update events
3. Tracking filled quantities and average execution prices

Zero external infrastructure dependencies; pure domain logic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Set

from trade_bot.domain.enums import OrderStatus
from trade_bot.domain.exceptions import OrderNotFoundError
from trade_bot.domain.models import Order, Trade, utc_now
from trade_bot.domain.state import OrderStateMachine
from trade_bot.portfolio.models import Fill


class OrderLifecycleTracker:
    """
    Tracks order lifecycles with strict state machine validation and idempotent deduplication.
    """

    def __init__(self) -> None:
        self._orders: Dict[str, Order] = {}
        self._processed_event_ids: Set[str] = set()
        self._daily_order_count: int = 0

    @property
    def orders(self) -> Dict[str, Order]:
        return dict(self._orders)

    @property
    def daily_order_count(self) -> int:
        return self._daily_order_count

    def register_order(self, order: Order) -> Order:
        """Registers a new order in the tracker."""
        if order.client_order_id in self._orders:
            return self._orders[order.client_order_id]

        self._orders[order.client_order_id] = order
        self._daily_order_count += 1
        return order

    def get_order(self, client_order_id: str) -> Optional[Order]:
        """Retrieves order by client_order_id."""
        return self._orders.get(client_order_id)

    def transition_order(
        self,
        client_order_id: str,
        to_status: OrderStatus,
        reason: Optional[str] = None,
        event_id: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> Order:
        """
        Transitions order status adhering to OrderStateMachine.
        Idempotent: Duplicate event IDs or re-submitting current status returns cleanly.
        """
        # IDEMPOTENCY GUARD: Event ID deduplication
        if event_id and event_id in self._processed_event_ids:
            order = self._orders.get(client_order_id)
            if order:
                return order

        if event_id:
            self._processed_event_ids.add(event_id)

        order = self._orders.get(client_order_id)
        if not order:
            raise OrderNotFoundError(f"Order '{client_order_id}' not found in portfolio tracker")

        # Idempotent status check
        if order.status == to_status:
            return order

        # Perform strict state transition
        OrderStateMachine.transition(order, to_status, reason=reason, timestamp=timestamp)
        return order

    def record_fill_on_order(
        self,
        fill: Fill,
        event_id: Optional[str] = None,
    ) -> Order:
        """
        Records a confirmed fill on the corresponding order and updates status.
        """
        if event_id and event_id in self._processed_event_ids:
            order = self._orders.get(fill.client_order_id)
            if order:
                return order

        if event_id:
            self._processed_event_ids.add(event_id)

        order = self._orders.get(fill.client_order_id)
        if not order:
            raise OrderNotFoundError(f"Order '{fill.client_order_id}' not found for fill '{fill.fill_id}'")

        # Update filled quantity and weighted average fill price
        prev_qty = order.filled_quantity
        new_qty = prev_qty + fill.quantity
        if new_qty > 0:
            total_val = (order.average_fill_price * prev_qty) + (fill.price * fill.quantity)
            order.average_fill_price = round(total_val / new_qty, 4)
        order.filled_quantity = new_qty
        order.updated_at = fill.timestamp

        # Transition order state based on fill progression
        if order.filled_quantity >= order.quantity:
            self.transition_order(
                client_order_id=order.client_order_id,
                to_status=OrderStatus.FILLED,
                timestamp=fill.timestamp,
            )
        elif order.filled_quantity > 0 and order.status != OrderStatus.PARTIALLY_FILLED:
            self.transition_order(
                client_order_id=order.client_order_id,
                to_status=OrderStatus.PARTIALLY_FILLED,
                timestamp=fill.timestamp,
            )

        return order

    def get_open_orders(self) -> List[Order]:
        """Returns all currently active / non-terminal orders."""
        return [o for o in self._orders.values() if o.is_active]

    def reset_daily_session(self) -> None:
        """Resets daily counter at session open."""
        self._daily_order_count = 0
