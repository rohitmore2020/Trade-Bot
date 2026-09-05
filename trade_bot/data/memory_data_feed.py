"""
In-Memory Market Data Feed.

Provides a deterministic streaming market data feed for testing, simulation, and backtesting.
"""

from __future__ import annotations

from typing import Callable, List, Optional
from trade_bot.data.interfaces import IMarketDataProvider
from trade_bot.domain.models import Tick


class InMemoryMarketDataFeed(IMarketDataProvider):
    """
    Simulated in-memory tick provider that streams prepared ticks sequentially.
    """

    def __init__(self) -> None:
        self._connected: bool = False
        self._subscriptions: set[str] = set()
        self._tick_handlers: List[Callable[[Tick], None]] = []

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def subscribe(self, symbols: List[str]) -> None:
        self._subscriptions.update(symbols)

    def unsubscribe(self, symbols: List[str]) -> None:
        self._subscriptions.difference_update(symbols)

    def get_subscriptions(self) -> set[str]:
        return set(self._subscriptions)

    def register_tick_handler(self, handler: Callable[[Tick], None]) -> None:
        self._tick_handlers.append(handler)

    def publish_tick(self, tick: Tick) -> None:
        """Push a single tick through registered callbacks if subscribed."""
        if not self._connected:
            return
        if not self._subscriptions or tick.symbol in self._subscriptions:
            for handler in self._tick_handlers:
                handler(tick)

    def publish_ticks(self, ticks: List[Tick]) -> None:
        """Push a sequence of ticks sequentially."""
        for tick in ticks:
            self.publish_tick(tick)
