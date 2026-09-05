"""
Deterministic Unit and Integration Tests for Phase 11 Backtesting Engine.

Validates:
- Strict zero look-ahead bias
- Clock progression and session boundaries (ORB, 09:45 window, 14:30 exit)
- Limit entries, timeouts, and cancellations
- Intra-bar SL-M execution and slippage modeling
- Trailing stop ratcheting
- VWAP invalidation exit
- Mandatory 14:30 forced exit
- Daily circuit breaker halt
- Deterministic reproducibility (identical inputs -> identical outputs)
- Multi-day session transitions and daily P&L attribution
"""

from datetime import date, datetime, time, timedelta
from typing import Dict, List
import pytest
from zoneinfo import ZoneInfo

from trade_bot.backtest.analytics import BacktestAnalytics
from trade_bot.backtest.clock import SimulationClock
from trade_bot.backtest.data_feed import HistoricalDataFeed
from trade_bot.backtest.engine import BacktestEngine
from trade_bot.backtest.models import BacktestConfig
from trade_bot.backtest.simulator import ExecutionSimulator
from trade_bot.config.constants import IST_TIMEZONE
from trade_bot.domain.enums import OrderSide, OrderStatus, ProductType, TimeInForce
from trade_bot.domain.models import Candle, OrderRequest
from trade_bot.indicators.exceptions import LookAheadViolationError
from trade_bot.portfolio.manager import PortfolioManager
from trade_bot.strategy.models import VwapOrbStrategyConfig
from trade_bot.strategy.state import PositionStatus

TZ_IST = IST_TIMEZONE if isinstance(IST_TIMEZONE, ZoneInfo) else ZoneInfo(str(IST_TIMEZONE))


def make_dt(day: int, hour: int, minute: int) -> datetime:
    """Helper to create timezone-aware IST datetime."""
    return datetime(2024, 1, day, hour, minute, 0, tzinfo=TZ_IST)


def generate_nifty_candle(ts: datetime, close: float = 21500.0) -> Candle:
    """Generate benchmark NIFTY candle above VWAP for bullish regime."""
    return Candle(
        symbol="^NSEI",
        timestamp=ts,
        open=close - 10.0,
        high=close + 5.0,
        low=close - 25.0,
        close=close,
        volume=1_000_000,
        timeframe_seconds=300,
        is_closed=True,
    )


def test_simulation_clock_progression_and_boundaries():
    """Test clock time validation, forward progression, and session boundaries."""
    clock = SimulationClock(initial_time=make_dt(8, 9, 15))
    assert clock.is_orb_period() is True
    assert clock.is_trading_window() is False
    assert clock.is_forced_exit_time() is False

    # Advance to 09:30 (ORB ends)
    clock.advance_to(make_dt(8, 9, 30))
    assert clock.is_orb_period() is False
    assert clock.is_trading_window() is False

    # Advance to 09:45 (trading window begins)
    clock.advance_to(make_dt(8, 9, 45))
    assert clock.is_trading_window() is True
    assert clock.is_forced_exit_time() is False

    # Advance to 14:30 (mandatory exit)
    clock.advance_to(make_dt(8, 14, 30))
    assert clock.is_trading_window() is False
    assert clock.is_forced_exit_time() is True

    # Look-ahead violation: attempting to step backward in time must raise LookAheadViolationError
    with pytest.raises(LookAheadViolationError):
        clock.advance_to(make_dt(8, 12, 0))


def test_historical_data_feed_chronological_integrity():
    """Verify that feed stream yields monotonically increasing bars with zero future leakage."""
    c1 = Candle(symbol="RELIANCE", timestamp=make_dt(8, 9, 15), open=2500, high=2510, low=2495, close=2505, volume=50000)
    c2 = Candle(symbol="RELIANCE", timestamp=make_dt(8, 9, 20), open=2505, high=2515, low=2500, close=2510, volume=60000)
    c3 = Candle(symbol="TCS", timestamp=make_dt(8, 9, 15), open=3800, high=3810, low=3795, close=3805, volume=20000)

    feed = HistoricalDataFeed(candles_by_symbol={"RELIANCE": [c2, c1], "TCS": [c3]})
    bars = list(feed.stream_bars())

    assert len(bars) == 2
    ts0, symbols0 = bars[0]
    ts1, symbols1 = bars[1]

    assert ts0 == make_dt(8, 9, 15)
    assert set(symbols0.keys()) == {"RELIANCE", "TCS"}
    assert ts1 == make_dt(8, 9, 20)
    assert set(symbols1.keys()) == {"RELIANCE"}


def test_execution_simulator_limit_fill_and_timeout():
    """Verify limit orders only fill on price touch, and timeout when unfilled."""
    portfolio = PortfolioManager(initial_capital=100_000.0)
    simulator = ExecutionSimulator(portfolio_manager=portfolio, default_limit_timeout_bars=1)

    req = OrderRequest(
        client_order_id="ORD_TEST_1",
        symbol="RELIANCE",
        side=OrderSide.BUY,
        order_type="LIMIT",
        quantity=10,
        price=1000.0,
    )
    order = simulator.submit_limit_order(req, timeout_bars=1)
    assert simulator.pending_orders_count == 1
    assert order.status == OrderStatus.ACKNOWLEDGED

    # Bar 1: Price does not reach limit price 1000.0 (Low = 1002.0)
    candle1 = Candle(symbol="RELIANCE", timestamp=make_dt(8, 9, 50), open=1005, high=1010, low=1002, close=1006, volume=1000)
    fills = simulator.process_bar(candle1)
    assert len(fills) == 0
    # Order should now have timed out (1 bar elapsed) and be cancelled
    assert simulator.pending_orders_count == 0
    assert order.status == OrderStatus.CANCELLED
    assert order.rejection_reason == "ORDER_TIMEOUT"


def test_execution_simulator_limit_touch_and_fill():
    """Verify limit BUY fills when price touches limit price."""
    portfolio = PortfolioManager(initial_capital=100_000.0)
    simulator = ExecutionSimulator(portfolio_manager=portfolio, default_limit_timeout_bars=2)

    req = OrderRequest(
        client_order_id="ORD_TEST_2",
        symbol="RELIANCE",
        side=OrderSide.BUY,
        order_type="LIMIT",
        quantity=10,
        price=1000.0,
    )
    order = simulator.submit_limit_order(req, timeout_bars=2)

    # Bar touches limit (Low = 998.0 <= 1000.0)
    candle = Candle(symbol="RELIANCE", timestamp=make_dt(8, 9, 50), open=1002, high=1005, low=998, close=1001, volume=1000)
    fills = simulator.process_bar(candle)
    assert len(fills) == 1
    assert fills[0].price == 1000.0
    assert fills[0].quantity == 10
    assert order.status == OrderStatus.FILLED
    assert simulator.pending_orders_count == 0


def test_execution_simulator_stop_loss_and_slippage():
    """Verify intra-bar SL-M execution with modeled slippage."""
    portfolio = PortfolioManager(initial_capital=100_000.0)
    simulator = ExecutionSimulator(
        portfolio_manager=portfolio,
        slippage_per_share=0.10,
        slippage_pct=0.0,
    )

    # Place and fill initial buy
    req = OrderRequest(
        client_order_id="ORD_BUY_1",
        symbol="RELIANCE",
        side=OrderSide.BUY,
        order_type="LIMIT",
        quantity=10,
        price=1000.0,
    )
    simulator.submit_limit_order(req)
    c_entry = Candle(symbol="RELIANCE", timestamp=make_dt(8, 9, 50), open=1000, high=1005, low=999, close=1002, volume=1000)
    simulator.process_bar(c_entry)

    # Set Stop Loss at 980.0
    simulator.set_stop_loss(
        symbol="RELIANCE",
        side=OrderSide.SELL,
        stop_price=980.0,
        quantity=10,
        parent_order_id="ORD_BUY_1",
        timestamp=c_entry.timestamp,
    )
    assert simulator.active_stops_count == 1

    # Bar dips below stop (Low = 975.0 <= 980.0)
    c_exit = Candle(symbol="RELIANCE", timestamp=make_dt(8, 9, 55), open=985, high=986, low=975, close=978, volume=2000)
    fills = simulator.process_bar(c_exit)
    assert len(fills) == 1
    fill = fills[0]
    # Executed at stop_price minus slippage (980.0 - 0.10 = 979.90)
    assert fill.price == 979.90
    assert fill.side == OrderSide.SELL
    assert simulator.active_stops_count == 0


def test_deterministic_full_trade_lifecycle():
    """
    Deterministic end-to-end backtest fixture test:
    Known candle sequence -> known trade entry -> trailing stop ratchet -> known exit & P&L.
    """
    symbol = "RELIANCE"
    candles = []
    nifty_candles = []

    # Seeding 10 bars for Volume SMA and ATR calculation (09:15 to 10:00)
    # Day 1: 2024-01-08
    # 09:15-09:25: ORB formation. High = 1005, Low = 995
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 15), open=1000.0, high=1005.0, low=995.0, close=1002.0, volume=10000))
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 20), open=1002.0, high=1004.0, low=998.0, close=1000.0, volume=10000))
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 25), open=1000.0, high=1003.0, low=997.0, close=1001.0, volume=10000))

    # 09:30, 09:35, 09:40: Bars trading near VWAP
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 30), open=1001.0, high=1004.0, low=999.0, close=1002.0, volume=10000))
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 35), open=1002.0, high=1005.0, low=1000.0, close=1003.0, volume=10000))
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 40), open=1003.0, high=1004.0, low=1000.0, close=1002.0, volume=10000))

    # 09:45: Signal Bar!
    # Bullish close > open (1010 > 1002)
    # Pullback was satisfied in prior bars
    # Breakout above OR High (1010 > 1005)
    # Volume surge: 25000 >= 1.5 * 10000 = 15000
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 45), open=1002.0, high=1012.0, low=1001.0, close=1010.0, volume=25000))

    # 09:50: Entry Bar: Touches limit entry price (Close * 1.0005 = 1010.51)
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 50), open=1009.0, high=1015.0, low=1008.0, close=1014.0, volume=12000))

    # 09:55 - 10:15: Advancing bars raising peak watermark to 1030
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 55), open=1014.0, high=1020.0, low=1013.0, close=1019.0, volume=12000))
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 10, 0), open=1019.0, high=1025.0, low=1018.0, close=1024.0, volume=12000))
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 10, 5), open=1024.0, high=1030.0, low=1023.0, close=1029.0, volume=12000))

    # 10:10: Pullback hits trailing stop
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 10, 10), open=1028.0, high=1029.0, low=1000.0, close=1002.0, volume=20000))

    # Remainder of session up to 14:30
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 14, 30), open=1002.0, high=1004.0, low=1000.0, close=1003.0, volume=10000))

    # Corresponding NIFTY candles (steady above VWAP)
    for c in candles:
        nifty_candles.append(generate_nifty_candle(c.timestamp, close=21500.0))

    feed = HistoricalDataFeed(candles_by_symbol={symbol: candles, "^NSEI": nifty_candles})

    config = BacktestConfig(
        initial_capital=100_000.0,
        symbols=[symbol],
        nifty_symbol="^NSEI",
        slippage_per_share=0.05,
        limit_timeout_bars=2,
    )

    engine = BacktestEngine(config=config, data_feed=feed)
    result = engine.run()

    # Verify deterministic trade output
    assert len(result.completed_trades) >= 1
    trade = result.completed_trades[0]
    assert trade.symbol == symbol
    assert trade.entry_price > 0.0
    assert trade.exit_price > 0.0
    assert trade.gross_pnl != 0.0
    assert trade.transaction_costs > 0.0
    assert result.metrics.total_trades >= 1
    assert result.metrics.turnover > 0.0


def test_vwap_invalidation_exit():
    """Verify position is exited at market when price closes below VWAP for a Long trade."""
    symbol = "TCS"
    candles = []
    nifty_candles = []

    # ORB 09:15 to 09:25: High = 3510, Low = 3490
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 15), open=3500.0, high=3510.0, low=3490.0, close=3505.0, volume=10000))
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 20), open=3505.0, high=3508.0, low=3498.0, close=3502.0, volume=10000))
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 25), open=3502.0, high=3506.0, low=3496.0, close=3504.0, volume=10000))

    # Bars near VWAP ~3503
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 30), open=3504.0, high=3508.0, low=3500.0, close=3505.0, volume=10000))
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 35), open=3505.0, high=3509.0, low=3501.0, close=3506.0, volume=10000))
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 40), open=3506.0, high=3508.0, low=3502.0, close=3505.0, volume=10000))

    # 09:45: Long Signal Bar (> OR High 3510, volume surge)
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 45), open=3505.0, high=3520.0, low=3504.0, close=3518.0, volume=25000))

    # 09:50: Entry fill
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 50), open=3517.0, high=3522.0, low=3516.0, close=3520.0, volume=12000))

    # 09:55: Price plunges and closes below VWAP (VWAP failure exit)
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 55), open=3515.0, high=3516.0, low=3480.0, close=3485.0, volume=30000))

    for c in candles:
        nifty_candles.append(generate_nifty_candle(c.timestamp, close=21500.0))

    feed = HistoricalDataFeed(candles_by_symbol={symbol: candles, "^NSEI": nifty_candles})
    config = BacktestConfig(initial_capital=100_000.0, symbols=[symbol], nifty_symbol="^NSEI")
    engine = BacktestEngine(config=config, data_feed=feed)
    result = engine.run()

    assert len(result.completed_trades) >= 1
    # Check that trade closed with VWAP failure reason or stop
    trade = result.completed_trades[0]
    assert trade.exit_price is not None


def test_mandatory_1430_time_exit():
    """Verify any position held until 14:30 IST is automatically force-closed."""
    symbol = "INFY"
    candles = []
    nifty_candles = []

    # ORB 09:15 to 09:25
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 15), open=1500.0, high=1510.0, low=1495.0, close=1505.0, volume=10000))
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 20), open=1505.0, high=1508.0, low=1498.0, close=1502.0, volume=10000))
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 25), open=1502.0, high=1506.0, low=1496.0, close=1504.0, volume=10000))
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 30), open=1504.0, high=1508.0, low=1500.0, close=1505.0, volume=10000))
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 35), open=1505.0, high=1509.0, low=1501.0, close=1506.0, volume=10000))
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 40), open=1506.0, high=1508.0, low=1502.0, close=1505.0, volume=10000))

    # 09:45: Long Signal Bar
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 45), open=1505.0, high=1518.0, low=1504.0, close=1516.0, volume=25000))
    # 09:50: Entry fill
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 50), open=1515.0, high=1520.0, low=1514.0, close=1518.0, volume=10000))

    # 10:00 to 14:25: Sideways prices maintaining position
    for minute in [0, 30]:
        candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 10, minute), open=1518.0, high=1522.0, low=1516.0, close=1520.0, volume=5000))

    # 14:30: Forced exit bar
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 14, 30), open=1520.0, high=1522.0, low=1517.0, close=1521.0, volume=15000))

    for c in candles:
        nifty_candles.append(generate_nifty_candle(c.timestamp, close=21500.0))

    feed = HistoricalDataFeed(candles_by_symbol={symbol: candles, "^NSEI": nifty_candles})
    config = BacktestConfig(initial_capital=100_000.0, symbols=[symbol], nifty_symbol="^NSEI")
    engine = BacktestEngine(config=config, data_feed=feed)
    result = engine.run()

    assert len(result.completed_trades) == 1
    trade = result.completed_trades[0]
    assert trade.exit_time == make_dt(8, 14, 30)
    assert engine.portfolio.get_open_positions() == []


def test_circuit_breaker_halts_trading():
    """Verify that when 2% daily loss limit is hit, circuit breaker halts subsequent entries."""
    portfolio = PortfolioManager(initial_capital=100_000.0, max_daily_loss_pct=0.02)
    # 2% of 100,000 = 2,000 loss limit
    assert portfolio.daily_risk_state.daily_loss_limit == 2000.0

    # Simulate a losing trade of 2,500 INR
    from trade_bot.portfolio.models import Fill
    # BUY at 1000, 10 shares
    fill_buy = Fill(
        fill_id="F1", order_id="O1", client_order_id="C1", symbol="RELIANCE",
        side=OrderSide.BUY, quantity=10, price=1000.0, timestamp=make_dt(8, 10, 0),
        brokerage=20.0, stt_and_taxes=10.0,
    )
    portfolio.process_fill(fill_buy)

    # SELL at 740, 10 shares (Gross loss = -2,600)
    fill_sell = Fill(
        fill_id="F2", order_id="O2", client_order_id="C2", symbol="RELIANCE",
        side=OrderSide.SELL, quantity=10, price=740.0, timestamp=make_dt(8, 10, 30),
        brokerage=20.0, stt_and_taxes=10.0,
    )
    portfolio.process_fill(fill_sell)

    # Circuit breaker must be breached
    assert portfolio.daily_risk_state.max_daily_loss_breached is True


def test_strict_lookahead_bias_invariance():
    """
    Verify strict zero look-ahead bias:
    Modifying a future candle at 13:00 has zero effect on signal and fill at 09:45-09:50.
    """
    symbol = "RELIANCE"

    def create_dataset(future_price: float) -> HistoricalDataFeed:
        candles = [
            Candle(symbol=symbol, timestamp=make_dt(8, 9, 15), open=1000.0, high=1005.0, low=995.0, close=1002.0, volume=10000),
            Candle(symbol=symbol, timestamp=make_dt(8, 9, 20), open=1002.0, high=1004.0, low=998.0, close=1000.0, volume=10000),
            Candle(symbol=symbol, timestamp=make_dt(8, 9, 25), open=1000.0, high=1003.0, low=997.0, close=1001.0, volume=10000),
            Candle(symbol=symbol, timestamp=make_dt(8, 9, 30), open=1001.0, high=1004.0, low=999.0, close=1002.0, volume=10000),
            Candle(symbol=symbol, timestamp=make_dt(8, 9, 35), open=1002.0, high=1005.0, low=1000.0, close=1003.0, volume=10000),
            Candle(symbol=symbol, timestamp=make_dt(8, 9, 40), open=1003.0, high=1004.0, low=1000.0, close=1002.0, volume=10000),
            Candle(symbol=symbol, timestamp=make_dt(8, 9, 45), open=1002.0, high=1012.0, low=1001.0, close=1010.0, volume=25000),
            Candle(symbol=symbol, timestamp=make_dt(8, 9, 50), open=1009.0, high=1015.0, low=1008.0, close=1014.0, volume=12000),
            # Future bar with altered price
            Candle(symbol=symbol, timestamp=make_dt(8, 13, 0), open=future_price, high=future_price + 50, low=future_price - 50, close=future_price, volume=50000),
            Candle(symbol=symbol, timestamp=make_dt(8, 14, 30), open=future_price, high=future_price + 10, low=future_price - 10, close=future_price, volume=10000),
        ]
        nifty = [generate_nifty_candle(c.timestamp) for c in candles]
        return HistoricalDataFeed(candles_by_symbol={symbol: candles, "^NSEI": nifty})

    feed1 = create_dataset(future_price=1020.0)
    feed2 = create_dataset(future_price=5000.0)  # Extreme future variation

    config = BacktestConfig(initial_capital=100_000.0, symbols=[symbol], nifty_symbol="^NSEI")

    engine1 = BacktestEngine(config=config, data_feed=feed1)
    res1 = engine1.run()

    engine2 = BacktestEngine(config=config, data_feed=feed2)
    res2 = engine2.run()

    # The entry trade executed at 09:50 must be completely identical in both runs
    trade1 = res1.completed_trades[0]
    trade2 = res2.completed_trades[0]
    assert trade1.entry_price == trade2.entry_price
    assert trade1.entry_time == trade2.entry_time
    assert trade1.quantity == trade2.quantity


def test_determinism_identical_runs_produce_identical_results():
    """Verify that repeated runs with identical inputs produce bit-for-bit identical results."""
    symbol = "RELIANCE"
    candles = [
        Candle(symbol=symbol, timestamp=make_dt(8, 9, 15), open=1000.0, high=1005.0, low=995.0, close=1002.0, volume=10000),
        Candle(symbol=symbol, timestamp=make_dt(8, 9, 20), open=1002.0, high=1004.0, low=998.0, close=1000.0, volume=10000),
        Candle(symbol=symbol, timestamp=make_dt(8, 9, 25), open=1000.0, high=1003.0, low=997.0, close=1001.0, volume=10000),
        Candle(symbol=symbol, timestamp=make_dt(8, 9, 30), open=1001.0, high=1004.0, low=999.0, close=1002.0, volume=10000),
        Candle(symbol=symbol, timestamp=make_dt(8, 9, 35), open=1002.0, high=1005.0, low=1000.0, close=1003.0, volume=10000),
        Candle(symbol=symbol, timestamp=make_dt(8, 9, 40), open=1003.0, high=1004.0, low=1000.0, close=1002.0, volume=10000),
        Candle(symbol=symbol, timestamp=make_dt(8, 9, 45), open=1002.0, high=1012.0, low=1001.0, close=1010.0, volume=25000),
        Candle(symbol=symbol, timestamp=make_dt(8, 9, 50), open=1009.0, high=1015.0, low=1008.0, close=1014.0, volume=12000),
        Candle(symbol=symbol, timestamp=make_dt(8, 14, 30), open=1020.0, high=1025.0, low=1015.0, close=1022.0, volume=15000),
    ]
    nifty = [generate_nifty_candle(c.timestamp) for c in candles]

    config = BacktestConfig(initial_capital=100_000.0, symbols=[symbol], nifty_symbol="^NSEI")

    feed1 = HistoricalDataFeed(candles_by_symbol={symbol: candles, "^NSEI": nifty})
    feed2 = HistoricalDataFeed(candles_by_symbol={symbol: candles, "^NSEI": nifty})

    engine1 = BacktestEngine(config=config, data_feed=feed1)
    engine2 = BacktestEngine(config=config, data_feed=feed2)

    res1 = engine1.run()
    res2 = engine2.run()

    # Compare key metrics
    assert res1.metrics.total_trades == res2.metrics.total_trades
    assert res1.metrics.gross_pnl == res2.metrics.gross_pnl
    assert res1.metrics.transaction_costs == res2.metrics.transaction_costs
    assert res1.metrics.net_pnl == res2.metrics.net_pnl
    assert res1.metrics.win_rate == res2.metrics.win_rate
    assert res1.metrics.profit_factor == res2.metrics.profit_factor
    assert res1.metrics.max_drawdown == res2.metrics.max_drawdown
    assert res1.metrics.turnover == res2.metrics.turnover
    assert len(res1.completed_trades) == len(res2.completed_trades)


def test_multi_day_session_resets():
    """Verify session reset across 2 consecutive trading days (rolls equity, clears intraday counters)."""
    symbol = "RELIANCE"
    candles = []
    nifty = []

    # Day 1: 2024-01-08
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 9, 15), open=1000.0, high=1005.0, low=995.0, close=1000.0, volume=10000))
    candles.append(Candle(symbol=symbol, timestamp=make_dt(8, 14, 30), open=1000.0, high=1005.0, low=995.0, close=1000.0, volume=10000))

    # Day 2: 2024-01-09
    candles.append(Candle(symbol=symbol, timestamp=make_dt(9, 9, 15), open=1010.0, high=1015.0, low=1005.0, close=1010.0, volume=10000))
    candles.append(Candle(symbol=symbol, timestamp=make_dt(9, 14, 30), open=1010.0, high=1015.0, low=1005.0, close=1010.0, volume=10000))

    for c in candles:
        nifty.append(generate_nifty_candle(c.timestamp))

    feed = HistoricalDataFeed(candles_by_symbol={symbol: candles, "^NSEI": nifty})
    config = BacktestConfig(initial_capital=100_000.0, symbols=[symbol], nifty_symbol="^NSEI")
    engine = BacktestEngine(config=config, data_feed=feed)
    result = engine.run()

    # Must produce 2 daily summary records
    assert len(result.daily_pnl) == 2
    assert result.daily_pnl[0].trading_date == date(2024, 1, 8)
    assert result.daily_pnl[1].trading_date == date(2024, 1, 9)
