"""
Stock Indicator Coordinator.

Coordinates and orchestrates all deterministic technical indicators for a given instrument.
Strictly eliminates look-ahead bias:
- Volume SMA compares candle t's volume against average of candles (t-1, ..., t-10) BEFORE appending candle t.
- ORB levels are only marked complete at 09:30:00 IST.
- Produces immutable IndicatorSnapshot at each candle interval.
"""

from __future__ import annotations

from typing import Optional
from trade_bot.domain.enums import MarketRegime
from trade_bot.domain.models import Candle
from trade_bot.indicators.atr import ATRCalculator
from trade_bot.indicators.gap import GapCalculator, GapInfo
from trade_bot.indicators.interfaces import IndicatorSnapshot
from trade_bot.indicators.nifty_regime import NiftyRegimeIndicator
from trade_bot.indicators.orb import OpeningRangeCalculator
from trade_bot.indicators.vix_filter import IndiaVIXFilter
from trade_bot.indicators.volume_sma import VolumeSMACalculator
from trade_bot.indicators.vwap import VWAPCalculator


class StockIndicatorCoordinator:
    """
    Unified manager for an instrument's strategy indicators.
    """

    def __init__(
        self,
        symbol: str,
        atr_period: int = 14,
        volume_sma_period: int = 10,
        min_gap_pct: float = 1.0,
    ) -> None:
        self.symbol = symbol.upper().strip()
        self.vwap_calc = VWAPCalculator(self.symbol)
        self.atr_calc = ATRCalculator(period=atr_period)
        self.orb_calc = OpeningRangeCalculator(self.symbol)
        self.volume_sma_calc = VolumeSMACalculator(period=volume_sma_period)
        self.gap_calc = GapCalculator(min_gap_pct=min_gap_pct)

        self._day_gap_info: Optional[GapInfo] = None
        self._prev_day_close: Optional[float] = None
        self._is_first_candle_of_day: bool = True

    def set_previous_day_close(self, prev_close: float) -> None:
        """Set previous session's closing price for morning gap & ATR initialization."""
        self._prev_day_close = prev_close
        self.atr_calc.set_previous_close(prev_close)

    def set_initial_atr(self, atr_val: float) -> None:
        """Seed initial ATR baseline."""
        self.atr_calc.set_initial_atr(atr_val)

    def seed_volume_history(self, volumes: List[int]) -> None:
        """Pre-seed historical volume moving average."""
        self.volume_sma_calc.seed_historical_volumes(volumes)

    def start_new_session(self, prev_day_close: Optional[float] = None) -> None:
        """
        Handle daily session boundary (09:15:00 IST).
        Resets intraday indicators (VWAP, ORB) while maintaining rolling ATR and volume continuity.
        """
        self.vwap_calc.reset()
        self.orb_calc.reset()
        self._is_first_candle_of_day = True
        self._day_gap_info = None

        if prev_day_close is not None:
            self.set_previous_day_close(prev_day_close)

    def process_completed_candle(
        self,
        candle: Candle,
        nifty_indicator: Optional[NiftyRegimeIndicator] = None,
        vix_filter: Optional[IndiaVIXFilter] = None,
    ) -> IndicatorSnapshot:
        """
        Process a completed 5-minute candle and produce an immutable IndicatorSnapshot.
        Enforces strict evaluation ordering to prevent look-ahead bias.
        """
        # 1. Handle Day Open Gap on the first candle of the session
        if self._is_first_candle_of_day:
            if self._prev_day_close is not None:
                self._day_gap_info = self.gap_calc.calculate(candle.open, self._prev_day_close)
            self._is_first_candle_of_day = False

        # 2. Update ORB (bars from 09:15 to 09:30 IST)
        self.orb_calc.update_candle(candle)
        orb_levels = self.orb_calc.get_levels()

        # 3. Update Session VWAP with completed candle
        self.vwap_calc.update_candle(candle)

        # 4. Update ATR(14)
        self.atr_calc.update_candle(candle)

        # 5. Volume Evaluation:
        # Calculate surge ratio against PRIOR completed candles strictly BEFORE appending candle.volume
        prior_avg_vol = self.volume_sma_calc.get_prior_average_volume()
        surge_ratio = self.volume_sma_calc.calculate_surge_ratio(candle.volume)
        # Now append candle.volume to rolling history for subsequent candles
        self.volume_sma_calc.update_candle(candle)

        # 6. Market Regime & Volatility Filters
        n_close = nifty_indicator.last_close if nifty_indicator else None
        n_vwap = nifty_indicator.vwap if nifty_indicator else None
        n_regime = nifty_indicator.regime if nifty_indicator else MarketRegime.NEUTRAL

        vix_val = vix_filter.current_vix if vix_filter else None
        vix_ok = vix_filter.is_trading_allowed() if vix_filter else True

        gap_percentage = self._day_gap_info.gap_pct if self._day_gap_info else None

        return IndicatorSnapshot(
            symbol=self.symbol,
            timestamp=candle.timestamp,
            close=candle.close,
            vwap=self.vwap_calc.value,
            atr_14=self.atr_calc.value,
            orb_high=orb_levels.high if orb_levels else None,
            orb_low=orb_levels.low if orb_levels else None,
            orb_is_complete=orb_levels.is_complete if orb_levels else False,
            prev_avg_volume_10=prior_avg_vol,
            current_volume=candle.volume,
            volume_surge_ratio=surge_ratio,
            gap_pct=gap_percentage,
            nifty_close=n_close,
            nifty_vwap=n_vwap,
            nifty_regime=n_regime,
            india_vix=vix_val,
            vix_is_acceptable=vix_ok,
        )
