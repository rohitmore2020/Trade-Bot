"""
Deterministic Unit Tests for Pure VWAP-ORB Strategy Domain Component (Phase 8).

Exhaustively verifies:
1. LONG:
   - Valid signal
   - VWAP rejection
   - NIFTY regime rejection
   - Pullback rejection
   - Bullish candle rejection
   - Volume rejection
   - ORB rejection
2. SHORT:
   - Valid signal
   - VWAP rejection
   - NIFTY regime rejection
   - Pullback rejection
   - Bearish candle rejection
   - Volume rejection
   - ORB rejection
3. EXITS:
   - Initial stop loss
   - ATR Trailing stop
   - VWAP invalidation exit
   - 14:30:00 IST time exit
4. STATE:
   - Duplicate signal prevention
   - Re-entry limits
   - Invalid state transitions
   - Trailing stop never moves adversely
5. EXACT BOUNDARY CONDITIONS:
   - Exact pullback tolerance equality
   - Exact volume threshold equality
   - Exact time window boundaries
   - Exact ORB level boundaries
"""

from datetime import datetime, time
import pytest

from trade_bot.config.constants import IST_TIMEZONE
from trade_bot.domain.enums import MarketRegime, OrderSide, TradingSessionStatus
from trade_bot.domain.exceptions import DuplicateSignalError, InvalidStrategyStateTransitionError
from trade_bot.domain.models import Candle, Instrument
from trade_bot.strategy.entry_rules import LongEntryRule, ShortEntryRule
from trade_bot.strategy.exit_rules import (
    ExitEvaluator,
    InitialStopEvaluator,
    TimeExitEvaluator,
    TrailingStopEvaluator,
    VwapExitEvaluator,
)
from trade_bot.strategy.models import (
    SignalTriggerReason,
    StrategyMarketInput,
    TradeIntent,
    VwapOrbStrategyConfig,
)
from trade_bot.strategy.pure_strategy import VwapOrbPureStrategy
from trade_bot.strategy.state import ExitReason, PositionStatus, StrategyTradeState


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def strategy() -> VwapOrbPureStrategy:
    return VwapOrbPureStrategy()


@pytest.fixture
def sample_instrument() -> Instrument:
    return Instrument(symbol="RELIANCE")


@pytest.fixture
def sample_state() -> StrategyTradeState:
    return StrategyTradeState(symbol="RELIANCE", max_trades_per_session=2)


# ==============================================================================
# 1. LONG Strategy Tests
# ==============================================================================

def test_long_valid_signal(strategy: VwapOrbPureStrategy, sample_state: StrategyTradeState) -> None:
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    # Candle: Open=2500, High=2520, Low=2495, Close=2515, Vol=2000
    candle = Candle("RELIANCE", ts, 2500.0, 2520.0, 2495.0, 2515.0, 2000, 300, True)

    market_input = StrategyMarketInput(
        candle=candle,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2505.0,
        opening_range_low=2480.0,
        volume_sma_10=1000.0,
        volume_ratio=2.0,
        market_regime=MarketRegime.BULLISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )

    intent = strategy.evaluate(market_input)
    assert intent is not None
    assert isinstance(intent, TradeIntent)
    assert intent.side == OrderSide.BUY
    assert intent.intent_type == "ENTRY"
    assert intent.signal_price == 2515.0
    # proposed entry = Close + 0.05% = 2515 * 1.0005 = 2516.26
    assert intent.proposed_entry_price == 2516.26
    # proposed stop = entry - 1.5 * ATR = 2516.26 - 22.5 = 2493.76
    assert intent.proposed_stop_price == 2493.76
    assert intent.signal_reason == SignalTriggerReason.LONG_ENTRY.value
    assert intent.strategy_version == "1.0.0"


def test_long_vwap_rejection(strategy: VwapOrbPureStrategy, sample_state: StrategyTradeState) -> None:
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    # Close (2495) <= VWAP (2500)
    candle = Candle("RELIANCE", ts, 2490.0, 2502.0, 2485.0, 2495.0, 2000, 300, True)

    market_input = StrategyMarketInput(
        candle=candle,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2480.0,
        opening_range_low=2460.0,
        volume_sma_10=1000.0,
        volume_ratio=2.0,
        market_regime=MarketRegime.BULLISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )

    eval_res = strategy.evaluate_entry(market_input)
    assert not eval_res.is_valid
    assert eval_res.reason == SignalTriggerReason.VWAP_REJECTION
    assert strategy.evaluate(market_input) is None


def test_long_nifty_regime_rejection(strategy: VwapOrbPureStrategy, sample_state: StrategyTradeState) -> None:
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    candle = Candle("RELIANCE", ts, 2500.0, 2520.0, 2495.0, 2515.0, 2000, 300, True)

    # Market regime is BEARISH instead of BULLISH
    market_input = StrategyMarketInput(
        candle=candle,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2505.0,
        opening_range_low=2480.0,
        volume_sma_10=1000.0,
        volume_ratio=2.0,
        market_regime=MarketRegime.BEARISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )

    rule = LongEntryRule()
    eval_res = rule.evaluate(market_input)
    assert not eval_res.is_valid
    assert eval_res.reason == SignalTriggerReason.REGIME_MISMATCH
    # Evaluated through strategy coordinator
    assert strategy.evaluate(market_input) is None


def test_long_pullback_rejection(strategy: VwapOrbPureStrategy, sample_state: StrategyTradeState) -> None:
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    # Low (2510) > VWAP (2500) * 1.002 = 2505.0
    candle = Candle("RELIANCE", ts, 2512.0, 2525.0, 2510.0, 2520.0, 2000, 300, True)

    market_input = StrategyMarketInput(
        candle=candle,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2505.0,
        opening_range_low=2480.0,
        volume_sma_10=1000.0,
        volume_ratio=2.0,
        market_regime=MarketRegime.BULLISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )

    eval_res = strategy.evaluate_entry(market_input)
    assert not eval_res.is_valid
    assert eval_res.reason == SignalTriggerReason.PULLBACK_REJECTION
    assert strategy.evaluate(market_input) is None


def test_long_bullish_candle_rejection(strategy: VwapOrbPureStrategy, sample_state: StrategyTradeState) -> None:
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    # Bearish close: Close (2508) < Open (2515)
    candle = Candle("RELIANCE", ts, 2515.0, 2520.0, 2498.0, 2508.0, 2000, 300, True)

    market_input = StrategyMarketInput(
        candle=candle,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2505.0,
        opening_range_low=2480.0,
        volume_sma_10=1000.0,
        volume_ratio=2.0,
        market_regime=MarketRegime.BULLISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )

    eval_res = strategy.evaluate_entry(market_input)
    assert not eval_res.is_valid
    assert eval_res.reason == SignalTriggerReason.NOT_BULLISH_CANDLE
    assert strategy.evaluate(market_input) is None


def test_long_volume_rejection(strategy: VwapOrbPureStrategy, sample_state: StrategyTradeState) -> None:
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    # Volume (1200) < 1.5 * 1000 = 1500
    candle = Candle("RELIANCE", ts, 2500.0, 2520.0, 2495.0, 2515.0, 1200, 300, True)

    market_input = StrategyMarketInput(
        candle=candle,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2505.0,
        opening_range_low=2480.0,
        volume_sma_10=1000.0,
        volume_ratio=1.2,
        market_regime=MarketRegime.BULLISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )

    eval_res = strategy.evaluate_entry(market_input)
    assert not eval_res.is_valid
    assert eval_res.reason == SignalTriggerReason.VOLUME_REJECTION
    assert strategy.evaluate(market_input) is None


def test_long_orb_rejection(strategy: VwapOrbPureStrategy, sample_state: StrategyTradeState) -> None:
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    # Close (2515) <= OR_High (2520)
    candle = Candle("RELIANCE", ts, 2500.0, 2520.0, 2495.0, 2515.0, 2000, 300, True)

    market_input = StrategyMarketInput(
        candle=candle,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2520.0,
        opening_range_low=2480.0,
        volume_sma_10=1000.0,
        volume_ratio=2.0,
        market_regime=MarketRegime.BULLISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )

    eval_res = strategy.evaluate_entry(market_input)
    assert not eval_res.is_valid
    assert eval_res.reason == SignalTriggerReason.ORB_REJECTION
    assert strategy.evaluate(market_input) is None


# ==============================================================================
# 2. SHORT Strategy Tests (Symmetrical Mirror)
# ==============================================================================

def test_short_valid_signal(strategy: VwapOrbPureStrategy, sample_state: StrategyTradeState) -> None:
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    # Candle: Open=2500, High=2505, Low=2480, Close=2485, Vol=2000
    candle = Candle("RELIANCE", ts, 2500.0, 2505.0, 2480.0, 2485.0, 2000, 300, True)

    market_input = StrategyMarketInput(
        candle=candle,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2520.0,
        opening_range_low=2495.0,
        volume_sma_10=1000.0,
        volume_ratio=2.0,
        market_regime=MarketRegime.BEARISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )

    intent = strategy.evaluate(market_input)
    assert intent is not None
    assert isinstance(intent, TradeIntent)
    assert intent.side == OrderSide.SELL
    assert intent.intent_type == "ENTRY"
    assert intent.signal_price == 2485.0
    # proposed entry = Close - 0.05% = 2485 * 0.9995 = 2483.76
    assert intent.proposed_entry_price == 2483.76
    # proposed stop = entry + 1.5 * ATR = 2483.76 + 22.5 = 2506.26
    assert intent.proposed_stop_price == 2506.26
    assert intent.signal_reason == SignalTriggerReason.SHORT_ENTRY.value


def test_short_vwap_rejection(strategy: VwapOrbPureStrategy, sample_state: StrategyTradeState) -> None:
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    # Close (2505) >= VWAP (2500)
    candle = Candle("RELIANCE", ts, 2510.0, 2515.0, 2498.0, 2505.0, 2000, 300, True)

    market_input = StrategyMarketInput(
        candle=candle,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2540.0,
        opening_range_low=2520.0,
        volume_sma_10=1000.0,
        volume_ratio=2.0,
        market_regime=MarketRegime.BEARISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )

    eval_res = strategy.evaluate_entry(market_input)
    assert not eval_res.is_valid
    assert eval_res.reason == SignalTriggerReason.VWAP_REJECTION
    assert strategy.evaluate(market_input) is None


def test_short_nifty_regime_rejection(strategy: VwapOrbPureStrategy, sample_state: StrategyTradeState) -> None:
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    candle = Candle("RELIANCE", ts, 2500.0, 2505.0, 2480.0, 2485.0, 2000, 300, True)

    market_input = StrategyMarketInput(
        candle=candle,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2520.0,
        opening_range_low=2495.0,
        volume_sma_10=1000.0,
        volume_ratio=2.0,
        market_regime=MarketRegime.BULLISH,  # Mismatch for short
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )

    rule = ShortEntryRule()
    eval_res = rule.evaluate(market_input)
    assert not eval_res.is_valid
    assert eval_res.reason == SignalTriggerReason.REGIME_MISMATCH
    assert strategy.evaluate(market_input) is None


def test_short_pullback_rejection(strategy: VwapOrbPureStrategy, sample_state: StrategyTradeState) -> None:
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    # High (2490) < VWAP (2500) * 0.998 = 2495.0
    candle = Candle("RELIANCE", ts, 2488.0, 2490.0, 2470.0, 2475.0, 2000, 300, True)

    market_input = StrategyMarketInput(
        candle=candle,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2520.0,
        opening_range_low=2495.0,
        volume_sma_10=1000.0,
        volume_ratio=2.0,
        market_regime=MarketRegime.BEARISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )

    eval_res = strategy.evaluate_entry(market_input)
    assert not eval_res.is_valid
    assert eval_res.reason == SignalTriggerReason.PULLBACK_REJECTION
    assert strategy.evaluate(market_input) is None


def test_short_bearish_candle_rejection(strategy: VwapOrbPureStrategy, sample_state: StrategyTradeState) -> None:
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    # Bullish close: Close (2490) > Open (2480)
    candle = Candle("RELIANCE", ts, 2480.0, 2500.0, 2475.0, 2490.0, 2000, 300, True)

    market_input = StrategyMarketInput(
        candle=candle,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2520.0,
        opening_range_low=2495.0,
        volume_sma_10=1000.0,
        volume_ratio=2.0,
        market_regime=MarketRegime.BEARISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )

    eval_res = strategy.evaluate_entry(market_input)
    assert not eval_res.is_valid
    assert eval_res.reason == SignalTriggerReason.NOT_BEARISH_CANDLE
    assert strategy.evaluate(market_input) is None


def test_short_volume_rejection(strategy: VwapOrbPureStrategy, sample_state: StrategyTradeState) -> None:
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    # Volume (1200) < 1.5 * 1000 = 1500
    candle = Candle("RELIANCE", ts, 2500.0, 2505.0, 2480.0, 2485.0, 1200, 300, True)

    market_input = StrategyMarketInput(
        candle=candle,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2520.0,
        opening_range_low=2495.0,
        volume_sma_10=1000.0,
        volume_ratio=1.2,
        market_regime=MarketRegime.BEARISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )

    eval_res = strategy.evaluate_entry(market_input)
    assert not eval_res.is_valid
    assert eval_res.reason == SignalTriggerReason.VOLUME_REJECTION
    assert strategy.evaluate(market_input) is None


def test_short_orb_rejection(strategy: VwapOrbPureStrategy, sample_state: StrategyTradeState) -> None:
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    # Close (2485) >= OR_Low (2480)
    candle = Candle("RELIANCE", ts, 2500.0, 2505.0, 2480.0, 2485.0, 2000, 300, True)

    market_input = StrategyMarketInput(
        candle=candle,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2520.0,
        opening_range_low=2480.0,
        volume_sma_10=1000.0,
        volume_ratio=2.0,
        market_regime=MarketRegime.BEARISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )

    eval_res = strategy.evaluate_entry(market_input)
    assert not eval_res.is_valid
    assert eval_res.reason == SignalTriggerReason.ORB_REJECTION
    assert strategy.evaluate(market_input) is None


# ==============================================================================
# 3. EXIT Strategy Tests
# ==============================================================================

def test_exit_initial_stop(strategy: VwapOrbPureStrategy, sample_state: StrategyTradeState) -> None:
    entry_ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    # Long trade opened at 2516.26 with stop at 2493.76
    sample_state.open_trade(
        timestamp=entry_ts,
        entry_price=2516.26,
        initial_stop=2493.76,
        side=OrderSide.BUY,
    )

    exit_ts = datetime(2024, 1, 10, 10, 15, tzinfo=IST_TIMEZONE)
    # Candle breaches initial stop: Low=2490.0 <= 2493.76
    candle = Candle("RELIANCE", exit_ts, 2505.0, 2510.0, 2490.0, 2492.0, 1500, 300, True)

    market_input = StrategyMarketInput(
        candle=candle,
        stock_vwap=2485.0,  # VWAP below price so VWAP failure doesn't mask stop
        atr=15.0,
        opening_range_high=2505.0,
        opening_range_low=2480.0,
        volume_sma_10=1000.0,
        volume_ratio=1.5,
        market_regime=MarketRegime.BULLISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )

    intent = strategy.evaluate(market_input)
    assert intent is not None
    assert intent.side == OrderSide.SELL
    assert intent.intent_type == "EXIT"
    assert intent.signal_reason == ExitReason.INITIAL_STOP.value
    assert intent.proposed_entry_price == 2493.76
    assert sample_state.position_status == PositionStatus.FLAT
    assert sample_state.active_trade is None


def test_exit_trailing_stop(strategy: VwapOrbPureStrategy, sample_state: StrategyTradeState) -> None:
    entry_ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    # Long trade opened at 2500 with initial stop at 2470
    sample_state.open_trade(
        timestamp=entry_ts,
        entry_price=2500.0,
        initial_stop=2470.0,
        side=OrderSide.BUY,
    )

    # Bar 1: Rallies to High=2550 while Low remains above new stop (Low=2532 > 2530)
    ts_1 = datetime(2024, 1, 10, 10, 5, tzinfo=IST_TIMEZONE)
    candle_1 = Candle("RELIANCE", ts_1, 2535.0, 2550.0, 2532.0, 2545.0, 1500, 300, True)
    market_input_1 = StrategyMarketInput(
        candle=candle_1,
        stock_vwap=2490.0,
        atr=10.0,
        opening_range_high=2505.0,
        opening_range_low=2480.0,
        volume_sma_10=1000.0,
        volume_ratio=1.5,
        market_regime=MarketRegime.BULLISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )
    # Trailing stop should ratchet: Peak 2550 - (2.0 * 10) = 2530
    strategy.evaluate(market_input_1)
    assert sample_state.active_trade is not None
    assert sample_state.active_trade.current_stop == 2530.0

    # Bar 2: Low breaches 2530 (Low=2525)
    ts_2 = datetime(2024, 1, 10, 10, 10, tzinfo=IST_TIMEZONE)
    candle_2 = Candle("RELIANCE", ts_2, 2540.0, 2542.0, 2525.0, 2528.0, 1500, 300, True)
    market_input_2 = StrategyMarketInput(
        candle=candle_2,
        stock_vwap=2490.0,
        atr=10.0,
        opening_range_high=2505.0,
        opening_range_low=2480.0,
        volume_sma_10=1000.0,
        volume_ratio=1.5,
        market_regime=MarketRegime.BULLISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )

    intent = strategy.evaluate(market_input_2)
    assert intent is not None
    assert intent.side == OrderSide.SELL
    assert intent.intent_type == "EXIT"
    assert intent.signal_reason == ExitReason.TRAILING_STOP.value
    assert intent.proposed_entry_price == 2530.0
    assert sample_state.position_status == PositionStatus.FLAT


def test_exit_vwap_failure(strategy: VwapOrbPureStrategy, sample_state: StrategyTradeState) -> None:
    entry_ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    sample_state.open_trade(
        timestamp=entry_ts,
        entry_price=2515.0,
        initial_stop=2470.0,
        side=OrderSide.BUY,
    )

    exit_ts = datetime(2024, 1, 10, 10, 30, tzinfo=IST_TIMEZONE)
    # Close crosses below VWAP: Close (2495) < VWAP (2500)
    candle = Candle("RELIANCE", exit_ts, 2502.0, 2504.0, 2490.0, 2495.0, 1500, 300, True)
    market_input = StrategyMarketInput(
        candle=candle,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2505.0,
        opening_range_low=2480.0,
        volume_sma_10=1000.0,
        volume_ratio=1.5,
        market_regime=MarketRegime.BULLISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )

    intent = strategy.evaluate(market_input)
    assert intent is not None
    assert intent.intent_type == "EXIT"
    assert intent.signal_reason == ExitReason.VWAP_FAILURE.value
    assert intent.proposed_entry_price == 2495.0


def test_exit_time_cutoff(strategy: VwapOrbPureStrategy, sample_state: StrategyTradeState) -> None:
    entry_ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    sample_state.open_trade(
        timestamp=entry_ts,
        entry_price=2515.0,
        initial_stop=2470.0,
        side=OrderSide.BUY,
    )

    # 14:30:00 IST Cutoff bar
    exit_ts = datetime(2024, 1, 10, 14, 30, tzinfo=IST_TIMEZONE)
    candle = Candle("RELIANCE", exit_ts, 2520.0, 2525.0, 2518.0, 2522.0, 1500, 300, True)
    market_input = StrategyMarketInput(
        candle=candle,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2505.0,
        opening_range_low=2480.0,
        volume_sma_10=1000.0,
        volume_ratio=1.5,
        market_regime=MarketRegime.BULLISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )

    intent = strategy.evaluate(market_input)
    assert intent is not None
    assert intent.intent_type == "EXIT"
    assert intent.signal_reason == ExitReason.TIME_EXIT.value
    assert intent.proposed_entry_price == 2522.0


# ==============================================================================
# 4. STATE & INVARIANT Tests
# ==============================================================================

def test_state_duplicate_signal_prevention(strategy: VwapOrbPureStrategy, sample_state: StrategyTradeState) -> None:
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    candle = Candle("RELIANCE", ts, 2500.0, 2520.0, 2495.0, 2515.0, 2000, 300, True)

    market_input = StrategyMarketInput(
        candle=candle,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2505.0,
        opening_range_low=2480.0,
        volume_sma_10=1000.0,
        volume_ratio=2.0,
        market_regime=MarketRegime.BULLISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )

    intent_1 = strategy.evaluate(market_input)
    assert intent_1 is not None

    # Sending identical bar immediately: duplicate check must suppress duplicate signal
    intent_2 = strategy.evaluate(market_input)
    assert intent_2 is None

    # Calling record_signal directly with duplicate must raise DuplicateSignalError
    with pytest.raises(DuplicateSignalError):
        sample_state.record_signal(intent_1)


def test_state_reentry_limit(sample_state: StrategyTradeState) -> None:
    # Max trades per session = 2
    ts1 = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    sample_state.open_trade(ts1, 2500.0, 2480.0, OrderSide.BUY)
    sample_state.close_trade(ts1, 2510.0, ExitReason.INITIAL_STOP)
    assert sample_state.trade_count == 1
    can_enter, _ = sample_state.can_enter()
    assert can_enter is True

    # Trade 2
    ts2 = datetime(2024, 1, 10, 11, 0, tzinfo=IST_TIMEZONE)
    sample_state.open_trade(ts2, 2510.0, 2490.0, OrderSide.BUY)
    sample_state.close_trade(ts2, 2520.0, ExitReason.INITIAL_STOP)
    assert sample_state.trade_count == 2

    # Attempt Trade 3 (exceeding max trades = 2)
    can_enter, reason = sample_state.can_enter()
    assert can_enter is False
    assert "Max trades per session reached" in str(reason)

    ts3 = datetime(2024, 1, 10, 12, 0, tzinfo=IST_TIMEZONE)
    with pytest.raises(InvalidStrategyStateTransitionError):
        sample_state.open_trade(ts3, 2520.0, 2500.0, OrderSide.BUY)


def test_state_invalid_transitions(sample_state: StrategyTradeState) -> None:
    # Cannot close trade when FLAT
    with pytest.raises(InvalidStrategyStateTransitionError):
        sample_state.close_trade(datetime.now(), 2500.0, ExitReason.TIME_EXIT)

    # Cannot update watermark when FLAT
    with pytest.raises(InvalidStrategyStateTransitionError):
        sample_state.update_watermark(2550.0, 2500.0)

    # Cannot update trailing stop when FLAT
    with pytest.raises(InvalidStrategyStateTransitionError):
        sample_state.update_trailing_stop(2520.0)

    # Open trade
    sample_state.open_trade(datetime.now(), 2500.0, 2470.0, OrderSide.BUY)

    # Cannot open another trade while OPEN
    with pytest.raises(InvalidStrategyStateTransitionError):
        sample_state.open_trade(datetime.now(), 2510.0, 2480.0, OrderSide.BUY)


def test_state_trailing_stop_never_retreats_adverse(sample_state: StrategyTradeState) -> None:
    # 1. Long position: Stop can only move UP, never DOWN
    sample_state.open_trade(datetime.now(), 2500.0, 2480.0, OrderSide.BUY)
    sample_state.update_trailing_stop(2490.0)
    assert sample_state.active_trade.current_stop == 2490.0

    # Attempting adverse retreat (2490 -> 2485) must raise InvalidStrategyStateTransitionError
    with pytest.raises(InvalidStrategyStateTransitionError):
        sample_state.update_trailing_stop(2485.0)

    # Close trade
    sample_state.close_trade(datetime.now(), 2500.0, ExitReason.TRAILING_STOP)

    # 2. Short position: Stop can only move DOWN, never UP
    sample_state.reset_session()
    sample_state.open_trade(datetime.now(), 2500.0, 2520.0, OrderSide.SELL)
    sample_state.update_trailing_stop(2510.0)
    assert sample_state.active_trade.current_stop == 2510.0

    # Attempting adverse retreat (2510 -> 2515) must raise InvalidStrategyStateTransitionError
    with pytest.raises(InvalidStrategyStateTransitionError):
        sample_state.update_trailing_stop(2515.0)


# ==============================================================================
# 5. EXACT BOUNDARY CONDITIONS
# ==============================================================================

def test_long_pullback_exact_boundary(strategy: VwapOrbPureStrategy, sample_state: StrategyTradeState) -> None:
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    # stock_vwap = 2500.0, pullback_tolerance = 1.002 -> threshold = 2505.0
    # Case A: Low == 2505.0 (Exact match passes)
    candle_pass = Candle("RELIANCE", ts, 2506.0, 2520.0, 2505.0, 2515.0, 2000, 300, True)
    input_pass = StrategyMarketInput(
        candle=candle_pass,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2500.0,
        opening_range_low=2480.0,
        volume_sma_10=1000.0,
        volume_ratio=2.0,
        market_regime=MarketRegime.BULLISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )
    assert strategy.evaluate_entry(input_pass).is_valid is True

    # Case B: Low == 2505.01 (0.01 above tolerance fails)
    candle_fail = Candle("RELIANCE", ts, 2506.0, 2520.0, 2505.01, 2515.0, 2000, 300, True)
    input_fail = StrategyMarketInput(
        candle=candle_fail,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2500.0,
        opening_range_low=2480.0,
        volume_sma_10=1000.0,
        volume_ratio=2.0,
        market_regime=MarketRegime.BULLISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )
    assert strategy.evaluate_entry(input_fail).is_valid is False
    assert strategy.evaluate_entry(input_fail).reason == SignalTriggerReason.PULLBACK_REJECTION


def test_short_pullback_exact_boundary(strategy: VwapOrbPureStrategy, sample_state: StrategyTradeState) -> None:
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    # stock_vwap = 2500.0, pullback_tolerance = 0.998 -> threshold = 2495.0
    # Case A: High == 2495.0 (Exact match passes)
    candle_pass = Candle("RELIANCE", ts, 2494.0, 2495.0, 2470.0, 2480.0, 2000, 300, True)
    input_pass = StrategyMarketInput(
        candle=candle_pass,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2520.0,
        opening_range_low=2490.0,
        volume_sma_10=1000.0,
        volume_ratio=2.0,
        market_regime=MarketRegime.BEARISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )
    assert strategy.evaluate_entry(input_pass).is_valid is True

    # Case B: High == 2494.99 (0.01 below threshold fails)
    candle_fail = Candle("RELIANCE", ts, 2494.0, 2494.99, 2470.0, 2480.0, 2000, 300, True)
    input_fail = StrategyMarketInput(
        candle=candle_fail,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2520.0,
        opening_range_low=2490.0,
        volume_sma_10=1000.0,
        volume_ratio=2.0,
        market_regime=MarketRegime.BEARISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )
    assert strategy.evaluate_entry(input_fail).is_valid is False
    assert strategy.evaluate_entry(input_fail).reason == SignalTriggerReason.PULLBACK_REJECTION


def test_volume_surge_exact_boundary(strategy: VwapOrbPureStrategy, sample_state: StrategyTradeState) -> None:
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    # SMA = 1000 -> 1.5x threshold = 1500
    # Case A: Volume == 1500 (Passes)
    candle_pass = Candle("RELIANCE", ts, 2500.0, 2520.0, 2495.0, 2515.0, 1500, 300, True)
    input_pass = StrategyMarketInput(
        candle=candle_pass,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2505.0,
        opening_range_low=2480.0,
        volume_sma_10=1000.0,
        volume_ratio=1.5,
        market_regime=MarketRegime.BULLISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )
    assert strategy.evaluate_entry(input_pass).is_valid is True

    # Case B: Volume == 1499 (Fails)
    candle_fail = Candle("RELIANCE", ts, 2500.0, 2520.0, 2495.0, 2515.0, 1499, 300, True)
    input_fail = StrategyMarketInput(
        candle=candle_fail,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2505.0,
        opening_range_low=2480.0,
        volume_sma_10=1000.0,
        volume_ratio=1.499,
        market_regime=MarketRegime.BULLISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )
    assert strategy.evaluate_entry(input_fail).is_valid is False
    assert strategy.evaluate_entry(input_fail).reason == SignalTriggerReason.VOLUME_REJECTION


def test_trading_window_exact_boundaries(strategy: VwapOrbPureStrategy, sample_state: StrategyTradeState) -> None:
    # Window start is 09:45:00 IST
    ts_early = datetime(2024, 1, 10, 9, 44, 59, tzinfo=IST_TIMEZONE)
    candle_early = Candle("RELIANCE", ts_early, 2500.0, 2520.0, 2495.0, 2515.0, 2000, 300, True)
    input_early = StrategyMarketInput(
        candle=candle_early,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2505.0,
        opening_range_low=2480.0,
        volume_sma_10=1000.0,
        volume_ratio=2.0,
        market_regime=MarketRegime.BULLISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )
    assert strategy.evaluate_entry(input_early).is_valid is False
    assert strategy.evaluate_entry(input_early).reason == SignalTriggerReason.OUTSIDE_TRADING_WINDOW

    ts_valid = datetime(2024, 1, 10, 9, 45, 0, tzinfo=IST_TIMEZONE)
    candle_valid = Candle("RELIANCE", ts_valid, 2500.0, 2520.0, 2495.0, 2515.0, 2000, 300, True)
    input_valid = StrategyMarketInput(
        candle=candle_valid,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2505.0,
        opening_range_low=2480.0,
        volume_sma_10=1000.0,
        volume_ratio=2.0,
        market_regime=MarketRegime.BULLISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )
    assert strategy.evaluate_entry(input_valid).is_valid is True

    # Time exit cutoff is 14:30:00 IST
    assert TimeExitEvaluator.should_exit(time(14, 29, 59)) is False
    assert TimeExitEvaluator.should_exit(time(14, 30, 0)) is True


def test_orb_level_exact_boundaries(strategy: VwapOrbPureStrategy, sample_state: StrategyTradeState) -> None:
    ts = datetime(2024, 1, 10, 10, 0, tzinfo=IST_TIMEZONE)
    # Long OR_High = 2515.0
    # Case A: Close == 2515.0 (Strictly greater required -> fails)
    candle_eq = Candle("RELIANCE", ts, 2500.0, 2520.0, 2495.0, 2515.0, 2000, 300, True)
    input_eq = StrategyMarketInput(
        candle=candle_eq,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2515.0,
        opening_range_low=2480.0,
        volume_sma_10=1000.0,
        volume_ratio=2.0,
        market_regime=MarketRegime.BULLISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )
    assert strategy.evaluate_entry(input_eq).is_valid is False
    assert strategy.evaluate_entry(input_eq).reason == SignalTriggerReason.ORB_REJECTION

    # Case B: Close == 2515.05 (Greater than OR_High -> passes)
    candle_gt = Candle("RELIANCE", ts, 2500.0, 2520.0, 2495.0, 2515.05, 2000, 300, True)
    input_gt = StrategyMarketInput(
        candle=candle_gt,
        stock_vwap=2500.0,
        atr=15.0,
        opening_range_high=2515.0,
        opening_range_low=2480.0,
        volume_sma_10=1000.0,
        volume_ratio=2.0,
        market_regime=MarketRegime.BULLISH,
        current_trading_session=TradingSessionStatus.OPEN,
        current_strategy_state=sample_state,
    )
    assert strategy.evaluate_entry(input_gt).is_valid is True
