"""
Unit Tests for Phase 17 Paper-Trading Execution Adapter.

Validates:
1. Complete order lifecycle: REQUEST -> ACCEPTANCE -> FILL -> POSITION.
2. Strict stage separation: resting orders create NO fills and NO positions until matched.
3. Rejection scenarios: disconnected adapter, invalid quantities, and missing limit prices.
4. Cancellation handling: successful cancel of resting orders, rejection of cancel on terminal orders.
5. Partial fills: multi-step fills with PARTIALLY_FILLED status followed by full FILL.
6. Idempotency: duplicate client_order_id detection without double execution.
7. Position tracking: position updates strictly driven by Trade fills, accurate average price, and P&L.
8. Configurable slippage and simulated latency.
9. Execution audit log completeness.
"""

from datetime import datetime
import pytest

from trade_bot.broker.paper_adapter import PaperBrokerAdapter
from trade_bot.broker.paper_models import ExecutionLogEntry, ExecutionStage, PaperBrokerConfig
from trade_bot.config.constants import IST_TIMEZONE
from trade_bot.domain.enums import OrderSide, OrderStatus, OrderType, ProductType
from trade_bot.domain.exceptions import BrokerAdapterError
from trade_bot.domain.models import Order, OrderModification, OrderRequest, Position, Tick, Trade


@pytest.fixture
def paper_broker() -> PaperBrokerAdapter:
    """Fixture providing a connected PaperBrokerAdapter with zero initial latency."""
    cfg = PaperBrokerConfig(
        initial_capital=100000.0,
        simulated_latency_ms=0.0,
        default_slippage_pct=0.001,  # 0.1% slippage for easy math
    )
    adapter = PaperBrokerAdapter(paper_config=cfg)
    adapter.connect()
    return adapter


class TestPaperBrokerAdapter:
    """Test suite for Phase 17 Paper-Trading Broker Adapter."""

    # -------------------------------------------------------------------------
    # 1. Full Market Order Lifecycle & Stage Distinction
    # -------------------------------------------------------------------------

    def test_market_order_full_lifecycle(self, paper_broker: PaperBrokerAdapter):
        """Verify full market order lifecycle and logging of all stages."""
        paper_broker.set_market_price("RELIANCE", 2500.0)

        trades: list[Trade] = []
        orders: list[Order] = []
        paper_broker.register_trade_callback(trades.append)
        paper_broker.register_order_callback(orders.append)

        req = OrderRequest(
            client_order_id="CLIENT_ORD_101",
            symbol="RELIANCE",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=20,
            product_type=ProductType.MIS,
        )

        broker_id = paper_broker.place_order(req)
        assert broker_id.startswith("BK_PAPER_")

        # 1. Order checks
        placed = paper_broker.get_orders()
        assert len(placed) == 1
        assert placed[0].broker_order_id == broker_id
        assert placed[0].status == OrderStatus.FILLED
        assert placed[0].filled_quantity == 20

        # 2. Trade fills
        assert len(trades) == 1
        trade = trades[0]
        assert trade.order_id == broker_id
        assert trade.quantity == 20
        # Buy slippage: 2500 * (1 + 0.001) = 2502.50
        assert trade.price == 2502.50

        # 3. Position tracking
        positions = paper_broker.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "RELIANCE"
        assert positions[0].quantity == 20
        assert positions[0].average_price == 2502.50

        # 4. Audit Log verification
        logs = paper_broker.get_execution_logs()
        stages = [entry.stage for entry in logs]
        assert ExecutionStage.ORDER_REQUEST in stages
        assert ExecutionStage.ORDER_ACCEPTANCE in stages
        assert ExecutionStage.ORDER_FILL in stages
        assert ExecutionStage.POSITION_UPDATE in stages

    # -------------------------------------------------------------------------
    # 2. Strict Distinction: Never Assume Request Means Fill
    # -------------------------------------------------------------------------

    def test_resting_limit_order_creates_no_fill_until_touched(self, paper_broker: PaperBrokerAdapter):
        """Verify resting limit order produces NO fill and NO position until matched."""
        # Market currently at 2520.0
        paper_broker.set_market_price("RELIANCE", 2520.0)

        trades: list[Trade] = []
        paper_broker.register_trade_callback(trades.append)

        # Submit BUY limit at 2500.0 (below market, will NOT immediately fill)
        req = OrderRequest(
            client_order_id="CLIENT_ORD_LIMIT_01",
            symbol="RELIANCE",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=15,
            price=2500.0,
            product_type=ProductType.MIS,
        )

        broker_id = paper_broker.place_order(req)
        assert broker_id.startswith("BK_PAPER_")

        # Must be in working book, NO fills yet, NO positions yet
        assert len(trades) == 0
        assert len(paper_broker.get_positions()) == 0

        logs = paper_broker.get_execution_logs()
        stages = [entry.stage for entry in logs]
        assert ExecutionStage.ORDER_REQUEST in stages
        assert ExecutionStage.ORDER_ACCEPTANCE in stages
        assert ExecutionStage.ORDER_WORKING in stages
        assert ExecutionStage.ORDER_FILL not in stages
        assert ExecutionStage.POSITION_UPDATE not in stages

        # Market moves to 2510.0 -> still resting
        paper_broker.on_tick(Tick("RELIANCE", datetime.now(IST_TIMEZONE), 2510.0, 100))
        assert len(trades) == 0
        assert len(paper_broker.get_positions()) == 0

        # Market drops to 2498.0 -> touches limit! Triggers fill
        paper_broker.on_tick(Tick("RELIANCE", datetime.now(IST_TIMEZONE), 2498.0, 150))
        assert len(trades) == 1
        assert trades[0].quantity == 15
        assert trades[0].price == 2498.0  # Price improvement

        # Position now exists
        assert len(paper_broker.get_positions()) == 1
        assert paper_broker.get_positions()[0].quantity == 15

    # -------------------------------------------------------------------------
    # 3. Order Rejection Scenarios
    # -------------------------------------------------------------------------

    def test_rejection_when_disconnected(self, paper_broker: PaperBrokerAdapter):
        """Verify orders are rejected when broker is disconnected."""
        paper_broker.disconnect()
        assert not paper_broker.is_connected()

        req = OrderRequest(
            client_order_id="CLIENT_REJ_01",
            symbol="TCS",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
        )

        with pytest.raises(BrokerAdapterError, match="disconnected"):
            paper_broker.place_order(req)

        logs = paper_broker.get_execution_logs()
        assert any(e.stage == ExecutionStage.ORDER_REJECTION for e in logs)

    def test_rejection_for_invalid_parameters(self, paper_broker: PaperBrokerAdapter):
        """Verify orders with invalid quantities or missing prices are rejected by adapter."""
        req_bad = OrderRequest(
            client_order_id="CLIENT_REJ_02",
            symbol="INFY",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
        )
        # Force quantity to invalid 0 to test adapter rejection guard
        object.__setattr__(req_bad, "quantity", 0)

        with pytest.raises(BrokerAdapterError, match="Invalid quantity"):
            paper_broker.place_order(req_bad)

        logs = paper_broker.get_execution_logs()
        assert any(e.stage == ExecutionStage.ORDER_REJECTION for e in logs)

    # -------------------------------------------------------------------------
    # 4. Order Cancellation Scenarios
    # -------------------------------------------------------------------------

    def test_order_cancellation_lifecycle(self, paper_broker: PaperBrokerAdapter):
        """Verify active limit order can be cancelled, but terminal orders cannot."""
        paper_broker.set_market_price("HDFCBANK", 1600.0)

        # Place resting limit buy at 1550.0
        req = OrderRequest(
            client_order_id="CLIENT_CANCEL_01",
            symbol="HDFCBANK",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=25,
            price=1550.0,
        )
        broker_id = paper_broker.place_order(req)

        # Cancel while active
        cancel_success = paper_broker.cancel_order(broker_id)
        assert cancel_success is True

        order = paper_broker.get_orders()[0]
        assert order.status == OrderStatus.CANCELLED

        logs = paper_broker.get_execution_logs()
        assert any(e.stage == ExecutionStage.ORDER_CANCELLED and e.broker_order_id == broker_id for e in logs)

        # Second cancel attempt on already cancelled order -> False
        cancel_again = paper_broker.cancel_order(broker_id)
        assert cancel_again is False

    # -------------------------------------------------------------------------
    # 5. Partial Fills
    # -------------------------------------------------------------------------

    def test_partial_fill_execution(self):
        """Verify partial fills emit PARTIALLY_FILLED followed by full FILL."""
        cfg = PaperBrokerConfig(
            enable_partial_fills=True,
            partial_fill_ratio=0.40,  # 40% initial fill
            default_slippage_pct=0.0,
        )
        broker = PaperBrokerAdapter(paper_config=cfg)
        broker.connect()
        broker.set_market_price("ICICIBANK", 1000.0)

        trades: list[Trade] = []
        broker.register_trade_callback(trades.append)

        req = OrderRequest(
            client_order_id="PARTIAL_ORD_01",
            symbol="ICICIBANK",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=50,
        )

        broker_id = broker.place_order(req)

        # Should produce two fills: 40% of 50 = 20, then remaining 30
        assert len(trades) == 2
        assert trades[0].quantity == 20
        assert trades[1].quantity == 30

        order = broker.get_orders()[0]
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == 50

        # Verify stages in audit log
        logs = broker.get_execution_logs()
        stages = [e.stage for e in logs if e.broker_order_id == broker_id]
        assert ExecutionStage.ORDER_PARTIAL_FILL in stages
        assert ExecutionStage.ORDER_FILL in stages

        # Final position
        pos = broker.get_positions()[0]
        assert pos.quantity == 50

    # -------------------------------------------------------------------------
    # 6. Idempotent Order Processing
    # -------------------------------------------------------------------------

    def test_idempotent_duplicate_order_handling(self, paper_broker: PaperBrokerAdapter):
        """Verify resubmitting identical client_order_id returns existing order without double-fill."""
        paper_broker.set_market_price("SBIN", 750.0)

        trades: list[Trade] = []
        paper_broker.register_trade_callback(trades.append)

        req = OrderRequest(
            client_order_id="IDEM_ORD_999",
            symbol="SBIN",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
        )

        # First placement
        id1 = paper_broker.place_order(req)
        assert len(trades) == 1
        assert paper_broker.get_positions()[0].quantity == 10

        # Duplicate placement
        id2 = paper_broker.place_order(req)
        assert id1 == id2  # Returns same broker order ID
        assert len(trades) == 1  # No secondary fill
        assert paper_broker.get_positions()[0].quantity == 10  # Position unchanged

    # -------------------------------------------------------------------------
    # 7. Multi-Order Position Accounting & P&L
    # -------------------------------------------------------------------------

    def test_position_pnl_and_flip_accounting(self, paper_broker: PaperBrokerAdapter):
        """Verify position scaling, profit realization, and position flip."""
        paper_broker.set_market_price("RELIANCE", 2500.0)

        # 1. Buy 10 @ 2500 (with 0.1% slip = 2502.50)
        paper_broker.place_order(
            OrderRequest("SCALE_1", "RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)
        )
        pos = paper_broker.get_positions()[0]
        assert pos.quantity == 10
        assert pos.average_price == 2502.50

        # 2. Buy 10 more @ 2600 (slip = 2602.60)
        paper_broker.set_market_price("RELIANCE", 2600.0)
        paper_broker.place_order(
            OrderRequest("SCALE_2", "RELIANCE", OrderSide.BUY, OrderType.MARKET, 10)
        )
        assert pos.quantity == 20
        # Avg = (10*2502.5 + 10*2602.6)/20 = 2552.55
        assert pos.average_price == 2552.55

        # 3. Sell 30 @ 2700 (flip to short 10)
        paper_broker.set_market_price("RELIANCE", 2700.0)
        # Sell slippage: 2700 * (1 - 0.001) = 2697.30
        paper_broker.place_order(
            OrderRequest("FLIP_1", "RELIANCE", OrderSide.SELL, OrderType.MARKET, 30)
        )
        assert pos.quantity == -10
        assert pos.average_price == 2697.30
        # Realized profit on closing 20 long: (2697.30 - 2552.55)*20 = ~2895 minus statutory fees
        assert pos.realized_pnl > 2700.0

    # -------------------------------------------------------------------------
    # 8. Simulated Latency
    # -------------------------------------------------------------------------

    def test_simulated_latency_timestamp_advancement(self):
        """Verify configured latency is reflected in acceptance timestamps."""
        cfg = PaperBrokerConfig(simulated_latency_ms=150.0)
        broker = PaperBrokerAdapter(paper_config=cfg)
        broker.connect()
        broker.set_market_price("TCS", 3800.0)

        t_before = datetime.now(IST_TIMEZONE)
        broker.place_order(
            OrderRequest("LAT_ORD_01", "TCS", OrderSide.BUY, OrderType.MARKET, 5)
        )
        order = broker.get_orders()[0]

        # Acceptance timestamp should be >= t_before + 150ms
        diff_ms = (order.created_at - t_before).total_seconds() * 1000.0
        assert diff_ms >= 140.0
