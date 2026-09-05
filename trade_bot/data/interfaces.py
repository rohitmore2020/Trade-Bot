"""
Market Data Interfaces and Abstractions.

Defines protocols for streaming tick providers, historical data loaders, and candle aggregators.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, List, Optional, Protocol, runtime_checkable
from trade_bot.domain.models import Candle, Tick


@runtime_checkable
class IMarketDataProvider(Protocol):
    """Protocol for real-time and replay market data feeds."""

    def connect(self) -> None:
        """Establish connection to data stream."""
        ...

    def disconnect(self) -> None:
        """Close connection to data stream."""
        ...

    def is_connected(self) -> bool:
        """Return True if connection is alive."""
        ...

    def subscribe(self, symbols: List[str]) -> None:
        """Subscribe to real-time quotes/ticks for given symbols."""
        ...

    def unsubscribe(self, symbols: List[str]) -> None:
        """Unsubscribe from real-time quotes/ticks."""
        ...

    def register_tick_handler(self, handler: Callable[[Tick], None]) -> None:
        """Register callback for incoming ticks."""
        ...


@runtime_checkable
class IHistoricalDataLoader(Protocol):
    """Protocol for fetching historical candle data."""

    def load_candles(
        self,
        symbol: str,
        timeframe_seconds: int,
        start_time: datetime,
        end_time: datetime,
    ) -> List[Candle]:
        """Load historical candles for a symbol within time range."""
        ...


@runtime_checkable
class ICandleAggregator(Protocol):
    """Protocol for aggregating streaming ticks into OHLCV candles."""

    def process_tick(self, tick: Tick) -> Optional[Candle]:
        """
        Process a single tick. Returns closed Candle if a candle boundary was crossed, else None.
        """
        ...

    def get_current_candle(self, symbol: str) -> Optional[Candle]:
        """Return the unclosed (forming) candle for a symbol."""
        ...

    def register_candle_handler(self, handler: Callable[[Candle], None]) -> None:
        """Register callback for when a new candle closes."""
        ...
