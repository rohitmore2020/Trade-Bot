"""
Average True Range (ATR) Indicator.

Calculates rolling volatility based on True Range across OHLC candles.
"""

from __future__ import annotations

from typing import List, Optional
from trade_bot.domain.models import Candle


class ATRCalculator:
    """
    Average True Range indicator for volatility and dynamic stop sizing.
    """

    def __init__(self, period: int = 14) -> None:
        self.period = period
        self._prev_candle: Optional[Candle] = None
        self._tr_history: List[float] = []
        self._current_atr: Optional[float] = None

    @property
    def is_ready(self) -> bool:
        return len(self._tr_history) >= self.period

    @property
    def value(self) -> Optional[float]:
        return self._current_atr

    def _calculate_true_range(self, candle: Candle, prev_candle: Optional[Candle]) -> float:
        if prev_candle is None:
            return candle.high - candle.low
        hl = candle.high - candle.low
        hpc = abs(candle.high - prev_candle.close)
        lpc = abs(candle.low - prev_candle.close)
        return max(hl, hpc, lpc)

    def update_candle(self, candle: Candle) -> Optional[float]:
        """Update ATR with a completed candle."""
        if not candle.is_closed:
            return self._current_atr

        tr = self._calculate_true_range(candle, self._prev_candle)
        self._prev_candle = candle
        self._tr_history.append(tr)

        if len(self._tr_history) == self.period:
            # Simple average for initial period
            self._current_atr = round(sum(self._tr_history) / self.period, 4)
        elif len(self._tr_history) > self.period and self._current_atr is not None:
            # Wilder's Smoothing: ATR = (Prior ATR * (period - 1) + Current TR) / period
            self._current_atr = round(((self._current_atr * (self.period - 1)) + tr) / self.period, 4)

        return self._current_atr

    def reset(self) -> None:
        """Reset ATR history."""
        self._prev_candle = None
        self._tr_history.clear()
        self._current_atr = None
