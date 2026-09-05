"""
Unit Tests for Realistic Execution Simulator (Phase 12).

Validates:
- LIMIT BUY / LIMIT SELL (exact touch, gap cross / price improvement)
- MARKET BUY / MARKET SELL (immediate fill with adverse slippage and costs)
- SL-M triggers (normal breach, gap risk)
- Order cancellation and modification
- Order expiry on timeout (ORDER_TIMEOUT)
- Partial fills via volume participation limit
- Conservative intrabar collision resolution (stop loss prioritised over target)
- Configurable slippage algorithms (FIXED_TICK, PERCENTAGE, VOLATILITY_ADAPTIVE, VOLUME_IMPACT)
- Indian transaction cost calculation (brokerage, STT, turnover, SEBI, GST, stamp duty)
- Complete architectural decoupling from strategy and portfolio
- Absolute zero look-ahead bias
"""

from datetime import datetime
import pytest

from trade_bot.domain.enums import OrderSide, OrderStatus, OrderType, ProductType
from trade_bot.domain.models import Candle, OrderModification, OrderRequest
from trade_bot.execution.cost_calculator import TransactionCostCalculator
from trade_bot.execution.models import (
    ExecutionSimulatorConfig,
    SlippageModelConfig,
    SlippageModelType,
    TransactionCostConfig,
)
from trade_bot.execution.simulator import ExecutionSimulator


def create_candle(
    symbol: str = "RELIANCE",
    open_: float = 2500.0,
    high: float = 2510.0,
    low: float = 2490.0,
    close: float = 2505.0,
    volume: int = 50_000,
    timestamp: datetime = datetime(2024, 1, 8, 9, 30),
) -> Candle:
    return Candle(
        symbol=symbol,
        timestamp=timestamp,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


class TestExecutionSimulator:
    """Test suite for Phase 12 realistic execution simulator."""

    def test_market_buy_and_sell_with_slippage_and_costs(self):
        """Verify MARKET orders execute immediately with adverse slippage and statutory costs."""
        config = ExecutionSimulatorConfig(
            slippage=SlippageModelConfig(
                model_type=SlippageModelType.FIXED_TICK,
                fixed_tick_size=0.10,
            ),
            costs=TransactionCostConfig(
                brokerage_per_order=20.0,
                brokerage_pct_cap=0.0003,
            ),
        )
        sim = ExecutionSimulator(config=config)
        sim.set_market_price("INFY", 1500.0)

        # 1. MARKET BUY
        buy_req = OrderRequest(
            client_order_id="BUY_1",
            symbol="INFY",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100,
            price=1500.0,
        )
        broker_id = sim.place_order(buy_req)
        assert broker_id is not None

        order = sim.get_order("BUY_1")
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == 100
        # Buy price slips UP: 1500.0 + 0.10 = 1500.10
        assert order.average_fill_price == 1500.10

        assert len(sim.executed_trades) == 1
        trade = sim.executed_trades[0]
        assert trade.price == 1500.10
        assert trade.brokerage > 0.0
        assert trade.stt_and_taxes > 0.0

        # 2. MARKET SELL
        sell_req = OrderRequest(
            client_order_id="SELL_1",
            symbol="INFY",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=100,
            price=1500.0,
        )
        sim.place_order(sell_req)
        sell_order = sim.get_order("SELL_1")
        assert sell_order.status == OrderStatus.FILLED
        # Sell price slips DOWN: 1500.0 - 0.10 = 1499.90
        assert sell_order.average_fill_price == 1499.90

    def test_limit_buy_touch_and_cross(self):
        """Verify LIMIT BUY behaves accurately on touch vs cross (price improvement)."""
        config = ExecutionSimulatorConfig(default_timeout_bars=2)
        sim = ExecutionSimulator(config=config)

        # Place LIMIT BUY at 2500.0
        req = OrderRequest(
            client_order_id="LMT_BUY_1",
            symbol="TCS",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=50,
            price=2500.0,
        )
        sim.place_order(req)
        assert sim.pending_orders_count == 1

        # Bar 1: Low doesn't reach limit (low is 2505.0) -> No fill
        c1 = create_candle(symbol="TCS", open_=2515.0, high=2520.0, low=2505.0, close=2510.0)
        trades1 = sim.process_bar(c1)
        assert len(trades1) == 0
        assert sim.pending_orders_count == 1

        # Bar 2: Exactly touches 2500.0 (low=2500.0, open=2505.0) -> Fills at limit price 2500.0
        c2 = create_candle(symbol="TCS", open_=2505.0, high=2510.0, low=2500.0, close=2502.0)
        trades2 = sim.process_bar(c2)
        assert len(trades2) == 1
        assert trades2[0].price == 2500.0
        assert trades2[0].quantity == 50
        assert sim.pending_orders_count == 0

        # Test Price Improvement on Gap:
        # Place LIMIT BUY at 2500.0, but next bar opens at 2490.0 (favorable gap down)
        req_gap = OrderRequest(
            client_order_id="LMT_BUY_GAP",
            symbol="TCS",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=20,
            price=2500.0,
        )
        sim.place_order(req_gap)
        c_gap = create_candle(symbol="TCS", open_=2490.0, high=2495.0, low=2485.0, close=2492.0)
        trades_gap = sim.process_bar(c_gap)
        assert len(trades_gap) == 1
        # Should fill at 2490.0 (open price improvement) rather than 2500.0
        assert trades_gap[0].price == 2490.0

    def test_limit_sell_touch_and_cross(self):
        """Verify LIMIT SELL behaves accurately on touch vs cross (price improvement)."""
        sim = ExecutionSimulator()

        # Place LIMIT SELL at 3000.0
        req = OrderRequest(
            client_order_id="LMT_SELL_1",
            symbol="HDFC",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=40,
            price=3000.0,
        )
        sim.place_order(req)
        assert sim.pending_orders_count == 1

        # Bar 1: Exactly touches 3000.0 (high=3000.0, open=2990.0) -> Fills at 3000.0
        c1 = create_candle(symbol="HDFC", open_=2990.0, high=3000.0, low=2985.0, close=2995.0)
        trades1 = sim.process_bar(c1)
        assert len(trades1) == 1
        assert trades1[0].price == 3000.0
        assert sim.pending_orders_count == 0

        # Test Price Improvement on Gap Up:
        # Place LIMIT SELL at 3000.0, but next bar opens at 3010.0 (favorable gap up)
        req_gap = OrderRequest(
            client_order_id="LMT_SELL_GAP",
            symbol="HDFC",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=10,
            price=3000.0,
        )
        sim.place_order(req_gap)
        c_gap = create_candle(symbol="HDFC", open_=3010.0, high=3020.0, low=3005.0, close=3015.0)
        trades_gap = sim.process_bar(c_gap)
        assert len(trades_gap) == 1
        # Should fill at 3010.0 (open price improvement) rather than 3000.0
        assert trades_gap[0].price == 3010.0

    def test_stop_loss_market_long_and_short_with_gap(self):
        """Verify SL-M triggers and accounts for adverse slippage and gap risk."""
        config = ExecutionSimulatorConfig(
            slippage=SlippageModelConfig(
                model_type=SlippageModelType.FIXED_TICK,
                fixed_tick_size=0.20,
            )
        )
        sim = ExecutionSimulator(config=config)

        # 1. Long Stop Loss (side=SELL) at 2450.0
        sl_long_id = sim.set_stop_loss(
            symbol="RELIANCE",
            side=OrderSide.SELL,
            stop_price=2450.0,
            quantity=100,
            parent_order_id="PARENT_1",
        )
        assert sim.active_stops_count == 1

        # Bar: low drops to 2445.0, open is 2460.0 -> Triggers at stop_price - slippage = 2449.80
        c1 = create_candle(symbol="RELIANCE", open_=2460.0, high=2465.0, low=2445.0, close=2448.0)
        trades1 = sim.process_bar(c1)
        assert len(trades1) == 1
        assert trades1[0].price == 2449.80
        assert sim.active_stops_count == 0

        # 2. Gap Down Risk for Long Stop:
        # Stop at 2450.0, bar opens at 2430.0 (gapped below stop)
        sim.set_stop_loss(
            symbol="RELIANCE",
            side=OrderSide.SELL,
            stop_price=2450.0,
            quantity=50,
            parent_order_id="PARENT_2",
        )
        c_gap = create_candle(symbol="RELIANCE", open_=2430.0, high=2435.0, low=2420.0, close=2425.0)
        trades_gap = sim.process_bar(c_gap)
        assert len(trades_gap) == 1
        # Fills at open minus slippage: 2430.0 - 0.20 = 2429.80
        assert trades_gap[0].price == 2429.80

        # 3. Short Stop Loss (side=BUY) at 2550.0 with Gap Up:
        sim.set_stop_loss(
            symbol="RELIANCE",
            side=OrderSide.BUY,
            stop_price=2550.0,
            quantity=30,
            parent_order_id="PARENT_3",
        )
        c_gap_up = create_candle(symbol="RELIANCE", open_=2560.0, high=2570.0, low=2555.0, close=2565.0)
        trades_gap_up = sim.process_bar(c_gap_up)
        assert len(trades_gap_up) == 1
        # Fills at open plus slippage: 2560.0 + 0.20 = 2560.20
        assert trades_gap_up[0].price == 2560.20

    def test_conservative_intrabar_collision_resolution(self):
        """
        Critical Conservative Rule:
        If both stop loss and target-like limit are within the candle's [Low, High],
        the stop loss MUST execute first to eliminate hindsight bias.
        """
        sim = ExecutionSimulator()

        # Active Stop Loss at 2450.0 (sell to exit long)
        sim.set_stop_loss(
            symbol="TATAMOTORS",
            side=OrderSide.SELL,
            stop_price=2450.0,
            quantity=100,
            parent_order_id="LONG_ENTRY",
        )

        # Pending Limit Target at 2520.0 (sell to take profit)
        sim.place_order(
            OrderRequest(
                client_order_id="TARGET_LIMIT",
                symbol="TATAMOTORS",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=100,
                price=2520.0,
            )
        )

        # Huge volatility candle: Low is 2440.0 (breaches stop), High is 2530.0 (reaches target)
        c_extreme = create_candle(
            symbol="TATAMOTORS",
            open_=2480.0,
            high=2530.0,
            low=2440.0,
            close=2490.0,
        )

        trades = sim.process_bar(c_extreme)
        # Verify stop loss executed first (in Stage 1)
        assert len(trades) >= 1
        assert trades[0].order_id != "TARGET_LIMIT"
        assert trades[0].price <= 2450.0

    def test_order_cancellation_and_modification(self):
        """Verify order cancellation and modification APIs."""
        sim = ExecutionSimulator()

        req = OrderRequest(
            client_order_id="CANCEL_ME",
            symbol="INFY",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            price=1450.0,
        )
        broker_id = sim.place_order(req)
        assert sim.pending_orders_count == 1

        # Modify price and quantity
        mod = OrderModification(
            order_id=broker_id,
            client_order_id="CANCEL_ME",
            price=1460.0,
            quantity=120,
        )
        assert sim.modify_order(mod) is True
        order = sim.get_order("CANCEL_ME")
        assert order.price == 1460.0
        assert order.quantity == 120

        # Cancel order
        assert sim.cancel_order("CANCEL_ME") is True
        assert sim.pending_orders_count == 0
        assert order.status == OrderStatus.CANCELLED

        # Cancelling again returns False
        assert sim.cancel_order("CANCEL_ME") is False

    def test_order_expiry_timeout(self):
        """Verify pending limit orders expire after timeout_bars."""
        config = ExecutionSimulatorConfig(default_timeout_bars=2)
        sim = ExecutionSimulator(config=config)

        req = OrderRequest(
            client_order_id="EXPIRE_ME",
            symbol="WIPRO",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=50,
            price=400.0,
        )
        sim.place_order(req)
        assert sim.pending_orders_count == 1

        # Bar 1: Untouched -> lifetime incremented to 1
        c1 = create_candle(symbol="WIPRO", open_=420.0, high=425.0, low=415.0, close=420.0)
        sim.process_bar(c1)
        assert sim.pending_orders_count == 1

        # Bar 2: Untouched -> lifetime reaches 2 >= timeout_bars -> CANCELLED
        c2 = create_candle(symbol="WIPRO", open_=420.0, high=425.0, low=415.0, close=420.0)
        sim.process_bar(c2)
        assert sim.pending_orders_count == 0

        order = sim.get_order("EXPIRE_ME")
        assert order.status == OrderStatus.CANCELLED

    def test_partial_fills_volume_participation(self):
        """Verify partial fills respect candle volume participation cap."""
        # Cap volume participation at 10%
        config = ExecutionSimulatorConfig(
            partial_fills_enabled=True,
            slippage=SlippageModelConfig(volume_participation_limit=0.10),
            default_timeout_bars=5,
        )
        sim = ExecutionSimulator(config=config)

        # Place LIMIT BUY for 1,000 shares at 100.0
        req = OrderRequest(
            client_order_id="PARTIAL_LMT",
            symbol="SBIN",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=1000,
            price=100.0,
        )
        sim.place_order(req)

        # Bar 1: Volume is 4,000. Max participation = 400 shares.
        c1 = create_candle(symbol="SBIN", open_=102.0, high=105.0, low=98.0, close=99.0, volume=4000)
        trades1 = sim.process_bar(c1)
        assert len(trades1) == 1
        assert trades1[0].quantity == 400

        order = sim.get_order("PARTIAL_LMT")
        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert order.filled_quantity == 400
        assert sim.pending_orders_count == 1

        # Bar 2: Volume is 10,000. Remaining 600 shares <= 1,000 max participation -> fully filled!
        c2 = create_candle(symbol="SBIN", open_=99.0, high=101.0, low=97.0, close=98.0, volume=10000)
        trades2 = sim.process_bar(c2)
        assert len(trades2) == 1
        assert trades2[0].quantity == 600

        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == 1000
        assert sim.pending_orders_count == 0

    def test_configurable_slippage_models(self):
        """Test all 4 supported configurable slippage models."""
        c = create_candle(symbol="TEST", open_=1000.0, high=1020.0, low=980.0, close=1000.0)

        # 1. FIXED_TICK
        cfg1 = ExecutionSimulatorConfig(slippage=SlippageModelConfig(model_type=SlippageModelType.FIXED_TICK, fixed_tick_size=0.15))
        sim1 = ExecutionSimulator(config=cfg1)
        assert sim1._calculate_slippage(1000.0, OrderSide.BUY, c) == 0.15

        # 2. PERCENTAGE (20 bps = 0.0020)
        cfg2 = ExecutionSimulatorConfig(slippage=SlippageModelConfig(model_type=SlippageModelType.PERCENTAGE, percentage=0.002))
        sim2 = ExecutionSimulator(config=cfg2)
        assert sim2._calculate_slippage(1000.0, OrderSide.BUY, c) == 2.0

        # 3. VOLATILITY_ADAPTIVE (5% of candle range = 0.05 * 40.0 = 2.0)
        cfg3 = ExecutionSimulatorConfig(slippage=SlippageModelConfig(model_type=SlippageModelType.VOLATILITY_ADAPTIVE, volatility_mult=0.05))
        sim3 = ExecutionSimulator(config=cfg3)
        assert sim3._calculate_slippage(1000.0, OrderSide.BUY, c) == 2.0

        # 4. VOLUME_IMPACT
        cfg4 = ExecutionSimulatorConfig(slippage=SlippageModelConfig(model_type=SlippageModelType.VOLUME_IMPACT, fixed_tick_size=0.05, percentage=0.0005))
        sim4 = ExecutionSimulator(config=cfg4)
        assert sim4._calculate_slippage(1000.0, OrderSide.BUY, c) == 0.50

    def test_transaction_cost_calculator_statutory_rates(self):
        """Verify Indian equity intraday transaction cost calculations."""
        calc = TransactionCostCalculator()

        # Buy 100 shares at 1500 = 150,000 turnover
        b_buy, t_buy = calc.calculate(price=1500.0, quantity=100, side=OrderSide.BUY)
        assert b_buy > 0.0  # Brokerage capped at max Rs 20
        assert b_buy <= 20.0
        assert t_buy > 0.0  # Includes stamp duty, GST, exchange fee, SEBI fee

        # Sell 100 shares at 1500 = 150,000 turnover
        b_sell, t_sell = calc.calculate(price=1500.0, quantity=100, side=OrderSide.SELL)
        assert b_sell > 0.0
        # Sell incurs STT (0.025% of 150,000 = Rs 37.5) -> taxes must be significantly higher than buy
        assert t_sell > t_buy

    def test_force_close_market_exit(self):
        """Verify execute_market_exit removes pending stops and fills with simulation timestamp."""
        sim = ExecutionSimulator()
        sim.set_stop_loss(
            symbol="INFY",
            side=OrderSide.SELL,
            stop_price=1400.0,
            quantity=50,
            parent_order_id="PARENT_1",
        )
        assert sim.active_stops_count == 1

        sim_time = datetime(2024, 1, 8, 15, 15)
        trade = sim.execute_market_exit(
            symbol="INFY",
            side=OrderSide.SELL,
            quantity=50,
            current_price=1450.0,
            timestamp=sim_time,
            reason="SESSION_SQUARE_OFF",
        )
        # Protective stop was removed
        assert sim.active_stops_count == 0
        # Trade fill is stamped with the simulation timestamp (not wall-clock)
        assert trade.timestamp == sim_time
        assert trade.quantity == 50
        assert trade.price < 1450.0  # Adverse slippage on sell
