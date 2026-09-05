"""
Execution Engine Interfaces and Protocols.

Manages order generation, routing, modification, cancellation, and fill confirmation.
"""

from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable
from trade_bot.domain.models import Order, OrderModification, OrderRequest, Trade


@runtime_checkable
class IExecutionEngine(Protocol):
    """Protocol for order routing, lifecycle tracking, and execution processing."""

    def submit_order(self, order_request: OrderRequest) -> Order:
        """Submit a new validated order request."""
        ...

    def cancel_order(self, client_order_id: str, reason: Optional[str] = None) -> Order:
        """Cancel an active order."""
        ...

    def modify_order(self, modification: OrderModification) -> Order:
        """Modify price or quantity of an active order."""
        ...

    def get_order(self, client_order_id: str) -> Optional[Order]:
        """Retrieve order state by client_order_id."""
        ...

    def get_active_orders(self) -> List[Order]:
        """Return all currently open/active orders."""
        ...

    def handle_fill(self, trade: Trade) -> Order:
        """Process execution fill callback from broker."""
        ...
