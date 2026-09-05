"""
NIFTY Session VWAP and Market Regime Indicator.

Calculates intraday Session VWAP for the benchmark NIFTY 50 index.
Evaluates market regime strictly at candle t:
- Close > VWAP  -> BULLISH (Long only)
- Close < VWAP  -> BEARISH (Short only)
- Close == VWAP -> NEUTRAL (No trades)

Supports volume-weighted index calculation when futures/turnover volume is present,
and falls back to running cumulative typical-price average when cash spot index volume is 0.
"""

from __future__ import annotations

from typing import Optional
from trade_bot.domain.enums import MarketRegime
from trade_bot.domain.models import Candle


class NiftyRegimeIndicator:
    """
    Computes session VWAP for NIFTY and determines current market regime.
    """

    def __init__(self, symbol: str = "^NSEI") -> None:
        self.symbol = symbol
        self._cumulative_pv: float = 0.0
        self._cumulative_vol: int = 0
        self._cumulative_tp: float = 0.0
        self._bar_count: int = 0
        self._current_vwap: Optional[float] = None
        self._current_close: Optional[float] = None
        self._current_regime: MarketRegime = MarketRegime.NEUTRAL

    @property
    def is_ready(self) -> bool:
        return self._current_vwap is not None

    @property
    def vwap(self) -> Optional[float]:
        return self._current_vwap

    @property
    def last_close(self) -> Optional[float]:
        return self._current_close

    @property
    def regime(self) -> MarketRegime:
        return self._current_regime

    def update_candle(self, candle: Candle) -> MarketRegime:
        """
        Update NIFTY VWAP and regime using completed NIFTY candle.
        """
        if not candle.is_closed:
            return self._current_regime

        typical_price = (candle.high + candle.low + candle.close) / 3.0
        self._current_close = candle.close
        self._bar_count += 1

        if candle.volume > 0:
            self._cumulative_pv += typical_price * candle.volume
            self._cumulative_vol += candle.volume
            self._current_vwap = round(self._cumulative_pv / self._cumulative_vol, 4)
        else:
            # Spot cash index without volume: running cumulative typical price
            self._cumulative_tp += typical_price
            self._current_vwap = round(self._cumulative_tp / self._bar_count, 4)

        # Determine regime
        if self._current_vwap is not None:
            if candle.close > self._current_vwap:
                self._current_regime = MarketRegime.BULLISH
            elif candle.close < self._current_vwap:
                self._current_regime = MarketRegime.BEARISH
            else:
                self._current_regime = MarketRegime.NEUTRAL

        return self._current_regime

    def is_direction_allowed(self, is_long: bool) -> bool:
        """
        Check if trade direction matches current NIFTY regime.
        """
        if is_long:
            return self._current_regime == MarketRegime.BULLISH
        else:
            return self._current_regime == MarketRegime.BEARISH

    def reset(self) -> None:
        """Reset for new trading day session."""
        self._cumulative_pv = 0.0
        self._cumulative_vol = 0
        self._cumulative_tp = 0.0
        self._bar_count = 0
        self._current_vwap = None
        self._current_close = None
        self._current_regime = MarketRegime.NEUTRAL
