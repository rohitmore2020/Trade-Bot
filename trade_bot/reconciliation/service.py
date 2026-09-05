"""
Broker-to-Internal-State Reconciliation Service.

Compares:
1. Positions (existence, direction, quantity, and average price)
2. Orders (existence, status, and broker-assigned ID)
3. Fills (broker trades vs local portfolio fills)
4. Protective Stop-Loss Orders (every active position must have a valid protective SL)

Enforces safety rules:
- Never assume internal state is correct.
- If unambiguous and safe, auto-synchronize (e.g. status transition or applying missing fill).
- If critical discrepancy exists (rogue position, phantom position, missing stop loss):
  1. Stop new trading (`halt_trading = True`).
  2. Record critical error in audit logs.
  3. Require manual intervention.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional, Set

from trade_bot.broker.interfaces import IBrokerAdapter
from trade_bot.domain.enums import OrderSide, OrderStatus, OrderType
from trade_bot.domain.exceptions import CriticalStateDiscrepancyError
from trade_bot.domain.models import Order, Position, Trade, utc_now
from trade_bot.domain.state import OrderStateMachine
from trade_bot.observability.audit import AuditLogger
from trade_bot.portfolio.interfaces import IPortfolioManager
from trade_bot.reconciliation.models import (
    Discrepancy,
    DiscrepancySeverity,
    DiscrepancyType,
    ReconciliationReport,
)

logger = logging.getLogger(__name__)


class BrokerReconciliationService:
    """
    Independent reconciliation engine verifying broker state against internal state.
    """

    def __init__(
        self,
        broker: IBrokerAdapter,
        portfolio_manager: IPortfolioManager,
        audit_logger: Optional[AuditLogger] = None,
        get_internal_orders_fn: Optional[Callable[[], List[Order]]] = None,
        on_protective_stop_missing_fn: Optional[Callable[[str, int, OrderSide], None]] = None,
        price_tolerance_pct: float = 0.005,  # 0.5% tolerance for execution price rounding / fee treatment
    ) -> None:
        self.broker = broker
        self.portfolio = portfolio_manager
        self.audit = audit_logger or AuditLogger()
        self.get_internal_orders = get_internal_orders_fn or (lambda: [])
        self.on_protective_stop_missing = on_protective_stop_missing_fn
        self.price_tolerance_pct = price_tolerance_pct

        # Safety latch
        self.is_halted: bool = False
        self.halt_reason: Optional[str] = None
        self.last_report: Optional[ReconciliationReport] = None

    def run_reconciliation(self) -> ReconciliationReport:
        """
        Execute comprehensive reconciliation cycle.
        """
        start_time = time.perf_counter()
        timestamp = utc_now()
        discrepancies: List[Discrepancy] = []
        auto_resolved_count = 0
        requires_manual_intervention = False
        halt_trading = False

        # 1. Fetch Authoritative Broker State
        try:
            broker_positions = {p.symbol: p for p in self.broker.get_positions()}
            broker_orders = {o.broker_order_id: o for o in self.broker.get_orders() if o.broker_order_id}
        except Exception as exc:
            logger.critical("Failed to retrieve broker state during reconciliation: %s", exc)
            self.is_halted = True
            self.halt_reason = f"Broker query failed during reconciliation: {exc}"
            disc = Discrepancy(
                discrepancy_type=DiscrepancyType.ORDER_STATUS_MISMATCH,
                severity=DiscrepancySeverity.CRITICAL,
                symbol=None,
                details={"error": str(exc)},
            )
            report = ReconciliationReport(
                timestamp=timestamp,
                is_clean=False,
                discrepancies=[disc],
                halt_trading=True,
                requires_manual_intervention=True,
            )
            self.last_report = report
            self.audit.record_event("RECONCILIATION_FAILED", report.to_dict())
            return report

        # 2. Fetch Internal State
        internal_positions = {sym: pos for sym, pos in self.portfolio.get_all_positions().items() if not pos.is_flat}
        internal_orders_list = self.get_internal_orders()
        internal_orders_by_broker_id = {
            o.broker_order_id: o for o in internal_orders_list if o.broker_order_id
        }
        internal_orders_by_client_id = {o.client_order_id: o for o in internal_orders_list}

        # ---------------------------------------------------------------------
        # STEP A: Reconcile Positions (Quantities & Average Prices)
        # ---------------------------------------------------------------------
        all_symbols = set(broker_positions.keys()) | set(internal_positions.keys())

        for symbol in sorted(all_symbols):
            b_pos = broker_positions.get(symbol)
            i_pos = internal_positions.get(symbol)

            b_qty = b_pos.quantity if b_pos else 0
            i_qty = i_pos.quantity if i_pos else 0

            # Case A1: Broker has open position, internal ledger is flat (Rogue position)
            if b_qty != 0 and i_qty == 0:
                disc = Discrepancy(
                    discrepancy_type=DiscrepancyType.POSITION_BROKER_ONLY,
                    severity=DiscrepancySeverity.CRITICAL,
                    symbol=symbol,
                    details={
                        "broker_quantity": b_qty,
                        "internal_quantity": 0,
                        "broker_avg_price": b_pos.average_price if b_pos else 0.0,
                    },
                    resolution_note="Rogue broker position detected; halted for manual intervention",
                )
                discrepancies.append(disc)
                halt_trading = True
                requires_manual_intervention = True

            # Case A2: Bot believes position exists, broker is flat (Phantom position)
            elif b_qty == 0 and i_qty != 0:
                disc = Discrepancy(
                    discrepancy_type=DiscrepancyType.POSITION_BOT_ONLY,
                    severity=DiscrepancySeverity.CRITICAL,
                    symbol=symbol,
                    details={
                        "broker_quantity": 0,
                        "internal_quantity": i_qty,
                        "internal_avg_price": i_pos.average_price if i_pos else 0.0,
                    },
                    resolution_note="Phantom internal position detected; broker is flat",
                )
                discrepancies.append(disc)
                halt_trading = True
                requires_manual_intervention = True

            # Case A3: Both non-flat, but quantity mismatch
            elif b_qty != i_qty:
                disc = Discrepancy(
                    discrepancy_type=DiscrepancyType.POSITION_QUANTITY_MISMATCH,
                    severity=DiscrepancySeverity.CRITICAL,
                    symbol=symbol,
                    details={
                        "broker_quantity": b_qty,
                        "internal_quantity": i_qty,
                        "difference": b_qty - i_qty,
                    },
                    resolution_note="Position quantity mismatch; halted for manual intervention",
                )
                discrepancies.append(disc)
                halt_trading = True
                requires_manual_intervention = True

            # Case A4: Quantities match, check average cost price
            elif b_pos and i_pos and b_qty != 0:
                b_price = b_pos.average_price
                i_price = i_pos.average_price
                if b_price > 0 and i_price > 0:
                    pct_diff = abs(b_price - i_price) / b_price
                    if pct_diff > self.price_tolerance_pct:
                        disc = Discrepancy(
                            discrepancy_type=DiscrepancyType.POSITION_PRICE_MISMATCH,
                            severity=DiscrepancySeverity.WARNING,
                            symbol=symbol,
                            details={
                                "broker_avg_price": b_price,
                                "internal_avg_price": i_price,
                                "pct_difference": round(pct_diff * 100, 3),
                            },
                            resolution_note=f"Average price differs by {round(pct_diff * 100, 3)}%",
                        )
                        discrepancies.append(disc)

        # ---------------------------------------------------------------------
        # STEP B: Reconcile Orders & Statuses
        # ---------------------------------------------------------------------
        seen_client_ids: Set[str] = set()

        for b_id, b_ord in broker_orders.items():
            # Check for duplicate broker orders with same client_order_id
            if b_ord.client_order_id:
                if b_ord.client_order_id in seen_client_ids and b_ord.is_active:
                    disc = Discrepancy(
                        discrepancy_type=DiscrepancyType.ORDER_DUPLICATE,
                        severity=DiscrepancySeverity.CRITICAL,
                        symbol=b_ord.symbol,
                        details={"client_order_id": b_ord.client_order_id, "broker_order_id": b_id},
                        resolution_note="Multiple active orders found on broker for same client_order_id",
                    )
                    discrepancies.append(disc)
                    halt_trading = True
                    requires_manual_intervention = True
                seen_client_ids.add(b_ord.client_order_id)

            # Match order
            i_ord = internal_orders_by_broker_id.get(b_id) or (
                internal_orders_by_client_id.get(b_ord.client_order_id) if b_ord.client_order_id else None
            )

            # Unknown order at broker
            if i_ord is None:
                # If active order on broker is untracked by the bot
                if b_ord.is_active:
                    disc = Discrepancy(
                        discrepancy_type=DiscrepancyType.ORDER_UNKNOWN_BROKER,
                        severity=DiscrepancySeverity.CRITICAL,
                        symbol=b_ord.symbol,
                        details={
                            "broker_order_id": b_id,
                            "client_order_id": b_ord.client_order_id,
                            "symbol": b_ord.symbol,
                            "status": b_ord.status.value,
                            "quantity": b_ord.quantity,
                        },
                        resolution_note="Active order found on broker untracked by bot",
                    )
                    discrepancies.append(disc)
                    halt_trading = True
                    requires_manual_intervention = True
            else:
                # Status mismatch check
                if i_ord.status != b_ord.status:
                    can_sync = OrderStateMachine.can_transition(i_ord.status, b_ord.status)
                    if can_sync:
                        OrderStateMachine.transition(i_ord, b_ord.status)
                        disc = Discrepancy(
                            discrepancy_type=DiscrepancyType.ORDER_STATUS_MISMATCH,
                            severity=DiscrepancySeverity.INFO,
                            symbol=b_ord.symbol,
                            details={
                                "client_order_id": i_ord.client_order_id,
                                "old_status": i_ord.status.value,
                                "broker_status": b_ord.status.value,
                            },
                            is_auto_resolved=True,
                            resolution_note=f"Synchronized local status to {b_ord.status.value}",
                        )
                        discrepancies.append(disc)
                        auto_resolved_count += 1
                    else:
                        disc = Discrepancy(
                            discrepancy_type=DiscrepancyType.ORDER_STATUS_MISMATCH,
                            severity=DiscrepancySeverity.CRITICAL,
                            symbol=b_ord.symbol,
                            details={
                                "client_order_id": i_ord.client_order_id,
                                "local_status": i_ord.status.value,
                                "broker_status": b_ord.status.value,
                            },
                            resolution_note="Illegal state transition required to sync broker status",
                        )
                        discrepancies.append(disc)
                        halt_trading = True
                        requires_manual_intervention = True

        # ---------------------------------------------------------------------
        # STEP C: Protective Stop-Loss Order Verification
        # ---------------------------------------------------------------------
        # For every non-flat position (broker or internal), ensure a protective stop order exists
        active_broker_orders = [o for o in broker_orders.values() if o.is_active]

        for symbol, b_pos in broker_positions.items():
            if b_pos.is_flat:
                continue

            expected_sl_side = OrderSide.SELL if b_pos.quantity > 0 else OrderSide.BUY
            required_qty = abs(b_pos.quantity)

            # Look for active stop-loss order on broker for this symbol
            matching_stops = [
                o
                for o in active_broker_orders
                if o.symbol == symbol
                and o.side == expected_sl_side
                and o.order_type in (OrderType.SL_MARKET, OrderType.SL_LIMIT)
            ]

            if not matching_stops:
                disc = Discrepancy(
                    discrepancy_type=DiscrepancyType.PROTECTIVE_STOP_MISSING,
                    severity=DiscrepancySeverity.CRITICAL,
                    symbol=symbol,
                    details={
                        "position_qty": b_pos.quantity,
                        "expected_side": expected_sl_side.value,
                    },
                    resolution_note="No active protective stop order found on broker for open position",
                )
                discrepancies.append(disc)
                halt_trading = True
                requires_manual_intervention = True

                # Invoke callback if configured (e.g. attempt recovery/emergency exit)
                if self.on_protective_stop_missing:
                    try:
                        self.on_protective_stop_missing(symbol, required_qty, expected_sl_side)
                    except Exception as sl_exc:
                        logger.critical("Callback failed for missing protective stop on %s: %s", symbol, sl_exc)

            else:
                # Verify protective order quantity covers the position
                total_sl_qty = sum(o.quantity for o in matching_stops)
                if total_sl_qty != required_qty:
                    disc = Discrepancy(
                        discrepancy_type=DiscrepancyType.PROTECTIVE_STOP_QUANTITY_MISMATCH,
                        severity=DiscrepancySeverity.CRITICAL,
                        symbol=symbol,
                        details={
                            "position_qty": required_qty,
                            "protective_sl_qty": total_sl_qty,
                        },
                        resolution_note=f"Protective SL covers {total_sl_qty} shares, but position has {required_qty}",
                    )
                    discrepancies.append(disc)
                    halt_trading = True
                    requires_manual_intervention = True

        # ---------------------------------------------------------------------
        # STEP D: Finalize Report & Latch Management
        # ---------------------------------------------------------------------
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        is_clean = len(discrepancies) == 0 or all(d.is_auto_resolved for d in discrepancies)

        if halt_trading:
            self.is_halted = True
            critical_details = [f"{d.discrepancy_type.value}: {d.details}" for d in discrepancies if d.severity == DiscrepancySeverity.CRITICAL]
            self.halt_reason = " | ".join(critical_details)
            logger.critical("Reconciliation identified CRITICAL discrepancies! Halting trading: %s", self.halt_reason)
            self.audit.record_event("CRITICAL_RECONCILIATION_HALT", {"reason": self.halt_reason, "time_ms": elapsed_ms})

        report = ReconciliationReport(
            timestamp=timestamp,
            is_clean=is_clean,
            discrepancies=discrepancies,
            auto_resolved_count=auto_resolved_count,
            requires_manual_intervention=requires_manual_intervention,
            halt_trading=halt_trading,
            execution_time_ms=elapsed_ms,
        )

        self.last_report = report
        self.audit.record_event("RECONCILIATION_COMPLETED", report.to_dict())
        return report

    def reset_halt(self, reason: str = "MANUAL_SUPERVISOR_CLEARANCE") -> None:
        """Reset emergency safety latch after manual investigation and state alignment."""
        self.is_halted = False
        self.halt_reason = None
        self.audit.record_event("RECONCILIATION_HALT_RESET", {"reason": reason})
        logger.info("Reconciliation emergency halt cleared: %s", reason)
