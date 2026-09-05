"""
Execution Engine.

Coordinates pre-trade risk checks, idempotency, order state lifecycle,
routing to broker adapters, and execution fill updates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional
from trade_bot.broker.interfaces import IBrokerAdapter
from trade_bot.domain.enums import OrderStatus
from trade_bot.domain.exceptions import (
    OrderNotFoundError,
    OrderRejectedError,
    StateInconsistencyError,
)
from trade_bot.domain.models import Order, OrderModification, OrderRequest, Trade, utc_now
from trade_bot.domain.state import OrderStateMachine
from trade_bot.execution.idempotency import IdempotencyManager
from trade_bot.execution.interfaces import IExecutionEngine
from trade_bot.portfolio.interfaces import IPortfolioManager
from trade_bot.risk.interfaces import IRiskManager


class ExecutionEngine(IExecutionEngine):
    """
    Production execution engine managing order lifecycles and broker interaction.
    """

    def __init__(
        self,
        broker: IBrokerAdapter,
        risk_manager: IRiskManager,
        portfolio_manager: IPortfolioManager,
        idempotency_manager: Optional[IdempotencyManager] = None,
    ) -> None:
        self.broker = broker
        self.risk_manager = risk_manager
        self.portfolio_manager = portfolio_manager
        self.idempotency_manager = idempotency_manager or IdempotencyManager()

        self._orders_by_client_id: Dict[str, Order] = {}
        self._orders_by_broker_id: Dict[str, Order] = {}

    def get_order(self, client_order_id: str) -> Optional[Order]:
        """Retrieve order state by client_order_id."""
        return self._orders_by_client_id.get(client_order_id)

    def get_active_orders(self) -> List[Order]:
        """Return all active, non-terminal orders."""
        return [order for order in self._orders_by_client_id.values() if order.is_active]

    def submit_order(self, order_request: OrderRequest) -> Order:
        """
        Validate, register, and submit order to broker adapter.
        """
        # Step 1: Idempotency check
        self.idempotency_manager.check_and_register(order_request)

        # Step 2: Pre-trade risk validation
        balance = self.portfolio_manager.get_account_balance()
        positions = self.portfolio_manager.get_all_positions()
        risk_decision = self.risk_manager.validate_order(order_request, balance, positions)

        if not risk_decision.is_approved:
            rejected_order = Order(
                client_order_id=order_request.client_order_id,
                symbol=order_request.symbol,
                side=order_request.side,
                order_type=order_request.order_type,
                quantity=order_request.quantity,
                product_type=order_request.product_type,
                time_in_force=order_request.time_in_force,
                price=order_request.price,
                trigger_price=order_request.trigger_price,
                status=OrderStatus.REJECTED,
                strategy_name=order_request.strategy_name,
                signal_id=order_request.signal_id,
                rejection_reason=risk_decision.reason,
            )
            self._orders_by_client_id[rejected_order.client_order_id] = rejected_order
            raise OrderRejectedError(
                f"Order rejected by risk management rule '{risk_decision.rule_name}': {risk_decision.reason}",
                context={"client_order_id": order_request.client_order_id, "rule": risk_decision.rule_name},
            )

        # Step 3: Create domain Order model
        order = Order(
            client_order_id=order_request.client_order_id,
            symbol=order_request.symbol,
            side=order_request.side,
            order_type=order_request.order_type,
            quantity=order_request.quantity,
            product_type=order_request.product_type,
            time_in_force=order_request.time_in_force,
            price=order_request.price,
            trigger_price=order_request.trigger_price,
            status=OrderStatus.CREATED,
            strategy_name=order_request.strategy_name,
            signal_id=order_request.signal_id,
        )
        self._orders_by_client_id[order.client_order_id] = order

        # Step 4: Advance to PENDING_SUBMIT and submit to broker
        OrderStateMachine.transition(order, OrderStatus.PENDING_SUBMIT)
        try:
            broker_order_id = self.broker.place_order(order_request)
            order.broker_order_id = broker_order_id
            self._orders_by_broker_id[broker_order_id] = order
            if order.is_active and order.status == OrderStatus.PENDING_SUBMIT:
                OrderStateMachine.transition(order, OrderStatus.ACKNOWLEDGED)
        except Exception as e:
            OrderStateMachine.transition(order, OrderStatus.REJECTED, reason=str(e))
            raise

        return order

    def cancel_order(self, client_order_id: str, reason: Optional[str] = None) -> Order:
        """Cancel an active order."""
        order = self.get_order(client_order_id)
        if order is None:
            raise OrderNotFoundError(
                f"Cannot cancel order: client_order_id '{client_order_id}' not found",
                context={"client_order_id": client_order_id},
            )

        if not order.is_active:
            return order

        if order.broker_order_id:
            self.broker.cancel_order(order.broker_order_id)

        OrderStateMachine.transition(order, OrderStatus.CANCELLED, reason=reason)
        return order

    def modify_order(self, modification: OrderModification) -> Order:
        """Modify an active order's price or quantity."""
        order = self.get_order(modification.client_order_id)
        if order is None:
            raise OrderNotFoundError(
                f"Cannot modify order: client_order_id '{modification.client_order_id}' not found",
                context={"client_order_id": modification.client_order_id},
            )

        if not order.is_active:
            raise StateInconsistencyError(
                f"Cannot modify terminal order {modification.client_order_id} with status {order.status.value}"
            )

        self.broker.modify_order(modification)
        if modification.price is not None:
            order.price = modification.price
        if modification.quantity is not None:
            order.quantity = modification.quantity
        if modification.trigger_price is not None:
            order.trigger_price = modification.trigger_price
        order.updated_at = utc_now()
        return order

    def handle_fill(self, trade: Trade) -> Order:
        """
        Process fill callback from broker adapter:
        Updates order filled quantity, average fill price, and forwards fill to PortfolioManager.
        """
        order = self.get_order(trade.client_order_id)
        if order is None:
            raise OrderNotFoundError(
                f"Fill received for unknown client_order_id '{trade.client_order_id}'",
                context={"trade_id": trade.trade_id, "client_order_id": trade.client_order_id},
            )

        order.fills.append(trade)
        new_filled_qty = order.filled_quantity + trade.quantity

        # Recalculate average fill price
        total_fill_cost = (order.average_fill_price * order.filled_quantity) + (trade.price * trade.quantity)
        order.filled_quantity = new_filled_qty
        order.average_fill_price = round(total_fill_cost / new_filled_qty, 4)

        # Transition order state
        if order.filled_quantity >= order.quantity:
            OrderStateMachine.transition(order, OrderStatus.FILLED, timestamp=trade.timestamp)
        else:
            OrderStateMachine.transition(order, OrderStatus.PARTIALLY_FILLED, timestamp=trade.timestamp)

        # Update portfolio ledger
        self.portfolio_manager.process_fill(trade)
        return order
