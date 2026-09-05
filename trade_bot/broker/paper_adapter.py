"""
Paper Trading Broker Execution Adapter.

Provides realistic simulated broker execution without submitting real orders:
- Unified IBrokerAdapter interface compatible with backtest and live execution.
- Strict lifecycle distinction: ORDER_REQUEST vs ORDER_ACCEPTANCE vs ORDER_FILL vs POSITION.
- Simulated deterministic order IDs.
- Idempotent order processing.
- Configurable adverse execution slippage and simulated latency.
- Realistic order book for resting limit and stop orders triggered on incoming ticks.
- Partial fills and order cancellation.
- In-memory position accounting updated strictly upon verified execution fills.
- Comprehensive structured execution audit logging.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional
import uuid

from trade_bot.broker.interfaces import IBrokerAdapter
from trade_bot.broker.paper_models import ExecutionLogEntry, ExecutionStage, PaperBrokerConfig
from trade_bot.config.constants import IST_TIMEZONE
from trade_bot.config.settings import BrokerConfig
from trade_bot.domain.enums import OrderSide, OrderStatus, OrderType, ProductType, TimeInForce
from trade_bot.domain.exceptions import BrokerAdapterError
from trade_bot.domain.models import (
    AccountBalance,
    Order,
    OrderModification,
    OrderRequest,
    Position,
    Tick,
    Trade,
    utc_now,
)

logger = logging.getLogger(__name__)


class PaperBrokerAdapter(IBrokerAdapter):
    """
    Realistic in-memory broker execution simulator for paper trading.
    """

    def __init__(
        self,
        config: Optional[BrokerConfig] = None,
        paper_config: Optional[PaperBrokerConfig] = None,
    ) -> None:
        self.config = config or BrokerConfig()
        self.paper_config = paper_config or PaperBrokerConfig()

        self._connected: bool = True
        self._order_sequence: int = 0
        self._trade_sequence: int = 0

        # State collections
        self._orders_by_broker_id: Dict[str, Order] = {}
        self._orders_by_client_id: Dict[str, Order] = {}
        self._open_orders: Dict[str, Order] = {}
        self._positions: Dict[str, Position] = {}
        self._last_market_prices: Dict[str, float] = {}
        self._execution_logs: List[ExecutionLogEntry] = []

        # Account balance tracking
        self._cash: float = self.paper_config.initial_capital
        self._realized_pnl: float = 0.0

        # Event callbacks
        self._trade_callbacks: List[Callable[[Trade], None]] = []
        self._order_callbacks: List[Callable[[Order], None]] = []
        self._log_callbacks: List[Callable[[ExecutionLogEntry], None]] = []

    # -------------------------------------------------------------------------
    # IBrokerAdapter Protocol Properties & Methods
    # -------------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "PaperBrokerAdapter"

    def connect(self) -> None:
        """Establish connection to paper broker simulation."""
        self._connected = True

    def disconnect(self) -> None:
        """Terminate connection to paper broker simulation."""
        self._connected = False

    def is_connected(self) -> bool:
        """Return True if simulated connection is active."""
        return self._connected

    def get_account_balance(self) -> AccountBalance:
        """Return current paper account capital, cash, and margin."""
        unrealized = sum(p.unrealized_pnl for p in self._positions.values() if not p.is_flat)
        used_margin = sum(p.market_value for p in self._positions.values() if not p.is_flat)
        return AccountBalance(
            initial_capital=self.paper_config.initial_capital,
            available_cash=round(self._cash, 2),
            used_margin=round(used_margin, 2),
            total_realized_pnl=round(self._realized_pnl, 2),
            total_unrealized_pnl=round(unrealized, 2),
            currency="INR",
            timestamp=datetime.now(IST_TIMEZONE),
        )

    def get_positions(self) -> List[Position]:
        """Return list of current positions."""
        return [p for p in self._positions.values() if not p.is_flat]

    def get_all_positions(self) -> List[Position]:
        """Return all tracked positions including flat positions."""
        return list(self._positions.values())

    def get_orders(self) -> List[Order]:
        """Return all orders placed in this session."""
        return list(self._orders_by_broker_id.values())

    def register_trade_callback(self, callback: Callable[[Trade], None]) -> None:
        """Register listener for trade fill executions."""
        self._trade_callbacks.append(callback)

    def register_order_callback(self, callback: Callable[[Order], None]) -> None:
        """Register listener for order lifecycle updates."""
        self._order_callbacks.append(callback)

    def register_log_callback(self, callback: Callable[[ExecutionLogEntry], None]) -> None:
        """Register listener for execution audit log entries."""
        self._log_callbacks.append(callback)

    def get_execution_logs(self) -> List[ExecutionLogEntry]:
        """Return full structured execution audit trail."""
        return list(self._execution_logs)

    # -------------------------------------------------------------------------
    # Market Data Feeds & Reference Prices
    # -------------------------------------------------------------------------

    def set_market_price(self, symbol: str, price: float) -> None:
        """Update reference price and evaluate resting orders."""
        if price <= 0:
            return
        self._last_market_prices[symbol] = price
        # Update unrealized PnL on existing positions
        if symbol in self._positions:
            self._positions[symbol].update_market_price(price)
        # Evaluate resting limit/stop orders
        self._evaluate_resting_orders(symbol, price)

    def on_tick(self, tick: Tick) -> None:
        """Process incoming market tick."""
        self.set_market_price(tick.symbol, tick.last_price)

    # -------------------------------------------------------------------------
    # Order Submission & Execution Lifecycle
    # -------------------------------------------------------------------------

    def place_order(self, request: OrderRequest) -> str:
        """
        Submit order to paper broker.
        Enforces:
        1. ORDER_REQUEST logging
        2. Idempotency check (returns existing broker_order_id if duplicate client_order_id)
        3. Connection and parameter validation (raises BrokerAdapterError if invalid)
        4. ORDER_ACCEPTANCE logging with deterministic broker order ID
        5. Routing to matching engine (immediate fill for MARKET, or resting queue for LIMIT/SL)
        """
        now = datetime.now(IST_TIMEZONE)

        # 1. ORDER_REQUEST stage
        self._log_stage(
            stage=ExecutionStage.ORDER_REQUEST,
            client_order_id=request.client_order_id,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            price=request.price,
            message=f"Received order request {request.client_order_id} for {request.quantity}x {request.symbol}",
        )

        # 2. Idempotency Guard
        if request.client_order_id in self._orders_by_client_id:
            existing = self._orders_by_client_id[request.client_order_id]
            logger.warning("Duplicate order request ignored: client_order_id=%s", request.client_order_id)
            self._log_stage(
                stage=ExecutionStage.ORDER_REQUEST,
                client_order_id=request.client_order_id,
                broker_order_id=existing.broker_order_id,
                symbol=request.symbol,
                message=f"Duplicate order request rejected by idempotency guard; returning existing {existing.broker_order_id}",
            )
            return existing.broker_order_id or ""

        # 3. Connection & Parameter Validation
        if not self._connected:
            self._log_stage(
                stage=ExecutionStage.ORDER_REJECTION,
                client_order_id=request.client_order_id,
                symbol=request.symbol,
                message="Order rejected: broker connection is disconnected",
            )
            raise BrokerAdapterError("PaperBrokerAdapter is disconnected.")

        if request.quantity <= 0:
            self._log_stage(
                stage=ExecutionStage.ORDER_REJECTION,
                client_order_id=request.client_order_id,
                symbol=request.symbol,
                message=f"Order rejected: quantity must be positive, got {request.quantity}",
            )
            raise BrokerAdapterError(f"Invalid quantity: {request.quantity}")

        if request.order_type in (OrderType.LIMIT, OrderType.SL_LIMIT) and (request.price is None or request.price <= 0):
            self._log_stage(
                stage=ExecutionStage.ORDER_REJECTION,
                client_order_id=request.client_order_id,
                symbol=request.symbol,
                message=f"Order rejected: price must be positive for {request.order_type}",
            )
            raise BrokerAdapterError(f"Price required for {request.order_type}")

        # 4. ORDER_ACCEPTANCE stage
        self._order_sequence += 1
        broker_order_id = f"BK_PAPER_{self._order_sequence:08d}"

        acceptance_time = now + timedelta(milliseconds=self.paper_config.simulated_latency_ms)

        order = Order(
            client_order_id=request.client_order_id,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            price=request.price,
            trigger_price=request.trigger_price,
            product_type=request.product_type,
            time_in_force=request.time_in_force,
            broker_order_id=broker_order_id,
            status=OrderStatus.SUBMITTED,
            created_at=acceptance_time,
            updated_at=acceptance_time,
            strategy_name=request.strategy_name,
            signal_id=request.signal_id,
        )

        self._orders_by_broker_id[broker_order_id] = order
        self._orders_by_client_id[request.client_order_id] = order

        self._log_stage(
            stage=ExecutionStage.ORDER_ACCEPTANCE,
            client_order_id=request.client_order_id,
            broker_order_id=broker_order_id,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            price=request.price,
            status=order.status,
            message=f"Order accepted and assigned broker_order_id={broker_order_id}",
        )
        self._notify_order_callbacks(order)

        # 5. Routing to Execution Engine
        if request.order_type == OrderType.MARKET:
            self._execute_market_order(order)
        elif request.order_type in (OrderType.LIMIT, OrderType.SL_LIMIT, OrderType.SL_MARKET):
            order.status = OrderStatus.ACKNOWLEDGED
            self._open_orders[broker_order_id] = order
            self._log_stage(
                stage=ExecutionStage.ORDER_WORKING,
                client_order_id=order.client_order_id,
                broker_order_id=broker_order_id,
                symbol=order.symbol,
                status=order.status,
                message=f"Order {broker_order_id} placed in working order book",
            )
            self._notify_order_callbacks(order)
            # Evaluate against reference market price if available, or request price if unquoted
            current_price = self._last_market_prices.get(order.symbol, order.price)
            if current_price:
                self._evaluate_single_order(order, current_price)

        return broker_order_id

    def modify_order(self, modification: OrderModification) -> bool:
        """Modify price or quantity of a resting order."""
        broker_order_id = modification.order_id
        if broker_order_id not in self._open_orders:
            logger.warning("Cannot modify non-working order: %s", broker_order_id)
            return False

        order = self._open_orders[broker_order_id]
        if modification.price is not None and modification.price > 0:
            order.price = modification.price
        if modification.quantity is not None and modification.quantity > 0:
            order.quantity = modification.quantity
        if modification.trigger_price is not None:
            order.trigger_price = modification.trigger_price

        order.updated_at = datetime.now(IST_TIMEZONE)
        self._log_stage(
            stage=ExecutionStage.ORDER_WORKING,
            client_order_id=order.client_order_id,
            broker_order_id=broker_order_id,
            symbol=order.symbol,
            price=order.price,
            quantity=order.quantity,
            message=f"Order {broker_order_id} modified",
        )
        self._notify_order_callbacks(order)
        return True

    def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel an open/resting order."""
        if broker_order_id not in self._open_orders:
            logger.warning("Cancel rejected: order %s is not in active order book", broker_order_id)
            return False

        order = self._open_orders.pop(broker_order_id)
        order.status = OrderStatus.CANCELLED
        order.updated_at = datetime.now(IST_TIMEZONE)

        self._log_stage(
            stage=ExecutionStage.ORDER_CANCELLED,
            client_order_id=order.client_order_id,
            broker_order_id=broker_order_id,
            symbol=order.symbol,
            status=order.status,
            message=f"Order {broker_order_id} cancelled by client request",
        )
        self._notify_order_callbacks(order)
        return True

    # -------------------------------------------------------------------------
    # Internal Execution Engine & Position Updates
    # -------------------------------------------------------------------------

    def _calculate_taxes(self, turnover: float) -> tuple[float, float]:
        """Calculate statutory charges and brokerage for equity intraday."""
        p = self.paper_config
        brokerage = p.brokerage_per_order
        stt = turnover * p.stt_pct
        txn = turnover * p.txn_charges_pct
        gst = (brokerage + txn) * p.gst_pct
        sebi = turnover * p.sebi_charges_pct
        stamp = turnover * p.stamp_duty_pct
        taxes = round(stt + txn + gst + sebi + stamp, 2)
        return round(brokerage, 2), taxes

    def _execute_market_order(self, order: Order) -> None:
        """Execute a market order with configurable adverse slippage and partial fill support."""
        base_price = self._last_market_prices.get(order.symbol, order.price or 100.0)
        slippage_pct = self.paper_config.default_slippage_pct

        # Apply adverse slippage
        if order.side == OrderSide.BUY:
            fill_price = round(base_price * (1.0 + slippage_pct), 2)
        else:
            fill_price = round(base_price * (1.0 - slippage_pct), 2)

        # Handle partial fills if enabled
        if self.paper_config.enable_partial_fills and order.quantity > 1:
            first_qty = max(1, int(order.quantity * self.paper_config.partial_fill_ratio))
            if first_qty < order.quantity:
                # Stage 1: Partial Fill
                self._apply_fill(order, first_qty, fill_price, is_final=False)
                # Stage 2: Final Fill of remaining quantity
                remaining_qty = order.quantity - first_qty
                self._apply_fill(order, remaining_qty, fill_price, is_final=True)
                return

        # Single Full Fill
        self._apply_fill(order, order.quantity, fill_price, is_final=True)

    def _evaluate_resting_orders(self, symbol: str, current_price: float) -> None:
        """Check all resting orders for symbol against new market price."""
        matching_orders = [o for o in list(self._open_orders.values()) if o.symbol == symbol]
        for order in matching_orders:
            self._evaluate_single_order(order, current_price)

    def _evaluate_single_order(self, order: Order, current_price: float) -> None:
        """Evaluate a single open order against current market price."""
        if order.broker_order_id not in self._open_orders:
            return

        fill_price: Optional[float] = None

        if order.order_type == OrderType.LIMIT and order.price is not None:
            # BUY LIMIT: fills when price <= limit
            if order.side == OrderSide.BUY and current_price <= order.price:
                fill_price = min(current_price, order.price)
            # SELL LIMIT: fills when price >= limit
            elif order.side == OrderSide.SELL and current_price >= order.price:
                fill_price = max(current_price, order.price)

        elif order.order_type in (OrderType.SL_MARKET, OrderType.STOP_LOSS) and order.trigger_price is not None:
            # BUY SL-M: fills when price >= trigger
            if order.side == OrderSide.BUY and current_price >= order.trigger_price:
                fill_price = round(current_price * (1.0 + self.paper_config.default_slippage_pct), 2)
            # SELL SL-M: fills when price <= trigger
            elif order.side == OrderSide.SELL and current_price <= order.trigger_price:
                fill_price = round(current_price * (1.0 - self.paper_config.default_slippage_pct), 2)

        if fill_price is not None:
            self._open_orders.pop(order.broker_order_id, None)
            self._apply_fill(order, order.quantity, fill_price, is_final=True)

    def _apply_fill(self, order: Order, fill_qty: int, fill_price: float, is_final: bool) -> None:
        """
        Record a fill, create Trade event, update Position strictly upon fill,
        and log ORDER_FILL and POSITION_UPDATE.
        """
        now = datetime.now(IST_TIMEZONE)
        self._trade_sequence += 1
        trade_id = f"TRD_PAPER_{self._trade_sequence:08d}"

        turnover = fill_price * fill_qty
        brokerage, taxes = self._calculate_taxes(turnover)

        trade = Trade(
            trade_id=trade_id,
            order_id=order.broker_order_id or "",
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=fill_qty,
            price=fill_price,
            timestamp=now,
            brokerage=brokerage,
            stt_and_taxes=taxes,
        )

        # Update Order model
        order.filled_quantity += fill_qty
        # Update average fill price
        total_value = sum(t.price * t.quantity for t in order.fills) + (fill_price * fill_qty)
        order.average_fill_price = round(total_value / order.filled_quantity, 2)
        order.fills.append(trade)
        order.status = OrderStatus.FILLED if is_final else OrderStatus.PARTIALLY_FILLED
        order.updated_at = now

        # Log FILL stage
        fill_stage = ExecutionStage.ORDER_FILL if is_final else ExecutionStage.ORDER_PARTIAL_FILL
        self._log_stage(
            stage=fill_stage,
            client_order_id=order.client_order_id,
            broker_order_id=order.broker_order_id,
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            quantity=order.quantity,
            filled_quantity=order.filled_quantity,
            fill_price=fill_price,
            status=order.status,
            message=f"Filled {fill_qty} @ ₹{fill_price:.2f} (Trade ID: {trade_id})",
            details={"trade_id": trade_id, "brokerage": brokerage, "taxes": taxes},
        )
        self._notify_order_callbacks(order)

        # Apply strictly to POSITION
        self._update_position_from_trade(trade)

        # Notify trade callbacks
        for callback in self._trade_callbacks:
            try:
                callback(trade)
            except Exception as e:
                logger.error("Error in trade fill callback: %s", e)

    def _update_position_from_trade(self, trade: Trade) -> None:
        """
        Update Position strictly upon verified Trade execution fill.
        Correctly calculates average price, position quantity, and realized P&L.
        """
        sym = trade.symbol
        if sym not in self._positions:
            self._positions[sym] = Position(
                symbol=sym,
                product_type=ProductType.MIS,
                quantity=0,
                average_price=0.0,
                realized_pnl=0.0,
                unrealized_pnl=0.0,
                last_price=trade.price,
                updated_at=trade.timestamp,
            )

        pos = self._positions[sym]
        prev_qty = pos.quantity
        prev_avg = pos.average_price
        fill_qty = trade.quantity if trade.side == OrderSide.BUY else -trade.quantity
        fill_price = trade.price

        # Realized PnL calculation
        realized_trade_pnl = 0.0

        if prev_qty == 0:
            # Opening new position
            pos.quantity = fill_qty
            pos.average_price = fill_price
        elif (prev_qty > 0 and fill_qty > 0) or (prev_qty < 0 and fill_qty < 0):
            # Increasing existing position in same direction
            new_qty = prev_qty + fill_qty
            total_cost = (prev_qty * prev_avg) + (fill_qty * fill_price)
            pos.average_price = round(total_cost / new_qty, 2)
            pos.quantity = new_qty
        else:
            # Closing or reversing position
            closed_qty = min(abs(prev_qty), abs(fill_qty))
            if prev_qty > 0:  # Closing long
                realized_trade_pnl = (fill_price - prev_avg) * closed_qty
            else:  # Closing short
                realized_trade_pnl = (prev_avg - fill_price) * closed_qty

            new_qty = prev_qty + fill_qty
            pos.quantity = new_qty
            if new_qty == 0:
                pos.average_price = 0.0
            elif (prev_qty > 0 and new_qty < 0) or (prev_qty < 0 and new_qty > 0):
                # Position flipped
                pos.average_price = fill_price

        # Deduct transaction costs from realized pnl
        net_trade_pnl = realized_trade_pnl - trade.brokerage - trade.stt_and_taxes
        pos.realized_pnl = round(pos.realized_pnl + net_trade_pnl, 2)
        self._realized_pnl = round(self._realized_pnl + net_trade_pnl, 2)
        self._cash = round(self._cash + net_trade_pnl, 2)

        pos.update_market_price(fill_price)

        # Log POSITION_UPDATE stage
        self._log_stage(
            stage=ExecutionStage.POSITION_UPDATE,
            client_order_id=trade.client_order_id or "",
            broker_order_id=trade.order_id,
            symbol=sym,
            quantity=pos.quantity,
            price=pos.average_price,
            message=f"Position updated for {sym}: net_qty={pos.quantity}, avg_price=₹{pos.average_price:.2f}, realized_pnl=₹{pos.realized_pnl:.2f}",
            details={"realized_pnl": pos.realized_pnl, "unrealized_pnl": pos.unrealized_pnl},
        )

    def _log_stage(
        self,
        stage: ExecutionStage,
        client_order_id: str,
        broker_order_id: Optional[str] = None,
        symbol: Optional[str] = None,
        side: Optional[OrderSide] = None,
        order_type: Optional[OrderType] = None,
        quantity: int = 0,
        filled_quantity: int = 0,
        price: Optional[float] = None,
        fill_price: Optional[float] = None,
        status: Optional[OrderStatus] = None,
        message: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> ExecutionLogEntry:
        """Record structured execution log entry and notify listeners."""
        entry = ExecutionLogEntry(
            timestamp=datetime.now(IST_TIMEZONE),
            stage=stage,
            client_order_id=client_order_id,
            broker_order_id=broker_order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            filled_quantity=filled_quantity,
            price=price,
            fill_price=fill_price,
            status=status,
            message=message,
            details=details or {},
        )
        self._execution_logs.append(entry)
        for callback in self._log_callbacks:
            try:
                callback(entry)
            except Exception as e:
                logger.error("Error in log callback: %s", e)
        return entry

    def _notify_order_callbacks(self, order: Order) -> None:
        for callback in self._order_callbacks:
            try:
                callback(order)
            except Exception as e:
                logger.error("Error in order callback: %s", e)
