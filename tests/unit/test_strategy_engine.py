"""
Unit Tests for VWAP-ORB Strategy Engine (Phase 5).

Covers all 12 required behavioral and safety specifications:
1. Valid Long Signal Generation
2. Invalid Long Signal Rejection (e.g. no pullback)
3. Valid Short Signal Generation
4. Invalid Short Signal Rejection (e.g. not bearish candle)
5. VWAP Invalidation Exit
6. Stop Loss Exit
7. Trailing Stop Ratchet & Exit
8. Time Exit (14:30:00 IST)
9. Market Regime Rejection
10. Volume Rejection
11. ORB Condition Rejection
12. Duplicate Signal Prevention & Re-entry Rules
"""

from datetime import datetime, time, timedelta
import pytest
from trade_bot.config.constants import IST_TIMEZONE
from trade_bot.domain.enums import MarketRegime, SignalDirection
from trade_bot.domain.models import Candle
from trade_bot.indicators.interfaces import IndicatorSnapshot
from trade_bot.strategy.engine import VWAPORBStrategyEngine
from trade_bot.strategy.models import VwapOrbSignal, VwapOrbStrategyConfig


@pytest.fixture
def strategy_engine() -> VWAPORBStrategyEngine:
    config = VwapOrbStrategyConfig(
        window_start=time(9, 45, 0),
        window_end=time(14, 30, 0),
        pullback_tolerance_long=1.002,
        pullback_tolerance_short=0.998,
        volume_surge_multiplier=1.5,
        limit_order_offset_pct=0.0005,  # 0.05%
        stop_loss_atr_mult=1.5,
        trailing_stop_atr_mult=2.0,
        max_open_positions=3,
        max_daily_trades=6,
    )
    return VWAPORBStrategyEngine(config=config, max_trades_per_symbol=2)


# ==============================================================================
# 1. Valid Long Signal
# ==============================================================================

def test_valid_long_signal(strategy_engine: VWAPORBStrategyEngine) -> None:
    # 10:00 AM bar (inside window 09:45 - 14:30)
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    # Candle: Open=2500, High=2515, Low=2498, Close=2510, Vol=2000
    # Bullish: Close (2510) > Open (2500)
    candle = Candle("RELIANCE", ts, 2500.0, 2515.0, 2498.0, 2510.0, 2000, 300, True)

    snapshot = IndicatorSnapshot(
        symbol="RELIANCE",
        timestamp=ts,
        close=2510.0,
        vwap=2500.0,  # Close (2510) > VWAP (2500)
        atr_14=10.0,
        orb_high=2505.0,  # Close (2510) > ORB High (2505)
        orb_low=2480.0,
        orb_is_complete=True,
        prev_avg_volume_10=1000.0,
        current_volume=2000,
        volume_surge_ratio=2.0,  # 2.0 >= 1.5
        gap_pct=1.5,
        nifty_regime=MarketRegime.BULLISH,
        vix_is_acceptable=True,
    )

    # Pullback condition: Low (2498) <= VWAP * 1.002 (2500 * 1.002 = 2505.0) -> True!
    signal = strategy_engine.process_candle(candle, snapshot)

    assert signal is not None
    assert isinstance(signal, VwapOrbSignal)
    assert signal.symbol == "RELIANCE"
    assert signal.direction == SignalDirection.LONG
    assert signal.reason == "LONG_ENTRY"
    assert signal.signal_price == 2510.0
    # Limit entry = Close * 1.0005 = 2510.0 * 1.0005 = 2511.25
    assert signal.entry_price == 2511.25
    # Stop price = Entry - 1.5 * ATR = 2511.25 - (1.5 * 10.0) = 2496.25
    assert signal.stop_price == 2496.25
    assert signal.atr == 10.0
    assert signal.vwap == 2500.0
    assert signal.or_high == 2505.0
    assert signal.volume_ratio == 2.0
    assert signal.strategy_version == "1.0.0"

    # Engine internal state should record active trade
    assert strategy_engine.is_symbol_in_active_trade("RELIANCE") is True
    assert strategy_engine.active_positions_count == 1
    assert strategy_engine.daily_trade_count == 1


# ==============================================================================
# 2. Invalid Long Signal (e.g. No Pullback)
# ==============================================================================

def test_invalid_long_no_pullback(strategy_engine: VWAPORBStrategyEngine) -> None:
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    # Candle Low is 2510, which is > VWAP * 1.002 (2500 * 1.002 = 2505) -> No pullback to VWAP
    candle = Candle("RELIANCE", ts, 2512.0, 2525.0, 2510.0, 2520.0, 2000, 300, True)

    snapshot = IndicatorSnapshot(
        symbol="RELIANCE",
        timestamp=ts,
        close=2520.0,
        vwap=2500.0,
        atr_14=10.0,
        orb_high=2505.0,
        orb_low=2480.0,
        orb_is_complete=True,
        prev_avg_volume_10=1000.0,
        current_volume=2000,
        volume_surge_ratio=2.0,
        gap_pct=1.5,
        nifty_regime=MarketRegime.BULLISH,
        vix_is_acceptable=True,
    )

    signal = strategy_engine.process_candle(candle, snapshot)
    assert signal is None
    assert strategy_engine.is_symbol_in_active_trade("RELIANCE") is False


# ==============================================================================
# 3. Valid Short Signal
# ==============================================================================

def test_valid_short_signal(strategy_engine: VWAPORBStrategyEngine) -> None:
    ts = datetime(2024, 1, 10, 10, 15, tzinfo=IST_TIMEZONE)
    # Candle: Open=2490, High=2502, Low=2475, Close=2480, Vol=3000
    # Bearish: Close (2480) < Open (2490)
    candle = Candle("INFY", ts, 2490.0, 2502.0, 2475.0, 2480.0, 3000, 300, True)

    snapshot = IndicatorSnapshot(
        symbol="INFY",
        timestamp=ts,
        close=2480.0,
        vwap=2500.0,  # Close (2480) < VWAP (2500)
        atr_14=12.0,
        orb_high=2520.0,
        orb_low=2490.0,  # Close (2480) < ORB Low (2490)
        orb_is_complete=True,
        prev_avg_volume_10=1500.0,
        current_volume=3000,
        volume_surge_ratio=2.0,  # 2.0 >= 1.5
        gap_pct=-1.2,
        nifty_regime=MarketRegime.BEARISH,
        vix_is_acceptable=True,
    )

    # Pullback condition: High (2502) >= VWAP * 0.998 (2500 * 0.998 = 2495.0) -> True!
    signal = strategy_engine.process_candle(candle, snapshot)

    assert signal is not None
    assert signal.direction == SignalDirection.SHORT
    assert signal.reason == "SHORT_ENTRY"
    assert signal.signal_price == 2480.0
    # Limit entry = Close * 0.9995 = 2480.0 * 0.9995 = 2478.76
    assert signal.entry_price == 2478.76
    # Stop price = Entry + 1.5 * ATR = 2478.76 + (1.5 * 12.0) = 2496.76
    assert signal.stop_price == 2496.76
    assert signal.strategy_version == "1.0.0"

    assert strategy_engine.is_symbol_in_active_trade("INFY") is True


# ==============================================================================
# 4. Invalid Short Signal (e.g. Not Bearish Bar)
# ==============================================================================

def test_invalid_short_not_bearish(strategy_engine: VWAPORBStrategyEngine) -> None:
    ts = datetime(2024, 1, 10, 10, 15, tzinfo=IST_TIMEZONE)
    # Green/Bullish candle: Close (2485) > Open (2480)
    candle = Candle("INFY", ts, 2480.0, 2502.0, 2475.0, 2485.0, 3000, 300, True)

    snapshot = IndicatorSnapshot(
        symbol="INFY",
        timestamp=ts,
        close=2485.0,
        vwap=2500.0,
        atr_14=12.0,
        orb_high=2520.0,
        orb_low=2490.0,
        orb_is_complete=True,
        prev_avg_volume_10=1500.0,
        current_volume=3000,
        volume_surge_ratio=2.0,
        gap_pct=-1.2,
        nifty_regime=MarketRegime.BEARISH,
        vix_is_acceptable=True,
    )

    signal = strategy_engine.process_candle(candle, snapshot)
    assert signal is None
    assert strategy_engine.is_symbol_in_active_trade("INFY") is False


# ==============================================================================
# 5. VWAP Invalidation Exit
# ==============================================================================

def test_vwap_failure_exit(strategy_engine: VWAPORBStrategyEngine) -> None:
    # First, enter a Long position
    test_valid_long_signal(strategy_engine)
    assert strategy_engine.is_symbol_in_active_trade("RELIANCE") is True

    # Next candle at 10:05: Stock breaks down and closes below VWAP (2500)
    ts = datetime(2024, 1, 10, 10, 5, tzinfo=IST_TIMEZONE)
    candle = Candle("RELIANCE", ts, 2505.0, 2508.0, 2490.0, 2495.0, 1200, 300, True)

    snapshot = IndicatorSnapshot(
        symbol="RELIANCE",
        timestamp=ts,
        close=2495.0,
        vwap=2500.0,  # Close (2495) < VWAP (2500) -> VWAP Invalidation!
        atr_14=10.0,
        orb_high=2505.0,
        orb_low=2480.0,
        orb_is_complete=True,
        prev_avg_volume_10=1000.0,
        current_volume=1200,
        volume_surge_ratio=1.2,
        gap_pct=1.5,
        nifty_regime=MarketRegime.BULLISH,
        vix_is_acceptable=True,
    )

    exit_signal = strategy_engine.process_candle(candle, snapshot)

    assert exit_signal is not None
    assert exit_signal.direction == SignalDirection.FLAT
    assert exit_signal.reason == "VWAP_FAILURE"
    assert exit_signal.signal_price == 2495.0
    assert strategy_engine.is_symbol_in_active_trade("RELIANCE") is False


# ==============================================================================
# 6. Stop Loss Exit
# ==============================================================================

def test_stop_loss_exit(strategy_engine: VWAPORBStrategyEngine) -> None:
    test_valid_long_signal(strategy_engine)
    trade = strategy_engine.active_trades["RELIANCE"]
    initial_sl = trade.initial_stop  # 2496.26

    # Next candle drops sharply: Low = 2490.0 <= initial_sl (2496.26)
    ts = datetime(2024, 1, 10, 10, 5, tzinfo=IST_TIMEZONE)
    candle = Candle("RELIANCE", ts, 2505.0, 2506.0, 2490.0, 2492.0, 1500, 300, True)

    snapshot = IndicatorSnapshot(
        symbol="RELIANCE",
        timestamp=ts,
        close=2492.0,
        vwap=2491.0,  # VWAP below close so SL triggers before VWAP
        atr_14=10.0,
        orb_high=2505.0,
        orb_low=2480.0,
        orb_is_complete=True,
        prev_avg_volume_10=1000.0,
        current_volume=1500,
        volume_surge_ratio=1.5,
        gap_pct=1.5,
        nifty_regime=MarketRegime.BULLISH,
        vix_is_acceptable=True,
    )

    exit_signal = strategy_engine.process_candle(candle, snapshot)

    assert exit_signal is not None
    assert exit_signal.direction == SignalDirection.FLAT
    assert exit_signal.reason == "STOP_LOSS"
    assert exit_signal.signal_price == initial_sl
    assert strategy_engine.is_symbol_in_active_trade("RELIANCE") is False


# ==============================================================================
# 7. Trailing Stop Ratchet & Exit
# ==============================================================================

def test_trailing_stop_ratchet_and_exit(strategy_engine: VWAPORBStrategyEngine) -> None:
    test_valid_long_signal(strategy_engine)
    trade = strategy_engine.active_trades["RELIANCE"]
    initial_sl = trade.initial_stop  # 2496.26

    # Candle 1 (10:05): Stock rallies to High = 2540.0
    # Trailing Stop = Peak - 2.0 * ATR = 2540 - (2.0 * 10) = 2520.0
    ts1 = datetime(2024, 1, 10, 10, 5, tzinfo=IST_TIMEZONE)
    c1 = Candle("RELIANCE", ts1, 2526.0, 2540.0, 2525.0, 2535.0, 2000, 300, True)
    snap1 = IndicatorSnapshot(
        symbol="RELIANCE", timestamp=ts1, close=2535.0, vwap=2505.0, atr_14=10.0,
        orb_high=2505.0, orb_low=2480.0, orb_is_complete=True, prev_avg_volume_10=1000.0,
        current_volume=2000, volume_surge_ratio=2.0, gap_pct=1.5, nifty_regime=MarketRegime.BULLISH,
        vix_is_acceptable=True,
    )
    sig1 = strategy_engine.process_candle(c1, snap1)
    # Position remains open
    assert sig1 is None
    # Current stop ratcheted to 2520.0 (well above initial SL 2496.26)
    assert trade.current_stop == 2520.0
    assert trade.highest_price == 2540.0

    # Candle 2 (10:10): Pullback drops Low to 2518.0 <= current_stop (2520.0)
    ts2 = datetime(2024, 1, 10, 10, 10, tzinfo=IST_TIMEZONE)
    c2 = Candle("RELIANCE", ts2, 2535.0, 2536.0, 2518.0, 2522.0, 1500, 300, True)
    snap2 = IndicatorSnapshot(
        symbol="RELIANCE", timestamp=ts2, close=2522.0, vwap=2510.0, atr_14=10.0,
        orb_high=2505.0, orb_low=2480.0, orb_is_complete=True, prev_avg_volume_10=1000.0,
        current_volume=1500, volume_surge_ratio=1.5, gap_pct=1.5, nifty_regime=MarketRegime.BULLISH,
        vix_is_acceptable=True,
    )
    exit_signal = strategy_engine.process_candle(c2, snap2)

    assert exit_signal is not None
    assert exit_signal.direction == SignalDirection.FLAT
    assert exit_signal.reason == "TRAILING_STOP"
    assert exit_signal.signal_price == 2520.0  # Stopped out at trailed profit level!
    assert strategy_engine.is_symbol_in_active_trade("RELIANCE") is False


# ==============================================================================
# 8. Time Exit (14:30:00 IST)
# ==============================================================================

def test_time_exit_at_cutoff(strategy_engine: VWAPORBStrategyEngine) -> None:
    test_valid_long_signal(strategy_engine)

    # 14:30:00 IST candle
    ts = datetime(2024, 1, 10, 14, 30, tzinfo=IST_TIMEZONE)
    candle = Candle("RELIANCE", ts, 2520.0, 2525.0, 2515.0, 2522.0, 1000, 300, True)
    snapshot = IndicatorSnapshot(
        symbol="RELIANCE", timestamp=ts, close=2522.0, vwap=2505.0, atr_14=10.0,
        orb_high=2505.0, orb_low=2480.0, orb_is_complete=True, prev_avg_volume_10=1000.0,
        current_volume=1000, volume_surge_ratio=1.0, gap_pct=1.5, nifty_regime=MarketRegime.BULLISH,
        vix_is_acceptable=True,
    )

    exit_signal = strategy_engine.process_candle(candle, snapshot)

    assert exit_signal is not None
    assert exit_signal.direction == SignalDirection.FLAT
    assert exit_signal.reason == "TIME_EXIT"
    assert exit_signal.signal_price == 2522.0
    assert strategy_engine.is_symbol_in_active_trade("RELIANCE") is False


# ==============================================================================
# 9. Regime Rejection
# ==============================================================================

def test_regime_rejection(strategy_engine: VWAPORBStrategyEngine) -> None:
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    candle = Candle("RELIANCE", ts, 2500.0, 2515.0, 2498.0, 2510.0, 2000, 300, True)

    # NIFTY Regime is BEARISH (blocks Long setup)
    snapshot_bearish = IndicatorSnapshot(
        symbol="RELIANCE", timestamp=ts, close=2510.0, vwap=2500.0, atr_14=10.0,
        orb_high=2505.0, orb_low=2480.0, orb_is_complete=True, prev_avg_volume_10=1000.0,
        current_volume=2000, volume_surge_ratio=2.0, gap_pct=1.5, nifty_regime=MarketRegime.BEARISH,
        vix_is_acceptable=True,
    )
    assert strategy_engine.process_candle(candle, snapshot_bearish) is None

    # NIFTY Regime is NEUTRAL (blocks all setups)
    snapshot_neutral = IndicatorSnapshot(
        symbol="RELIANCE", timestamp=ts, close=2510.0, vwap=2500.0, atr_14=10.0,
        orb_high=2505.0, orb_low=2480.0, orb_is_complete=True, prev_avg_volume_10=1000.0,
        current_volume=2000, volume_surge_ratio=2.0, gap_pct=1.5, nifty_regime=MarketRegime.NEUTRAL,
        vix_is_acceptable=True,
    )
    assert strategy_engine.process_candle(candle, snapshot_neutral) is None


# ==============================================================================
# 10. Volume Rejection
# ==============================================================================

def test_volume_rejection(strategy_engine: VWAPORBStrategyEngine) -> None:
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    candle = Candle("RELIANCE", ts, 2500.0, 2515.0, 2498.0, 2510.0, 1200, 300, True)

    # Volume surge ratio is 1.2 (< 1.5 threshold required)
    snapshot = IndicatorSnapshot(
        symbol="RELIANCE", timestamp=ts, close=2510.0, vwap=2500.0, atr_14=10.0,
        orb_high=2505.0, orb_low=2480.0, orb_is_complete=True, prev_avg_volume_10=1000.0,
        current_volume=1200, volume_surge_ratio=1.2, gap_pct=1.5, nifty_regime=MarketRegime.BULLISH,
        vix_is_acceptable=True,
    )
    assert strategy_engine.process_candle(candle, snapshot) is None


# ==============================================================================
# 11. ORB Condition Rejection
# ==============================================================================

def test_orb_rejection(strategy_engine: VWAPORBStrategyEngine) -> None:
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    candle = Candle("RELIANCE", ts, 2500.0, 2504.0, 2498.0, 2502.0, 2000, 300, True)

    # Close (2502) is NOT above OR High (2505)
    snapshot = IndicatorSnapshot(
        symbol="RELIANCE", timestamp=ts, close=2502.0, vwap=2500.0, atr_14=10.0,
        orb_high=2505.0, orb_low=2480.0, orb_is_complete=True, prev_avg_volume_10=1000.0,
        current_volume=2000, volume_surge_ratio=2.0, gap_pct=1.5, nifty_regime=MarketRegime.BULLISH,
        vix_is_acceptable=True,
    )
    assert strategy_engine.process_candle(candle, snapshot) is None


# ==============================================================================
# 12. Duplicate Signal Prevention & Re-Entry Rules
# ==============================================================================

def test_duplicate_signal_prevention_and_reentry(strategy_engine: VWAPORBStrategyEngine) -> None:
    # 1. Bar 1: Triggers initial entry signal
    test_valid_long_signal(strategy_engine)
    assert strategy_engine.active_positions_count == 1
    assert strategy_engine.daily_trade_count == 1

    # 2. Bar 2 (10:05): Another bullish breakout setup forms on the same stock
    ts2 = datetime(2024, 1, 10, 10, 5, tzinfo=IST_TIMEZONE)
    candle2 = Candle("RELIANCE", ts2, 2515.0, 2530.0, 2512.0, 2525.0, 2500, 300, True)
    snap2 = IndicatorSnapshot(
        symbol="RELIANCE", timestamp=ts2, close=2525.0, vwap=2510.0, atr_14=10.0,
        orb_high=2505.0, orb_low=2480.0, orb_is_complete=True, prev_avg_volume_10=1000.0,
        current_volume=2500, volume_surge_ratio=2.5, gap_pct=1.5, nifty_regime=MarketRegime.BULLISH,
        vix_is_acceptable=True,
    )

    # Must return None (DUPLICATE SIGNAL PREVENTED: Position already open!)
    sig2 = strategy_engine.process_candle(candle2, snap2)
    assert sig2 is None
    assert strategy_engine.active_positions_count == 1
    assert strategy_engine.daily_trade_count == 1

    # 3. Bar 3 (10:10): Position exits via VWAP Invalidation
    ts3 = datetime(2024, 1, 10, 10, 10, tzinfo=IST_TIMEZONE)
    candle3 = Candle("RELIANCE", ts3, 2515.0, 2518.0, 2500.0, 2502.0, 1500, 300, True)
    snap3 = IndicatorSnapshot(
        symbol="RELIANCE", timestamp=ts3, close=2502.0, vwap=2508.0, atr_14=10.0,
        orb_high=2505.0, orb_low=2480.0, orb_is_complete=True, prev_avg_volume_10=1000.0,
        current_volume=1500, volume_surge_ratio=1.5, gap_pct=1.5, nifty_regime=MarketRegime.BULLISH,
        vix_is_acceptable=True,
    )
    exit_sig = strategy_engine.process_candle(candle3, snap3)
    assert exit_sig is not None
    assert exit_sig.reason == "VWAP_FAILURE"
    assert strategy_engine.active_positions_count == 0

    # 4. Same Bar Re-entry Attempt (10:10): Cooldown blocks immediate re-entry on same bar
    assert strategy_engine.process_candle(candle3, snap3) is None

    # 5. Subsequent Bar 4 (10:15): Valid re-entry setup forms (trade #2 for RELIANCE)
    ts4 = datetime(2024, 1, 10, 10, 15, tzinfo=IST_TIMEZONE)
    candle4 = Candle("RELIANCE", ts4, 2505.0, 2520.0, 2502.0, 2515.0, 2200, 300, True)
    snap4 = IndicatorSnapshot(
        symbol="RELIANCE", timestamp=ts4, close=2515.0, vwap=2504.0, atr_14=10.0,
        orb_high=2505.0, orb_low=2480.0, orb_is_complete=True, prev_avg_volume_10=1000.0,
        current_volume=2200, volume_surge_ratio=2.2, gap_pct=1.5, nifty_regime=MarketRegime.BULLISH,
        vix_is_acceptable=True,
    )
    sig4 = strategy_engine.process_candle(candle4, snap4)
    assert sig4 is not None
    assert sig4.reason == "LONG_ENTRY"
    assert strategy_engine.active_positions_count == 1
    assert strategy_engine.daily_trade_count == 2
