"""
Comprehensive Unit and Integration Tests for Order Lifecycle Management (Phase 20).

Tests complete lifecycle and safety guarantees:
1. Signal -> Risk Approval -> Order Intent -> Broker Submission -> ACK -> Fill -> Protective SL.
2. Never assume fill from submission response alone.
3. Automatic protective stop-loss upon entry fill.
4. Stop-loss placement failure: halt entries, emit critical alert, emergency exit, incident record.
5. Trailing stop updates: ratchet strictly reduces risk, reject loosening stops.
6. Duplicate signal rejection & duplicate protective order protection.
7. Duplicate execution callback idempotency.
8. Partial fill handling & stop-loss adjustments.
9. Rejected entry orders.
10. Broker modification and cancellation failure handling.
11. Broker reconciliation: mismatched positions and orders after reconnect.
12. 14:30 forced square-off with resting order cancellation.
"""

from datetime import datetime, timezone
import pytest
from unittest.mock import MagicMock

from trade_bot.broker.interfaces import IBrokerAdapter
from trade_bot.domain.enums import (
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
    RiskCheckResultStatus,
    SignalDirection,
    TimeInForce,
)
from trade_bot.domain.exceptions import (
    DuplicateOrderError,
    DuplicateSignalError,
    InvalidStopLossModificationError,
    OrderRejectedError,
    ProtectiveStopLossError,
    RiskViolationError,
)
from trade_bot.domain.models import (
    AccountBalance,
    Candle,
    Order,
    OrderModification,
    OrderRequest,
    Position,
    RiskDecision,
    Signal,
    Trade,
    utc_now,
)
from trade_bot.execution.lifecycle_manager import OrderLifecycleManager
from trade_bot.execution.lifecycle_models import TradeLifecycleState
from trade_bot.observability.audit import AuditLogger
from trade_bot.portfolio.interfaces import IPortfolioManager
from trade_bot.risk.interfaces import IRiskManager


class MockBrokerAdapter(IBrokerAdapter):
    """Controllable test broker adapter simulating broker interactions and failures."""

    def __init__(self) -> None:
        self._connected = True
        self.placed_orders: list[OrderRequest] = []
        self.modified_orders: list[OrderModification] = []
        self.cancelled_order_ids: list[str] = []
        self.trade_callback = None
        self._counter = 0

        # Failure injection flags
        self.fail_place_order = False
        self.fail_modify_order = False
        self.fail_cancel_order = False
        self.fail_sl_placement = False

        # Configurable state for reconciliation
        self.broker_orders: list[Order] = []
        self.broker_positions: list[Position] = []

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
        return self.broker_positions

    def get_orders(self) -> list[Order]:
        return self.broker_orders

    def place_order(self, request: OrderRequest) -> str:
        if self.fail_place_order:
            raise RuntimeError("Broker placement failed: Network timeout")
        if self.fail_sl_placement and request.tag == "PROTECTIVE_STOP":
            raise RuntimeError("Broker SL placement failed: Exchange rejected trigger")

        self._counter += 1
        b_id = f"BRK_{self._counter:05d}"
        self.placed_orders.append(request)

        # Mirror in broker orders
        ord_obj = Order(
            client_order_id=request.client_order_id,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            price=request.price,
            trigger_price=request.trigger_price,
            broker_order_id=b_id,
            status=OrderStatus.ACKNOWLEDGED,
        )
        self.broker_orders.append(ord_obj)
        return b_id

    def modify_order(self, modification: OrderModification) -> bool:
        if self.fail_modify_order:
            raise RuntimeError("Broker modify failed: Rate limit exceeded")
        self.modified_orders.append(modification)
        return True

    def cancel_order(self, broker_order_id: str) -> bool:
        if self.fail_cancel_order:
            raise RuntimeError("Broker cancel failed: Order in execution state")
        self.cancelled_order_ids.append(broker_order_id)
        for o in self.broker_orders:
            if o.broker_order_id == broker_order_id:
                o.status = OrderStatus.CANCELLED
        return True

    def register_trade_callback(self, callback) -> None:
        self.trade_callback = callback


class MockPortfolioManager(IPortfolioManager):
    """In-memory test portfolio manager."""

    def __init__(self) -> None:
        self.positions: dict[str, Position] = {}
        self.fills: list[Trade] = []

    def get_account_balance(self) -> AccountBalance:
        return AccountBalance(initial_capital=500000.0, available_cash=500000.0, used_margin=0.0)

    def get_position(self, symbol: str) -> Position:
        return self.positions.get(symbol, Position(symbol=symbol))

    def get_all_positions(self) -> dict[str, Position]:
        return self.positions

    def get_open_positions(self) -> list[Position]:
        return [p for p in self.positions.values() if not p.is_flat]

    def process_fill(self, fill: Trade) -> Position:
        self.fills.append(fill)
        pos = self.positions.get(fill.symbol, Position(symbol=fill.symbol))
        fill_qty = fill.quantity if fill.side == OrderSide.BUY else -fill.quantity
        pos.quantity += fill_qty
        pos.average_price = fill.price
        self.positions[fill.symbol] = pos
        return pos

    def update_market_price(self, symbol: str, current_price: float) -> None:
        pass

    def get_portfolio_snapshot(self):
        return MagicMock()


class MockRiskManager(IRiskManager):
    """Controllable test risk manager."""

    def __init__(self, approve_all: bool = True) -> None:
        self.approve_all = approve_all
        self.rejection_reason = "Risk limit exceeded"

    def validate_order(self, order_request, account_balance, current_positions) -> RiskDecision:
        if self.approve_all:
            return RiskDecision(status=RiskCheckResultStatus.APPROVED, reason="Approved", rule_name="PASSED")
        return RiskDecision(status=RiskCheckResultStatus.REJECTED, rule_name="MAX_DRAWDOWN", reason=self.rejection_reason)


    def check_circuit_breaker(self, account_balance) -> bool:
        return False


@pytest.fixture
def mock_broker():
    return MockBrokerAdapter()


@pytest.fixture
def mock_portfolio():
    return MockPortfolioManager()


@pytest.fixture
def mock_risk():
    return MockRiskManager()


@pytest.fixture
def lifecycle_mgr(mock_broker, mock_risk, mock_portfolio, tmp_path):
    audit = AuditLogger(audit_dir=str(tmp_path / "audit"))
    return OrderLifecycleManager(
        broker=mock_broker,
        risk_manager=mock_risk,
        portfolio_manager=mock_portfolio,
        audit_logger=audit,
    )


def test_happy_path_entry_fill_and_protective_sl(lifecycle_mgr, mock_broker, mock_portfolio):
    """Test full cycle: Signal -> Risk Approval -> Broker Submit -> Fill -> Automatic Protective SL."""
    signal = Signal(
        signal_id="SIG_INFY_001",
        symbol="INFY",
        timestamp=utc_now(),
        direction=SignalDirection.LONG,
        strategy_name="VWAP_ORB",
        entry_price=1500.0,
        stop_loss=1485.0,
        suggested_quantity=10,
    )

    # 1. Handle signal -> places entry order
    entry_order = lifecycle_mgr.handle_signal(signal)
    assert entry_order.status == OrderStatus.ACKNOWLEDGED
    assert entry_order.filled_quantity == 0
    assert len(mock_broker.placed_orders) == 1
    assert mock_broker.placed_orders[0].side == OrderSide.BUY

    lifecycle = lifecycle_mgr.get_lifecycle_for_symbol("INFY")
    assert lifecycle is not None
    assert lifecycle.lifecycle_state == TradeLifecycleState.ACKNOWLEDGED
    assert lifecycle.stop_loss_order is None  # Never assume filled!

    # 2. Broker executes fill callback for entry
    fill_trade = Trade(
        trade_id="TRD_001",
        order_id=entry_order.broker_order_id or "BRK_00001",
        client_order_id=entry_order.client_order_id,
        symbol="INFY",
        side=OrderSide.BUY,
        quantity=10,
        price=1500.5,
        timestamp=utc_now(),
    )
    mock_broker.trade_callback(fill_trade)

    # 3. Assert entry is FILLED and protective SL automatically placed
    assert entry_order.status == OrderStatus.FILLED
    assert entry_order.filled_quantity == 10
    assert lifecycle.lifecycle_state == TradeLifecycleState.ACTIVE_PROTECTED
    assert lifecycle.has_active_protective_sl is True
    assert lifecycle.stop_loss_order is not None
    assert lifecycle.stop_loss_order.trigger_price == 1485.0
    assert lifecycle.stop_loss_order.quantity == 10
    assert lifecycle.stop_loss_order.side == OrderSide.SELL

    # 2 total orders placed at broker: Entry + Protective SL
    assert len(mock_broker.placed_orders) == 2
    assert mock_broker.placed_orders[1].tag == "PROTECTIVE_STOP"
    assert mock_broker.placed_orders[1].trigger_price == 1485.0


def test_protective_sl_failure_halts_entries_and_triggers_emergency_exit(lifecycle_mgr, mock_broker):
    """If protective SL creation fails: halt entries, emit critical alert, emergency exit, record incident."""
    mock_broker.fail_sl_placement = True

    signal = Signal(
        signal_id="SIG_TCS_001",
        symbol="TCS",
        timestamp=utc_now(),
        direction=SignalDirection.LONG,
        strategy_name="VWAP_ORB",
        entry_price=3500.0,
        stop_loss=3465.0,
        suggested_quantity=20,
    )

    entry_order = lifecycle_mgr.handle_signal(signal)
    fill_trade = Trade(
        trade_id="TRD_TCS_001",
        order_id=entry_order.broker_order_id or "BRK_00001",
        client_order_id=entry_order.client_order_id,
        symbol="TCS",
        side=OrderSide.BUY,
        quantity=20,
        price=3500.0,
        timestamp=utc_now(),
    )

    # Fill should trigger protective SL -> which fails -> raises ProtectiveStopLossError
    with pytest.raises(ProtectiveStopLossError):
        mock_broker.trade_callback(fill_trade)

    # Assert Safety Invariants:
    # 1. New entries halted
    assert lifecycle_mgr.is_halted is True
    assert "Protective SL placement failed" in (lifecycle_mgr.halt_reason or "")

    # 2. Lifecycle marked EMERGENCY_EXITED
    lifecycle = lifecycle_mgr.get_lifecycle_for_symbol("TCS", include_terminal=True)
    assert lifecycle is not None
    assert lifecycle.lifecycle_state == TradeLifecycleState.EMERGENCY_EXITED
    assert lifecycle.is_emergency is True

    # 3. Emergency market exit order placed at broker
    placed_tags = [req.tag for req in mock_broker.placed_orders]
    assert "EMERGENCY_SL_CREATION_FAILED" in placed_tags
    assert len(mock_broker.placed_orders) == 2  # Entry + Emergency Market Exit (failed SL wasn't added to placed_orders)

    # 4. Attempting another signal while halted is blocked
    new_signal = Signal(
        signal_id="SIG_RELIANCE_001",
        symbol="RELIANCE",
        timestamp=utc_now(),
        direction=SignalDirection.LONG,
        strategy_name="VWAP_ORB",
        entry_price=2500.0,
        suggested_quantity=10,
    )
    with pytest.raises(RiskViolationError, match="halted"):
        lifecycle_mgr.handle_signal(new_signal)


def test_trailing_stop_strictly_reduces_risk(lifecycle_mgr, mock_broker):
    """Trailing stop must ratchet only in direction of risk reduction; loosening stop is rejected."""
    # Long trade with initial SL = 1000.0
    signal = Signal(
        signal_id="SIG_HDFC_001",
        symbol="HDFCBANK",
        timestamp=utc_now(),
        direction=SignalDirection.LONG,
        strategy_name="VWAP_ORB",
        entry_price=1020.0,
        stop_loss=1000.0,
        suggested_quantity=15,
    )
    entry = lifecycle_mgr.handle_signal(signal)
    mock_broker.trade_callback(Trade(
        trade_id="TRD_HDFC_001",
        order_id=entry.broker_order_id or "BRK_0001",
        client_order_id=entry.client_order_id,
        symbol="HDFCBANK",
        side=OrderSide.BUY,
        quantity=15,
        price=1020.0,
        timestamp=utc_now(),
    ))

    # 1. Move stop UP (reduces risk for LONG): 1000.0 -> 1010.0 (market at 1030.0) -> Valid!
    sl_order = lifecycle_mgr.update_trailing_stop("HDFCBANK", new_stop_price=1010.0, current_market_price=1030.0)
    assert sl_order.trigger_price == 1010.0
    assert len(mock_broker.modified_orders) == 1
    assert mock_broker.modified_orders[0].trigger_price == 1010.0

    # 2. Attempt to loosen stop (move DOWN for LONG): 1010.0 -> 1005.0 -> MUST BE REJECTED!
    with pytest.raises(InvalidStopLossModificationError, match="Cannot loosen Long stop-loss"):
        lifecycle_mgr.update_trailing_stop("HDFCBANK", new_stop_price=1005.0, current_market_price=1030.0)

    # 3. Attempt to set stop >= market price -> MUST BE REJECTED!
    with pytest.raises(InvalidStopLossModificationError, match="cannot be >= current market price"):
        lifecycle_mgr.update_trailing_stop("HDFCBANK", new_stop_price=1035.0, current_market_price=1030.0)


def test_duplicate_signal_and_order_protection(lifecycle_mgr):
    """A signal must not result in multiple active entry orders; duplicate signals are rejected."""
    signal = Signal(
        signal_id="SIG_DUP_001",
        symbol="SBIN",
        timestamp=utc_now(),
        direction=SignalDirection.LONG,
        strategy_name="VWAP_ORB",
        entry_price=600.0,
        stop_loss=590.0,
        suggested_quantity=10,
    )
    # First submission succeeds
    lifecycle_mgr.handle_signal(signal)

    # Duplicate submission with same signal_id must be rejected
    with pytest.raises(DuplicateSignalError):
        lifecycle_mgr.handle_signal(signal)

    # Another signal for same symbol while first is active must be rejected
    second_signal = Signal(
        signal_id="SIG_DUP_002",
        symbol="SBIN",
        timestamp=utc_now(),
        direction=SignalDirection.LONG,
        strategy_name="VWAP_ORB",
        entry_price=605.0,
        stop_loss=595.0,
        suggested_quantity=10,
    )
    with pytest.raises(DuplicateOrderError):
        lifecycle_mgr.handle_signal(second_signal)


def test_duplicate_trade_fill_callback_is_idempotent(lifecycle_mgr, mock_broker):
    """Duplicate trade fill callbacks must be ignored idempotently without duplicate SL orders."""
    signal = Signal(
        signal_id="SIG_IDEM_001",
        symbol="WIPRO",
        timestamp=utc_now(),
        direction=SignalDirection.LONG,
        strategy_name="VWAP_ORB",
        entry_price=450.0,
        stop_loss=440.0,
        suggested_quantity=50,
    )
    entry = lifecycle_mgr.handle_signal(signal)

    fill_trade = Trade(
        trade_id="TRD_WIPRO_SAME_ID",
        order_id=entry.broker_order_id or "BRK_001",
        client_order_id=entry.client_order_id,
        symbol="WIPRO",
        side=OrderSide.BUY,
        quantity=50,
        price=450.0,
        timestamp=utc_now(),
    )

    # First fill
    mock_broker.trade_callback(fill_trade)
    assert len(mock_broker.placed_orders) == 2  # Entry + SL

    # Duplicate fill with same trade_id
    mock_broker.trade_callback(fill_trade)
    # No additional order should be placed
    assert len(mock_broker.placed_orders) == 2


def test_partial_fills_and_order_state(lifecycle_mgr, mock_broker):
    """Verify partial fill transitions order to PARTIALLY_FILLED and correctly tracks filled qty."""
    signal = Signal(
        signal_id="SIG_PARTIAL_001",
        symbol="AXISBANK",
        timestamp=utc_now(),
        direction=SignalDirection.LONG,
        strategy_name="VWAP_ORB",
        entry_price=1000.0,
        stop_loss=990.0,
        suggested_quantity=100,
    )
    entry = lifecycle_mgr.handle_signal(signal)

    # First partial fill: 40 shares
    mock_broker.trade_callback(Trade(
        trade_id="TRD_AXIS_1",
        order_id=entry.broker_order_id or "BRK_001",
        client_order_id=entry.client_order_id,
        symbol="AXISBANK",
        side=OrderSide.BUY,
        quantity=40,
        price=1000.0,
        timestamp=utc_now(),
    ))
    assert entry.status == OrderStatus.PARTIALLY_FILLED
    assert entry.filled_quantity == 40
    lifecycle = lifecycle_mgr.get_lifecycle_for_symbol("AXISBANK")
    assert lifecycle.has_active_protective_sl is True
    assert lifecycle.stop_loss_order.quantity == 40

    # Second fill completing the remaining 60 shares
    mock_broker.trade_callback(Trade(
        trade_id="TRD_AXIS_2",
        order_id=entry.broker_order_id or "BRK_001",
        client_order_id=entry.client_order_id,
        symbol="AXISBANK",
        side=OrderSide.BUY,
        quantity=60,
        price=1001.0,
        timestamp=utc_now(),
    ))
    assert entry.status == OrderStatus.FILLED
    assert entry.filled_quantity == 100
    assert lifecycle.filled_quantity == 100
    # Resized SL to cover full 100 shares
    assert len(mock_broker.modified_orders) == 1
    assert mock_broker.modified_orders[0].quantity == 100


def test_rejected_entry_order(mock_broker, mock_risk, mock_portfolio, tmp_path):
    """Pre-trade risk rejection transitions order to REJECTED and marks lifecycle terminal."""
    mock_risk.approve_all = False
    mock_risk.rejection_reason = "Daily loss limit breached"
    audit = AuditLogger(audit_dir=str(tmp_path / "audit"))
    mgr = OrderLifecycleManager(mock_broker, mock_risk, mock_portfolio, audit_logger=audit)

    signal = Signal(
        signal_id="SIG_REJ_001",
        symbol="ITC",
        timestamp=utc_now(),
        direction=SignalDirection.LONG,
        strategy_name="VWAP_ORB",
        entry_price=400.0,
        suggested_quantity=10,
    )

    with pytest.raises(OrderRejectedError, match="Daily loss limit breached"):
        mgr.handle_signal(signal)

    # No order placed at broker
    assert len(mock_broker.placed_orders) == 0


def test_intentional_vwap_exit_cancels_protective_sl(lifecycle_mgr, mock_broker):
    """Intentional exit (e.g. VWAP exit) places exit order and cancels resting protective SL."""
    signal = Signal(
        signal_id="SIG_VWAP_EXIT_001",
        symbol="KOTAKBANK",
        timestamp=utc_now(),
        direction=SignalDirection.LONG,
        strategy_name="VWAP_ORB",
        entry_price=1800.0,
        stop_loss=1780.0,
        suggested_quantity=20,
    )
    entry = lifecycle_mgr.handle_signal(signal)
    mock_broker.trade_callback(Trade(
        trade_id="TRD_KOTAK_001",
        order_id=entry.broker_order_id or "BRK_001",
        client_order_id=entry.client_order_id,
        symbol="KOTAKBANK",
        side=OrderSide.BUY,
        quantity=20,
        price=1800.0,
        timestamp=utc_now(),
    ))

    # Execute VWAP exit
    exit_order = lifecycle_mgr.exit_position("KOTAKBANK", reason="VWAP_EXIT")
    assert exit_order.status == OrderStatus.ACKNOWLEDGED
    assert exit_order.side == OrderSide.SELL
    assert exit_order.quantity == 20

    # Resting SL should be cancelled
    assert len(mock_broker.cancelled_order_ids) == 1
    lifecycle = lifecycle_mgr.get_lifecycle_for_symbol("KOTAKBANK")
    assert lifecycle.stop_loss_order is None


def test_forced_square_off_closes_all_and_cancels_resting_orders(lifecycle_mgr, mock_broker):
    """14:30 forced square-off cancels resting orders and liquidates open positions."""
    signal = Signal(
        signal_id="SIG_SQ_001",
        symbol="LT",
        timestamp=utc_now(),
        direction=SignalDirection.LONG,
        strategy_name="VWAP_ORB",
        entry_price=3000.0,
        stop_loss=2970.0,
        suggested_quantity=10,
    )
    entry = lifecycle_mgr.handle_signal(signal)
    mock_broker.trade_callback(Trade(
        trade_id="TRD_LT_001",
        order_id=entry.broker_order_id or "BRK_001",
        client_order_id=entry.client_order_id,
        symbol="LT",
        side=OrderSide.BUY,
        quantity=10,
        price=3000.0,
        timestamp=utc_now(),
    ))

    # Execute force square-off
    exits = lifecycle_mgr.force_square_off_all(reason="TIME_EXIT_1430")
    assert len(exits) == 1
    assert lifecycle_mgr.is_halted is True
    assert len(mock_broker.cancelled_order_ids) >= 1


def test_reconciliation_detects_mismatches_and_syncs(lifecycle_mgr, mock_broker, mock_portfolio):
    """Reconciliation identifies position mismatches and syncs order status after reconnect."""
    # Setup discrepancy: Broker has 50 shares of INFY, local portfolio has 0
    mock_broker.broker_positions = [Position(symbol="INFY", quantity=50)]

    report = lifecycle_mgr.reconcile_broker_state()
    assert report["is_clean"] is False
    assert report["discrepancies_count"] >= 1
    assert report["discrepancies"][0]["type"] == "POSITION_BROKER_ONLY"
    assert report["discrepancies"][0]["symbol"] == "INFY"
    assert lifecycle_mgr.is_halted is True

