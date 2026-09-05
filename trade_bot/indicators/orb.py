"""
Opening Range Breakout (ORB) Levels Indicator.

Tracks the high, low, range, and status of the opening period (e.g. 09:15 - 09:30 IST).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional
from trade_bot.domain.models import Candle, Tick


@dataclass(frozen=True, slots=True)
class ORBLevels:
    """Calculated Opening Range levels."""
    high: float
    low: float
    range: float
    is_complete: bool
    calculated_at: datetime


class OpeningRangeCalculator:
    """
    Computes Opening Range high, low, and range for a configurable time window.
    """

    def __init__(
        self,
        symbol: str,
        start_time: time = time(9, 15, 0),
        end_time: time = time(9, 30, 0),
    ) -> None:
        self.symbol = symbol
        self.start_time = start_time
        self.end_time = end_time

        self._high: Optional[float] = None
        self._low: Optional[float] = None
        self._is_complete: bool = False
        self._last_timestamp: Optional[datetime] = None

    @property
    def is_complete(self) -> bool:
        return self._is_complete

    @property
    def high(self) -> Optional[float]:
        return self._high

    @property
    def low(self) -> Optional[float]:
        return self._low

    @property
    def range(self) -> Optional[float]:
        if self._high is not None and self._low is not None:
            return round(self._high - self._low, 4)
        return None

    def get_levels(self) -> Optional[ORBLevels]:
        if self._high is None or self._low is None or self._last_timestamp is None:
            return None
        return ORBLevels(
            high=self._high,
            low=self._low,
            range=round(self._high - self._low, 4),
            is_complete=self._is_complete,
            calculated_at=self._last_timestamp,
        )

    def update_tick(self, tick: Tick) -> Optional[ORBLevels]:
        """Update ORB with incoming tick."""
        t_time = tick.timestamp.time()
        self._last_timestamp = tick.timestamp

        if self.start_time <= t_time <= self.end_time:
            self._high = max(self._high, tick.last_price) if self._high is not None else tick.last_price
            self._low = min(self._low, tick.last_price) if self._low is not None else tick.last_price
        elif t_time > self.end_time and self._high is not None:
            self._is_complete = True

        return self.get_levels()

    def update_candle(self, candle: Candle) -> Optional[ORBLevels]:
        """Update ORB with incoming candle."""
        c_time = candle.timestamp.time()
        self._last_timestamp = candle.timestamp

        if self.start_time <= c_time <= self.end_time:
            self._high = max(self._high, candle.high) if self._high is not None else candle.high
            self._low = min(self._low, candle.low) if self._low is not None else candle.low
        elif c_time > self.end_time and self._high is not None:
            self._is_complete = True

        return self.get_levels()

    def reset(self) -> None:
        """Reset for next trading session."""
        self._high = None
        self._low = None
        self._is_complete = False
        self._last_timestamp = None
