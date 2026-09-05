"""
Portfolio Manager Implementation.

Maintains ledger of cash balance, open positions, realized and unrealized P&L.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional
from trade_bot.domain.enums import OrderSide
from trade_bot.domain.models import AccountBalance, Position, Trade, utc_now
from trade_bot.domain.state import PositionTracker
from trade_bot.portfolio.interfaces import IPortfolioManager


class PortfolioManager(IPortfolioManager):
    """
    Manages portfolio state, cash ledger, and position trackers.
    """

    def __init__(self, initial_capital: float = 100000.0, currency: str = "INR") -> None:
        self.initial_capital = initial_capital
        self.available_cash = initial_capital
        self.currency = currency
        self._trackers: Dict[str, PositionTracker] = {}
        self._total_brokerage_and_taxes: float = 0.0

    def get_position(self, symbol: str) -> Optional[Position]:
        """Get current position for a given symbol."""
        tracker = self._trackers.get(symbol)
        return tracker.position if tracker else None

    def get_all_positions(self) -> Dict[str, Position]:
        """Return snapshot of all positions."""
        return {sym: tracker.position for sym, tracker in self._trackers.items()}

    def get_open_positions(self) -> List[Position]:
        """Return list of all non-flat positions."""
        return [tracker.position for tracker in self._trackers.values() if not tracker.position.is_flat]

    def _get_or_create_tracker(self, symbol: str) -> PositionTracker:
        if symbol not in self._trackers:
            self._trackers[symbol] = PositionTracker(symbol=symbol)
        return self._trackers[symbol]

    def process_fill(self, trade: Trade) -> Position:
        """
        Update positions and available cash upon execution fill.
        """
        tracker = self._get_or_create_tracker(trade.symbol)

        # Apply fill to position tracker
        new_pos = tracker.apply_trade(trade)

        # Cash impact calculation
        trade_value = trade.price * trade.quantity
        fees = trade.brokerage + trade.stt_and_taxes
        self._total_brokerage_and_taxes += fees

        if trade.side == OrderSide.BUY:
            self.available_cash -= (trade_value + fees)
        else:
            self.available_cash += (trade_value - fees)

        return new_pos

    def update_market_price(self, symbol: str, current_price: float) -> None:
        """Update unrealized P&L on the active position."""
        if symbol in self._trackers:
            self._trackers[symbol].position.update_market_price(current_price)

    def get_account_balance(self) -> AccountBalance:
        """Compute current account balance and total equity."""
        total_realized = sum(t.position.realized_pnl for t in self._trackers.values())
        total_unrealized = sum(t.position.unrealized_pnl for t in self._trackers.values())
        used_margin = sum(t.position.market_value for t in self._trackers.values() if not t.position.is_flat)

        return AccountBalance(
            initial_capital=self.initial_capital,
            available_cash=round(self.available_cash, 2),
            used_margin=round(used_margin, 2),
            total_realized_pnl=round(total_realized, 2),
            total_unrealized_pnl=round(total_unrealized, 2),
            currency=self.currency,
            timestamp=utc_now(),
        )
