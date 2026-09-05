"""
Average True Range (ATR) Indicator.

Calculates rolling volatility based on True Range across OHLC candles.
Uses Wilder's Smoothing Method (period 14).
Preserves cross-session close for accurate overnight gap True Range calculation.
"""

from __future__ import annotations

from typing import List, Optional
from trade_bot.domain.models import Candle


class ATRCalculator:
    """
    Average True Range indicator for volatility and dynamic stop sizing.
    Uses Wilder's Smoothing: ATR = (Prior ATR * (period - 1) + Current TR) / period
    """

    def __init__(self, period: int = 14) -> None:
        self.period = period
        self._prev_candle: Optional[Candle] = None
        self._tr_history: List[float] = []
        self._current_atr: Optional[float] = None

    @property
    def is_ready(self) -> bool:
        """True once at least 'period' candles have been processed."""
        return self._current_atr is not None

    @property
    def value(self) -> Optional[float]:
        return self._current_atr

    @property
    def prev_close(self) -> Optional[float]:
        return self._prev_candle.close if self._prev_candle else None

    def calculate_true_range(self, candle: Candle, prev_close: Optional[float] = None) -> float:
        """
        Calculate True Range for a candle given previous close.
        TR = max(High - Low, |High - PrevClose|, |Low - PrevClose|)
        """
        hl = candle.high - candle.low
        ref_close = prev_close if prev_close is not None else (self._prev_candle.close if self._prev_candle else None)
        if ref_close is None:
            return hl
        hpc = abs(candle.high - ref_close)
        lpc = abs(candle.low - ref_close)
        return max(hl, hpc, lpc)

    def update_candle(self, candle: Candle) -> Optional[float]:
        """
        Update ATR with a completed candle.
        Only completed candles mutate permanent ATR state.
        """
        if not candle.is_closed:
            return self._current_atr

        tr = self.calculate_true_range(candle)
        self._prev_candle = candle
        self._tr_history.append(tr)

        if len(self._tr_history) == self.period:
            # Simple average for the initial baseline period
            self._current_atr = round(sum(self._tr_history) / self.period, 4)
        elif len(self._tr_history) > self.period and self._current_atr is not None:
            # Wilder's Smoothing
            self._current_atr = round(
                ((self._current_atr * (self.period - 1)) + tr) / self.period, 4
            )

        return self._current_atr

    def preview_candle(self, candle: Candle) -> Optional[float]:
        """
        Compute hypothetical ATR if forming candle closes now, without mutating permanent state.
        """
        tr = self.calculate_true_range(candle)
        if self._current_atr is None:
            if len(self._tr_history) + 1 == self.period:
                combined = self._tr_history + [tr]
                return round(sum(combined) / self.period, 4)
            return None
        return round(((self._current_atr * (self.period - 1)) + tr) / self.period, 4)

    def set_initial_atr(self, atr_val: float) -> None:
        """
        Explicitly seed initial ATR baseline (e.g. from historical data or pre-market screening).
        """
        self._current_atr = round(float(atr_val), 4)

    def set_previous_close(self, prev_close: float) -> None:
        """
        Explicitly set previous day's official close for the first morning bar TR calculation.
        """
        if self._prev_candle is not None:
            # Create a synthetic boundary candle to hold the previous close
            self._prev_candle = Candle(
                symbol=self._prev_candle.symbol,
                timestamp=self._prev_candle.timestamp,
                open=prev_close,
                high=prev_close,
                low=prev_close,
                close=prev_close,
                volume=0,
                timeframe_seconds=self._prev_candle.timeframe_seconds,
                is_closed=True,
            )

    def reset(self) -> None:
        """Reset ATR state entirely."""
        self._prev_candle = None
        self._tr_history.clear()
        self._current_atr = None
