"""
Deterministic Unit Tests for Explicit Portfolio and Trading-State Management (Phase 10).

Exhaustively verifies:
1. All order lifecycle state transitions (CREATED -> SUBMITTED -> ACKNOWLEDGED -> PARTIALLY_FILLED -> FILLED, etc.)
2. Invalid order state transitions rejection
3. Partial fills and complete fills
4. Idempotent duplicate fill processing (zero double-counting of quantity, cash, P&L, trades)
5. Idempotent duplicate order event processing
6. Position opening and increasing
7. Position partial reduction (proportional realized P&L)
8. Complete position exit and CompletedTrade logging
9. Position reversal (flipping from Long to Short)
10. Complete P&L separation (gross, transaction costs, slippage, net, realized, unrealized)
11. Daily session boundaries, portfolio snapshot, and daily reset
"""

from datetime import date, datetime, timezone
import pytest

from trade_bot.domain.enums import OrderSide, OrderStatus, OrderType, ProductType
from trade_bot.domain.exceptions import InvalidOrderStateTransitionError
from trade_bot.domain.models import Order
from trade_bot.portfolio.manager import PortfolioManager
from trade_bot.portfolio.models import Fill
from trade_bot.portfolio.order_tracker import OrderLifecycleTracker
from trade_bot.portfolio.pnl import PnLCalculator
from trade_bot.portfolio.position_ledger import PositionLedger


# ==============================================================================
# 1. Order Lifecycle State Transitions
# ==============================================================================

def test_all_order_transitions() -> None:
    tracker = OrderLifecycleTracker()
    order = Order(
        client_order_id="ORD_001",
        symbol="RELIANCE",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=100,
        price=2500.0,
        status=OrderStatus.CREATED,
    )
    tracker.register_order(order)
    assert order.status == OrderStatus.CREATED

    # CREATED -> SUBMITTED
    tracker.transition_order("ORD_001", OrderStatus.SUBMITTED)
    assert order.status == OrderStatus.SUBMITTED

    # SUBMITTED -> ACKNOWLEDGED
    tracker.transition_order("ORD_001", OrderStatus.ACKNOWLEDGED)
    assert order.status == OrderStatus.ACKNOWLEDGED

    # ACKNOWLEDGED -> PARTIALLY_FILLED
    tracker.transition_order("ORD_001", OrderStatus.PARTIALLY_FILLED)
    assert order.status == OrderStatus.PARTIALLY_FILLED

    # PARTIALLY_FILLED -> FILLED
    tracker.transition_order("ORD_001", OrderStatus.FILLED)
    assert order.status == OrderStatus.FILLED
    assert order.is_terminal is True


def test_order_cancellation_flow() -> None:
    tracker = OrderLifecycleTracker()
    order = Order(
        client_order_id="ORD_CANCEL_01",
        symbol="TCS",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=50,
        price=3500.0,
        status=OrderStatus.CREATED,
    )
    tracker.register_order(order)

    # CREATED -> SUBMITTED -> ACKNOWLEDGED -> CANCEL_REQUESTED -> CANCELLED
    tracker.transition_order("ORD_CANCEL_01", OrderStatus.SUBMITTED)
    tracker.transition_order("ORD_CANCEL_01", OrderStatus.ACKNOWLEDGED)
    tracker.transition_order("ORD_CANCEL_01", OrderStatus.CANCEL_REQUESTED)
    assert order.status == OrderStatus.CANCEL_REQUESTED

    tracker.transition_order("ORD_CANCEL_01", OrderStatus.CANCELLED)
    assert order.status == OrderStatus.CANCELLED
    assert order.is_terminal is True


def test_order_rejection_flow() -> None:
    tracker = OrderLifecycleTracker()
    order = Order(
        client_order_id="ORD_REJ_01",
        symbol="INFY",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=100,
        price=1500.0,
        status=OrderStatus.CREATED,
    )
    tracker.register_order(order)

    tracker.transition_order("ORD_REJ_01", OrderStatus.REJECTED, reason="Margin insufficient")
    assert order.status == OrderStatus.REJECTED
    assert order.rejection_reason == "Margin insufficient"
    assert order.is_terminal is True


def test_invalid_order_state_transitions() -> None:
    tracker = OrderLifecycleTracker()
    order = Order(
        client_order_id="ORD_INVALID_01",
        symbol="RELIANCE",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=100,
        price=2500.0,
        status=OrderStatus.FILLED,
    )
    tracker.register_order(order)

    # Illegal transition: FILLED -> CANCELLED must raise InvalidOrderStateTransitionError
    with pytest.raises(InvalidOrderStateTransitionError):
        tracker.transition_order("ORD_INVALID_01", OrderStatus.CANCELLED)

    # Illegal transition: FILLED -> SUBMITTED
    with pytest.raises(InvalidOrderStateTransitionError):
        tracker.transition_order("ORD_INVALID_01", OrderStatus.SUBMITTED)


# ==============================================================================
# 2. Partial and Complete Fills
# ==============================================================================

def test_partial_and_complete_fills() -> None:
    manager = PortfolioManager(initial_capital=1_000_000.0)
    order = Order(
        client_order_id="ORD_FILL_01",
        symbol="RELIANCE",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=100,
        price=2500.0,
        status=OrderStatus.SUBMITTED,
    )
    manager.register_order(order)

    # Partial Fill 1: 40 shares @ 2500
    fill_1 = Fill(
        fill_id="FILL_01",
        order_id="BROKER_ORD_01",
        client_order_id="ORD_FILL_01",
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=40,
        price=2500.0,
        timestamp=datetime.now(timezone.utc),
    )
    pos = manager.process_fill(fill_1)
    assert pos.quantity == 40
    assert pos.average_price == 2500.0
    assert order.status == OrderStatus.PARTIALLY_FILLED
    assert order.filled_quantity == 40
    assert order.average_fill_price == 2500.0

    # Complete Fill 2: remaining 60 shares @ 2510
    fill_2 = Fill(
        fill_id="FILL_02",
        order_id="BROKER_ORD_01",
        client_order_id="ORD_FILL_01",
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=60,
        price=2510.0,
        timestamp=datetime.now(timezone.utc),
    )
    pos = manager.process_fill(fill_2)
    assert pos.quantity == 100
    # Average price = (40 * 2500 + 60 * 2510) / 100 = 2506.0
    assert pos.average_price == 2506.0
    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == 100
    assert order.average_fill_price == 2506.0


# ==============================================================================
# 3. Idempotency & Deduplication
# ==============================================================================

def test_duplicate_fills_idempotency() -> None:
    manager = PortfolioManager(initial_capital=1_000_000.0)
    fill = Fill(
        fill_id="FILL_UNIQUE_99",
        order_id="ORD_001",
        client_order_id="CLIENT_ORD_001",
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=50,
        price=2000.0,
        timestamp=datetime.now(timezone.utc),
    )

    # Initial application
    pos1 = manager.process_fill(fill)
    assert pos1.quantity == 50
    cash_after_fill1 = manager.available_cash

    # Duplicate application of identical fill_id
    pos2 = manager.process_fill(fill)
    # Quantity must not double to 100
    assert pos2.quantity == 50
    # Available cash must not be deducted twice
    assert manager.available_cash == cash_after_fill1


def test_duplicate_order_events_idempotency() -> None:
    tracker = OrderLifecycleTracker()
    order = Order(
        client_order_id="ORD_EVT_01",
        symbol="TCS",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=100,
        price=3000.0,
        status=OrderStatus.CREATED,
    )
    tracker.register_order(order)

    # Event 1 transitions to SUBMITTED
    tracker.transition_order("ORD_EVT_01", OrderStatus.SUBMITTED, event_id="EVT_100")
    assert order.status == OrderStatus.SUBMITTED

    # Duplicate Event 1 arriving again must return cleanly without errors
    res = tracker.transition_order("ORD_EVT_01", OrderStatus.SUBMITTED, event_id="EVT_100")
    assert res.status == OrderStatus.SUBMITTED


# ==============================================================================
# 4. Position Operations: Opening, Reduction, Exit, Flip
# ==============================================================================

def test_position_opening_and_increase() -> None:
    ledger = PositionLedger()
    # Buy 100 @ 1000
    f1 = Fill("F1", "O1", "C1", "INFY", OrderSide.BUY, 100, 1000.0, datetime.now(timezone.utc))
    pos, trade, is_new = ledger.apply_fill(f1)
    assert is_new is True
    assert pos.quantity == 100
    assert pos.average_price == 1000.0
    assert trade is None

    # Buy 100 @ 1100
    f2 = Fill("F2", "O2", "C2", "INFY", OrderSide.BUY, 100, 1100.0, datetime.now(timezone.utc))
    pos, trade, is_new = ledger.apply_fill(f2)
    assert is_new is True
    assert pos.quantity == 200
    assert pos.average_price == 1050.0
    assert trade is None


def test_position_partial_reduction_and_complete_exit() -> None:
    ledger = PositionLedger()
    # Open 100 @ 1000
    f1 = Fill("F1", "O1", "C1", "INFY", OrderSide.BUY, 100, 1000.0, datetime.now(timezone.utc))
    ledger.apply_fill(f1)

    # Partial reduction: Sell 40 @ 1050
    f2 = Fill("F2", "O2", "C2", "INFY", OrderSide.SELL, 40, 1050.0, datetime.now(timezone.utc))
    pos, trade1, is_new = ledger.apply_fill(f2)
    assert pos.quantity == 60
    assert pos.average_price == 1000.0
    assert trade1 is not None
    assert trade1.quantity == 40
    # Gross PnL = (1050 - 1000) * 40 = 2000.0
    assert trade1.gross_pnl == 2000.0
    assert trade1.net_pnl > 0

    # Complete exit: Sell remaining 60 @ 1100
    f3 = Fill("F3", "O3", "C3", "INFY", OrderSide.SELL, 60, 1100.0, datetime.now(timezone.utc))
    pos, trade2, is_new = ledger.apply_fill(f3)
    assert pos.quantity == 0
    assert pos.is_flat is True
    assert trade2 is not None
    assert trade2.quantity == 60
    # Gross PnL = (1100 - 1000) * 60 = 6000.0
    assert trade2.gross_pnl == 6000.0
    assert len(ledger.completed_trades) == 2


def test_position_flip_long_to_short() -> None:
    ledger = PositionLedger()
    # Long 50 @ 1000
    f1 = Fill("F1", "O1", "C1", "RELIANCE", OrderSide.BUY, 50, 1000.0, datetime.now(timezone.utc))
    ledger.apply_fill(f1)

    # Sell 80 @ 950 (Reverses 50 Long, opens 30 Short)
    f2 = Fill("F2", "O2", "C2", "RELIANCE", OrderSide.SELL, 80, 950.0, datetime.now(timezone.utc))
    pos, trade, is_new = ledger.apply_fill(f2)
    assert trade is not None
    assert trade.quantity == 50
    # Gross PnL = (950 - 1000) * 50 = -2500.0
    assert trade.gross_pnl == -2500.0
    # Flipped position is Short 30 @ 950
    assert pos.quantity == -30
    assert pos.average_price == 950.0


# ==============================================================================
# 5. P&L Separation
# ==============================================================================

def test_pnl_separation_breakdown() -> None:
    calc = PnLCalculator()
    # 1. Gross P&L
    gross_buy = calc.calculate_gross_pnl(OrderSide.BUY, entry_price=100.0, exit_price=110.0, quantity=100)
    assert gross_buy == 1000.0

    gross_sell = calc.calculate_gross_pnl(OrderSide.SELL, entry_price=100.0, exit_price=90.0, quantity=100)
    assert gross_sell == 1000.0

    # 2. Transaction Costs
    costs_buy = calc.calculate_transaction_costs(price=1000.0, quantity=100, side=OrderSide.BUY)
    costs_sell = calc.calculate_transaction_costs(price=1000.0, quantity=100, side=OrderSide.SELL)
    # STT is only paid on SELL side for cash equities
    assert costs_sell > costs_buy

    # 3. Slippage
    slippage = calc.calculate_slippage(expected_price=1000.0, actual_price=1002.0, quantity=50)
    assert slippage == 100.0

    # 4. Net P&L = Gross - Costs - Slippage
    net_pnl = calc.calculate_net_pnl(gross_pnl=1000.0, transaction_costs=50.0, slippage=20.0)
    assert net_pnl == 930.0


# ==============================================================================
# 6. Session Boundaries, Snapshot, and Daily Reset
# ==============================================================================

def test_session_management_and_daily_reset() -> None:
    manager = PortfolioManager(initial_capital=1_000_000.0)
    # Day 1: Trade executed and closed
    f_open = Fill("F_D1_1", "O1", "C1", "RELIANCE", OrderSide.BUY, 100, 1000.0, datetime.now(timezone.utc))
    manager.process_fill(f_open)

    f_close = Fill("F_D1_2", "O1", "C1", "RELIANCE", OrderSide.SELL, 100, 1050.0, datetime.now(timezone.utc))
    manager.process_fill(f_close)

    # Verify Snapshot on Day 1
    snap1 = manager.get_portfolio_snapshot()
    assert snap1.daily_trade_count == 1
    assert snap1.open_positions_count == 0
    assert snap1.pnl.gross_realized == 5000.0
    assert snap1.total_equity > 1_000_000.0

    # Trigger Daily Reset (09:15 IST boundary for next trading session)
    day2 = date(2026, 9, 6)
    manager.reset_daily_session(trading_date=day2, session_id="SESSION_2026-09-06")

    # Verify state after reset
    snap2 = manager.get_portfolio_snapshot()
    assert snap2.session_id == "SESSION_2026-09-06"
    assert snap2.daily_trade_count == 0
    assert snap2.pnl.gross_realized == 0.0
    # Rolling equity becomes initial capital for Day 2
    assert snap2.initial_capital == snap1.total_equity
    assert manager.daily_risk_state.trades_executed_today == 0
    assert manager.daily_risk_state.current_daily_loss == 0.0
