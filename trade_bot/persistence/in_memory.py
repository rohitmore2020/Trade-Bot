"""
In-Memory Repositories.

Thread-safe, deterministic repositories for backtesting, simulations, and unit testing.
"""

from __future__ import annotations

from datetime import datetime
import threading
from typing import Dict, List, Optional
from trade_bot.domain.models import Candle, Order, Trade
from trade_bot.persistence.interfaces import (
    ICandleRepository,
    IOrderRepository,
    ITradeRepository,
)


class InMemoryOrderRepository(IOrderRepository):
    """In-memory storage for orders."""

    def __init__(self) -> None:
        self._orders: Dict[str, Order] = {}
        self._lock = threading.Lock()

    def save(self, order: Order) -> None:
        with self._lock:
            self._orders[order.client_order_id] = order

    def get_by_client_id(self, client_order_id: str) -> Optional[Order]:
        with self._lock:
            return self._orders.get(client_order_id)

    def get_all(self) -> List[Order]:
        with self._lock:
            return list(self._orders.values())


class InMemoryTradeRepository(ITradeRepository):
    """In-memory storage for execution trades."""

    def __init__(self) -> None:
        self._trades: List[Trade] = []
        self._lock = threading.Lock()

    def save(self, trade: Trade) -> None:
        with self._lock:
            self._trades.append(trade)

    def get_by_order_id(self, order_id: str) -> List[Trade]:
        with self._lock:
            return [t for t in self._trades if t.order_id == order_id]

    def get_all(self) -> List[Trade]:
        with self._lock:
            return list(self._trades)


class InMemoryCandleRepository(ICandleRepository):
    """In-memory storage for OHLCV candles."""

    def __init__(self) -> None:
        self._candles: Dict[str, List[Candle]] = {}
        self._lock = threading.Lock()

    def save_candle(self, candle: Candle) -> None:
        with self._lock:
            key = f"{candle.symbol}_{candle.timeframe_seconds}"
            self._candles.setdefault(key, []).append(candle)

    def save_candles(self, candles: List[Candle]) -> None:
        for c in candles:
            self.save_candle(c)

    def get_candles(
        self,
        symbol: str,
        timeframe_seconds: int,
        start_time: datetime,
        end_time: datetime,
    ) -> List[Candle]:
        with self._lock:
            key = f"{symbol}_{timeframe_seconds}"
            bars = self._candles.get(key, [])
            return [b for b in bars if start_time <= b.timestamp <= end_time]
