"""
Broker Adapter Interfaces and Contracts.

Enforces Ports & Adapters architecture. Backtest, Paper, and Live (Upstox) brokers
must implement the identical IBrokerAdapter contract.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Protocol, runtime_checkable
from trade_bot.domain.models import (
    AccountBalance,
    Order,
    OrderModification,
    OrderRequest,
    Position,
    Trade,
)


@runtime_checkable
class IBrokerAdapter(Protocol):
    """Protocol for broker communication adapters."""

    @property
    def name(self) -> str:
        """Name of the broker adapter."""
        ...

    def connect(self) -> None:
        """Establish session / authenticate with broker."""
        ...

    def disconnect(self) -> None:
        """Terminate broker session cleanly."""
        ...

    def is_connected(self) -> bool:
        """Return True if connection to broker is active."""
        ...

    def get_account_balance(self) -> AccountBalance:
        """Fetch current funds and margin from broker."""
        ...

    def get_positions(self) -> List[Position]:
        """Fetch confirmed positions from broker."""
        ...

    def get_orders(self) -> List[Order]:
        """Fetch all orders from broker."""
        ...

    def place_order(self, request: OrderRequest) -> str:
        """
        Submit order to broker.
        Returns:
            str: Broker-assigned order ID.
        """
        ...

    def modify_order(self, modification: OrderModification) -> bool:
        """Modify existing open order at broker."""
        ...

    def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel open order at broker."""
        ...

    def register_trade_callback(self, callback: Callable[[Trade], None]) -> None:
        """Register callback for asynchronous fill/execution notifications."""
        ...
