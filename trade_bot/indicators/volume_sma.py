"""
Rolling Volume Moving Average Indicator.

Computes the average volume over previous N completed candles (default: 10 bars).
CRITICAL FOR ZERO LOOK-AHEAD BIAS:
When evaluating candle t, the reference average volume is computed STRICTLY from
candles prior to t (candles t-1, t-2, ..., t-10). Candle t's volume is evaluated
against this prior average and only appended to the rolling history after candle t closes.
"""

from __future__ import annotations

from collections import deque
from typing import Deque, List, Optional
from trade_bot.domain.models import Candle


class VolumeSMACalculator:
    """
    Rolling simple moving average of volume over previous completed candles.
    """

    def __init__(self, period: int = 10, min_periods: Optional[int] = None) -> None:
        self.period = period
        self.min_periods = min_periods if min_periods is not None else period
        self._history: Deque[int] = deque(maxlen=period)

    @property
    def is_ready(self) -> bool:
        """True if sufficient prior completed candles are stored in history."""
        return len(self._history) >= self.min_periods

    @property
    def current_count(self) -> int:
        return len(self._history)

    @property
    def history(self) -> List[int]:
        return list(self._history)

    def get_prior_average_volume(self) -> Optional[float]:
        """
        Returns the average volume of candles strictly prior to the current candle.
        Returns None if fewer than min_periods completed candles are present.
        """
        if not self.is_ready:
            return None
        return round(sum(self._history) / len(self._history), 2)

    def calculate_surge_ratio(self, current_volume: int) -> Optional[float]:
        """
        Calculates current_volume / prior_average_volume without mutating rolling history.
        """
        prior_avg = self.get_prior_average_volume()
        if prior_avg is None or prior_avg == 0:
            return None
        return round(current_volume / prior_avg, 4)

    def is_volume_surge(self, current_volume: int, multiplier: float = 1.5) -> bool:
        """
        Checks if current_volume >= multiplier * prior_average_volume.
        """
        prior_avg = self.get_prior_average_volume()
        if prior_avg is None:
            return False
        return current_volume >= (multiplier * prior_avg)

    def update_candle(self, candle: Candle) -> Optional[float]:
        """
        Records a completed candle's volume into rolling history.
        Must ONLY be called after the signal evaluation for candle t is complete!
        """
        if not candle.is_closed:
            return self.get_prior_average_volume()

        self._history.append(candle.volume)
        return self.get_prior_average_volume()

    def seed_historical_volumes(self, volumes: List[int]) -> None:
        """
        Pre-seed calculator with historical completed candle volumes (e.g. from prior session).
        """
        for vol in volumes:
            self._history.append(vol)

    def reset(self) -> None:
        """Reset rolling volume history."""
        self._history.clear()
