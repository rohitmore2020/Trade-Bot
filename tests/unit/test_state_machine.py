"""
Unit tests for Order State Machine and Position Tracking.
"""

from datetime import datetime, timezone
import pytest
from trade_bot.domain.enums import OrderSide, OrderStatus, OrderType, PositionSide
from trade_bot.domain.exceptions import InvalidOrderStateTransitionError
from trade_bot.domain.models import Order, Trade
from trade_bot.domain.state import OrderStateMachine, PositionTracker


def test_order_state_valid_lifecycle() -> None:
    order = Order(
        client_order_id="ORD_001",
        symbol="RELIANCE",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=10,
        price=2500.0,
    )
    assert order.status == OrderStatus.CREATED

    # Advance to PENDING_SUBMIT
    OrderStateMachine.transition(order, OrderStatus.PENDING_SUBMIT)
    assert order.status == OrderStatus.PENDING_SUBMIT

    # Advance to ACKNOWLEDGED
    OrderStateMachine.transition(order, OrderStatus.ACKNOWLEDGED)
    assert order.status == OrderStatus.ACKNOWLEDGED

    # Advance to FILLED
    OrderStateMachine.transition(order, OrderStatus.FILLED)
    assert order.status == OrderStatus.FILLED
    assert order.is_terminal is True


def test_order_state_invalid_transition_rejected() -> None:
    order = Order(
        client_order_id="ORD_002",
        symbol="RELIANCE",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=10,
        price=2500.0,
    )
    # Direct jump from CREATED to FILLED is illegal
    with pytest.raises(InvalidOrderStateTransitionError):
        OrderStateMachine.transition(order, OrderStatus.FILLED)


def test_position_tracker_buy_and_square_off() -> None:
    tracker = PositionTracker(symbol="RELIANCE")
    assert tracker.position.is_flat is True

    # Fill 1: Buy 10 shares at 2500
    trade1 = Trade(
        trade_id="TRD_1",
        order_id="BK_1",
        client_order_id="ORD_1",
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=10,
        price=2500.0,
        timestamp=datetime.now(timezone.utc),
    )
    pos = tracker.apply_trade(trade1)
    assert pos.quantity == 10
    assert pos.average_price == 2500.0
    assert pos.side == PositionSide.LONG

    # Fill 2: Sell 10 shares at 2520 (Profit of 20 * 10 = 200)
    trade2 = Trade(
        trade_id="TRD_2",
        order_id="BK_2",
        client_order_id="ORD_2",
        symbol="RELIANCE",
        side=OrderSide.SELL,
        quantity=10,
        price=2520.0,
        timestamp=datetime.now(timezone.utc),
    )
    pos = tracker.apply_trade(trade2)
    assert pos.quantity == 0
    assert pos.is_flat is True
    assert pos.realized_pnl == 200.0
