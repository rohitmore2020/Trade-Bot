"""
Execution Simulator for Backtesting.

Models realistic, non-idealized order execution:
- LIMIT entries with price-touch evaluation and 1-bar timeout
- Intra-bar SL-M execution with slippage modeling
- Trailing stop ratcheting
- Immediate market exits (VWAP failure, 14:30 mandatory exit)
- Transaction cost accounting (reusing Phase 10 PnLCalculator)
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional
import uuid

from trade_bot.domain.enums import (
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
    TimeInForce,
)
from trade_bot.domain.models import Candle, Order, OrderRequest
from trade_bot.domain.state import OrderStateMachine
from trade_bot.portfolio.manager import PortfolioManager
from trade_bot.portfolio.models import Fill
from trade_bot.portfolio.pnl import PnLCalculator
from trade_bot.backtest.models import ActiveStopLoss, PendingLimitOrder


class ExecutionSimulator:
    """
    Deterministic execution simulator reproducing realistic exchange dynamics.
    Enforces that orders execute only upon physical price-touch/cross conditions.
    """

    def __init__(
        self,
        portfolio_manager: PortfolioManager,
        slippage_per_share: float = 0.05,
        slippage_pct: float = 0.0,
        default_limit_timeout_bars: int = 1,
    ) -> None:
        self.portfolio_manager = portfolio_manager
        self.slippage_per_share = float(slippage_per_share)
        self.slippage_pct = float(slippage_pct)
        self.default_limit_timeout_bars = default_limit_timeout_bars

        # Pending limit orders: client_order_id -> PendingLimitOrder
        self._pending_limits: Dict[str, PendingLimitOrder] = {}
        # Active stop losses for open positions: symbol -> ActiveStopLoss
        self._active_stops: Dict[str, ActiveStopLoss] = {}
        # History of completed orders: client_order_id -> Order
        self._all_orders: Dict[str, Order] = {}

    @property
    def pending_orders_count(self) -> int:
        return len(self._pending_limits)

    @property
    def active_stops_count(self) -> int:
        return len(self._active_stops)

    def get_all_orders(self) -> List[Order]:
        return list(self._all_orders.values())

    def _calc_slippage(self, price: float) -> float:
        """Calculates per-share slippage amount."""
        pct_slippage = price * self.slippage_pct
        return max(self.slippage_per_share, pct_slippage)

    def submit_limit_order(
        self,
        order_request: OrderRequest,
        timeout_bars: Optional[int] = None,
    ) -> Order:
        """
        Stages a LIMIT order into the pending queue.
        Order will be tested for fill on subsequent candle price action.
        """
        timeout = timeout_bars if timeout_bars is not None else self.default_limit_timeout_bars

        order = Order(
            client_order_id=order_request.client_order_id,
            symbol=order_request.symbol.upper().strip(),
            side=order_request.side,
            order_type=OrderType.LIMIT,
            quantity=order_request.quantity,
            product_type=order_request.product_type or ProductType.MIS,
            time_in_force=order_request.time_in_force or TimeInForce.DAY,
            price=order_request.price,
            trigger_price=order_request.trigger_price,
            status=OrderStatus.CREATED,
            strategy_name=order_request.strategy_name or "VWAP_ORB",
            signal_id=order_request.signal_id,
        )

        # Register in portfolio tracker
        self.portfolio_manager.register_order(order)
        OrderStateMachine.transition(order, OrderStatus.SUBMITTED)
        self.portfolio_manager.transition_order(order.client_order_id, OrderStatus.SUBMITTED)
        OrderStateMachine.transition(order, OrderStatus.ACKNOWLEDGED)
        self.portfolio_manager.transition_order(order.client_order_id, OrderStatus.ACKNOWLEDGED)

        self._pending_limits[order.client_order_id] = PendingLimitOrder(
            order=order,
            placed_at=order.created_at,
            bars_active=0,
            timeout_bars=timeout,
        )
        self._all_orders[order.client_order_id] = order
        return order

    def set_stop_loss(
        self,
        symbol: str,
        side: OrderSide,
        stop_price: float,
        quantity: int,
        parent_order_id: str,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """Registers an active stop-loss order (SL-M)."""
        sym = symbol.upper().strip()
        ts = timestamp or datetime.min
        self._active_stops[sym] = ActiveStopLoss(
            symbol=sym,
            side=side,
            stop_price=round(stop_price, 2),
            quantity=quantity,
            parent_order_id=parent_order_id,
            last_updated=ts,
        )

    def update_stop_loss(self, symbol: str, new_stop: float, timestamp: Optional[datetime] = None) -> None:
        """Ratchets an active trailing stop loss strictly favorably."""
        sym = symbol.upper().strip()
        if sym not in self._active_stops:
            return

        stop_entry = self._active_stops[sym]
        new_level = round(new_stop, 2)

        if stop_entry.side == OrderSide.SELL:
            # Long position: stop price can only move upwards
            if new_level > stop_entry.stop_price:
                stop_entry.stop_price = new_level
                if timestamp:
                    stop_entry.last_updated = timestamp
        elif stop_entry.side == OrderSide.BUY:
            # Short position: stop price can only move downwards
            if new_level < stop_entry.stop_price:
                stop_entry.stop_price = new_level
                if timestamp:
                    stop_entry.last_updated = timestamp

    def remove_stop_loss(self, symbol: str) -> Optional[ActiveStopLoss]:
        """Removes stop loss when position is closed."""
        return self._active_stops.pop(symbol.upper().strip(), None)

    def execute_market_exit(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        current_price: float,
        timestamp: datetime,
        reason: str,
    ) -> Fill:
        """
        Executes immediate market exit with modeled slippage.
        """
        sym = symbol.upper().strip()
        self.remove_stop_loss(sym)

        # Slippage applied unfavorably: SELL gets less, BUY pays more
        slip = self._calc_slippage(current_price)
        if side == OrderSide.SELL:
            fill_price = round(max(0.05, current_price - slip), 2)
        else:
            fill_price = round(current_price + slip, 2)

        client_order_id = f"EXIT_{sym}_{timestamp.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
        order = Order(
            client_order_id=client_order_id,
            symbol=sym,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            product_type=ProductType.MIS,
            time_in_force=TimeInForce.IOC,
            price=fill_price,
            status=OrderStatus.CREATED,
            strategy_name="VWAP_ORB",
        )
        self.portfolio_manager.register_order(order)
        OrderStateMachine.transition(order, OrderStatus.SUBMITTED)
        self.portfolio_manager.transition_order(order.client_order_id, OrderStatus.SUBMITTED)
        OrderStateMachine.transition(order, OrderStatus.ACKNOWLEDGED)
        self.portfolio_manager.transition_order(order.client_order_id, OrderStatus.ACKNOWLEDGED)

        fill = self._create_and_apply_fill(
            order=order,
            fill_price=fill_price,
            quantity=quantity,
            timestamp=timestamp,
            slippage=round(slip * quantity, 2),
        )
        self._all_orders[order.client_order_id] = order
        return fill

    def process_bar(self, candle: Candle) -> List[Fill]:
        """
        Processes price action of incoming bar:
        1. Checks active Stop Losses (SL-M) intra-bar touches
        2. Checks pending LIMIT entry orders touches
        3. Updates order timeout and cancels expired orders
        """
        fills: List[Fill] = []
        sym = candle.symbol.upper().strip()

        # Step 1: Check active Stop Loss for this symbol
        stop_fill = self._check_stop_loss(candle)
        if stop_fill is not None:
            fills.append(stop_fill)

        # Step 2: Check pending Limit Orders for this symbol
        limit_fills = self._check_pending_limits(candle)
        fills.extend(limit_fills)

        return fills

    def _check_stop_loss(self, candle: Candle) -> Optional[Fill]:
        """Evaluates intra-bar stop loss triggers."""
        sym = candle.symbol.upper().strip()
        if sym not in self._active_stops:
            return None

        stop_loss = self._active_stops[sym]
        slip = self._calc_slippage(stop_loss.stop_price)

        triggered = False
        fill_price: float = stop_loss.stop_price

        if stop_loss.side == OrderSide.SELL:
            # Long position stop (SELL order triggered if low drops to/below stop price)
            if candle.low <= stop_loss.stop_price:
                triggered = True
                # If market gapped down below stop price, fill at candle.open minus slippage
                base_price = min(candle.open, stop_loss.stop_price)
                fill_price = round(max(0.05, base_price - slip), 2)
        elif stop_loss.side == OrderSide.BUY:
            # Short position stop (BUY order triggered if high rises to/above stop price)
            if candle.high >= stop_loss.stop_price:
                triggered = True
                # If market gapped up above stop price, fill at candle.open plus slippage
                base_price = max(candle.open, stop_loss.stop_price)
                fill_price = round(base_price + slip, 2)

        if triggered:
            # Remove active stop
            self.remove_stop_loss(sym)

            client_order_id = f"SL_{sym}_{candle.timestamp.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
            order = Order(
                client_order_id=client_order_id,
                symbol=sym,
                side=stop_loss.side,
                order_type=OrderType.SL_MARKET,
                quantity=stop_loss.quantity,
                product_type=ProductType.MIS,
                time_in_force=TimeInForce.DAY,
                price=fill_price,
                trigger_price=stop_loss.stop_price,
                status=OrderStatus.CREATED,
                strategy_name="VWAP_ORB",
            )
            self.portfolio_manager.register_order(order)
            OrderStateMachine.transition(order, OrderStatus.SUBMITTED)
            self.portfolio_manager.transition_order(order.client_order_id, OrderStatus.SUBMITTED)
            OrderStateMachine.transition(order, OrderStatus.ACKNOWLEDGED)
            self.portfolio_manager.transition_order(order.client_order_id, OrderStatus.ACKNOWLEDGED)

            fill = self._create_and_apply_fill(
                order=order,
                fill_price=fill_price,
                quantity=stop_loss.quantity,
                timestamp=candle.timestamp,
                slippage=round(slip * stop_loss.quantity, 2),
            )
            self._all_orders[order.client_order_id] = order
            return fill

        return None

    def _check_pending_limits(self, candle: Candle) -> List[Fill]:
        """Evaluates price touches on pending limit orders."""
        sym = candle.symbol.upper().strip()
        fills: List[Fill] = []
        filled_order_ids: List[str] = []
        expired_order_ids: List[str] = []

        for client_id, pending in list(self._pending_limits.items()):
            order = pending.order
            if order.symbol != sym:
                continue

            limit_price = order.price
            if limit_price is None:
                continue

            filled = False
            fill_price: float = limit_price

            if order.side == OrderSide.BUY:
                # Limit BUY: market must trade at or below limit_price
                if candle.low <= limit_price:
                    filled = True
                    # If open was already below limit, price improvement
                    fill_price = round(min(candle.open, limit_price), 2)
            elif order.side == OrderSide.SELL:
                # Limit SELL: market must trade at or above limit_price
                if candle.high >= limit_price:
                    filled = True
                    # If open was already above limit, price improvement
                    fill_price = round(max(candle.open, limit_price), 2)

            if filled:
                filled_order_ids.append(client_id)
                fill = self._create_and_apply_fill(
                    order=order,
                    fill_price=fill_price,
                    quantity=order.quantity,
                    timestamp=candle.timestamp,
                    slippage=0.0,  # Limit orders experience zero adverse slippage
                )
                fills.append(fill)
            else:
                # Increment bar counter
                pending.bars_active += 1
                if pending.bars_active >= pending.timeout_bars:
                    expired_order_ids.append(client_id)

        # Cleanup filled
        for cid in filled_order_ids:
            self._pending_limits.pop(cid, None)

        # Cleanup expired (timeout)
        for cid in expired_order_ids:
            pending = self._pending_limits.pop(cid, None)
            if pending:
                OrderStateMachine.transition(pending.order, OrderStatus.CANCELLED, reason="ORDER_TIMEOUT")
                self.portfolio_manager.transition_order(
                    client_order_id=cid,
                    to_status=OrderStatus.CANCELLED,
                    reason="ORDER_TIMEOUT",
                )

        return fills

    def _create_and_apply_fill(
        self,
        order: Order,
        fill_price: float,
        quantity: int,
        timestamp: datetime,
        slippage: float,
    ) -> Fill:
        """Constructs Fill domain model and feeds it to PortfolioManager."""
        tx_costs = PnLCalculator.calculate_transaction_costs(
            price=fill_price,
            quantity=quantity,
            side=order.side,
        )

        fill_id = f"FILL_{uuid.uuid4().hex[:10].upper()}"
        fill = Fill(
            fill_id=fill_id,
            order_id=order.client_order_id,
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=quantity,
            price=fill_price,
            timestamp=timestamp,
            brokerage=tx_costs * 0.15,  # Separated brokerage estimate
            stt_and_taxes=tx_costs * 0.85,  # Statutory STT, GST, Stamp Duty
            exchange="NSE",
        )

        # Transition order to FILLED
        OrderStateMachine.transition(order, OrderStatus.FILLED)
        self.portfolio_manager.transition_order(
            client_order_id=order.client_order_id,
            to_status=OrderStatus.FILLED,
            timestamp=timestamp,
        )

        # Apply to portfolio ledger
        self.portfolio_manager.process_fill(fill)
        return fill

    def cancel_all_pending(self, reason: str = "SESSION_END") -> List[Order]:
        """Cancels all active pending limit orders."""
        cancelled = []
        for cid, pending in list(self._pending_limits.items()):
            OrderStateMachine.transition(pending.order, OrderStatus.CANCELLED, reason=reason)
            self.portfolio_manager.transition_order(
                client_order_id=cid,
                to_status=OrderStatus.CANCELLED,
                reason=reason,
            )
            cancelled.append(pending.order)
        self._pending_limits.clear()
        return cancelled
