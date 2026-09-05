"""
Order Lifecycle Manager.

Orchestrates the deterministic, end-to-end order execution lifecycle:
Signal -> Risk Approval -> Order Intent -> Broker Submission -> ACK ->
Fill/Rejection -> Position -> Protective SL -> SL Ratchet Modification ->
Exit -> Broker Reconciliation.

Guarantees safety invariants:
1. Never assumes fill from submission response alone. Confirms broker state.
2. Automatically places protective stop loss on entry fill.
3. If protective SL placement fails: halts new entries, emits critical alert,
   triggers emergency market exit procedure, and records audit incident.
4. Trailing stop ratcheting strictly reduces risk; never loosens an existing stop.
5. Duplicate protection: rejects duplicate entry signals and duplicate protective SL orders.
6. Full broker reconciliation and state verification.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set
import uuid

from trade_bot.broker.interfaces import IBrokerAdapter
from trade_bot.domain.enums import (
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
    SignalDirection,
    TimeInForce,
)
from trade_bot.domain.exceptions import (
    DuplicateOrderError,
    DuplicateSignalError,
    EmergencyExitTriggeredError,
    InvalidOrderStateTransitionError,
    InvalidStopLossModificationError,
    OrderNotFoundError,
    OrderRejectedError,
    ProtectiveStopLossError,
    RiskViolationError,
    StateInconsistencyError,
)
from trade_bot.domain.models import (
    AccountBalance,
    Candle,
    Order,
    OrderModification,
    OrderRequest,
    Position,
    Signal,
    Trade,
    utc_now,
)
from trade_bot.domain.state import OrderStateMachine
from trade_bot.execution.idempotency import IdempotencyManager
from trade_bot.execution.lifecycle_models import (
    ActiveTradeLifecycle,
    TradeLifecycleState,
)
from trade_bot.observability.audit import AuditLogger
from trade_bot.portfolio.interfaces import IPortfolioManager
from trade_bot.risk.interfaces import IRiskManager

logger = logging.getLogger(__name__)


from trade_bot.reconciliation.service import BrokerReconciliationService


class OrderLifecycleManager:
    """
    Manages complete, stateful order lifecycles and protective execution invariants.
    """

    def __init__(
        self,
        broker: IBrokerAdapter,
        risk_manager: IRiskManager,
        portfolio_manager: IPortfolioManager,
        audit_logger: Optional[AuditLogger] = None,
        idempotency_manager: Optional[IdempotencyManager] = None,
        use_sl_market: bool = True,
        reconciliation_service: Optional[BrokerReconciliationService] = None,
    ) -> None:
        self.broker = broker
        self.risk_manager = risk_manager
        self.portfolio_manager = portfolio_manager
        self.audit = audit_logger or AuditLogger()
        self.idempotency = idempotency_manager or IdempotencyManager()
        self.use_sl_market = use_sl_market

        # Safety latch: halts any further entries upon critical protective failure
        self.entries_halted: bool = False
        self.halt_reason: Optional[str] = None

        # Tracking registries
        self._lifecycles_by_id: Dict[str, ActiveTradeLifecycle] = {}
        self._lifecycles_by_symbol: Dict[str, ActiveTradeLifecycle] = {}
        self._lifecycles_by_signal: Dict[str, ActiveTradeLifecycle] = {}
        self._orders_by_client_id: Dict[str, Order] = {}
        self._orders_by_broker_id: Dict[str, Order] = {}
        self._order_to_lifecycle: Dict[str, ActiveTradeLifecycle] = {}
        self._processed_trade_ids: Set[str] = set()

        # Connect reconciliation service
        self.reconciliation_service = reconciliation_service or BrokerReconciliationService(
            broker=self.broker,
            portfolio_manager=self.portfolio_manager,
            audit_logger=self.audit,
            get_internal_orders_fn=self.get_all_orders,
        )

        # Connect broker fill callback
        self.broker.register_trade_callback(self.on_trade_fill)


    # -------------------------------------------------------------------------
    # State Query Properties
    # -------------------------------------------------------------------------

    @property
    def is_halted(self) -> bool:
        """Return True if new entries are blocked due to emergency safety latch."""
        return self.entries_halted

    def get_lifecycle(self, lifecycle_id: str) -> Optional[ActiveTradeLifecycle]:
        """Retrieve lifecycle container by ID."""
        return self._lifecycles_by_id.get(lifecycle_id)

    def get_lifecycle_for_symbol(self, symbol: str, include_terminal: bool = False) -> Optional[ActiveTradeLifecycle]:
        """Retrieve trade lifecycle for a given symbol."""
        lc = self._lifecycles_by_symbol.get(symbol)
        if lc:
            if include_terminal or not lc.is_terminal:
                return lc
        return None

    def get_order(self, client_order_id: str) -> Optional[Order]:
        """Retrieve order by client order ID."""
        return self._orders_by_client_id.get(client_order_id)

    def get_active_orders(self) -> List[Order]:
        """Return all active, non-terminal orders across all lifecycles."""
        return [ord for ord in self._orders_by_client_id.values() if ord.is_active]

    def get_all_orders(self) -> List[Order]:
        """Return all tracked orders."""
        return list(self._orders_by_client_id.values())


    # -------------------------------------------------------------------------
    # 1. Signal -> Risk Approval -> Order Submission
    # -------------------------------------------------------------------------

    def handle_signal(self, signal: Signal, candle: Optional[Candle] = None) -> Order:
        """
        Process a new strategy signal:
        - Verify safety latch (entries_halted).
        - Enforce duplicate protection (no active trade for symbol/signal).
        - Pre-trade risk approval.
        - Create order intent and register idempotency.
        - Submit to broker and transition states.
        """
        # Step 1: Safety check - emergency latch
        if self.entries_halted:
            msg = f"New entries halted due to emergency protection: {self.halt_reason}"
            logger.error(msg)
            self.audit.record_event("SIGNAL_BLOCKED_ENTRIES_HALTED", {"symbol": signal.symbol, "reason": msg})
            raise RiskViolationError(msg)

        # Step 2: Duplicate Signal Protection
        if signal.signal_id in self._lifecycles_by_signal:
            existing = self._lifecycles_by_signal[signal.signal_id]
            if not existing.is_terminal:
                msg = f"Duplicate active signal detected for signal_id='{signal.signal_id}' on {signal.symbol}"
                logger.warning(msg)
                self.audit.record_event("DUPLICATE_SIGNAL_REJECTED", {"symbol": signal.symbol, "signal_id": signal.signal_id})
                raise DuplicateSignalError(msg)

        active_lc = self.get_lifecycle_for_symbol(signal.symbol)
        if active_lc is not None and active_lc.is_active_in_market:
            msg = f"Duplicate active trade lifecycle already exists for symbol='{signal.symbol}' (lifecycle_id='{active_lc.lifecycle_id}')"
            logger.warning(msg)
            self.audit.record_event("DUPLICATE_ENTRY_REJECTED", {"symbol": signal.symbol, "lifecycle_id": active_lc.lifecycle_id})
            raise DuplicateOrderError(msg)

        # Step 3: Determine order properties
        side = OrderSide.BUY if signal.direction == SignalDirection.LONG else OrderSide.SELL
        quantity = signal.suggested_quantity or 1
        client_order_id = f"ENTRY_{signal.symbol}_{int(utc_now().timestamp())}_{uuid.uuid4().hex[:6]}"
        
        order_req = OrderRequest(
            client_order_id=client_order_id,
            symbol=signal.symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            product_type=ProductType.MIS,
            time_in_force=TimeInForce.DAY,
            strategy_name=signal.strategy_name,
            signal_id=signal.signal_id,
            tag="ENTRY_SIGNAL",
        )

        # Step 4: Idempotency check
        self.idempotency.check_and_register(order_req)

        # Step 5: Risk assessment
        balance = self.portfolio_manager.get_account_balance()
        positions = self.portfolio_manager.get_all_positions()
        risk_decision = self.risk_manager.validate_order(order_req, balance, positions)

        lifecycle_id = f"LC_{signal.symbol}_{uuid.uuid4().hex[:8]}"
        lifecycle = ActiveTradeLifecycle(
            lifecycle_id=lifecycle_id,
            symbol=signal.symbol,
            signal_id=signal.signal_id,
            side=side,
            target_quantity=quantity,
            current_stop_loss_price=signal.stop_loss,
            trailing_watermark=signal.entry_price,
            lifecycle_state=TradeLifecycleState.PENDING_RISK,
        )
        self._lifecycles_by_id[lifecycle_id] = lifecycle
        self._lifecycles_by_symbol[signal.symbol] = lifecycle
        self._lifecycles_by_signal[signal.signal_id] = lifecycle

        if not risk_decision.is_approved:
            lifecycle.lifecycle_state = TradeLifecycleState.REJECTED
            rejected_order = Order(
                client_order_id=order_req.client_order_id,
                symbol=order_req.symbol,
                side=order_req.side,
                order_type=order_req.order_type,
                quantity=order_req.quantity,
                product_type=order_req.product_type,
                time_in_force=order_req.time_in_force,
                price=order_req.price,
                status=OrderStatus.REJECTED,
                strategy_name=order_req.strategy_name,
                signal_id=order_req.signal_id,
                rejection_reason=risk_decision.reason,
            )
            lifecycle.entry_order = rejected_order
            self._orders_by_client_id[client_order_id] = rejected_order
            self._order_to_lifecycle[client_order_id] = lifecycle
            self.audit.log_risk_event(
                decision="REJECTED",
                reason=risk_decision.reason,
                rule=risk_decision.rule_name,
                details={"symbol": signal.symbol, "client_order_id": client_order_id},
            )
            raise OrderRejectedError(
                f"Order rejected by risk management: {risk_decision.reason}",
                context={"client_order_id": client_order_id, "rule": risk_decision.rule_name},
            )

        # Step 6: Create order model and advance state
        entry_order = Order(
            client_order_id=order_req.client_order_id,
            symbol=order_req.symbol,
            side=order_req.side,
            order_type=order_req.order_type,
            quantity=order_req.quantity,
            product_type=order_req.product_type,
            time_in_force=order_req.time_in_force,
            price=order_req.price,
            status=OrderStatus.CREATED,
            strategy_name=order_req.strategy_name,
            signal_id=order_req.signal_id,
        )
        lifecycle.entry_order = entry_order
        self._orders_by_client_id[client_order_id] = entry_order
        self._order_to_lifecycle[client_order_id] = lifecycle

        # Step 7: Broker submission
        OrderStateMachine.transition(entry_order, OrderStatus.PENDING_SUBMIT)
        lifecycle.lifecycle_state = TradeLifecycleState.PENDING_SUBMIT
        self.audit.log_order_event("SUBMITTING", client_order_id, {"symbol": signal.symbol, "qty": quantity})

        try:
            broker_order_id = self.broker.place_order(order_req)
            entry_order.broker_order_id = broker_order_id
            self._orders_by_broker_id[broker_order_id] = entry_order

            OrderStateMachine.transition(entry_order, OrderStatus.SUBMITTED)
            lifecycle.lifecycle_state = TradeLifecycleState.SUBMITTED
            
            # Transition to ACKNOWLEDGED once broker returns valid order id
            OrderStateMachine.transition(entry_order, OrderStatus.ACKNOWLEDGED)
            lifecycle.lifecycle_state = TradeLifecycleState.ACKNOWLEDGED
            self.audit.log_order_event(
                "ACKNOWLEDGED",
                client_order_id,
                {"broker_order_id": broker_order_id, "symbol": signal.symbol},
            )
        except Exception as exc:
            OrderStateMachine.transition(entry_order, OrderStatus.REJECTED, reason=str(exc))
            lifecycle.lifecycle_state = TradeLifecycleState.REJECTED
            self.audit.log_order_event("REJECTED_SUBMISSION", client_order_id, {"error": str(exc)})
            raise

        return entry_order

    # -------------------------------------------------------------------------
    # 2. Broker Fill / Execution Handling & Protective Stop-Loss Automation
    # -------------------------------------------------------------------------

    def on_trade_fill(self, trade: Trade) -> None:
        """
        Process trade fill callback from broker:
        - Deduplicate fills idempotently.
        - Advance order state (PARTIALLY_FILLED or FILLED).
        - Update portfolio manager position and cash.
        - CRITICAL SAFETY: After entry fill, verify/place protective stop-loss.
        - Handle exit / stop-loss fill closures.
        """
        if trade.trade_id in self._processed_trade_ids:
            logger.info("Ignoring duplicate trade fill: %s", trade.trade_id)
            return
        self._processed_trade_ids.add(trade.trade_id)

        order = self.get_order(trade.client_order_id)
        if order is None:
            logger.warning("Trade fill received for untracked order: %s", trade.client_order_id)
            return

        lifecycle = self._order_to_lifecycle.get(order.client_order_id)

        # Update order fill metrics
        order.fills.append(trade)
        new_filled_qty = order.filled_quantity + trade.quantity
        total_fill_cost = (order.average_fill_price * order.filled_quantity) + (trade.price * trade.quantity)
        order.filled_quantity = new_filled_qty
        order.average_fill_price = round(total_fill_cost / new_filled_qty, 4)

        # Advance order state via state machine
        if order.filled_quantity >= order.quantity:
            OrderStateMachine.transition(order, OrderStatus.FILLED, timestamp=trade.timestamp)
        else:
            OrderStateMachine.transition(order, OrderStatus.PARTIALLY_FILLED, timestamp=trade.timestamp)

        # Forward fill to portfolio manager
        self.portfolio_manager.process_fill(trade)
        self.audit.record_event(
            "ORDER_FILL_PROCESSED",
            {
                "trade_id": trade.trade_id,
                "client_order_id": order.client_order_id,
                "symbol": order.symbol,
                "qty": trade.quantity,
                "price": trade.price,
                "status": order.status.value,
            },
        )

        if lifecycle is None:
            return

        lifecycle.trades.append(trade)

        # CASE A: Fill is on the ENTRY order
        if lifecycle.entry_order and lifecycle.entry_order.client_order_id == order.client_order_id:
            lifecycle.filled_quantity = order.filled_quantity
            lifecycle.average_entry_price = order.average_fill_price
            lifecycle.trailing_watermark = order.average_fill_price

            if order.status == OrderStatus.FILLED:
                lifecycle.lifecycle_state = TradeLifecycleState.ACTIVE_UNPROTECTED
            elif order.status == OrderStatus.PARTIALLY_FILLED:
                lifecycle.lifecycle_state = TradeLifecycleState.PARTIALLY_FILLED

            # CRITICAL SAFETY: Ensure protective stop loss is in place
            self._ensure_protective_stop_loss(lifecycle, filled_qty=trade.quantity)

        # CASE B: Fill is on the PROTECTIVE STOP LOSS order
        elif lifecycle.stop_loss_order and lifecycle.stop_loss_order.client_order_id == order.client_order_id:
            logger.info("Protective stop-loss filled for %s at %.2f", lifecycle.symbol, trade.price)
            lifecycle.lifecycle_state = TradeLifecycleState.CLOSED
            lifecycle.stop_loss_order = None
            self.audit.record_event("STOP_LOSS_EXECUTED", {"lifecycle_id": lifecycle.lifecycle_id, "symbol": lifecycle.symbol, "price": trade.price})

        # CASE C: Fill is on the EXIT order (e.g. VWAP exit, 14:30 square-off, emergency)
        elif lifecycle.exit_order and lifecycle.exit_order.client_order_id == order.client_order_id:
            logger.info("Exit order filled for %s at %.2f", lifecycle.symbol, trade.price)
            # Cancel resting protective stop loss order if still active
            self._cancel_resting_sl(lifecycle)
            lifecycle.lifecycle_state = TradeLifecycleState.CLOSED
            self.audit.record_event("POSITION_EXIT_EXECUTED", {"lifecycle_id": lifecycle.lifecycle_id, "symbol": lifecycle.symbol, "price": trade.price})

    def _ensure_protective_stop_loss(self, lifecycle: ActiveTradeLifecycle, filled_qty: int) -> None:
        """
        Creates or adjusts the protective stop-loss order following an entry fill.
        If protective SL creation fails:
        1. Halt all new entries (entries_halted = True).
        2. Emit CRITICAL audit log and alert.
        3. Trigger emergency market exit to liquidate unprotected position.
        4. Record the incident.
        """
        # Prevent duplicate protective orders if one is already active and covers full filled quantity
        if lifecycle.has_active_protective_sl:
            active_sl = lifecycle.stop_loss_order
            if active_sl and active_sl.quantity >= lifecycle.filled_quantity:
                logger.info("Protective SL already covers position (%d shares) for %s", active_sl.quantity, lifecycle.symbol)
                return
            elif active_sl and active_sl.is_active:
                # Need to resize SL quantity for partial fill accumulation
                try:
                    logger.info("Resizing protective SL for %s from %d to %d", lifecycle.symbol, active_sl.quantity, lifecycle.filled_quantity)
                    mod = OrderModification(
                        order_id=active_sl.broker_order_id or "",
                        client_order_id=active_sl.client_order_id,
                        quantity=lifecycle.filled_quantity,
                    )
                    self.broker.modify_order(mod)
                    active_sl.quantity = lifecycle.filled_quantity
                    return
                except Exception as exc:
                    logger.error("Failed to resize protective SL: %s", exc)
                    # Proceed to emergency protection

        # Fallback stop loss calculation if none provided
        sl_price = lifecycle.current_stop_loss_price
        if sl_price is None or sl_price <= 0:
            avg_entry = lifecycle.average_entry_price or 100.0
            sl_price = round(avg_entry * 0.99, 2) if lifecycle.side == OrderSide.BUY else round(avg_entry * 1.01, 2)
            lifecycle.current_stop_loss_price = sl_price

        sl_side = OrderSide.SELL if lifecycle.side == OrderSide.BUY else OrderSide.BUY
        sl_client_id = f"SL_{lifecycle.symbol}_{int(utc_now().timestamp())}_{uuid.uuid4().hex[:6]}"
        sl_order_type = OrderType.SL_MARKET if self.use_sl_market else OrderType.SL_LIMIT
        limit_price = sl_price if sl_order_type == OrderType.SL_LIMIT else None

        sl_request = OrderRequest(
            client_order_id=sl_client_id,
            symbol=lifecycle.symbol,
            side=sl_side,
            order_type=sl_order_type,
            quantity=lifecycle.filled_quantity,
            price=limit_price,
            trigger_price=sl_price,
            product_type=ProductType.MIS,
            time_in_force=TimeInForce.DAY,
            strategy_name="PROTECTIVE_SL",
            signal_id=lifecycle.signal_id,
            tag="PROTECTIVE_STOP",
        )

        sl_order = Order(
            client_order_id=sl_client_id,
            symbol=lifecycle.symbol,
            side=sl_side,
            order_type=sl_order_type,
            quantity=lifecycle.filled_quantity,
            price=limit_price,
            trigger_price=sl_price,
            product_type=ProductType.MIS,
            status=OrderStatus.CREATED,
            strategy_name="PROTECTIVE_SL",
            signal_id=lifecycle.signal_id,
        )

        try:
            self.idempotency.check_and_register(sl_request)
            self._orders_by_client_id[sl_client_id] = sl_order
            self._order_to_lifecycle[sl_client_id] = lifecycle
            OrderStateMachine.transition(sl_order, OrderStatus.PENDING_SUBMIT)

            broker_order_id = self.broker.place_order(sl_request)
            sl_order.broker_order_id = broker_order_id
            self._orders_by_broker_id[broker_order_id] = sl_order

            OrderStateMachine.transition(sl_order, OrderStatus.SUBMITTED)
            OrderStateMachine.transition(sl_order, OrderStatus.ACKNOWLEDGED)

            lifecycle.stop_loss_order = sl_order
            lifecycle.lifecycle_state = TradeLifecycleState.ACTIVE_PROTECTED
            self.audit.record_event(
                "PROTECTIVE_SL_PLACED",
                {
                    "lifecycle_id": lifecycle.lifecycle_id,
                    "symbol": lifecycle.symbol,
                    "sl_order_id": sl_client_id,
                    "broker_order_id": broker_order_id,
                    "trigger_price": sl_price,
                    "quantity": lifecycle.filled_quantity,
                },
            )
            logger.info("Protective SL placed successfully for %s at %.2f (Qty: %d)", lifecycle.symbol, sl_price, lifecycle.filled_quantity)

        except Exception as exc:
            # CRITICAL FAILURE PROCEDURE
            msg = f"CRITICAL: Failed to place protective stop loss for {lifecycle.symbol}: {exc}"
            logger.critical(msg)
            OrderStateMachine.transition(sl_order, OrderStatus.REJECTED, reason=str(exc))
            
            # 1. Trip safety latch
            self.entries_halted = True
            self.halt_reason = f"Protective SL placement failed on {lifecycle.symbol}: {exc}"

            # 2. Record critical incident
            self.audit.record_event(
                "CRITICAL_PROTECTIVE_SL_FAILURE",
                {
                    "lifecycle_id": lifecycle.lifecycle_id,
                    "symbol": lifecycle.symbol,
                    "error": str(exc),
                    "action": "HALTING_ENTRIES_AND_TRIGGERING_EMERGENCY_EXIT",
                },
            )

            # 3. Trigger emergency liquidation
            self._execute_emergency_exit(lifecycle, reason="EMERGENCY_SL_CREATION_FAILED")
            raise ProtectiveStopLossError(msg) from exc

    # -------------------------------------------------------------------------
    # 3. Emergency Protection & Exit Procedure
    # -------------------------------------------------------------------------

    def _execute_emergency_exit(self, lifecycle: ActiveTradeLifecycle, reason: str) -> None:
        """
        Execute emergency market square-off for unprotected position:
        - Places immediate market exit order.
        - Marks lifecycle state as EMERGENCY_EXITED.
        - Records incident details in audit log.
        """
        logger.critical("Executing EMERGENCY MARKET EXIT for %s (Reason: %s)", lifecycle.symbol, reason)
        exit_side = OrderSide.SELL if lifecycle.side == OrderSide.BUY else OrderSide.BUY
        client_order_id = f"EMERGENCY_EXIT_{lifecycle.symbol}_{int(utc_now().timestamp())}_{uuid.uuid4().hex[:6]}"

        exit_req = OrderRequest(
            client_order_id=client_order_id,
            symbol=lifecycle.symbol,
            side=exit_side,
            order_type=OrderType.MARKET,
            quantity=lifecycle.filled_quantity,
            product_type=ProductType.MIS,
            strategy_name="EMERGENCY_EXIT",
            signal_id=lifecycle.signal_id,
            tag=reason,
        )

        exit_order = Order(
            client_order_id=client_order_id,
            symbol=lifecycle.symbol,
            side=exit_side,
            order_type=OrderType.MARKET,
            quantity=lifecycle.filled_quantity,
            product_type=ProductType.MIS,
            status=OrderStatus.CREATED,
            strategy_name="EMERGENCY_EXIT",
            signal_id=lifecycle.signal_id,
        )

        lifecycle.is_emergency = True
        lifecycle.emergency_reason = reason
        lifecycle.exit_order = exit_order
        lifecycle.lifecycle_state = TradeLifecycleState.EMERGENCY_EXITED

        self._orders_by_client_id[client_order_id] = exit_order
        self._order_to_lifecycle[client_order_id] = lifecycle

        try:
            OrderStateMachine.transition(exit_order, OrderStatus.PENDING_SUBMIT)
            broker_order_id = self.broker.place_order(exit_req)
            exit_order.broker_order_id = broker_order_id
            self._orders_by_broker_id[broker_order_id] = exit_order
            OrderStateMachine.transition(exit_order, OrderStatus.SUBMITTED)
            OrderStateMachine.transition(exit_order, OrderStatus.ACKNOWLEDGED)

            self.audit.record_event(
                "EMERGENCY_EXIT_SUBMITTED",
                {
                    "lifecycle_id": lifecycle.lifecycle_id,
                    "symbol": lifecycle.symbol,
                    "exit_order_id": client_order_id,
                    "broker_order_id": broker_order_id,
                    "reason": reason,
                },
            )
        except Exception as exc:
            logger.critical("EMERGENCY EXIT SUBMISSION FAILED for %s: %s", lifecycle.symbol, exc)
            OrderStateMachine.transition(exit_order, OrderStatus.REJECTED, reason=str(exc))
            self.audit.record_event(
                "CRITICAL_EMERGENCY_EXIT_FAILED",
                {"lifecycle_id": lifecycle.lifecycle_id, "symbol": lifecycle.symbol, "error": str(exc)},
            )
            raise EmergencyExitTriggeredError(f"Emergency exit order placement failed: {exc}") from exc

    # -------------------------------------------------------------------------
    # 4. Trailing Stop Ratchet Modification (Never Loosen Risk)
    # -------------------------------------------------------------------------

    def update_trailing_stop(self, symbol: str, new_stop_price: float, current_market_price: float) -> Order:
        """
        Update the trailing stop-loss for an active position:
        - SAFETY INVARIANT: Only move stops in a direction that reduces risk.
          - LONG: new_stop_price must be > current_stop_loss_price.
          - SHORT: new_stop_price must be < current_stop_loss_price.
        - Never loosen an existing stop.
        - Atomically update broker order and local lifecycle state.
        """
        lifecycle = self.get_lifecycle_for_symbol(symbol)
        if lifecycle is None or not lifecycle.has_active_protective_sl:
            raise OrderNotFoundError(f"No active protected trade lifecycle found for {symbol}")

        sl_order = lifecycle.stop_loss_order
        assert sl_order is not None

        old_stop_price = lifecycle.current_stop_loss_price
        if old_stop_price is None:
            old_stop_price = sl_order.trigger_price or sl_order.price or 0.0

        # Enforce strict monotonic ratcheting:
        if lifecycle.side == OrderSide.BUY:
            # Long position: stop-loss must only move UP
            if new_stop_price <= old_stop_price:
                raise InvalidStopLossModificationError(
                    f"Cannot loosen Long stop-loss on {symbol}: new {new_stop_price} <= current {old_stop_price}",
                    context={"symbol": symbol, "old_stop": old_stop_price, "new_stop": new_stop_price},
                )
            if new_stop_price >= current_market_price:
                raise InvalidStopLossModificationError(
                    f"Stop price {new_stop_price} cannot be >= current market price {current_market_price} for Long",
                    context={"symbol": symbol, "current_market_price": current_market_price},
                )
        else:
            # Short position: stop-loss must only move DOWN
            if new_stop_price >= old_stop_price:
                raise InvalidStopLossModificationError(
                    f"Cannot loosen Short stop-loss on {symbol}: new {new_stop_price} >= current {old_stop_price}",
                    context={"symbol": symbol, "old_stop": old_stop_price, "new_stop": new_stop_price},
                )
            if new_stop_price <= current_market_price:
                raise InvalidStopLossModificationError(
                    f"Stop price {new_stop_price} cannot be <= current market price {current_market_price} for Short",
                    context={"symbol": symbol, "current_market_price": current_market_price},
                )

        # Build broker modification intent
        limit_price = new_stop_price if sl_order.order_type == OrderType.SL_LIMIT else None
        mod = OrderModification(
            order_id=sl_order.broker_order_id or "",
            client_order_id=sl_order.client_order_id,
            price=limit_price,
            trigger_price=new_stop_price,
        )

        try:
            self.broker.modify_order(mod)
            sl_order.trigger_price = new_stop_price
            if limit_price is not None:
                sl_order.price = limit_price
            sl_order.updated_at = utc_now()

            lifecycle.current_stop_loss_price = new_stop_price
            lifecycle.trailing_watermark = max(lifecycle.trailing_watermark or current_market_price, current_market_price) if lifecycle.side == OrderSide.BUY else min(lifecycle.trailing_watermark or current_market_price, current_market_price)
            lifecycle.lifecycle_state = TradeLifecycleState.TRAILING

            self.audit.record_event(
                "STOP_LOSS_MODIFIED",
                {
                    "lifecycle_id": lifecycle.lifecycle_id,
                    "symbol": symbol,
                    "old_stop": old_stop_price,
                    "new_stop": new_stop_price,
                    "market_price": current_market_price,
                },
            )
            logger.info("Successfully ratcheted stop-loss for %s: %.2f -> %.2f", symbol, old_stop_price, new_stop_price)
            return sl_order

        except Exception as exc:
            logger.error("Failed to modify stop-loss on broker for %s: %s", symbol, exc)
            self.audit.record_event("STOP_LOSS_MODIFICATION_FAILED", {"symbol": symbol, "error": str(exc)})
            raise

    # -------------------------------------------------------------------------
    # 5. Position Exits (VWAP Exits & Scheduled Square-Off)
    # -------------------------------------------------------------------------

    def exit_position(self, symbol: str, reason: str = "VWAP_EXIT", exit_price: Optional[float] = None) -> Order:
        """
        Execute an intentional exit (e.g. VWAP invalidation or profit target):
        - Submits market exit order to close full open quantity.
        - Cancels resting protective SL order.
        """
        lifecycle = self.get_lifecycle_for_symbol(symbol)
        if lifecycle is None or not lifecycle.is_active_in_market:
            raise OrderNotFoundError(f"No active trade lifecycle found for exit on {symbol}")

        exit_side = OrderSide.SELL if lifecycle.side == OrderSide.BUY else OrderSide.BUY
        client_order_id = f"EXIT_{symbol}_{int(utc_now().timestamp())}_{uuid.uuid4().hex[:6]}"

        exit_req = OrderRequest(
            client_order_id=client_order_id,
            symbol=symbol,
            side=exit_side,
            order_type=OrderType.MARKET,
            quantity=lifecycle.filled_quantity,
            price=exit_price,
            product_type=ProductType.MIS,
            strategy_name="POSITION_EXIT",
            signal_id=lifecycle.signal_id,
            tag=reason,
        )

        exit_order = Order(
            client_order_id=client_order_id,
            symbol=symbol,
            side=exit_side,
            order_type=OrderType.MARKET,
            quantity=lifecycle.filled_quantity,
            price=exit_price,
            product_type=ProductType.MIS,
            status=OrderStatus.CREATED,
            strategy_name="POSITION_EXIT",
            signal_id=lifecycle.signal_id,
        )

        lifecycle.exit_order = exit_order
        lifecycle.lifecycle_state = TradeLifecycleState.EXIT_PENDING
        self._orders_by_client_id[client_order_id] = exit_order
        self._order_to_lifecycle[client_order_id] = lifecycle

        try:
            OrderStateMachine.transition(exit_order, OrderStatus.PENDING_SUBMIT)
            broker_order_id = self.broker.place_order(exit_req)
            exit_order.broker_order_id = broker_order_id
            self._orders_by_broker_id[broker_order_id] = exit_order
            OrderStateMachine.transition(exit_order, OrderStatus.SUBMITTED)
            OrderStateMachine.transition(exit_order, OrderStatus.ACKNOWLEDGED)

            # Cancel resting protective stop loss order
            self._cancel_resting_sl(lifecycle)

            self.audit.record_event(
                "EXIT_ORDER_PLACED",
                {"lifecycle_id": lifecycle.lifecycle_id, "symbol": symbol, "client_order_id": client_order_id, "reason": reason},
            )
            return exit_order

        except Exception as exc:
            OrderStateMachine.transition(exit_order, OrderStatus.REJECTED, reason=str(exc))
            self.audit.record_event("EXIT_ORDER_REJECTED", {"symbol": symbol, "error": str(exc)})
            raise

    def force_square_off_all(self, reason: str = "FORCED_SQUARE_OFF") -> List[Order]:
        """
        Execute mandatory intraday square-off (e.g. at 14:30 IST):
        - Cancels all active orders (resting entries, stops, limits).
        - Closes all non-flat positions at market.
        """
        logger.info("Initiating force square-off for all active positions (Reason: %s)...", reason)
        self.entries_halted = True
        self.halt_reason = f"Forced square-off active: {reason}"

        # 1. Cancel all resting orders at broker
        for ord in self.get_active_orders():
            if ord.broker_order_id:
                try:
                    self.broker.cancel_order(ord.broker_order_id)
                    OrderStateMachine.transition(ord, OrderStatus.CANCELLED, reason=reason)
                except Exception as exc:
                    logger.warning("Failed to cancel active order %s during square-off: %s", ord.client_order_id, exc)

        # 2. Market close all active lifecycles with open filled quantity
        closed_orders: List[Order] = []
        for lifecycle in list(self._lifecycles_by_id.values()):
            if lifecycle.is_active_in_market and lifecycle.filled_quantity > 0:
                try:
                    ord = self.exit_position(lifecycle.symbol, reason=reason)
                    closed_orders.append(ord)
                except Exception as exc:
                    logger.critical("Failed to execute square-off exit for %s: %s", lifecycle.symbol, exc)

        self.audit.record_event("FORCED_SQUARE_OFF_COMPLETED", {"reason": reason, "exits_submitted": len(closed_orders)})
        return closed_orders

    def _cancel_resting_sl(self, lifecycle: ActiveTradeLifecycle) -> None:
        """Cancel the resting protective stop loss order for a lifecycle."""
        if lifecycle.has_active_protective_sl:
            sl = lifecycle.stop_loss_order
            assert sl is not None
            if sl.broker_order_id:
                try:
                    self.broker.cancel_order(sl.broker_order_id)
                    OrderStateMachine.transition(sl, OrderStatus.CANCELLED, reason="EXIT_FILLED")
                    logger.info("Cancelled resting SL order %s for %s", sl.client_order_id, lifecycle.symbol)
                except Exception as exc:
                    logger.warning("Failed to cancel resting SL order %s: %s", sl.client_order_id, exc)
            lifecycle.stop_loss_order = None

    # -------------------------------------------------------------------------
    # 6. Broker State Reconciliation
    # -------------------------------------------------------------------------

    def reconcile_broker_state(self) -> Dict[str, Any]:
        """
        Reconcile local application state against authoritative broker state via BrokerReconciliationService.
        Halts entries if any critical discrepancies are detected.
        """
        report = self.reconciliation_service.run_reconciliation()
        if report.halt_trading:
            self.entries_halted = True
            self.halt_reason = self.reconciliation_service.halt_reason or "Reconciliation identified critical discrepancy"

        return report.to_dict()


    def reset_halt(self, reason: str = "MANUAL_SUPERVISOR_OVERRIDE") -> None:
        """Reset emergency safety latch to permit new entries after manual supervisor clearance."""
        self.entries_halted = False
        self.halt_reason = None
        self.audit.record_event("EMERGENCY_HALT_RESET", {"reason": reason})
        logger.info("Emergency halt reset: %s", reason)
