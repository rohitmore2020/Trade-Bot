"""
Persistence Interfaces and Repositories.

Decouples domain logic from database and filesystem implementations.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Protocol, runtime_checkable
from trade_bot.domain.models import Candle, Order, Trade


@runtime_checkable
class IOrderRepository(Protocol):
    """Protocol for order storage and retrieval."""

    def save(self, order: Order) -> None:
        """Save or update order record."""
        ...

    def get_by_client_id(self, client_order_id: str) -> Optional[Order]:
        """Retrieve order by client order ID."""
        ...

    def get_all(self) -> List[Order]:
        """Retrieve all recorded orders."""
        ...


@runtime_checkable
class ITradeRepository(Protocol):
    """Protocol for execution trade storage and audit logs."""

    def save(self, trade: Trade) -> None:
        """Save trade fill."""
        ...

    def get_by_order_id(self, order_id: str) -> List[Trade]:
        """Retrieve fills for a given order ID."""
        ...

    def get_all(self) -> List[Trade]:
        """Retrieve all recorded trades."""
        ...


@runtime_checkable
class ICandleRepository(Protocol):
    """Protocol for historical and cached candle persistence."""

    def save_candle(self, candle: Candle) -> None:
        """Persist a single candle."""
        ...

    def save_candles(self, candles: List[Candle]) -> None:
        """Persist batch of candles."""
        ...

    def get_candles(
        self,
        symbol: str,
        timeframe_seconds: int,
        start_time: datetime,
        end_time: datetime,
    ) -> List[Candle]:
        """Fetch candles for symbol in time window."""
        ...
