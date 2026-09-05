"""
Unit tests for VWAP, ORB, and ATR Indicators.
"""

from datetime import datetime, time, timezone
from trade_bot.domain.models import Candle, Tick
from trade_bot.indicators.atr import ATRCalculator
from trade_bot.indicators.orb import OpeningRangeCalculator
from trade_bot.indicators.vwap import VWAPCalculator


def test_vwap_calculation_streaming_ticks() -> None:
    vwap = VWAPCalculator(symbol="TCS")
    assert vwap.is_ready is False

    # Tick 1: Price 3000, Vol 100 -> PV = 300000, Vol = 100 -> VWAP = 3000
    t1 = Tick(
        symbol="TCS",
        timestamp=datetime.now(timezone.utc),
        last_price=3000.0,
        volume=100,
    )
    val1 = vwap.update_tick(t1)
    assert val1 == 3000.0

    # Tick 2: Price 3100, Vol 100 -> PV = 300000 + 310000 = 610000, Vol = 200 -> VWAP = 3050
    t2 = Tick(
        symbol="TCS",
        timestamp=datetime.now(timezone.utc),
        last_price=3100.0,
        volume=100,
    )
    val2 = vwap.update_tick(t2)
    assert val2 == 3050.0


def test_orb_levels_tracking() -> None:
    orb = OpeningRangeCalculator(
        symbol="RELIANCE",
        start_time=time(9, 15, 0),
        end_time=time(9, 30, 0),
    )

    # In range tick 1: 09:16 @ 2500
    orb.update_tick(
        Tick(
            symbol="RELIANCE",
            timestamp=datetime(2026, 9, 5, 9, 16, 0),
            last_price=2500.0,
            volume=10,
        )
    )

    # In range tick 2: 09:20 @ 2550
    orb.update_tick(
        Tick(
            symbol="RELIANCE",
            timestamp=datetime(2026, 9, 5, 9, 20, 0),
            last_price=2550.0,
            volume=10,
        )
    )

    # In range tick 3: 09:25 @ 2480
    orb.update_tick(
        Tick(
            symbol="RELIANCE",
            timestamp=datetime(2026, 9, 5, 9, 25, 0),
            last_price=2480.0,
            volume=10,
        )
    )

    assert orb.high == 2550.0
    assert orb.low == 2480.0
    assert orb.range == 70.0
    assert orb.is_complete is False

    # Out of range tick: 09:31
    orb.update_tick(
        Tick(
            symbol="RELIANCE",
            timestamp=datetime(2026, 9, 5, 9, 31, 0),
            last_price=2560.0,
            volume=10,
        )
    )
    assert orb.is_complete is True
    # Range should remain locked
    assert orb.high == 2550.0
    assert orb.low == 2480.0


def test_atr_calculator() -> None:
    atr = ATRCalculator(period=3)
    # Feed 3 closed candles
    c1 = Candle(
        symbol="INFY",
        timestamp=datetime(2026, 9, 5, 9, 15),
        open=100.0,
        high=105.0,
        low=95.0,
        close=102.0,
        volume=100,
        is_closed=True,
    )
    c2 = Candle(
        symbol="INFY",
        timestamp=datetime(2026, 9, 5, 9, 16),
        open=102.0,
        high=108.0,
        low=101.0,
        close=107.0,
        volume=100,
        is_closed=True,
    )
    c3 = Candle(
        symbol="INFY",
        timestamp=datetime(2026, 9, 5, 9, 17),
        open=107.0,
        high=110.0,
        low=104.0,
        close=105.0,
        volume=100,
        is_closed=True,
    )

    atr.update_candle(c1)
    atr.update_candle(c2)
    val = atr.update_candle(c3)

    assert atr.is_ready is True
    assert val is not None
    assert val > 0.0
