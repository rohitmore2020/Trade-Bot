"""
Realistic Execution Simulator.

Pure execution component implementing IBrokerAdapter contract for backtesting.
Decoupled completely from Strategy rules and Portfolio accounting:
- Does not contain strategy rules
- Does not contain portfolio accounting
- Ingests OrderRequests and Candles; emits confirmed Trade fills and execution events
- Conservative, documented intrabar OHLCV collision handling
- Configurable slippage and transaction cost models

ORDER EXECUTION SEMANTICS & INTRABAR AMBIGUITY RULES:
1. Limit Order Touches Price:
   - For LIMIT BUY: Triggered when candle Low <= limit_price. If candle Low touches
     the limit price exactly (Low == limit_price), the order is filled at limit_price,
     subject to volume participation constraints.
   - For LIMIT SELL: Triggered when candle High >= limit_price. If High touches
     the limit price exactly (High == limit_price), filled at limit_price.
2. Limit Order Crosses Price (Price Improvement / Gap):
   - For LIMIT BUY: If candle Open < limit_price (market opened favorably or gapped down
     through the limit), price improvement is granted and fill executes at candle Open.
   - For LIMIT SELL: If candle Open > limit_price (market opened favorably or gapped up
     through the limit), price improvement is granted and fill executes at candle Open.
3. Stop Loss (SL-M) Trigger:
   - For Long Stop (OrderSide.SELL): Triggered when candle Low <= stop_price.
     Executes at min(Open, stop_price) minus adverse slippage. If the bar opens below
     the stop price (gap-down), it executes at Open - slippage (capturing gap risk).
   - For Short Stop (OrderSide.BUY): Triggered when candle High >= stop_price.
     Executes at max(Open, stop_price) plus adverse slippage. If the bar opens above
     the stop price (gap-up), it executes at Open + slippage.
4. Intrabar Collision Resolution (Stop Loss vs Limit / Target in same candle):
   - When only OHLCV data is available and both a stop loss trigger and a limit target
     fall within [Low, High], conservative execution evaluates STOP LOSS FIRST (Stage 1)
     before any limit orders (Stage 2).
   - This eliminates hindsight bias and guarantees worst-case risk evaluation.
5. Multiple Active Orders:
   - Orders are queued independently in `_pending_limits` and `_active_stops`.
   - Each order is processed deterministically according to its symbol, price, and side.
6. Order Expiry / Timeout:
   - Pending limit orders track `bars_active`. If not touched within `timeout_bars`
     (default 1 bar), the order transitions to CANCELLED with reason "ORDER_TIMEOUT".
7. Position Force-Closed / Market Exits:
   - Via `execute_market_exit`, any open protective stops for the symbol are immediately
     cancelled (`remove_stop_loss`), and an immediate MARKET fill is generated at the current
     market price plus adverse slippage and statutory costs, stamped with the bar's timestamp.
8. Partial Fills:
   - When `partial_fills_enabled=True`, max fill per bar is capped at
     `volume * volume_participation_limit` (default 10%). Unfilled portions remain active
     as PARTIALLY_FILLED until fully filled or expired.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
import uuid

from trade_bot.broker.interfaces import IBrokerAdapter
from trade_bot.domain.enums import OrderSide, OrderStatus, OrderType, ProductType, TimeInForce
from trade_bot.domain.models import (
    AccountBalance,
    Candle,
    Order,
    OrderModification,
    OrderRequest,
    Position,
    Trade,
    utc_now,
)
from trade_bot.domain.state import OrderStateMachine
from trade_bot.execution.cost_calculator import TransactionCostCalculator
from trade_bot.execution.models import (
    ExecutionSimulatorConfig,
    SimulatorPendingOrder,
    SlippageModelConfig,
    SlippageModelType,
)


class ExecutionSimulator(IBrokerAdapter):
    """
    Realistic execution simulator implementing IBrokerAdapter.
    Models exchange fills with non-idealized limits, intra-bar SL-M, partial fills,
    adverse slippage, and configurable statutory transaction charges.
    """

    def __init__(
        self,
        config: Optional[ExecutionSimulatorConfig] = None,
        portfolio_manager: Optional[Any] = None,
        slippage_per_share: Optional[float] = None,
        slippage_pct: Optional[float] = None,
        default_limit_timeout_bars: Optional[int] = None,
    ) -> None:
        if config is None:
            slip_cfg = SlippageModelConfig(
                fixed_tick_size=float(slippage_per_share) if slippage_per_share is not None else 0.05,
                percentage=float(slippage_pct) if slippage_pct is not None else 0.0002,
            )
            self.config = ExecutionSimulatorConfig(
                slippage=slip_cfg,
                default_timeout_bars=default_limit_timeout_bars if default_limit_timeout_bars is not None else 1,
            )
        else:
            self.config = config

        self.cost_calculator = TransactionCostCalculator(config=self.config.costs)

        self._connected: bool = True
        self._trade_callbacks: List[Callable[[Trade], None]] = []

        if portfolio_manager is not None and hasattr(portfolio_manager, "process_fill"):
            self.register_trade_callback(portfolio_manager.process_fill)

        # Order tracking books
        self._orders_by_broker_id: Dict[str, Order] = {}
        self._orders_by_client_id: Dict[str, Order] = {}
        # Active pending limit orders: broker_order_id -> SimulatorPendingOrder
        self._pending_limits: Dict[str, SimulatorPendingOrder] = {}
        # Active stop loss orders: broker_order_id -> SimulatorPendingOrder
        self._active_stops: Dict[str, SimulatorPendingOrder] = {}
        # Reference market prices for instant market order estimation
        self._last_market_prices: Dict[str, float] = {}
        # Completed fills history
        self._executed_trades: List[Trade] = []

    @property
    def executed_trades(self) -> List[Trade]:
        return list(self._executed_trades)

    @property
    def name(self) -> str:
        return "ExecutionSimulator"

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def register_trade_callback(self, callback: Callable[[Trade], None]) -> None:
        """Register listener for execution fill events."""
        self._trade_callbacks.append(callback)

    def set_market_price(self, symbol: str, price: float) -> None:
        """Update last seen market price for symbol."""
        self._last_market_prices[symbol.upper().strip()] = float(price)

    def get_account_balance(self) -> AccountBalance:
        """Dummy balance satisfying IBrokerAdapter contract."""
        return AccountBalance(
            initial_capital=100_000.0,
            available_cash=100_000.0,
            used_margin=0.0,
            timestamp=utc_now(),
        )

    def get_positions(self) -> List[Position]:
        """Positions are owned by PortfolioManager, not the simulator."""
        return []

    def get_orders(self) -> List[Order]:
        """Return all tracked orders."""
        return list(self._orders_by_broker_id.values())

    def get_all_orders(self) -> List[Order]:
        """Alias for get_orders for backwards compatibility."""
        return self.get_orders()

    def get_order(self, client_order_id: str) -> Optional[Order]:
        return self._orders_by_client_id.get(client_order_id)

    @property
    def pending_orders_count(self) -> int:
        return len(self._pending_limits)

    @property
    def active_stops_count(self) -> int:
        return len(self._active_stops)

    def _calculate_slippage(self, price: float, side: OrderSide, candle: Optional[Candle] = None) -> float:
        """
        Calculates per-share slippage amount based on configurable model.
        Slippage is strictly adverse (added for BUY, subtracted for SELL).
        """
        slip_cfg = self.config.slippage
        if slip_cfg.model_type == SlippageModelType.FIXED_TICK:
            return slip_cfg.fixed_tick_size
        elif slip_cfg.model_type == SlippageModelType.PERCENTAGE:
            return round(price * slip_cfg.percentage, 4)
        elif slip_cfg.model_type == SlippageModelType.VOLATILITY_ADAPTIVE:
            ref_range = candle.range if candle else (price * 0.01)
            return round(ref_range * slip_cfg.volatility_mult, 4)
        elif slip_cfg.model_type == SlippageModelType.VOLUME_IMPACT:
            return round(max(slip_cfg.fixed_tick_size, price * slip_cfg.percentage), 4)
        return slip_cfg.fixed_tick_size

    def place_order(self, request: OrderRequest) -> str:
        """
        Submits an order into the simulator.
        - MARKET orders execute immediately against the latest market price (with slippage).
        - LIMIT orders are queued in pending book for subsequent bar evaluation.
        - SL_MARKET / SL_LIMIT orders are queued in active stop book.
        """
        broker_order_id = f"BK_{uuid.uuid4().hex[:10]}"
        sym = request.symbol.upper().strip()

        order = Order(
            client_order_id=request.client_order_id,
            symbol=sym,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            product_type=request.product_type or ProductType.MIS,
            time_in_force=request.time_in_force or TimeInForce.DAY,
            price=request.price,
            trigger_price=request.trigger_price,
            broker_order_id=broker_order_id,
            status=OrderStatus.CREATED,
            strategy_name=request.strategy_name or "SIMULATED",
            signal_id=request.signal_id,
        )
        self._orders_by_broker_id[broker_order_id] = order
        self._orders_by_client_id[order.client_order_id] = order

        OrderStateMachine.transition(order, OrderStatus.SUBMITTED)
        OrderStateMachine.transition(order, OrderStatus.ACKNOWLEDGED)

        # 1. MARKET ORDER: Execute immediately
        if request.order_type in (OrderType.MARKET, "MARKET"):
            ref_price = self._last_market_prices.get(sym, request.price or 100.0)
            slip = self._calculate_slippage(ref_price, request.side)
            fill_price = round(ref_price + slip if request.side == OrderSide.BUY else max(0.05, ref_price - slip), 2)
            self._execute_fill(order, fill_price, request.quantity, utc_now())
            return broker_order_id

        # 2. STOP-LOSS ORDER (SL_MARKET or SL_LIMIT)
        if request.order_type in (OrderType.SL_MARKET, OrderType.SL_LIMIT, "SL_MARKET", "SL_LIMIT", "STOP_LOSS"):
            self._active_stops[broker_order_id] = SimulatorPendingOrder(
                order=order,
                placed_at=utc_now(),
                stop_price=request.trigger_price or request.price,
                timeout_bars=9999,  # Stops remain active until filled or explicitly cancelled
            )
            return broker_order_id

        # 3. LIMIT ORDER: Queue for price touch on subsequent bars
        if request.order_type in (OrderType.LIMIT, "LIMIT") or order.price is not None:
            self._pending_limits[broker_order_id] = SimulatorPendingOrder(
                order=order,
                placed_at=utc_now(),
                timeout_bars=self.config.default_timeout_bars,
            )
            return broker_order_id

        return broker_order_id

    def cancel_order(self, broker_order_id: str, reason: Optional[str] = None) -> bool:
        """Cancels an open pending limit or stop loss order."""
        order = self._orders_by_broker_id.get(broker_order_id)
        if not order or not order.is_active:
            # Check by client_order_id
            order = self._orders_by_client_id.get(broker_order_id)
            if not order or not order.is_active:
                return False

        b_id = order.broker_order_id or broker_order_id
        self._pending_limits.pop(b_id, None)
        self._active_stops.pop(b_id, None)

        OrderStateMachine.transition(order, OrderStatus.CANCELLED, reason=reason or "USER_CANCELLED")
        return True

    def modify_order(self, modification: OrderModification) -> bool:
        """Modifies price or quantity of an active pending limit order."""
        order = self._orders_by_client_id.get(modification.client_order_id)
        if not order or not order.is_active:
            return False

        b_id = order.broker_order_id
        pending = self._pending_limits.get(b_id) or self._active_stops.get(b_id)
        if not pending:
            return False

        new_price = getattr(modification, "price", None)
        if new_price is None:
            new_price = getattr(modification, "new_price", None)

        new_trigger = getattr(modification, "trigger_price", None)
        if new_trigger is None:
            new_trigger = getattr(modification, "new_trigger_price", None)

        new_qty = getattr(modification, "quantity", None)
        if new_qty is None:
            new_qty = getattr(modification, "new_quantity", None)

        if new_price is not None:
            order.price = new_price
            if pending.stop_price is not None:
                pending.stop_price = new_price
        if new_trigger is not None:
            order.trigger_price = new_trigger
            pending.stop_price = new_trigger
        if new_qty is not None:
            order.quantity = new_qty
            pending.remaining_quantity = max(0, new_qty - pending.filled_quantity)

        return True

    def cancel_all_pending(self, symbol: Optional[str] = None, reason: str = "MASS_CANCEL") -> List[Order]:
        """Cancels all active pending limit orders (optionally filtered by symbol)."""
        cancelled = []
        for b_id, pending in list(self._pending_limits.items()):
            if symbol is None or pending.order.symbol == symbol.upper().strip():
                self.cancel_order(b_id, reason=reason)
                cancelled.append(pending.order)
        return cancelled

    def update_stop_loss(self, symbol: str, new_stop: float, timestamp: Optional[datetime] = None) -> bool:
        """Ratchets an active trailing stop loss strictly favorably."""
        sym = symbol.upper().strip()
        updated = False
        new_val = round(new_stop, 2)

        for pending in self._active_stops.values():
            if pending.order.symbol == sym:
                # Long position stop (order side is SELL) -> only moves up
                if pending.order.side == OrderSide.SELL:
                    if pending.stop_price is None or new_val > pending.stop_price:
                        pending.stop_price = new_val
                        pending.order.trigger_price = new_val
                        if timestamp:
                            pending.placed_at = timestamp
                        updated = True
                # Short position stop (order side is BUY) -> only moves down
                elif pending.order.side == OrderSide.BUY:
                    if pending.stop_price is None or new_val < pending.stop_price:
                        pending.stop_price = new_val
                        pending.order.trigger_price = new_val
                        if timestamp:
                            pending.placed_at = timestamp
                        updated = True
        return updated

    def process_bar(self, candle: Candle) -> List[Trade]:
        """
        Evaluates incoming OHLCV candle against all active orders.
        Resolves intrabar collisions conservatively without hindsight bias:
        1. Evaluates Stop-Loss (SL-M) orders first (conservative priority).
        2. Evaluates Pending Limit orders with touch/cross and volume participation.
        3. Advances order timeout counters and expires orders.
        Returns list of generated Trade fills.
        """
        sym = candle.symbol.upper().strip()
        self.set_market_price(sym, candle.close)
        generated_trades: List[Trade] = []

        # ----------------------------------------------------------------------
        # STAGE 1: Evaluate Active Stop Loss Orders (SL-M)
        # ----------------------------------------------------------------------
        stop_trades = self._process_stops_for_candle(candle)
        generated_trades.extend(stop_trades)

        # ----------------------------------------------------------------------
        # STAGE 2: Evaluate Pending Limit Orders
        # ----------------------------------------------------------------------
        limit_trades = self._process_limits_for_candle(candle)
        generated_trades.extend(limit_trades)

        return generated_trades

    def _process_stops_for_candle(self, candle: Candle) -> List[Trade]:
        """Evaluates intra-bar SL-M triggers against candle High/Low."""
        sym = candle.symbol.upper().strip()
        trades: List[Trade] = []
        triggered_stops: List[str] = []

        for b_id, pending in list(self._active_stops.items()):
            order = pending.order
            if order.symbol != sym or pending.stop_price is None:
                continue

            stop_price = pending.stop_price
            slip = self._calculate_slippage(stop_price, order.side, candle)
            triggered = False
            fill_price = stop_price

            if order.side == OrderSide.SELL:
                # Long Position Stop: Triggered if candle Low drops to/below stop price
                if candle.low <= stop_price:
                    triggered = True
                    # Gapped open below stop: fill at open minus slippage
                    base = min(candle.open, stop_price)
                    fill_price = round(max(0.05, base - slip), 2)
            elif order.side == OrderSide.BUY:
                # Short Position Stop: Triggered if candle High rises to/above stop price
                if candle.high >= stop_price:
                    triggered = True
                    # Gapped open above stop: fill at open plus slippage
                    base = max(candle.open, stop_price)
                    fill_price = round(base + slip, 2)

            if triggered:
                triggered_stops.append(b_id)
                trade = self._execute_fill(order, fill_price, pending.remaining_quantity, candle.timestamp)
                trades.append(trade)

        for b_id in triggered_stops:
            self._active_stops.pop(b_id, None)

        return trades

    def _process_limits_for_candle(self, candle: Candle) -> List[Trade]:
        """Evaluates limit orders against candle price range and volume participation."""
        sym = candle.symbol.upper().strip()
        trades: List[Trade] = []
        completed_orders: List[str] = []
        expired_orders: List[str] = []

        for b_id, pending in list(self._pending_limits.items()):
            order = pending.order
            if order.symbol != sym or order.price is None:
                continue

            limit_price = order.price
            touched = False
            fill_price = limit_price

            if order.side == OrderSide.BUY:
                # LIMIT BUY: Market must trade at or below limit price
                if candle.low <= limit_price:
                    touched = True
                    # Price improvement: if market opened below limit, fill at open
                    fill_price = round(min(candle.open, limit_price), 2)
            elif order.side == OrderSide.SELL:
                # LIMIT SELL: Market must trade at or above limit price
                if candle.high >= limit_price:
                    touched = True
                    # Price improvement: if market opened above limit, fill at open
                    fill_price = round(max(candle.open, limit_price), 2)

            if touched:
                # Determine fill quantity (handling partial fills via volume participation limit)
                fill_qty = pending.remaining_quantity
                if self.config.partial_fills_enabled and candle.volume > 0:
                    max_allowed_vol = max(1, int(candle.volume * self.config.slippage.volume_participation_limit))
                    fill_qty = min(pending.remaining_quantity, max_allowed_vol)

                if fill_qty > 0:
                    trade = self._execute_fill(order, fill_price, fill_qty, candle.timestamp)
                    trades.append(trade)
                    pending.filled_quantity += fill_qty
                    pending.remaining_quantity -= fill_qty

                if pending.remaining_quantity == 0:
                    completed_orders.append(b_id)
                else:
                    # Order remains active with PARTIALLY_FILLED status
                    OrderStateMachine.transition(order, OrderStatus.PARTIALLY_FILLED)
            else:
                # Price was not reached: increment bar lifetime
                pending.bars_active += 1
                if pending.bars_active >= pending.timeout_bars:
                    expired_orders.append(b_id)

        # Cleanup completed
        for b_id in completed_orders:
            self._pending_limits.pop(b_id, None)

        # Cleanup expired
        for b_id in expired_orders:
            pending = self._pending_limits.pop(b_id, None)
            if pending:
                OrderStateMachine.transition(pending.order, OrderStatus.CANCELLED, reason="ORDER_TIMEOUT")

        return trades

    def _execute_fill(self, order: Order, price: float, quantity: int, timestamp: datetime) -> Trade:
        """Constructs confirmed Trade execution event, updates order, and triggers callbacks."""
        brokerage, taxes = self.cost_calculator.calculate(price=price, quantity=quantity, side=order.side)

        trade = Trade(
            trade_id=f"TRD_{uuid.uuid4().hex[:10].upper()}",
            order_id=order.broker_order_id or order.client_order_id,
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=quantity,
            price=price,
            timestamp=timestamp,
            brokerage=brokerage,
            stt_and_taxes=taxes,
            exchange="NSE",
        )

        # Update order fill metrics
        order.filled_quantity += quantity
        order.average_fill_price = price
        if order.filled_quantity >= order.quantity:
            OrderStateMachine.transition(order, OrderStatus.FILLED)
        else:
            OrderStateMachine.transition(order, OrderStatus.PARTIALLY_FILLED)

        self._executed_trades.append(trade)

        # Notify registered listeners
        for cb in self._trade_callbacks:
            cb(trade)

        return trade

    # =========================================================================
    # Convenient Simulation Helpers
    # =========================================================================

    def submit_limit_order(
        self,
        order_request: OrderRequest,
        timeout_bars: Optional[int] = None,
    ) -> Order:
        """Convenience helper to stage a pending LIMIT order with specified timeout."""
        timeout = timeout_bars if timeout_bars is not None else self.config.default_timeout_bars
        if order_request.order_type != OrderType.LIMIT:
            order_request = OrderRequest(
                client_order_id=order_request.client_order_id,
                symbol=order_request.symbol,
                side=order_request.side,
                order_type=OrderType.LIMIT,
                quantity=order_request.quantity,
                price=order_request.price,
                trigger_price=order_request.trigger_price,
                product_type=order_request.product_type,
                time_in_force=order_request.time_in_force,
                strategy_name=order_request.strategy_name,
                signal_id=order_request.signal_id,
            )
        b_id = self.place_order(order_request)
        order = self._orders_by_broker_id[b_id]
        if b_id in self._pending_limits:
            self._pending_limits[b_id].timeout_bars = timeout
        return order

    def set_stop_loss(
        self,
        symbol: str,
        side: OrderSide,
        stop_price: float,
        quantity: int,
        parent_order_id: str,
        timestamp: Optional[datetime] = None,
    ) -> str:
        """Convenience helper to register an active SL_MARKET stop loss order."""
        client_id = f"SL_{symbol}_{uuid.uuid4().hex[:6]}"
        req = OrderRequest(
            client_order_id=client_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.SL_MARKET,
            quantity=quantity,
            price=stop_price,
            trigger_price=stop_price,
            product_type=ProductType.MIS,
        )
        return self.place_order(req)

    def remove_stop_loss(self, symbol: str) -> List[Order]:
        """Convenience helper to cancel all active stop loss orders for symbol."""
        sym = symbol.upper().strip()
        cancelled = []
        for b_id, pending in list(self._active_stops.items()):
            if pending.order.symbol == sym:
                self.cancel_order(b_id, reason="STOP_REMOVED")
                cancelled.append(pending.order)
        return cancelled

    def execute_market_exit(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        current_price: float,
        timestamp: datetime,
        reason: str,
    ) -> Trade:
        """Convenience helper to immediately execute a MARKET exit order with modeled slippage and costs."""
        sym = symbol.upper().strip()
        self.remove_stop_loss(sym)
        self.set_market_price(sym, current_price)

        slip = self._calculate_slippage(current_price, side)
        fill_price = round(current_price + slip if side == OrderSide.BUY else max(0.05, current_price - slip), 2)

        client_order_id = f"EXIT_{sym}_{timestamp.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
        broker_order_id = f"BK_{uuid.uuid4().hex[:10]}"

        order = Order(
            client_order_id=client_order_id,
            symbol=sym,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            price=fill_price,
            product_type=ProductType.MIS,
            time_in_force=TimeInForce.IOC,
            broker_order_id=broker_order_id,
            status=OrderStatus.CREATED,
            strategy_name="VWAP_ORB",
        )
        self._orders_by_broker_id[broker_order_id] = order
        self._orders_by_client_id[client_order_id] = order

        OrderStateMachine.transition(order, OrderStatus.SUBMITTED)
        OrderStateMachine.transition(order, OrderStatus.ACKNOWLEDGED)

        trade = self._execute_fill(order, fill_price, quantity, timestamp)
        return trade
