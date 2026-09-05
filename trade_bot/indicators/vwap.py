"""
Volume-Weighted Average Price (VWAP) Indicator.

Computes intraday cumulative Session VWAP from completed candles or streaming ticks.
Strictly distinguishes completed candles from currently forming candles to prevent look-ahead bias.
Resets at daily session start.
"""

from __future__ import annotations

from typing import Optional
from trade_bot.domain.models import Candle, Tick


class VWAPCalculator:
    """
    Intraday Volume-Weighted Average Price calculator.
    Formula: VWAP = sum(Typical Price * Volume) / sum(Volume)
    where Typical Price = (High + Low + Close) / 3.0
    """

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self._cumulative_pv: float = 0.0  # Sum of (Typical Price * Volume)
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

    @property
    def cumulative_pv(self) -> float:
        return self._cumulative_pv

    def update_candle(self, candle: Candle) -> Optional[float]:
        """
        Update VWAP with a completed candle.
        Only completed candles mutate permanent session VWAP state.
        """
        if candle.volume <= 0:
            return self._current_vwap

        typical_price = (candle.high + candle.low + candle.close) / 3.0
        self._cumulative_pv += typical_price * candle.volume
        self._cumulative_volume += candle.volume
        self._current_vwap = round(self._cumulative_pv / self._cumulative_volume, 4)
        return self._current_vwap

    def preview_candle(self, candle: Candle) -> Optional[float]:
        """
        Compute temporary VWAP including a forming/unclosed candle without mutating permanent state.
        """
        if candle.volume <= 0:
            return self._current_vwap
        typical_price = (candle.high + candle.low + candle.close) / 3.0
        temp_pv = self._cumulative_pv + (typical_price * candle.volume)
        temp_vol = self._cumulative_volume + candle.volume
        if temp_vol == 0:
            return self._current_vwap
        return round(temp_pv / temp_vol, 4)

    def update_tick(self, tick: Tick) -> Optional[float]:
        """Update VWAP using a single tick."""
        if tick.volume <= 0:
            return self._current_vwap

        self._cumulative_pv += tick.last_price * tick.volume
        self._cumulative_volume += tick.volume
        self._current_vwap = round(self._cumulative_pv / self._cumulative_volume, 4)
        return self._current_vwap

    def reset(self) -> None:
        """Reset cumulative stats at start of trading day."""
        self._cumulative_pv = 0.0
        self._cumulative_volume = 0
        self._current_vwap = None
