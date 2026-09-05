"""
Volume-Weighted Average Price (VWAP) Indicator.

Computes intraday cumulative VWAP from streaming ticks or candles.
Resets at session start to ensure pure intraday calculation.
"""

from __future__ import annotations

from typing import Optional
from trade_bot.domain.models import Candle, Tick


class VWAPCalculator:
    """
    Intraday Volume-Weighted Average Price calculator.
    Formula: VWAP = sum(Price * Volume) / sum(Volume)
    """

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self._cumulative_pv: float = 0.0  # Sum of (Price * Volume)
        self._cumulative_volume: int = 0  # Sum of Volume
        self._current_vwap: Optional[float] = None

    @property
    def is_ready(self) -> bool:
        return self._cumulative_volume > 0

    @property
    def value(self) -> Optional[float]:
        return self._current_vwap

    @property
    def cumulative_volume(self) -> int:
        return self._cumulative_volume

    def update_tick(self, tick: Tick) -> Optional[float]:
        """Update VWAP using a single tick."""
        if tick.volume <= 0:
            return self._current_vwap

        self._cumulative_pv += tick.last_price * tick.volume
        self._cumulative_volume += tick.volume
        self._current_vwap = round(self._cumulative_pv / self._cumulative_volume, 4)
        return self._current_vwap

    def update_candle(self, candle: Candle) -> Optional[float]:
        """
        Update VWAP using a candle typical price: (High + Low + Close) / 3.
        """
        if candle.volume <= 0:
            return self._current_vwap

        typical_price = (candle.high + candle.low + candle.close) / 3.0
        self._cumulative_pv += typical_price * candle.volume
        self._cumulative_volume += candle.volume
        self._current_vwap = round(self._cumulative_pv / self._cumulative_volume, 4)
        return self._current_vwap

    def reset(self) -> None:
        """Reset cumulative stats at start of trading day."""
        self._cumulative_pv = 0.0
        self._cumulative_volume = 0
        self._current_vwap = None
