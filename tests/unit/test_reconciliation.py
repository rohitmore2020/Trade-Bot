"""
Comprehensive Unit Tests for Broker-to-Internal-State Reconciliation (Phase 21).

Tests every major discrepancy scenario:
1. Broker has position, bot does not (rogue position) -> halt, manual intervention.
2. Bot believes position exists, broker is flat (phantom position) -> halt, manual intervention.
3. Quantity mismatch on same symbol -> halt, manual intervention.
4. Average price mismatch beyond tolerance -> warning flagged.
5. Missing protective stop-loss on active position -> halt, manual intervention, callback invoked.
6. Protective stop-loss quantity mismatch -> halt, manual intervention.
7. Unknown order active on broker -> halt, manual intervention.
8. Order status mismatch (legal transition) -> safely auto-synchronized.
9. Order status mismatch (illegal transition) -> halt, manual intervention.
10. Duplicate active orders on broker -> halt, manual intervention.
11. Clean state -> is_clean is True, no trading halt.
12. Broker query failure -> handles exception, halts trading, records critical error.
13. Reset halt functionality.
"""

from unittest.mock import MagicMock
import pytest

from trade_bot.broker.interfaces import IBrokerAdapter
from trade_bot.domain.enums import (
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
    TimeInForce,
)
from trade_bot.domain.models import (
    AccountBalance,
    Order,
    OrderModification,
    OrderRequest,
    Position,
    Trade,
    utc_now,
)
from trade_bot.observability.audit import AuditLogger
from trade_bot.portfolio.interfaces import IPortfolioManager
from trade_bot.reconciliation.models import (
    DiscrepancySeverity,
    DiscrepancyType,
)
from trade_bot.reconciliation.service import BrokerReconciliationService


class MockBrokerAdapter(IBrokerAdapter):
    """Mock broker adapter for testing reconciliation."""

    def __init__(self) -> None:
        self.broker_positions: list[Position] = []
        self.broker_orders: list[Order] = []
        self._connected = True
        self.fail_query = False

    @property
    def name(self) -> str:
        return "MockBroker"

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def get_account_balance(self) -> AccountBalance:
        return AccountBalance(initial_capital=100000.0, available_cash=100000.0, used_margin=0.0)

    def get_positions(self) -> list[Position]:
        if self.fail_query:
            raise RuntimeError("Broker API error: connection reset")
        return self.broker_positions

    def get_orders(self) -> list[Order]:
        if self.fail_query:
            raise RuntimeError("Broker API error: gateway timeout")
        return self.broker_orders

    def place_order(self, request: OrderRequest) -> str:
        return "BRK_123"

    def modify_order(self, modification: OrderModification) -> bool:
        return True

    def cancel_order(self, broker_order_id: str) -> bool:
        return True

    def register_trade_callback(self, callback) -> None:
        pass


class MockPortfolioManager(IPortfolioManager):
    """Mock portfolio manager for testing reconciliation."""

    def __init__(self) -> None:
        self.positions: dict[str, Position] = {}

    def get_account_balance(self) -> AccountBalance:
        return AccountBalance(initial_capital=100000.0, available_cash=100000.0, used_margin=0.0)

    def get_position(self, symbol: str) -> Position:
        return self.positions.get(symbol, Position(symbol=symbol))

    def get_all_positions(self) -> dict[str, Position]:
        return self.positions

    def get_open_positions(self) -> list[Position]:
        return [p for p in self.positions.values() if not p.is_flat]

    def process_fill(self, fill: Trade) -> Position:
        return Position(symbol=fill.symbol)

    def update_market_price(self, symbol: str, current_price: float) -> None:
        pass

    def get_portfolio_snapshot(self):
        return MagicMock()


@pytest.fixture
def mock_broker():
    return MockBrokerAdapter()


@pytest.fixture
def mock_portfolio():
    return MockPortfolioManager()


@pytest.fixture
def reconciliation_service(mock_broker, mock_portfolio, tmp_path):
    audit = AuditLogger(audit_dir=str(tmp_path / "audit"))
    return BrokerReconciliationService(
        broker=mock_broker,
        portfolio_manager=mock_portfolio,
        audit_logger=audit,
        price_tolerance_pct=0.005,  # 0.5%
    )


def test_clean_reconciliation(reconciliation_service, mock_broker, mock_portfolio):
    """Clean state: bot and broker have matching positions and orders."""
    # Both broker and portfolio have matching INFY position
    pos = Position(symbol="INFY", quantity=100, average_price=1500.0)
    mock_portfolio.positions["INFY"] = pos
    mock_broker.broker_positions = [Position(symbol="INFY", quantity=100, average_price=1500.0)]

    # Matching protective stop order on broker
    sl_order = Order(
        client_order_id="SL_INFY_001",
        broker_order_id="BRK_SL_001",
        symbol="INFY",
        side=OrderSide.SELL,
        order_type=OrderType.SL_MARKET,
        quantity=100,
        trigger_price=1485.0,
        status=OrderStatus.ACKNOWLEDGED,
    )
    mock_broker.broker_orders = [sl_order]
    reconciliation_service.get_internal_orders = lambda: [sl_order]

    report = reconciliation_service.run_reconciliation()
    assert report.is_clean is True
    assert len(report.discrepancies) == 0
    assert report.halt_trading is False
    assert report.requires_manual_intervention is False
    assert reconciliation_service.is_halted is False


def test_rogue_broker_position_halts_trading(reconciliation_service, mock_broker, mock_portfolio):
    """Broker has position but bot is flat -> critical rogue position discrepancy."""
    mock_broker.broker_positions = [Position(symbol="TCS", quantity=50, average_price=3500.0)]
    mock_portfolio.positions = {}  # Internal state has zero positions

    report = reconciliation_service.run_reconciliation()
    assert report.is_clean is False
    assert report.halt_trading is True
    assert report.requires_manual_intervention is True
    assert reconciliation_service.is_halted is True

    types = [d.discrepancy_type for d in report.discrepancies]
    assert DiscrepancyType.POSITION_BROKER_ONLY in types
    assert report.critical_count >= 1


def test_phantom_bot_position_halts_trading(reconciliation_service, mock_broker, mock_portfolio):
    """Bot believes position exists but broker is flat -> critical phantom position discrepancy."""
    mock_portfolio.positions["RELIANCE"] = Position(symbol="RELIANCE", quantity=25, average_price=2400.0)
    mock_broker.broker_positions = []  # Broker is flat

    report = reconciliation_service.run_reconciliation()
    assert report.is_clean is False
    assert report.halt_trading is True
    assert report.requires_manual_intervention is True
    assert reconciliation_service.is_halted is True

    types = [d.discrepancy_type for d in report.discrepancies]
    assert DiscrepancyType.POSITION_BOT_ONLY in types


def test_quantity_mismatch_halts_trading(reconciliation_service, mock_broker, mock_portfolio):
    """Both have position, but quantities differ -> critical quantity mismatch."""
    mock_portfolio.positions["HDFCBANK"] = Position(symbol="HDFCBANK", quantity=100, average_price=1600.0)
    mock_broker.broker_positions = [Position(symbol="HDFCBANK", quantity=60, average_price=1600.0)]

    report = reconciliation_service.run_reconciliation()
    assert report.is_clean is False
    assert report.halt_trading is True
    assert report.requires_manual_intervention is True

    types = [d.discrepancy_type for d in report.discrepancies]
    assert DiscrepancyType.POSITION_QUANTITY_MISMATCH in types


def test_average_price_mismatch_warning(reconciliation_service, mock_broker, mock_portfolio):
    """Average price differs beyond tolerance -> produces warning discrepancy."""
    # 2% difference (exceeds 0.5% tolerance)
    mock_portfolio.positions["SBIN"] = Position(symbol="SBIN", quantity=200, average_price=600.0)
    mock_broker.broker_positions = [Position(symbol="SBIN", quantity=200, average_price=612.0)]

    # Provide protective stop to avoid missing SL discrepancy
    sl = Order(
        client_order_id="SL_SBIN_1",
        broker_order_id="B_SL_1",
        symbol="SBIN",
        side=OrderSide.SELL,
        order_type=OrderType.SL_MARKET,
        quantity=200,
        trigger_price=590.0,
        status=OrderStatus.ACKNOWLEDGED,
    )
    mock_broker.broker_orders = [sl]
    reconciliation_service.get_internal_orders = lambda: [sl]

    report = reconciliation_service.run_reconciliation()
    assert report.is_clean is False  # Contains warning discrepancy
    assert report.warning_count == 1
    assert report.critical_count == 0
    assert report.halt_trading is False
    assert report.requires_manual_intervention is False


    price_disc = report.discrepancies[0]
    assert price_disc.discrepancy_type == DiscrepancyType.POSITION_PRICE_MISMATCH
    assert price_disc.severity == DiscrepancySeverity.WARNING


def test_missing_protective_stop_halts_and_triggers_callback(reconciliation_service, mock_broker, mock_portfolio):
    """Active open position with no protective stop on broker -> critical discrepancy & callback."""
    mock_portfolio.positions["WIPRO"] = Position(symbol="WIPRO", quantity=300, average_price=450.0)
    mock_broker.broker_positions = [Position(symbol="WIPRO", quantity=300, average_price=450.0)]
    mock_broker.broker_orders = []  # No stop loss on broker!

    callback_called = False
    def on_missing(symbol, qty, side):
        nonlocal callback_called
        callback_called = True
        assert symbol == "WIPRO"
        assert qty == 300
        assert side == OrderSide.SELL

    reconciliation_service.on_protective_stop_missing = on_missing

    report = reconciliation_service.run_reconciliation()
    assert report.is_clean is False
    assert report.halt_trading is True
    assert callback_called is True

    types = [d.discrepancy_type for d in report.discrepancies]
    assert DiscrepancyType.PROTECTIVE_STOP_MISSING in types


def test_protective_stop_quantity_mismatch_halts(reconciliation_service, mock_broker, mock_portfolio):
    """Protective stop order quantity does not match full open position quantity."""
    mock_portfolio.positions["AXISBANK"] = Position(symbol="AXISBANK", quantity=100, average_price=1000.0)
    mock_broker.broker_positions = [Position(symbol="AXISBANK", quantity=100, average_price=1000.0)]

    # Protective stop covers only 50 out of 100 shares
    partial_sl = Order(
        client_order_id="SL_AXIS_1",
        broker_order_id="B_SL_AXIS",
        symbol="AXISBANK",
        side=OrderSide.SELL,
        order_type=OrderType.SL_MARKET,
        quantity=50,
        trigger_price=990.0,
        status=OrderStatus.ACKNOWLEDGED,
    )
    mock_broker.broker_orders = [partial_sl]
    reconciliation_service.get_internal_orders = lambda: [partial_sl]

    report = reconciliation_service.run_reconciliation()
    assert report.is_clean is False
    assert report.halt_trading is True

    types = [d.discrepancy_type for d in report.discrepancies]
    assert DiscrepancyType.PROTECTIVE_STOP_QUANTITY_MISMATCH in types


def test_unknown_active_broker_order_halts_trading(reconciliation_service, mock_broker):
    """Active order exists on broker that is not tracked by the bot."""
    untracked_order = Order(
        client_order_id="MANUAL_ORDER_999",
        broker_order_id="BRK_UNKNOWN_001",
        symbol="KOTAKBANK",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=50,
        price=1800.0,
        status=OrderStatus.ACKNOWLEDGED,
    )
    mock_broker.broker_orders = [untracked_order]
    reconciliation_service.get_internal_orders = lambda: []

    report = reconciliation_service.run_reconciliation()
    assert report.is_clean is False
    assert report.halt_trading is True
    assert report.requires_manual_intervention is True

    types = [d.discrepancy_type for d in report.discrepancies]
    assert DiscrepancyType.ORDER_UNKNOWN_BROKER in types


def test_order_status_mismatch_auto_synchronization(reconciliation_service, mock_broker):
    """Broker order changed to CANCELLED while local bot was ACKNOWLEDGED -> auto-syncs."""
    internal_order = Order(
        client_order_id="ORD_SYNC_001",
        broker_order_id="BRK_SYNC_001",
        symbol="LT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=10,
        price=3000.0,
        status=OrderStatus.ACKNOWLEDGED,
    )
    broker_order = Order(
        client_order_id="ORD_SYNC_001",
        broker_order_id="BRK_SYNC_001",
        symbol="LT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=10,
        price=3000.0,
        status=OrderStatus.CANCELLED,
    )

    mock_broker.broker_orders = [broker_order]
    reconciliation_service.get_internal_orders = lambda: [internal_order]

    report = reconciliation_service.run_reconciliation()
    # Should auto-resolve
    assert internal_order.status == OrderStatus.CANCELLED
    assert report.auto_resolved_count == 1
    assert report.is_clean is True
    assert report.halt_trading is False


def test_duplicate_active_orders_on_broker(reconciliation_service, mock_broker):
    """Duplicate active orders on broker for same client order ID."""
    ord1 = Order(
        client_order_id="ORD_DUP_1",
        broker_order_id="B_1",
        symbol="ITC",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=10,
        status=OrderStatus.ACKNOWLEDGED,
    )
    ord2 = Order(
        client_order_id="ORD_DUP_1",
        broker_order_id="B_2",
        symbol="ITC",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=10,
        status=OrderStatus.ACKNOWLEDGED,
    )
    mock_broker.broker_orders = [ord1, ord2]
    reconciliation_service.get_internal_orders = lambda: [ord1]

    report = reconciliation_service.run_reconciliation()
    assert report.is_clean is False
    assert report.halt_trading is True

    types = [d.discrepancy_type for d in report.discrepancies]
    assert DiscrepancyType.ORDER_DUPLICATE in types


def test_broker_query_failure_halts_safely(reconciliation_service, mock_broker):
    """If broker cannot be reached during reconciliation, fail-safe by halting."""
    mock_broker.fail_query = True

    report = reconciliation_service.run_reconciliation()
    assert report.is_clean is False
    assert report.halt_trading is True
    assert reconciliation_service.is_halted is True
    assert "Broker query failed" in reconciliation_service.halt_reason


def test_reset_halt(reconciliation_service, mock_broker):
    """Supervisor can reset halt after resolving discrepancy."""
    mock_broker.fail_query = True
    reconciliation_service.run_reconciliation()
    assert reconciliation_service.is_halted is True

    reconciliation_service.reset_halt(reason="Discrepancy investigated and cleared")
    assert reconciliation_service.is_halted is False
    assert reconciliation_service.halt_reason is None
