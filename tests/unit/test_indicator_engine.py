"""
Unit tests for IndicatorEngine (Phase 6).

Comprehensive deterministic tests for all required behaviors:
1. Normal VWAP calculation
2. VWAP session reset on new trading day
3. Multiple trading sessions with overnight gap and continuous ATR
4. ATR calculation with Wilder's smoothing
5. Insufficient candles for ATR (returns None, not ready)
6. Opening-range calculation (09:15-09:30 IST window)
7. Previous 10-candle volume average (strictly prior bars)
8. Volume ratio calculation (surge multiplier)
9. Overnight gap calculation
10. NIFTY session VWAP
11. NIFTY market regime relative to VWAP
12. Malformed / empty data handling
13. Timestamp boundaries and look-ahead prevention
14. Completed vs currently forming candle isolation
15. Architectural purity verification (zero broker / infrastructure imports)
"""

from datetime import date, datetime, time, timedelta
import pytest
from trade_bot.config.constants import IST_TIMEZONE
from trade_bot.domain.enums import MarketRegime
from trade_bot.domain.exceptions import DomainValidationError
from trade_bot.domain.models import Candle
from trade_bot.indicators.engine import IndicatorEngine
from trade_bot.indicators.exceptions import (
    IndicatorValidationError,
    LookAheadViolationError,
)
from trade_bot.indicators.interfaces import MarketDataInput


@pytest.fixture
def engine() -> IndicatorEngine:
    return IndicatorEngine(
        atr_period=3,
        volume_sma_period=3,
        min_gap_pct=1.0,
    )


# ==============================================================================
# 1. Normal VWAP Calculation
# ==============================================================================

def test_normal_vwap_calculation(engine: IndicatorEngine) -> None:
    # Bar 1: TP = (105 + 95 + 100) / 3 = 100.0, Vol = 1000 -> PV = 100,000, VWAP = 100.0
    c1 = Candle(
        symbol="TCS",
        timestamp=datetime(2024, 1, 10, 9, 15, tzinfo=IST_TIMEZONE),
        open=98.0, high=105.0, low=95.0, close=100.0, volume=1000, timeframe_seconds=300, is_closed=True,
    )
    snap1 = engine.process_candle(c1)
    assert snap1.session_vwap == 100.0
    assert engine.get_session_vwap("TCS") == 100.0

    # Bar 2: TP = (115 + 105 + 110) / 3 = 110.0, Vol = 2000
    # Cum PV = 100,000 + 220,000 = 320,000, Cum Vol = 3000 -> VWAP = 320,000 / 3000 = 106.6667
    c2 = Candle(
        symbol="TCS",
        timestamp=datetime(2024, 1, 10, 9, 20, tzinfo=IST_TIMEZONE),
        open=106.0, high=115.0, low=105.0, close=110.0, volume=2000, timeframe_seconds=300, is_closed=True,
    )
    snap2 = engine.process_candle(c2)
    assert snap2.session_vwap == 106.6667
    assert engine.get_session_vwap("TCS") == 106.6667


# ==============================================================================
# 2. VWAP Session Reset on Date Boundary
# ==============================================================================

def test_vwap_session_reset(engine: IndicatorEngine) -> None:
    # Day 1 Bar
    c_day1 = Candle(
        symbol="INFY",
        timestamp=datetime(2024, 1, 10, 15, 25, tzinfo=IST_TIMEZONE),
        open=1500.0, high=1510.0, low=1495.0, close=1505.0, volume=10000, timeframe_seconds=300, is_closed=True,
    )
    engine.process_candle(c_day1)
    assert engine.get_session_vwap("INFY") is not None

    # Day 2 First Bar (09:15 next day): VWAP must reset purely to Day 2 bar
    # Day 2 Bar 1: TP = (1530 + 1515 + 1520) / 3 = 1521.6667, Vol = 2000
    c_day2 = Candle(
        symbol="INFY",
        timestamp=datetime(2024, 1, 11, 9, 15, tzinfo=IST_TIMEZONE),
        open=1518.0, high=1530.0, low=1515.0, close=1520.0, volume=2000, timeframe_seconds=300, is_closed=True,
    )
    snap_day2 = engine.process_candle(c_day2)
    assert snap_day2.session_vwap == 1521.6667
    assert engine.get_session_vwap("INFY") == 1521.6667


# ==============================================================================
# 3. Multiple Trading Sessions with Overnight Gap and Continuous ATR
# ==============================================================================

def test_multiple_trading_sessions(engine: IndicatorEngine) -> None:
    # Day 1: Feed 3 candles to warm up ATR(period=3)
    base_d1 = datetime(2024, 1, 10, 9, 15, tzinfo=IST_TIMEZONE)
    # C1: H=105, L=95, C=100 -> TR=10
    c1 = Candle("RELIANCE", base_d1, 98.0, 105.0, 95.0, 100.0, 1000, 300, True)
    # C2: H=108, L=98, C=105 -> TR=10
    c2 = Candle("RELIANCE", base_d1 + timedelta(minutes=5), 101.0, 108.0, 98.0, 105.0, 1000, 300, True)
    # C3: H=112, L=102, C=110 -> TR=10 -> Initial ATR = 10.0
    c3 = Candle("RELIANCE", base_d1 + timedelta(minutes=10), 106.0, 112.0, 102.0, 110.0, 1000, 300, True)

    engine.process_candle(c1)
    engine.process_candle(c2)
    snap3 = engine.process_candle(c3)
    assert snap3.atr_14 == 10.0
    assert snap3.close == 110.0

    # Day 2: Stock gaps up to Open=125.0 (overnight gap from Day 1 close of 110.0)
    # Morning Bar: Open=125.0, High=130.0, Low=122.0, Close=128.0
    # TR on morning bar = max(130 - 122 = 8, |130 - 110| = 20, |122 - 110| = 12) = 20.0!
    # Wilder's Smoothing: ATR = (Prior_ATR * 2 + TR) / 3 = (10.0 * 2 + 20.0) / 3 = 13.3333
    d2 = datetime(2024, 1, 11, 9, 15, tzinfo=IST_TIMEZONE)
    c_d2 = Candle("RELIANCE", d2, 125.0, 130.0, 122.0, 128.0, 2000, 300, True)
    snap_d2 = engine.process_candle(c_d2)

    # Gap % = ((125 - 110) / 110) * 100 = 13.6364%
    assert snap_d2.gap_pct == 13.6364
    assert snap_d2.atr_14 == 13.3333
    # VWAP on Day 2 must only reflect Day 2: TP = (130+122+128)/3 = 126.6667
    assert snap_d2.session_vwap == 126.6667


# ==============================================================================
# 4. ATR Calculation with Wilder's Smoothing
# ==============================================================================

def test_atr_calculation(engine: IndicatorEngine) -> None:
    dt = datetime(2024, 1, 10, 9, 15, tzinfo=IST_TIMEZONE)
    # 3 bars with TR = 10, 10, 10
    c1 = Candle("SBIN", dt, 98.0, 105.0, 95.0, 100.0, 1000, 300, True)
    c2 = Candle("SBIN", dt + timedelta(minutes=5), 101.0, 108.0, 98.0, 105.0, 1000, 300, True)
    c3 = Candle("SBIN", dt + timedelta(minutes=10), 106.0, 112.0, 102.0, 110.0, 1000, 300, True)
    engine.process_candle(c1)
    engine.process_candle(c2)
    s3 = engine.process_candle(c3)
    assert s3.atr_14 == 10.0

    # 4th bar with TR = 16: H=126, L=110, C=120, PrevClose=110 -> TR = max(16, 16, 0) = 16.0
    # Wilder's: (10.0 * 2 + 16.0) / 3 = 12.0
    c4 = Candle("SBIN", dt + timedelta(minutes=15), 112.0, 126.0, 110.0, 120.0, 1000, 300, True)
    s4 = engine.process_candle(c4)
    assert s4.atr_14 == 12.0


# ==============================================================================
# 5. Insufficient Candles for ATR
# ==============================================================================

def test_insufficient_candles_for_atr(engine: IndicatorEngine) -> None:
    dt = datetime(2024, 1, 10, 9, 15, tzinfo=IST_TIMEZONE)
    c1 = Candle("WIPRO", dt, 400.0, 405.0, 395.0, 402.0, 1000, 300, True)
    s1 = engine.process_candle(c1)
    # Only 1 candle processed for period=3
    assert s1.atr_14 is None
    assert engine.get_atr("WIPRO") is None


# ==============================================================================
# 6. Opening Range Calculation (09:15 - 09:30 IST)
# ==============================================================================

def test_opening_range_calculation(engine: IndicatorEngine) -> None:
    dt = datetime(2024, 1, 10, 9, 15, tzinfo=IST_TIMEZONE)
    # Bar 1 (09:15): H=500, L=490
    c1 = Candle("AXISBANK", dt, 492.0, 500.0, 490.0, 498.0, 1000, 300, True)
    s1 = engine.process_candle(c1)
    assert s1.orb_high == 500.0
    assert s1.orb_low == 490.0
    assert s1.orb_is_complete is False

    # Bar 2 (09:20): H=510, L=485
    c2 = Candle("AXISBANK", dt + timedelta(minutes=5), 498.0, 510.0, 485.0, 505.0, 1000, 300, True)
    s2 = engine.process_candle(c2)
    assert s2.orb_high == 510.0
    assert s2.orb_low == 485.0
    assert s2.orb_is_complete is False

    # Bar 3 (09:25): H=508, L=495 -> Closes at 09:30 -> OR complete!
    c3 = Candle("AXISBANK", dt + timedelta(minutes=10), 505.0, 508.0, 495.0, 502.0, 1000, 300, True)
    s3 = engine.process_candle(c3)
    assert s3.orb_high == 510.0
    assert s3.orb_low == 485.0
    assert s3.orb_is_complete is True

    # Bar 4 (09:30): Outside OR window -> Must NOT change OR high/low
    c4 = Candle("AXISBANK", dt + timedelta(minutes=15), 502.0, 530.0, 470.0, 520.0, 1000, 300, True)
    s4 = engine.process_candle(c4)
    assert s4.orb_high == 510.0
    assert s4.orb_low == 485.0
    assert s4.orb_is_complete is True


# ==============================================================================
# 7. Previous 10-Candle Volume Average & 8. Volume Ratio
# ==============================================================================

def test_volume_average_and_ratio(engine: IndicatorEngine) -> None:
    dt = datetime(2024, 1, 10, 9, 15, tzinfo=IST_TIMEZONE)
    # Ingest 3 candles with volumes: 1000, 2000, 3000 (Average = 2000.0)
    c1 = Candle("HDFCBANK", dt, 100.0, 105.0, 95.0, 100.0, 1000, 300, True)
    c2 = Candle("HDFCBANK", dt + timedelta(minutes=5), 101.0, 106.0, 96.0, 102.0, 2000, 300, True)
    c3 = Candle("HDFCBANK", dt + timedelta(minutes=10), 103.0, 108.0, 98.0, 105.0, 3000, 300, True)
    engine.process_candle(c1)
    engine.process_candle(c2)
    engine.process_candle(c3)

    # 4th candle arrives with volume = 4000
    # Prior average volume MUST be 2000.0 (strictly excluding candle 4's volume)
    # Volume Ratio = 4000 / 2000 = 2.0
    c4 = Candle("HDFCBANK", dt + timedelta(minutes=15), 105.0, 110.0, 100.0, 108.0, 4000, 300, True)
    s4 = engine.process_candle(c4)

    assert s4.prev_avg_volume_10 == 2000.0
    assert s4.volume_ratio == 2.0
    # After bar 4 is committed, rolling history is [2000, 3000, 4000] -> new average for next bar is 3000.0
    assert engine.get_volume_average("HDFCBANK") == 3000.0


# ==============================================================================
# 9. Overnight Gap Calculation
# ==============================================================================

def test_gap_calculation(engine: IndicatorEngine) -> None:
    # Set day 1 close to 2000.0
    c_d1 = Candle("KOTAKBANK", datetime(2024, 1, 10, 15, 25, tzinfo=IST_TIMEZONE), 1995.0, 2005.0, 1990.0, 2000.0, 1000, 300, True)
    engine.process_candle(c_d1)

    # Day 2 opens at 2030.0 -> Gap = +1.5%
    c_d2 = Candle("KOTAKBANK", datetime(2024, 1, 11, 9, 15, tzinfo=IST_TIMEZONE), 2030.0, 2040.0, 2025.0, 2035.0, 1000, 300, True)
    s_d2 = engine.process_candle(c_d2)
    assert s_d2.gap_pct == 1.5
    assert engine.get_gap_pct("KOTAKBANK") == 1.5


# ==============================================================================
# 10. NIFTY VWAP & 11. Market Regime
# ==============================================================================

def test_nifty_vwap_and_regime(engine: IndicatorEngine) -> None:
    dt = datetime(2024, 1, 10, 9, 15, tzinfo=IST_TIMEZONE)
    # Stock candle
    c_stock = Candle("TCS", dt, 3000.0, 3010.0, 2995.0, 3005.0, 1000, 300, True)

    # NIFTY Candle: TP = (21550+21450+21500)/3 = 21500.0, Close = 21550.0 > VWAP -> BULLISH
    c_nifty = Candle("^NSEI", dt, 21480.0, 21550.0, 21450.0, 21550.0, 5000, 300, True)

    snap = engine.process(MarketDataInput(candle=c_stock, nifty_candle=c_nifty, india_vix=15.0))
    # NIFTY TP = (21550+21450+21550)/3 = 21516.6667
    assert snap.nifty_vwap == 21516.6667
    assert snap.nifty_regime == MarketRegime.BULLISH
    assert engine.get_nifty_regime() == MarketRegime.BULLISH
    assert snap.india_vix == 15.0
    assert snap.vix_is_acceptable is True


# ==============================================================================
# 12. Malformed / Empty Data Handling
# ==============================================================================

def test_malformed_data_handling(engine: IndicatorEngine) -> None:
    dt = datetime(2024, 1, 10, 9, 15, tzinfo=IST_TIMEZONE)

    # Inverted High < Low should be caught
    with pytest.raises((DomainValidationError, IndicatorValidationError)):
        Candle("TCS", dt, 100.0, 90.0, 110.0, 105.0, 1000, 300, True)

    # Negative volume should raise validation error
    with pytest.raises((DomainValidationError, IndicatorValidationError)):
        c_bad_vol = Candle("TCS", dt, 100.0, 110.0, 95.0, 105.0, -100, 300, True)
        engine.process_candle(c_bad_vol)

    # Negative VIX should raise IndicatorValidationError
    c_ok = Candle("TCS", dt, 100.0, 110.0, 95.0, 105.0, 100, 300, True)
    with pytest.raises(IndicatorValidationError):
        engine.process_candle(c_ok, india_vix=-5.0)


# ==============================================================================
# 13. Timestamp Boundaries and Look-Ahead Prevention
# ==============================================================================

def test_timestamp_boundaries_and_lookahead(engine: IndicatorEngine) -> None:
    dt1 = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    c1 = Candle("TCS", dt1, 100.0, 105.0, 95.0, 100.0, 1000, 300, True)
    engine.process_candle(c1)

    # Out-of-order candle (9:55 arrives after 10:00) -> Must raise LookAheadViolationError!
    dt_past = datetime(2024, 1, 10, 9, 55, tzinfo=IST_TIMEZONE)
    c_past = Candle("TCS", dt_past, 98.0, 102.0, 96.0, 100.0, 1000, 300, True)
    with pytest.raises(LookAheadViolationError):
        engine.process_candle(c_past)

    # NIFTY timestamp in the future relative to stock candle
    dt2 = datetime(2024, 1, 10, 10, 5, tzinfo=IST_TIMEZONE)
    c_stock = Candle("TCS", dt2, 100.0, 105.0, 95.0, 100.0, 1000, 300, True)
    c_future_nifty = Candle("^NSEI", dt2 + timedelta(minutes=5), 21500.0, 21550.0, 21450.0, 21500.0, 5000, 300, True)

    with pytest.raises(LookAheadViolationError):
        engine.process(MarketDataInput(candle=c_stock, nifty_candle=c_future_nifty))


# ==============================================================================
# 14. Completed vs Currently Forming Candle Isolation
# ==============================================================================

def test_completed_vs_forming_candle_isolation(engine: IndicatorEngine) -> None:
    dt = datetime(2024, 1, 10, 9, 15, tzinfo=IST_TIMEZONE)
    # Bar 1 Completed: TP = 100.0, Vol = 1000 -> VWAP = 100.0
    c1 = Candle("INFY", dt, 98.0, 105.0, 95.0, 100.0, 1000, 300, True)
    engine.process_candle(c1)
    assert engine.get_session_vwap("INFY") == 100.0

    # Bar 2 is currently FORMING (not closed) with high price TP = (205+195+200)/3 = 200.0, Vol = 1000
    # Preview VWAP would be (100000 + 200000) / 2000 = 150.0
    c2_forming = Candle("INFY", dt + timedelta(minutes=5), 195.0, 205.0, 195.0, 200.0, 1000, 300, False)
    snap_forming = engine.process_candle(c2_forming, is_forming=True)
    assert snap_forming.session_vwap == 150.0

    # Permanent engine state MUST remain unpolluted at 100.0!
    assert engine.get_session_vwap("INFY") == 100.0


# ==============================================================================
# 15. Pure Business Logic Architecture Verification
# ==============================================================================

def test_pure_business_logic_zero_infrastructure_imports() -> None:
    import sys
    # Verify that trade_bot.indicators does not import broker or database packages
    forbidden_tokens = ["upstox", "websocket", "requests", "httpx", "sqlalchemy"]
    for mod_name in sys.modules:
        if mod_name.startswith("trade_bot.indicators"):
            module = sys.modules[mod_name]
            module_file = getattr(module, "__file__", "")
            if module_file:
                with open(module_file, "r", encoding="utf-8") as f:
                    content = f.read().lower()
                    for token in forbidden_tokens:
                        assert f"import {token}" not in content, f"Forbidden import '{token}' in {module_file}"
                        assert f"from {token}" not in content, f"Forbidden from import '{token}' in {module_file}"
