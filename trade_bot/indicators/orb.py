"""
Opening Range Breakout (ORB) Levels Indicator.

Tracks the high, low, range, and status of the opening period (09:15 - 09:30 IST).
Strictly prevents look-ahead bias: opening range is NOT marked complete until 09:30:00 IST.
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
    Default: 09:15 to 09:30 IST (first 15 minutes of regular NSE trading).
    For 5-minute bars, bars opening at 09:15, 09:20, and 09:25 constitute the range.
    At 09:30 (close of 09:25 bar or arrival of 09:30 bar), the range is marked complete.
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
        self._bars_in_range: int = 0

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

    @property
    def bars_in_range(self) -> int:
        return self._bars_in_range

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

        if self.start_time <= t_time < self.end_time:
            self._high = max(self._high, tick.last_price) if self._high is not None else tick.last_price
            self._low = min(self._low, tick.last_price) if self._low is not None else tick.last_price
        elif t_time >= self.end_time and self._high is not None:
            self._is_complete = True

        return self.get_levels()

    def update_candle(self, candle: Candle) -> Optional[ORBLevels]:
        """
        Update ORB with incoming candle.
        Assumes candle timestamp is bar OPEN timestamp.
        Candles opening at 09:15, 09:20, 09:25 are inside [09:15, 09:30).
        A candle opening at 09:30 is outside and signals OR completion.
        """
        c_time = candle.timestamp.time()
        self._last_timestamp = candle.timestamp

        if self.start_time <= c_time < self.end_time:
            self._high = max(self._high, candle.high) if self._high is not None else candle.high
            self._low = min(self._low, candle.low) if self._low is not None else candle.low
            self._bars_in_range += 1
            # If 3 bars have been accumulated (for 5m timeframe, 09:15 to 09:30 = 3 bars)
            # and candle is closed, range can also be considered complete
            if candle.timeframe_seconds == 300 and self._bars_in_range >= 3 and candle.is_closed:
                self._is_complete = True
        elif c_time >= self.end_time and self._high is not None:
            self._is_complete = True

        return self.get_levels()

    def reset(self) -> None:
        """Reset for next trading session."""
        self._high = None
        self._low = None
        self._is_complete = False
        self._last_timestamp = None
        self._bars_in_range = 0
