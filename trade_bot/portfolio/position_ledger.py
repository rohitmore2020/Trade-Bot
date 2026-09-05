"""
Deterministic Position Ledger with Idempotent Fill Processing.

Guarantees:
1. Positions strictly derived from confirmed fills
2. Safe idempotent deduplication of duplicate fill events (zero double-counting)
3. Strict separation of gross P&L, transaction costs, slippage, and net realized P&L
4. Accurate position reduction, complete exit, and flipping accounting

Zero external infrastructure dependencies; pure domain ledger.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from trade_bot.domain.enums import OrderSide
from trade_bot.domain.models import Position, utc_now
from trade_bot.portfolio.models import CompletedTrade, Fill, PnLBreakdown
from trade_bot.portfolio.pnl import PnLCalculator


class PositionLedger:
    """
    Stateful ledger tracking positions, completed trades, and P&L breakdowns.
    Guarantees idempotency via fill ID tracking.
    """

    def __init__(self) -> None:
        self._positions: Dict[str, Position] = {}
        self._entry_timestamps: Dict[str, datetime] = {}
        self._processed_fills: Dict[str, Fill] = {}
        self._completed_trades: List[CompletedTrade] = []

        # Running fee and P&L aggregates
        self._gross_realized: float = 0.0
        self._total_transaction_costs: float = 0.0
        self._total_slippage: float = 0.0

    @property
    def positions(self) -> Dict[str, Position]:
        return {k: v for k, v in self._positions.items()}

    @property
    def open_positions(self) -> List[Position]:
        return [p for p in self._positions.values() if not p.is_flat]

    @property
    def completed_trades(self) -> List[CompletedTrade]:
        return list(self._completed_trades)

    @property
    def processed_fills_count(self) -> int:
        return len(self._processed_fills)

    def is_fill_processed(self, fill_id: str) -> bool:
        """Checks if a fill ID has already been applied."""
        return fill_id in self._processed_fills

    def get_position(self, symbol: str) -> Position:
        """Get or initialize position for symbol."""
        if symbol not in self._positions:
            self._positions[symbol] = Position(symbol=symbol)
        return self._positions[symbol]

    def apply_fill(self, fill: Fill) -> tuple[Position, Optional[CompletedTrade], bool]:
        """
        Applies a confirmed execution fill to the ledger.
        Idempotent: If fill_id was already processed, returns existing position without double-counting.
        Returns: (updated_position, completed_trade_if_closed, is_new_fill)
        """
        # IDEMPOTENCY GUARD: Do not double count duplicate fill IDs
        if self.is_fill_processed(fill.fill_id):
            return self.get_position(fill.symbol), None, False

        # Mark fill as processed
        self._processed_fills[fill.fill_id] = fill

        # Calculate transaction fees and slippage
        tx_costs = (
            fill.brokerage + fill.stt_and_taxes
            if (fill.brokerage > 0.0 or fill.stt_and_taxes > 0.0)
            else PnLCalculator.calculate_transaction_costs(fill.price, fill.quantity, fill.side)
        )
        slippage = (
            fill.slippage
            if fill.slippage > 0.0
            else PnLCalculator.calculate_slippage(fill.expected_price, fill.price, fill.quantity)
        )

        self._total_transaction_costs = round(self._total_transaction_costs + tx_costs, 2)
        self._total_slippage = round(self._total_slippage + slippage, 2)

        pos = self.get_position(fill.symbol)
        signed_fill = fill.quantity if fill.side == OrderSide.BUY else -fill.quantity
        curr_qty = pos.quantity
        completed_trade: Optional[CompletedTrade] = None

        # CASE 1: Opening or increasing position in the same direction
        if curr_qty == 0 or (curr_qty > 0 and signed_fill > 0) or (curr_qty < 0 and signed_fill < 0):
            if curr_qty == 0:
                self._entry_timestamps[fill.symbol] = fill.timestamp

            new_qty = curr_qty + signed_fill
            total_cost = (pos.average_price * abs(curr_qty)) + (fill.price * abs(signed_fill))
            pos.quantity = new_qty
            pos.average_price = round(total_cost / abs(new_qty), 4) if new_qty != 0 else 0.0
            pos.last_price = fill.price
            pos.updated_at = fill.timestamp

        # CASE 2: Reducing, closing, or flipping position (opposite direction)
        else:
            closing_qty = min(abs(curr_qty), abs(signed_fill))
            entry_side = OrderSide.BUY if curr_qty > 0 else OrderSide.SELL

            gross_pnl = PnLCalculator.calculate_gross_pnl(
                entry_side=entry_side,
                entry_price=pos.average_price,
                exit_price=fill.price,
                quantity=closing_qty,
            )
            net_pnl = PnLCalculator.calculate_net_pnl(
                gross_pnl=gross_pnl,
                transaction_costs=tx_costs,
                slippage=slippage,
            )

            self._gross_realized = round(self._gross_realized + gross_pnl, 2)
            pos.realized_pnl = round(pos.realized_pnl + net_pnl, 2)

            # Record completed round-trip trade record
            completed_trade = CompletedTrade(
                trade_id=f"TR_{fill.fill_id}",
                symbol=fill.symbol,
                side=entry_side,
                quantity=closing_qty,
                entry_price=pos.average_price,
                exit_price=fill.price,
                entry_time=self._entry_timestamps.get(fill.symbol, fill.timestamp),
                exit_time=fill.timestamp,
                gross_pnl=gross_pnl,
                transaction_costs=tx_costs,
                slippage=slippage,
                net_pnl=net_pnl,
            )
            self._completed_trades.append(completed_trade)

            # Adjust remaining open quantity
            if abs(signed_fill) < abs(curr_qty):
                # Partial reduction: average price remains unchanged
                pos.quantity = curr_qty + signed_fill
            elif abs(signed_fill) == abs(curr_qty):
                # Complete exit
                pos.quantity = 0
                pos.average_price = 0.0
                pos.unrealized_pnl = 0.0
                self._entry_timestamps.pop(fill.symbol, None)
            else:
                # Reversal / Position flip
                flipped_qty = abs(signed_fill) - abs(curr_qty)
                pos.quantity = -flipped_qty if curr_qty > 0 else flipped_qty
                pos.average_price = fill.price
                pos.unrealized_pnl = 0.0
                self._entry_timestamps[fill.symbol] = fill.timestamp

            pos.last_price = fill.price
            pos.updated_at = fill.timestamp

        return pos, completed_trade, True

    def update_market_price(self, symbol: str, current_price: float) -> None:
        """Updates unrealized mark-to-market P&L on an active position."""
        if symbol in self._positions:
            pos = self._positions[symbol]
            pos.update_market_price(current_price)

    def get_pnl_breakdown(self) -> PnLBreakdown:
        """Computes current segregated P&L breakdown."""
        unrealized = round(sum(p.unrealized_pnl for p in self.open_positions), 2)
        net_realized = round(
            self._gross_realized - self._total_transaction_costs - self._total_slippage, 2
        )
        total_net = round(net_realized + unrealized, 2)

        return PnLBreakdown(
            gross_realized=self._gross_realized,
            net_realized=net_realized,
            unrealized=unrealized,
            total_transaction_costs=self._total_transaction_costs,
            total_slippage=self._total_slippage,
            total_net_pnl=total_net,
        )

    def reset_daily_session(self) -> None:
        """Resets daily ledger counters at session boundary."""
        self._completed_trades.clear()
        self._gross_realized = 0.0
        self._total_transaction_costs = 0.0
        self._total_slippage = 0.0
        for pos in self._positions.values():
            pos.realized_pnl = 0.0
