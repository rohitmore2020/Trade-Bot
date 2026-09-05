"""
Unit tests for Technical Indicators (Phase 4).

Deterministic calculations with known manual input/output cases:
- Session VWAP
- 5-minute ATR(14) with Wilder's smoothing & session gap handling
- Opening Range (09:15 - 09:30 IST)
- Previous 10-candle Volume Moving Average (zero look-ahead)
- NIFTY Session VWAP & Market Regime Filter
- India VIX Volatility Filter
- Overnight Gap % Calculation
- StockIndicatorCoordinator Pipeline Snapshot
"""

from datetime import datetime, time, timedelta
import pytest
from trade_bot.config.constants import IST_TIMEZONE
from trade_bot.domain.enums import MarketRegime
from trade_bot.domain.models import Candle, Tick
from trade_bot.indicators.atr import ATRCalculator
from trade_bot.indicators.coordinator import StockIndicatorCoordinator
from trade_bot.indicators.gap import GapCalculator, GapDirection
from trade_bot.indicators.nifty_regime import NiftyRegimeIndicator
from trade_bot.indicators.orb import OpeningRangeCalculator
from trade_bot.indicators.vix_filter import IndiaVIXFilter, VIXRegime
from trade_bot.indicators.volume_sma import VolumeSMACalculator
from trade_bot.indicators.vwap import VWAPCalculator


# ==============================================================================
# 1. Session VWAP Tests
# ==============================================================================

def test_session_vwap_deterministic_calculation_and_reset() -> None:
    vwap = VWAPCalculator(symbol="TCS")
    assert vwap.is_ready is False
    assert vwap.value is None

    # Candle 1: High=105, Low=95, Close=100 -> Typical Price = (105+95+100)/3 = 100.0, Vol=1000
    # Cumulative PV = 100.0 * 1000 = 100,000, Cum Vol = 1000 -> VWAP = 100.0
    c1 = Candle(
        symbol="TCS",
        timestamp=datetime(2024, 1, 10, 9, 15, tzinfo=IST_TIMEZONE),
        open=98.0,
        high=105.0,
        low=95.0,
        close=100.0,
        volume=1000,
        timeframe_seconds=300,
        is_closed=True,
    )
    val1 = vwap.update_candle(c1)
    assert val1 == 100.0
    assert vwap.value == 100.0
    assert vwap.cumulative_volume == 1000

    # Test preview_candle without mutating state
    c_preview = Candle(
        symbol="TCS",
        timestamp=datetime(2024, 1, 10, 9, 20, tzinfo=IST_TIMEZONE),
        open=112.0,
        high=120.0,
        low=110.0,
        close=115.0,  # TP = (120+110+115)/3 = 115.0
        volume=1000,
        timeframe_seconds=300,
        is_closed=False,
    )
    # Hypothetical PV = 100,000 + 115,000 = 215,000, Vol = 2000 -> Preview VWAP = 107.5
    preview_val = vwap.preview_candle(c_preview)
    assert preview_val == 107.5
    # Permanent VWAP must remain unchanged at 100.0
    assert vwap.value == 100.0
    assert vwap.cumulative_volume == 1000

    # Candle 2 (Completed): TP = (115+105+110)/3 = 110.0, Vol=2000
    # Cum PV = 100,000 + (110.0 * 2000) = 320,000, Cum Vol = 3000 -> VWAP = 320,000 / 3000 = 106.6667
    c2 = Candle(
        symbol="TCS",
        timestamp=datetime(2024, 1, 10, 9, 20, tzinfo=IST_TIMEZONE),
        open=106.0,
        high=115.0,
        low=105.0,
        close=110.0,
        volume=2000,
        timeframe_seconds=300,
        is_closed=True,
    )
    val2 = vwap.update_candle(c2)
    assert val2 == 106.6667

    # Reset for next session
    vwap.reset()
    assert vwap.is_ready is False
    assert vwap.value is None
    assert vwap.cumulative_volume == 0


# ==============================================================================
# 2. 5-Minute ATR(14) with Wilder's Smoothing
# ==============================================================================

def test_5min_atr14_exact_wilders_smoothing() -> None:
    # Use period=3 for explicit manual arithmetic check
    atr = ATRCalculator(period=3)

    # Candle 1: H=110, L=100, C=105 (no prev close) -> TR1 = 110 - 100 = 10.0
    c1 = Candle("INFY", datetime(2024, 1, 10, 9, 15, tzinfo=IST_TIMEZONE), 102.0, 110.0, 100.0, 105.0, 500, 300, True)
    atr.update_candle(c1)
    assert atr.is_ready is False

    # Candle 2: H=112, L=104, C=108, Prev Close=105 -> TR2 = max(8, |112-105|=7, |104-105|=1) = 8.0
    c2 = Candle("INFY", datetime(2024, 1, 10, 9, 20, tzinfo=IST_TIMEZONE), 105.0, 112.0, 104.0, 108.0, 500, 300, True)
    atr.update_candle(c2)
    assert atr.is_ready is False

    # Candle 3: H=118, L=106, C=115, Prev Close=108 -> TR3 = max(12, |118-108|=10, |106-108|=2) = 12.0
    # Period 3 initial ATR = (10.0 + 8.0 + 12.0) / 3 = 30.0 / 3 = 10.0
    c3 = Candle("INFY", datetime(2024, 1, 10, 9, 25, tzinfo=IST_TIMEZONE), 108.0, 118.0, 106.0, 115.0, 500, 300, True)
    val3 = atr.update_candle(c3)
    assert atr.is_ready is True
    assert val3 == 10.0

    # Candle 4: H=125, L=110, C=120, Prev Close=115 -> TR4 = max(15, |125-115|=10, |110-115|=5) = 15.0
    # Wilder's formula: ATR = (Prior_ATR * (period - 1) + TR) / period
    # ATR4 = (10.0 * 2 + 15.0) / 3 = 35.0 / 3 = 11.6667
    c4 = Candle("INFY", datetime(2024, 1, 10, 9, 30, tzinfo=IST_TIMEZONE), 115.0, 125.0, 110.0, 120.0, 500, 300, True)
    val4 = atr.update_candle(c4)
    assert val4 == 11.6667


def test_atr_cross_session_gap_handling() -> None:
    atr = ATRCalculator(period=2)
    # Feed yesterday's closing bar: Close = 500.0
    c_yesterday = Candle("RELIANCE", datetime(2024, 1, 9, 15, 25, tzinfo=IST_TIMEZONE), 498.0, 502.0, 497.0, 500.0, 1000, 300, True)
    atr.update_candle(c_yesterday)

    # Today's morning bar gaps up to 520.0: H=525, L=518, C=522
    # TR = max(525 - 518 = 7, |525 - 500| = 25, |518 - 500| = 18) = 25.0
    c_today = Candle("RELIANCE", datetime(2024, 1, 10, 9, 15, tzinfo=IST_TIMEZONE), 520.0, 525.0, 518.0, 522.0, 1500, 300, True)
    tr_morning = atr.calculate_true_range(c_today)
    assert tr_morning == 25.0  # Correctly captured the overnight gap!


# ==============================================================================
# 3. Opening Range (09:15 - 09:30 IST)
# ==============================================================================

def test_opening_range_15min_window() -> None:
    orb = OpeningRangeCalculator(symbol="SBIN")

    # Bar 1: 09:15 to 09:20 (H=600, L=590)
    c1 = Candle("SBIN", datetime(2024, 1, 10, 9, 15, tzinfo=IST_TIMEZONE), 592.0, 600.0, 590.0, 598.0, 1000, 300, True)
    orb.update_candle(c1)
    assert orb.high == 600.0
    assert orb.low == 590.0
    assert orb.is_complete is False

    # Bar 2: 09:20 to 09:25 (H=610, L=585)
    c2 = Candle("SBIN", datetime(2024, 1, 10, 9, 20, tzinfo=IST_TIMEZONE), 598.0, 610.0, 585.0, 605.0, 1200, 300, True)
    orb.update_candle(c2)
    assert orb.high == 610.0
    assert orb.low == 585.0
    assert orb.is_complete is False

    # Bar 3: 09:25 to 09:30 (H=608, L=595) - Closes at 09:30:00 IST -> ORB completed
    c3 = Candle("SBIN", datetime(2024, 1, 10, 9, 25, tzinfo=IST_TIMEZONE), 605.0, 608.0, 595.0, 600.0, 900, 300, True)
    orb.update_candle(c3)
    assert orb.high == 610.0
    assert orb.low == 585.0
    assert orb.range == 25.0
    assert orb.is_complete is True

    # Bar 4: 09:30 to 09:35 (H=630, L=570) - Outside OR window; MUST NOT expand the range!
    c4 = Candle("SBIN", datetime(2024, 1, 10, 9, 30, tzinfo=IST_TIMEZONE), 600.0, 630.0, 570.0, 620.0, 2000, 300, True)
    orb.update_candle(c4)
    assert orb.high == 610.0  # Kept locked
    assert orb.low == 585.0   # Kept locked
    assert orb.range == 25.0


# ==============================================================================
# 4. Previous 10-Candle Volume SMA (Strict Look-Ahead Prevention)
# ==============================================================================

def test_previous_10_candle_volume_sma_zero_lookahead() -> None:
    vol_sma = VolumeSMACalculator(period=10)

    # Feed 10 completed candles with known volumes: 100, 200, 300, ..., 1000
    # Sum = 5500, Average = 550.0
    volumes = [100 * i for i in range(1, 11)]
    base_dt = datetime(2024, 1, 10, 9, 15, tzinfo=IST_TIMEZONE)
    for idx, v in enumerate(volumes):
        c = Candle("HDFCBANK", base_dt + timedelta(minutes=idx * 5), 100.0, 105.0, 95.0, 100.0, v, 300, True)
        vol_sma.update_candle(c)

    assert vol_sma.is_ready is True
    # Reference average volume strictly prior to candle 11
    prior_avg = vol_sma.get_prior_average_volume()
    assert prior_avg == 550.0

    # Candle 11 arrives with volume = 1100 (which is 2.0x the prior average)
    current_vol = 1100
    surge_ratio = vol_sma.calculate_surge_ratio(current_vol)
    assert surge_ratio == 2.0
    assert vol_sma.is_volume_surge(current_vol, multiplier=1.5) is True

    # Ensure calculating surge ratio did NOT append current_vol to rolling history
    assert vol_sma.get_prior_average_volume() == 550.0

    # After candle 11 is processed and signal evaluation is completed, we commit it:
    c11 = Candle("HDFCBANK", datetime(2024, 1, 10, 10, 5, tzinfo=IST_TIMEZONE), 100.0, 105.0, 95.0, 100.0, current_vol, 300, True)
    new_avg = vol_sma.update_candle(c11)
    # Oldest volume (100) dropped, newest (1100) added -> sum = 5500 - 100 + 1100 = 6500 -> Avg = 650.0
    assert new_avg == 650.0


# ==============================================================================
# 5. NIFTY Session VWAP & Market Regime Indicator
# ==============================================================================

def test_nifty_session_vwap_and_regime_filter() -> None:
    nifty = NiftyRegimeIndicator()

    # NIFTY Candle 1: TP = (21550 + 21450 + 21500) / 3 = 21500.0, Vol = 10,000
    # VWAP = 21500.0, Close = 21500.0 -> NEUTRAL
    c1 = Candle("^NSEI", datetime(2024, 1, 10, 9, 15, tzinfo=IST_TIMEZONE), 21480.0, 21550.0, 21450.0, 21500.0, 10000, 300, True)
    regime1 = nifty.update_candle(c1)
    assert nifty.vwap == 21500.0
    assert regime1 == MarketRegime.NEUTRAL
    assert nifty.is_direction_allowed(is_long=True) is False

    # NIFTY Candle 2: Strong rally, Close = 21600.0 > VWAP
    c2 = Candle("^NSEI", datetime(2024, 1, 10, 9, 20, tzinfo=IST_TIMEZONE), 21500.0, 21620.0, 21490.0, 21600.0, 15000, 300, True)
    regime2 = nifty.update_candle(c2)
    assert regime2 == MarketRegime.BULLISH
    assert nifty.is_direction_allowed(is_long=True) is True
    assert nifty.is_direction_allowed(is_long=False) is False

    # NIFTY Candle 3: Massive drop, Close falls below VWAP
    c3 = Candle("^NSEI", datetime(2024, 1, 10, 9, 25, tzinfo=IST_TIMEZONE), 21600.0, 21610.0, 21300.0, 21350.0, 30000, 300, True)
    regime3 = nifty.update_candle(c3)
    assert regime3 == MarketRegime.BEARISH
    assert nifty.is_direction_allowed(is_long=False) is True
    assert nifty.is_direction_allowed(is_long=True) is False


# ==============================================================================
# 6. India VIX Volatility Filter
# ==============================================================================

def test_india_vix_filter_regimes() -> None:
    vix = IndiaVIXFilter(min_vix=10.0, max_vix=24.0, extreme_vix=28.0)

    assert vix.update_vix(9.5) == VIXRegime.LOW
    assert vix.is_ideal_regime() is False
    assert vix.is_trading_allowed() is True

    assert vix.update_vix(15.2) == VIXRegime.NORMAL
    assert vix.is_ideal_regime() is True
    assert vix.is_trading_allowed() is True

    assert vix.update_vix(25.5) == VIXRegime.ELEVATED
    assert vix.is_ideal_regime() is False
    assert vix.is_trading_allowed() is True

    assert vix.update_vix(29.8) == VIXRegime.EXTREME
    assert vix.is_ideal_regime() is False
    assert vix.is_trading_allowed() is False  # Blocks trading during extreme volatility event


# ==============================================================================
# 7. Overnight Gap Calculator
# ==============================================================================

def test_overnight_gap_calculation() -> None:
    gap_calc = GapCalculator(min_gap_pct=1.0)

    # Gap Up: Prev Close = 1000, Open = 1025 -> +2.5%
    gap_up = gap_calc.calculate(day_open=1025.0, prev_close=1000.0)
    assert gap_up is not None
    assert gap_up.gap_points == 25.0
    assert gap_up.gap_pct == 2.5
    assert gap_up.direction == GapDirection.UP
    assert gap_up.meets_threshold is True

    # Gap Down: Prev Close = 1000, Open = 980 -> -2.0%
    gap_down = gap_calc.calculate(day_open=980.0, prev_close=1000.0)
    assert gap_down is not None
    assert gap_down.gap_points == -20.0
    assert gap_down.gap_pct == -2.0
    assert gap_down.absolute_gap_pct == 2.0
    assert gap_down.direction == GapDirection.DOWN
    assert gap_down.meets_threshold is True

    # Negligible Gap: Prev Close = 1000, Open = 1005 -> +0.5% (below 1.0% threshold)
    small_gap = gap_calc.calculate(day_open=1005.0, prev_close=1000.0)
    assert small_gap is not None
    assert small_gap.gap_pct == 0.5
    assert small_gap.meets_threshold is False


# ==============================================================================
# 8. StockIndicatorCoordinator End-to-End Snapshot
# ==============================================================================

def test_stock_indicator_coordinator_pipeline() -> None:
    coord = StockIndicatorCoordinator(
        symbol="RELIANCE",
        atr_period=3,
        volume_sma_period=3,
        min_gap_pct=1.0,
    )
    coord.start_new_session(prev_day_close=2500.0)

    # Market context
    nifty = NiftyRegimeIndicator()
    nifty_c = Candle("^NSEI", datetime(2024, 1, 10, 9, 15, tzinfo=IST_TIMEZONE), 21500.0, 21550.0, 21480.0, 21540.0, 5000, 300, True)
    nifty.update_candle(nifty_c)

    vix = IndiaVIXFilter()
    vix.update_vix(14.5)

    # Bar 1 (09:15): Open=2530 (Gap = +1.2%), H=2540, L=2520, C=2535, Vol=1000
    c1 = Candle("RELIANCE", datetime(2024, 1, 10, 9, 15, tzinfo=IST_TIMEZONE), 2530.0, 2540.0, 2520.0, 2535.0, 1000, 300, True)
    snap1 = coord.process_completed_candle(c1, nifty_indicator=nifty, vix_filter=vix)

    assert snap1.symbol == "RELIANCE"
    assert snap1.close == 2535.0
    assert snap1.gap_pct == 1.2  # ((2530 - 2500) / 2500) * 100 = 1.2%
    assert snap1.orb_high == 2540.0
    assert snap1.orb_low == 2520.0
    assert snap1.orb_is_complete is False
    assert snap1.prev_avg_volume_10 is None  # Not enough history yet
    assert snap1.nifty_regime == MarketRegime.BULLISH
    assert snap1.vix_is_acceptable is True
