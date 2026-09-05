"""
Portfolio Management Interfaces.

Defines contracts for position accounting, balance calculation, and P&L tracking.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Protocol, runtime_checkable
from trade_bot.domain.models import AccountBalance, Position, Trade


@runtime_checkable
class IPortfolioManager(Protocol):
    """Protocol for managing positions, cash balances, and P&L."""

    def get_account_balance(self) -> AccountBalance:
        """Return current account balance and equity snapshot."""
        ...

    def get_position(self, symbol: str) -> Optional[Position]:
        """Get current position for a given symbol."""
        ...

    def get_all_positions(self) -> Dict[str, Position]:
        """Return dictionary of all managed symbol positions."""
        ...

    def get_open_positions(self) -> List[Position]:
        """Return list of all non-flat positions."""
        ...

    def process_fill(self, trade: Trade) -> Position:
        """Process an execution fill and update position & cash balances."""
        ...

    def update_market_price(self, symbol: str, current_price: float) -> None:
        """Update unrealized P&L given latest market price."""
        ...
